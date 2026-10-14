"""Autenticação por X-API-Key (RF-10)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from customer_lookup.models import Consulta
from tests.fakes import PublicadorFake

ERRO_401 = {"error": {"code": "UNAUTHORIZED", "message": "Chave de API ausente ou inválida."}}
PAYLOAD = {"documento": "529.982.247-25", "tipo": "CPF"}


@pytest.fixture(params=["ausente", "errada", "vazia", "prefixo"])
def headers_invalidos(request: pytest.FixtureRequest) -> dict[str, str | None]:
    return {
        "ausente": {"X-API-Key": None},
        "errada": {"X-API-Key": "outra-chave"},
        "vazia": {"X-API-Key": ""},
        "prefixo": {"X-API-Key": "chave-de-test"},
    }[request.param]


def _sem_chave(client: TestClient, headers: dict[str, str | None]) -> TestClient:
    for nome, valor in headers.items():
        if valor is None:
            client.headers.pop(nome, None)
        else:
            client.headers[nome] = valor
    return client


def test_post_sem_chave_valida_retorna_401_e_nao_grava(
    client: TestClient, headers_invalidos, db: Session, publicador: PublicadorFake
):
    resp = _sem_chave(client, headers_invalidos).post("/api/v1/consultas", json=PAYLOAD)

    assert resp.status_code == 401
    assert resp.json() == ERRO_401
    assert db.scalar(select(func.count()).select_from(Consulta)) == 0
    assert publicador.publicacoes == []


@pytest.mark.parametrize("rota", ["/api/v1/consultas", f"/api/v1/consultas/{uuid.uuid4()}"])
def test_get_sem_chave_valida_retorna_401(client: TestClient, headers_invalidos, rota: str):
    resp = _sem_chave(client, headers_invalidos).get(rota)

    assert resp.status_code == 401
    assert resp.json() == ERRO_401


def test_401_vem_antes_da_validacao_do_payload(client: TestClient):
    # Sem chave, o cliente não deve aprender nada sobre o contrato (nem receber 422).
    resp = _sem_chave(client, {"X-API-Key": None}).post("/api/v1/consultas", json={"campo": "errado"})

    assert resp.status_code == 401


def test_chave_correta_e_aceita(client: TestClient):
    assert client.post("/api/v1/consultas", json=PAYLOAD).status_code == 202
    assert client.get("/api/v1/consultas").status_code == 200


@pytest.mark.parametrize("rota", ["/health", "/health/ready", "/docs", "/openapi.json"])
def test_rotas_publicas_nao_exigem_chave(client: TestClient, rota: str):
    resp = _sem_chave(client, {"X-API-Key": None}).get(rota)

    assert resp.status_code == 200


def test_comparacao_da_chave_em_tempo_constante(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import secrets

    from customer_lookup.api import deps

    original = secrets.compare_digest
    chamadas: list[tuple[bytes, bytes]] = []

    def compare_digest_espiao(a: bytes, b: bytes) -> bool:
        chamadas.append((a, b))
        return original(a, b)

    monkeypatch.setattr(deps.secrets, "compare_digest", compare_digest_espiao)

    client.get("/api/v1/consultas")

    assert chamadas == [(b"chave-de-teste", b"chave-de-teste")]


def test_openapi_declara_o_esquema_de_seguranca(client: TestClient):
    esquema = client.get("/openapi.json").json()

    assert esquema["components"]["securitySchemes"] == {
        "APIKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }
