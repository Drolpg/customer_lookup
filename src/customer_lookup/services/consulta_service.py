"""Casos de uso da consulta: criar, obter e listar."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from customer_lookup.core import documento as doc
from customer_lookup.core.dominio import StatusConsulta, TipoDocumento
from customer_lookup.core.errors import ConsultaNaoEncontrada, FilaIndisponivel
from customer_lookup.core.logging import LOGGER_NAME
from customer_lookup.models import Consulta
from customer_lookup.ports import FalhaAoPublicar, PublicadorDeTarefas

logger = logging.getLogger(LOGGER_NAME)


def criar(
    db: Session,
    publicador: PublicadorDeTarefas,
    *,
    documento: str,
    tipo: TipoDocumento,
    validar_dv: bool,
    request_id: str | None,
) -> Consulta:
    digitos = doc.validar(documento, tipo, validar_dv=validar_dv)
    consulta = Consulta(
        id=uuid.uuid4(),
        documento=digitos,
        tipo=tipo,
        status=StatusConsulta.PENDING,
        tentativas=0,
        request_id=request_id,
    )
    db.add(consulta)
    # Commit antes de publicar: o worker nunca recebe um id que ainda não existe para a conexão dele.
    db.commit()
    log = {"consulta_id": str(consulta.id)}
    logger.info("consulta_criada", extra={**log, "tipo": str(tipo)})

    try:
        publicador.publicar_processamento(consulta.id, request_id)
    except FalhaAoPublicar as exc:
        # Sem isso a consulta ficaria PENDING para sempre: ninguém vai processá-la.
        _marcar_falha_de_fila(db, consulta.id)
        causa = exc.__cause__ or exc
        logger.error("falha_ao_enfileirar", extra={**log, "erro": type(causa).__name__})
        raise FilaIndisponivel(str(consulta.id)) from exc

    logger.info("consulta_enfileirada", extra=log)
    return consulta


def _marcar_falha_de_fila(db: Session, consulta_id: uuid.UUID) -> None:
    db.execute(
        update(Consulta)
        .where(Consulta.id == consulta_id, Consulta.status == StatusConsulta.PENDING)
        .values(status=StatusConsulta.ERROR, ultimo_erro="fila indisponível", processado_em=datetime.now(UTC))
    )
    db.commit()


def obter(db: Session, consulta_id: uuid.UUID) -> Consulta:
    consulta = db.get(Consulta, consulta_id)
    if consulta is None:
        raise ConsultaNaoEncontrada()
    return consulta


def listar(
    db: Session,
    *,
    status: StatusConsulta | None,
    documento: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Consulta], int]:
    filtro = select(Consulta)
    if status is not None:
        filtro = filtro.where(Consulta.status == status)
    if documento is not None:
        filtro = filtro.where(Consulta.documento == doc.normalizar(documento))

    total = db.scalar(select(func.count()).select_from(filtro.subquery())) or 0
    # id como desempate: sem ele, consultas com o mesmo criado_em podem aparecer em duas páginas.
    pagina = filtro.order_by(Consulta.criado_em.desc(), Consulta.id.desc()).offset((page - 1) * page_size)
    itens = db.scalars(pagina.limit(page_size)).all()
    return list(itens), total
