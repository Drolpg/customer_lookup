"""Envelope de erro único, X-Request-ID e logs do tratamento global (RF-13, RF-14)."""

import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from customer_lookup.core.errors import AppError
from customer_lookup.core.logging import LOGGER_NAME


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str


@pytest.fixture
def client(app: FastAPI):
    """Cliente com rotas extras usadas só para exercitar os handlers globais."""

    @app.get("/_teste/erro-inesperado")
    def erro_inesperado() -> None:
        raise RuntimeError("detalhe interno: senha=123")

    @app.get("/_teste/erro-de-app")
    def erro_de_app() -> None:
        raise AppError(
            "Algo previsto.",
            code="ALGO_PREVISTO",
            status_code=409,
            details=[{"field": "x", "message": "y"}],
            headers={"Retry-After": "7"},
        )

    @app.post("/_teste/payload")
    def payload(_: _Payload) -> dict[str, str]:
        return {"ok": "sim"}

    @app.get("/_teste/log")
    def gera_log() -> dict[str, str]:
        logging.getLogger(LOGGER_NAME).info("evento_na_requisicao")
        return {"ok": "sim"}

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_rota_inexistente_retorna_404_no_envelope(client: TestClient):
    resp = client.get("/nao-existe")

    assert resp.status_code == 404
    assert resp.json() == {"error": {"code": "NOT_FOUND", "message": "Recurso não encontrado."}}
    assert resp.headers["X-Request-ID"]


def test_metodo_nao_permitido_retorna_405_no_envelope(client: TestClient):
    resp = client.delete("/health")

    assert resp.status_code == 405
    assert resp.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_erro_inesperado_retorna_500_sem_vazar_detalhe(client: TestClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)

    resp = client.get("/_teste/erro-inesperado", headers={"X-Request-ID": "req-500"})

    assert resp.status_code == 500
    corpo = resp.json()
    assert corpo == {
        "error": {"code": "INTERNAL_ERROR", "message": "Erro interno do servidor.", "request_id": "req-500"}
    }
    assert "senha" not in resp.text
    assert "RuntimeError" not in resp.text
    assert resp.headers["X-Request-ID"] == "req-500"

    registro = next(r for r in caplog.records if r.getMessage() == "erro_inesperado")
    assert registro.request_id == "req-500"
    assert registro.exc_info is not None


def test_app_error_usa_status_codigo_detalhes_e_headers(client: TestClient):
    resp = client.get("/_teste/erro-de-app")

    assert resp.status_code == 409
    assert resp.json() == {
        "error": {
            "code": "ALGO_PREVISTO",
            "message": "Algo previsto.",
            "details": [{"field": "x", "message": "y"}],
        }
    }
    assert resp.headers["Retry-After"] == "7"
    assert resp.headers["X-Request-ID"]


def test_payload_invalido_retorna_422_com_campos_em_portugues(client: TestClient):
    resp = client.post("/_teste/payload", json={"extra": 1})

    assert resp.status_code == 422
    erro = resp.json()["error"]
    assert erro["code"] == "VALIDATION_ERROR"
    assert erro["message"] == "Payload inválido."
    assert {"field": "nome", "message": "campo obrigatório"} in erro["details"]
    assert {"field": "extra", "message": "campo não permitido"} in erro["details"]


def test_json_malformado_retorna_422_apontando_o_corpo(client: TestClient):
    resp = client.post("/_teste/payload", content=b"{nome:", headers={"Content-Type": "application/json"})

    assert resp.status_code == 422
    assert resp.json()["error"]["details"] == [{"field": "body", "message": "JSON malformado"}]


def test_request_id_do_cliente_e_propagado(client: TestClient):
    resp = client.get("/health", headers={"X-Request-ID": "abc-123_x.y"})

    assert resp.headers["X-Request-ID"] == "abc-123_x.y"


def test_request_id_e_gerado_quando_ausente(client: TestClient):
    resp = client.get("/health")

    uuid.UUID(resp.headers["X-Request-ID"])


@pytest.mark.parametrize("invalido", ["a" * 65, "com espaco", "quebra\rlinha", ""])
def test_request_id_invalido_e_substituido(client: TestClient, invalido: str):
    # Valor arbitrário do cliente iria parar nos logs: só aceitamos um formato seguro.
    resp = client.get("/health", headers={"X-Request-ID": invalido})

    uuid.UUID(resp.headers["X-Request-ID"])


def test_logs_durante_a_requisicao_carregam_o_request_id(client: TestClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    client.get("/_teste/log", headers={"X-Request-ID": "req-log"})

    registro = next(r for r in caplog.records if r.getMessage() == "evento_na_requisicao")
    assert registro.request_id == "req-log"
