"""Processamento de uma consulta pelo worker (RN-02 a RN-06).

Idempotente: a mensagem pode chegar mais de uma vez (acks_late). Toda mudança de estado é um UPDATE condicionado
ao status atual, e nenhuma transação fica aberta durante a chamada ao serviço externo.
"""

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.orm import Session

from customer_lookup.core import contexto
from customer_lookup.core.dominio import STATUS_TERMINAIS, StatusConsulta
from customer_lookup.core.logging import LOGGER_NAME
from customer_lookup.models import Consulta
from customer_lookup.ports import ClienteExterno, ErroIntegracao
from customer_lookup.services.politica_retry import PoliticaRetry, Retentar

logger = logging.getLogger(LOGGER_NAME)

_EM_ANDAMENTO = (StatusConsulta.PENDING, StatusConsulta.PROCESSING)


def processar_consulta(
    db: Session, cliente: ClienteExterno, politica: PoliticaRetry, consulta_id: uuid.UUID
) -> Retentar | None:
    """Faz uma tentativa. Devolve `Retentar` quando o worker deve agendar outra; senão `None`."""
    token = contexto.consulta_id.set(str(consulta_id))
    try:
        return _processar(db, cliente, politica, consulta_id)
    finally:
        contexto.consulta_id.reset(token)


def _processar(
    db: Session, cliente: ClienteExterno, politica: PoliticaRetry, consulta_id: uuid.UUID
) -> Retentar | None:
    claim = db.execute(
        update(Consulta)
        .where(
            Consulta.id == consulta_id,
            Consulta.status.in_(_EM_ANDAMENTO),
            Consulta.tentativas < politica.max_tentativas,
        )
        .values(status=StatusConsulta.PROCESSING, tentativas=Consulta.tentativas + 1)
        .returning(Consulta.tentativas, Consulta.documento, Consulta.criado_em)
    ).one_or_none()
    # Commit antes da chamada externa: libera a conexão e torna o claim visível para os outros workers.
    db.commit()

    if claim is None:
        _tratar_sem_claim(db, consulta_id)
        return None
    tentativa, documento, criado_em = claim

    if tentativa == 1:
        logger.info("processamento_iniciado")
    logger.info("integracao_tentativa", extra={"tentativa": tentativa})
    inicio = time.perf_counter()
    try:
        dados = cliente.consultar_cliente(documento)
    except ErroIntegracao as erro:
        return _tratar_erro(db, politica, consulta_id, erro, tentativa, inicio, criado_em)

    logger.info("integracao_sucesso", extra={"tentativa": tentativa, "duracao_ms": _ms_desde(inicio)})
    if _finalizar(db, consulta_id, StatusConsulta.SUCCESS, resultado=dados, ultimo_erro=None):
        _log_finalizada(StatusConsulta.SUCCESS, tentativa, criado_em)
    return None


def _tratar_erro(
    db: Session,
    politica: PoliticaRetry,
    consulta_id: uuid.UUID,
    erro: ErroIntegracao,
    tentativa: int,
    inicio: float,
    criado_em: datetime,
) -> Retentar | None:
    logger.warning(
        "integracao_erro",
        extra={
            "tentativa": tentativa,
            "tipo_erro": erro.tipo,
            "retentavel": erro.retentavel,
            "duracao_ms": _ms_desde(inicio),
        },
    )
    decisao = politica.decidir(retentavel=erro.retentavel, tentativa=tentativa)
    if decisao is None:
        if _finalizar(db, consulta_id, StatusConsulta.ERROR, ultimo_erro=erro.motivo):
            _log_finalizada(StatusConsulta.ERROR, tentativa, criado_em)
        return None

    registrado = _executar(
        db,
        update(Consulta)
        .where(Consulta.id == consulta_id, Consulta.status == StatusConsulta.PROCESSING)
        .values(ultimo_erro=erro.motivo),
    )
    if not registrado:
        logger.info("consulta_ignorada", extra={"motivo": "finalizada por outro worker"})
        return None
    logger.info("retry_agendado", extra={"tentativa": tentativa, "delay_s": round(decisao.delay_s, 3)})
    return decisao


def _tratar_sem_claim(db: Session, consulta_id: uuid.UUID) -> None:
    consulta = db.get(Consulta, consulta_id)
    if consulta is None:
        logger.warning("consulta_ignorada", extra={"motivo": "consulta inexistente"})
    elif consulta.status in STATUS_TERMINAIS:
        logger.info("consulta_ignorada", extra={"motivo": "consulta em estado terminal"})
    elif _finalizar(db, consulta_id, StatusConsulta.ERROR, ultimo_erro="limite de tentativas atingido"):
        # Em andamento mas sem tentativas: mensagem extra depois da última tentativa. Nunca passa do limite.
        _log_finalizada(StatusConsulta.ERROR, consulta.tentativas, consulta.criado_em)
    db.rollback()  # encerra a transação aberta pelo db.get


def _finalizar(db: Session, consulta_id: uuid.UUID, status: StatusConsulta, **valores: Any) -> bool:
    # Só finaliza o que ainda está em andamento: estados terminais nunca são sobrescritos.
    finalizou = _executar(
        db,
        update(Consulta)
        .where(Consulta.id == consulta_id, Consulta.status.in_(_EM_ANDAMENTO))
        .values(status=status, processado_em=datetime.now(UTC), **valores),
    )
    if not finalizou:
        logger.info("consulta_ignorada", extra={"motivo": "finalizada por outro worker"})
    return finalizou


def _executar(db: Session, comando: Any) -> bool:
    linhas = cast(CursorResult[Any], db.execute(comando)).rowcount
    db.commit()
    return linhas > 0


def _log_finalizada(status: StatusConsulta, tentativas: int, criado_em: datetime) -> None:
    criado_utc = criado_em.replace(tzinfo=UTC) if criado_em.tzinfo is None else criado_em
    duracao_total = int((datetime.now(UTC) - criado_utc).total_seconds() * 1000)
    logger.info(
        "consulta_finalizada",
        extra={"status": str(status), "tentativas": tentativas, "duracao_total_ms": duracao_total},
    )


def _ms_desde(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)
