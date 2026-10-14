"""Fluxo completo sem Docker: API → publicador Celery (modo eager) → task → serviço externo fake → banco."""

import logging

import pytest
from fastapi.testclient import TestClient

from customer_lookup.adapters.publicador_celery import PublicadorCelery
from customer_lookup.api.deps import get_publicador
from customer_lookup.core.logging import LOGGER_NAME
from customer_lookup.ports import ErroIntegracao
from customer_lookup.services.politica_retry import PoliticaRetry
from customer_lookup.worker import tasks
from customer_lookup.worker.celery_app import celery_app
from tests.fakes import ClienteExternoFake

SUCESSO = {"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"}
HTTP_503 = ErroIntegracao("serviço externo respondeu HTTP 503", tipo="http_503", retentavel=True)
HTTP_404 = ErroIntegracao("cliente não encontrado no serviço externo", tipo="http_404", retentavel=False)


@pytest.fixture
def externo(app, client: TestClient, monkeypatch: pytest.MonkeyPatch, session_factory) -> ClienteExternoFake:
    cliente = ClienteExternoFake([SUCESSO])
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "cliente_externo", lambda: cliente)
    monkeypatch.setattr(
        tasks, "politica_retry", lambda: PoliticaRetry(5, base_segundos=0.01, teto_segundos=0.01, aleatorio=lambda: 0.5)
    )
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    # Sem task_eager_propagates: no modo eager ele faria o Retry (reagendamento) subir até o apply_async.
    app.dependency_overrides[get_publicador] = PublicadorCelery
    return cliente


def _criar_e_consultar(client: TestClient, documento: str, request_id: str = "req-fluxo") -> dict[str, object]:
    resp = client.post(
        "/api/v1/consultas", json={"documento": documento, "tipo": "CPF"}, headers={"X-Request-ID": request_id}
    )
    assert resp.status_code == 202
    return client.get(resp.headers["Location"]).json()


def test_fluxo_de_sucesso(client: TestClient, externo: ClienteExternoFake):
    consulta = _criar_e_consultar(client, "529.982.247-25")

    assert consulta["status"] == "SUCCESS"
    assert consulta["resultado"] == SUCESSO
    assert consulta["tentativas"] == 1
    assert externo.chamadas[0].documento == "52998224725"


def test_fluxo_com_falha_temporaria_que_se_recupera(client: TestClient, externo: ClienteExternoFake):
    externo.roteiro = [HTTP_503, HTTP_503, SUCESSO]

    consulta = _criar_e_consultar(client, "111.444.781-11")

    assert consulta["status"] == "SUCCESS"
    assert consulta["tentativas"] == 3
    assert consulta["ultimo_erro"] is None


def test_fluxo_com_falha_na_integracao_externa(client: TestClient, externo: ClienteExternoFake):
    externo.roteiro = [HTTP_404]

    consulta = _criar_e_consultar(client, "111.444.783-83")

    assert consulta["status"] == "ERROR"
    assert consulta["tentativas"] == 1
    assert consulta["ultimo_erro"] == "cliente não encontrado no serviço externo"
    assert consulta["processado_em"] is not None


def test_request_id_liga_os_logs_da_api_e_do_worker(
    client: TestClient, externo: ClienteExternoFake, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    _criar_e_consultar(client, "529.982.247-25", request_id="req-ponta-a-ponta")

    eventos = {r.getMessage(): r.request_id for r in caplog.records if r.name == LOGGER_NAME}
    assert eventos["consulta_criada"] == "req-ponta-a-ponta"
    assert eventos["integracao_sucesso"] == "req-ponta-a-ponta"
    assert eventos["consulta_finalizada"] == "req-ponta-a-ponta"
