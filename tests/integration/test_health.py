"""Liveness e readiness (RF-12)."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from customer_lookup.core.logging import LOGGER_NAME
from tests.fakes import RedisFora


def test_health_responde_ok(client: TestClient):
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_com_dependencias_no_ar(client: TestClient):
    resp = client.get("/health/ready")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.fixture
def redis_fora(app):
    from customer_lookup.api.deps import get_redis

    app.dependency_overrides[get_redis] = RedisFora


@pytest.fixture
def banco_fora(app, tmp_path):
    from customer_lookup.db.session import get_db

    # Diretório inexistente: o SQLite falha ao abrir o arquivo, como um banco fora do ar.
    fabrica = sessionmaker(bind=create_engine(f"sqlite:///{tmp_path / 'nao-existe' / 'x.db'}"))

    def _get_db():
        with fabrica() as sessao:
            yield sessao

    app.dependency_overrides[get_db] = _get_db


def test_ready_com_redis_fora_retorna_503(client: TestClient, redis_fora, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)

    resp = client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "Serviço indisponível.",
            "details": [{"component": "redis", "status": "indisponível"}],
        }
    }
    registro = next(r for r in caplog.records if r.getMessage() == "readiness_falhou")
    assert registro.componentes == ["redis"]


def test_ready_com_banco_fora_retorna_503(client: TestClient, banco_fora):
    resp = client.get("/health/ready")

    assert resp.status_code == 503
    assert resp.json()["error"]["details"] == [{"component": "database", "status": "indisponível"}]


def test_ready_com_tudo_fora_lista_os_dois(client: TestClient, banco_fora, redis_fora):
    resp = client.get("/health/ready")

    componentes = [d["component"] for d in resp.json()["error"]["details"]]
    assert componentes == ["database", "redis"]


def test_liveness_nao_depende_do_banco_nem_do_redis(client: TestClient, banco_fora, redis_fora):
    # Se o liveness dependesse deles, o orquestrador reiniciaria a API à toa durante uma queda do banco.
    assert client.get("/health").status_code == 200
