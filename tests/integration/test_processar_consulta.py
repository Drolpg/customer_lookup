"""Processamento da consulta pelo worker (RN-02 a RN-06, RNF-02)."""

import logging
import uuid

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from customer_lookup.core.dominio import StatusConsulta
from customer_lookup.core.logging import LOGGER_NAME, JsonFormatter
from customer_lookup.models import Consulta
from customer_lookup.ports import ErroIntegracao
from customer_lookup.services.politica_retry import PoliticaRetry, Retentar
from customer_lookup.services.processamento import processar_consulta
from tests.fakes import ClienteExternoFake

SUCESSO = {"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"}
HTTP_503 = ErroIntegracao("serviço externo respondeu HTTP 503", tipo="http_503", retentavel=True)
HTTP_500 = ErroIntegracao("serviço externo respondeu HTTP 500", tipo="http_500", retentavel=True)
HTTP_404 = ErroIntegracao("cliente não encontrado no serviço externo", tipo="http_404", retentavel=False)
POLITICA = PoliticaRetry(max_tentativas=3, base_segundos=2.0, teto_segundos=60.0, aleatorio=lambda: 0.5)


def _processar(db: Session, cliente: ClienteExternoFake, consulta: Consulta) -> Retentar | None:
    return processar_consulta(db, cliente, POLITICA, consulta.id)


def _recarregar(db: Session, consulta: Consulta) -> Consulta:
    db.expire_all()
    return db.get(Consulta, consulta.id)


def test_sucesso_grava_resultado_e_finaliza(db: Session, criar_consulta):
    consulta = criar_consulta()
    cliente = ClienteExternoFake([SUCESSO])

    assert _processar(db, cliente, consulta) is None

    final = _recarregar(db, consulta)
    assert final.status is StatusConsulta.SUCCESS
    assert final.resultado == SUCESSO
    assert final.tentativas == 1
    assert final.ultimo_erro is None
    assert final.processado_em is not None
    assert [c.documento for c in cliente.chamadas] == ["52998224725"]


def test_erro_transitorio_mantem_processing_e_pede_retry(db: Session, criar_consulta):
    consulta = criar_consulta()

    decisao = _processar(db, ClienteExternoFake([HTTP_503]), consulta)

    assert decisao == Retentar(delay_s=2.0)
    final = _recarregar(db, consulta)
    assert final.status is StatusConsulta.PROCESSING
    assert final.tentativas == 1
    assert final.ultimo_erro == "serviço externo respondeu HTTP 503"
    assert final.processado_em is None


def test_recupera_depois_de_falhas_transitorias_e_limpa_o_ultimo_erro(db: Session, criar_consulta):
    consulta = criar_consulta()
    cliente = ClienteExternoFake([HTTP_503, HTTP_503, SUCESSO])

    decisoes = [_processar(db, cliente, consulta) for _ in range(3)]

    assert decisoes == [Retentar(delay_s=2.0), Retentar(delay_s=4.0), None]
    final = _recarregar(db, consulta)
    assert final.status is StatusConsulta.SUCCESS
    assert final.tentativas == 3
    assert final.ultimo_erro is None


def test_esgota_as_tentativas_e_finaliza_com_erro(db: Session, criar_consulta):
    consulta = criar_consulta()
    cliente = ClienteExternoFake([HTTP_500])

    decisoes = [_processar(db, cliente, consulta) for _ in range(3)]

    assert decisoes == [Retentar(delay_s=2.0), Retentar(delay_s=4.0), None]
    final = _recarregar(db, consulta)
    assert final.status is StatusConsulta.ERROR
    assert final.tentativas == 3
    assert final.ultimo_erro == "serviço externo respondeu HTTP 500"
    assert final.processado_em is not None
    assert len(cliente.chamadas) == 3


def test_erro_permanente_finaliza_sem_retry(db: Session, criar_consulta):
    consulta = criar_consulta()

    assert _processar(db, ClienteExternoFake([HTTP_404]), consulta) is None

    final = _recarregar(db, consulta)
    assert final.status is StatusConsulta.ERROR
    assert final.tentativas == 1
    assert final.ultimo_erro == "cliente não encontrado no serviço externo"


@pytest.mark.parametrize("status", [StatusConsulta.SUCCESS, StatusConsulta.ERROR])
def test_estado_terminal_nao_e_reprocessado(db: Session, criar_consulta, status: StatusConsulta):
    # Mensagem reentregue (acks_late) depois de a consulta já ter terminado.
    consulta = criar_consulta(status=status, tentativas=1, resultado={"original": True})
    cliente = ClienteExternoFake([SUCESSO])

    assert _processar(db, cliente, consulta) is None

    final = _recarregar(db, consulta)
    assert cliente.chamadas == []
    assert (final.status, final.tentativas, final.resultado) == (status, 1, {"original": True})


