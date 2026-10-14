"""Task Celery: casca fina que monta as dependências, restaura o contexto e aplica a decisão de retry."""

import logging
import uuid

import pytest
from celery.exceptions import Retry
from sqlalchemy.exc import OperationalError

from customer_lookup.core import contexto
from customer_lookup.core.dominio import StatusConsulta
from customer_lookup.core.logging import LOGGER_NAME
from customer_lookup.models import Consulta
from customer_lookup.ports import ErroIntegracao
from customer_lookup.services.politica_retry import PoliticaRetry, Retentar
from customer_lookup.worker import tasks
from customer_lookup.worker.tasks import processar_consulta_task
from tests.fakes import ClienteExternoFake

SUCESSO = {"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"}
HTTP_503 = ErroIntegracao("serviço externo respondeu HTTP 503", tipo="http_503", retentavel=True)


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch, session_factory):
    """Liga a task ao banco de teste, a um cliente fake e a uma política sem espera."""
    cliente = ClienteExternoFake([SUCESSO])
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "cliente_externo", lambda: cliente)
    monkeypatch.setattr(
        tasks, "politica_retry", lambda: PoliticaRetry(3, base_segundos=0.01, teto_segundos=0.01, aleatorio=lambda: 0.5)
    )
    return cliente


def _executar(consulta_id: uuid.UUID, request_id: str | None = "req-worker"):
    # apply() roda a task no próprio processo (modo eager); retries também rodam na hora, sem countdown.
    return processar_consulta_task.apply(args=[str(consulta_id), request_id])


def _recarregar(db, consulta_id: uuid.UUID) -> Consulta:
    db.expire_all()
    return db.get(Consulta, consulta_id)


def test_task_processa_com_sucesso(worker: ClienteExternoFake, db, criar_consulta):
    consulta = criar_consulta()

    resultado = _executar(consulta.id)

    assert resultado.successful()
    assert _recarregar(db, consulta.id).status is StatusConsulta.SUCCESS


def test_task_reagenda_ate_recuperar(worker: ClienteExternoFake, db, criar_consulta):
    worker.roteiro = [HTTP_503, HTTP_503, SUCESSO]
    consulta = criar_consulta()

    _executar(consulta.id)

    final = _recarregar(db, consulta.id)
    assert final.status is StatusConsulta.SUCCESS
    assert final.tentativas == 3


def test_task_para_no_limite_de_tentativas(worker: ClienteExternoFake, db, criar_consulta):
    worker.roteiro = [HTTP_503]
    consulta = criar_consulta()

    _executar(consulta.id)

    final = _recarregar(db, consulta.id)
    assert final.status is StatusConsulta.ERROR
    assert final.tentativas == 3
    assert len(worker.chamadas) == 3


def test_decisao_de_retry_vira_countdown_do_celery(monkeypatch: pytest.MonkeyPatch, worker, criar_consulta):
    pedidos: list[dict[str, object]] = []

    def retry_falso(**kwargs: object) -> Retry:
        pedidos.append(kwargs)
        return Retry()

    monkeypatch.setattr(tasks, "processar_consulta", lambda *a, **k: Retentar(delay_s=3.25))
    monkeypatch.setattr(processar_consulta_task, "retry", retry_falso)

    _executar(criar_consulta().id)

    assert pedidos == [{"countdown": 3.25}]


def test_banco_indisponivel_reagenda_com_limite(monkeypatch: pytest.MonkeyPatch, worker, criar_consulta):
    pedidos: list[dict[str, object]] = []
    falha = OperationalError("SELECT 1", {}, ConnectionError("db fora"))

    def banco_fora(*_: object, **__: object) -> None:
        raise falha

    def retry_falso(**kwargs: object) -> Retry:
        pedidos.append(kwargs)
        return Retry()

    monkeypatch.setattr(tasks, "processar_consulta", banco_fora)
    monkeypatch.setattr(processar_consulta_task, "retry", retry_falso)

    _executar(criar_consulta().id)

    assert len(pedidos) == 1
    assert pedidos[0]["exc"] is falha
    assert pedidos[0]["max_retries"] == tasks.MAX_RETRIES_BANCO
    assert pedidos[0]["countdown"] > 0


def test_logs_do_worker_tem_request_id_da_requisicao_original(worker, criar_consulta, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    consulta = criar_consulta()

    _executar(consulta.id, request_id="req-original")

    registros = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert registros
    assert all(r.request_id == "req-original" for r in registros)
    assert all(r.consulta_id == str(consulta.id) for r in registros)


def test_contexto_e_limpo_depois_da_task(worker, criar_consulta):
    _executar(criar_consulta().id, request_id="req-x")

    assert contexto.request_id.get() is None
    assert contexto.consulta_id.get() is None