def test_consulta_inexistente_e_ignorada(db: Session):
    cliente = ClienteExternoFake([SUCESSO])

    assert processar_consulta(db, cliente, POLITICA, uuid.uuid4()) is None
    assert cliente.chamadas == []


def test_limite_ja_atingido_finaliza_sem_chamar_o_externo(db: Session, criar_consulta):
    # Ex.: mensagem duplicada depois da última tentativa, com a consulta ainda em PROCESSING.
    consulta = criar_consulta(
        status=StatusConsulta.PROCESSING, tentativas=3, ultimo_erro="serviço externo respondeu HTTP 500"
    )
    cliente = ClienteExternoFake([SUCESSO])

    assert _processar(db, cliente, consulta) is None

    final = _recarregar(db, consulta)
    assert cliente.chamadas == []
    assert final.status is StatusConsulta.ERROR
    assert final.tentativas == 3
    assert final.ultimo_erro == "limite de tentativas atingido"
    assert final.processado_em is not None


def test_nenhuma_transacao_aberta_durante_a_chamada_externa(
    db: Session, session_factory: sessionmaker[Session], criar_consulta
):
    consulta = criar_consulta()
    visto_por_outra_conexao: list[tuple[StatusConsulta, int]] = []

    def observar() -> None:
        with session_factory() as outra:
            c = outra.get(Consulta, consulta.id)
            visto_por_outra_conexao.append((c.status, c.tentativas))

    cliente = ClienteExternoFake([SUCESSO], sessao_observada=db, ao_chamar=observar)

    _processar(db, cliente, consulta)

    assert cliente.chamadas[0].transacao_aberta is False
    # O claim já estava commitado quando a chamada começou.
    assert visto_por_outra_conexao == [(StatusConsulta.PROCESSING, 1)]


def test_nao_sobrescreve_consulta_finalizada_por_outro_worker(
    db: Session, session_factory: sessionmaker[Session], criar_consulta
):
    consulta = criar_consulta()

    def outro_worker_finaliza() -> None:
        with session_factory() as outra:
            outra.execute(
                update(Consulta)
                .where(Consulta.id == consulta.id)
                .values(status=StatusConsulta.ERROR, ultimo_erro="decidido por outro worker")
            )
            outra.commit()

    _processar(db, ClienteExternoFake([SUCESSO], ao_chamar=outro_worker_finaliza), consulta)

    final = _recarregar(db, consulta)
    assert final.status is StatusConsulta.ERROR
    assert final.ultimo_erro == "decidido por outro worker"
    assert final.resultado is None


def test_logs_do_sucesso(db: Session, criar_consulta, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    consulta = criar_consulta()

    _processar(db, ClienteExternoFake([SUCESSO]), consulta)

    eventos = {r.getMessage(): r for r in caplog.records}
    assert {"processamento_iniciado", "integracao_tentativa", "integracao_sucesso", "consulta_finalizada"} <= set(
        eventos
    )
    assert all(r.consulta_id == str(consulta.id) for r in caplog.records)
    assert eventos["integracao_tentativa"].tentativa == 1
    assert eventos["integracao_sucesso"].duracao_ms >= 0
    assert eventos["consulta_finalizada"].status == "SUCCESS"
    assert eventos["consulta_finalizada"].tentativas == 1
    assert eventos["consulta_finalizada"].duracao_total_ms >= 0


def test_logs_do_erro_e_do_retry_sem_o_documento(db: Session, criar_consulta, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    consulta = criar_consulta()

    _processar(db, ClienteExternoFake([HTTP_503]), consulta)

    eventos = {r.getMessage(): r for r in caplog.records}
    erro = eventos["integracao_erro"]
    assert erro.levelno == logging.WARNING
    assert (erro.tentativa, erro.tipo_erro, erro.retentavel) == (1, "http_503", True)
    assert erro.duracao_ms >= 0
    assert eventos["retry_agendado"].delay_s == 2.0
    assert all("52998224725" not in JsonFormatter().format(r) for r in caplog.records)


def test_consulta_ignorada_e_logada_com_motivo(db: Session, criar_consulta, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    consulta = criar_consulta(status=StatusConsulta.SUCCESS)

    _processar(db, ClienteExternoFake([SUCESSO]), consulta)

    registro = next(r for r in caplog.records if r.getMessage() == "consulta_ignorada")
    assert registro.motivo == "consulta em estado terminal"


def test_contexto_da_consulta_e_limpo_ao_final(db: Session, criar_consulta):
    from customer_lookup.core import contexto

    _processar(db, ClienteExternoFake([SUCESSO]), criar_consulta())

    assert contexto.consulta_id.get() is None
