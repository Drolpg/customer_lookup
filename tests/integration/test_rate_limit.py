"""Rate limit no POST por chave de API, janela fixa no Redis (RF-11)."""

import logging

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from customer_lookup.core.config import Settings, get_settings
from customer_lookup.core.logging import LOGGER_NAME
from customer_lookup.models import Consulta
from customer_lookup.services.rate_limit import LimitadorDeTaxa
from tests.fakes import API_KEY_TESTE, RedisFora

PAYLOAD = {"documento": "529.982.247-25", "tipo": "CPF"}


class Relogio:
    def __init__(self, agora: float) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora


# ---------- unidade: o limitador ----------


def test_permite_ate_o_limite_e_bloqueia_depois():
    limitador = LimitadorDeTaxa(fakeredis.FakeRedis(), limite=3, relogio=Relogio(120.0))

    assert [limitador.verificar("k") for _ in range(4)] == [None, None, None, 60]


def test_retry_after_e_o_tempo_ate_o_fim_da_janela():
    limitador = LimitadorDeTaxa(fakeredis.FakeRedis(), limite=1, relogio=Relogio(125.4))
    limitador.verificar("k")

    assert limitador.verificar("k") == 55  # janela [120, 180): faltam 54,6 s → arredonda para cima


def test_nova_janela_zera_a_contagem():
    relogio = Relogio(120.0)
    limitador = LimitadorDeTaxa(fakeredis.FakeRedis(), limite=1, relogio=relogio)
    limitador.verificar("k")
    assert limitador.verificar("k") is not None

    relogio.agora = 180.0

    assert limitador.verificar("k") is None


def test_chaves_diferentes_tem_contagens_independentes():
    limitador = LimitadorDeTaxa(fakeredis.FakeRedis(), limite=1, relogio=Relogio(0.0))

    assert limitador.verificar("a") is None
    assert limitador.verificar("b") is None
    assert limitador.verificar("a") is not None


def test_chave_no_redis_expira_e_nao_contem_a_api_key():
    servidor = fakeredis.FakeRedis()
    LimitadorDeTaxa(servidor, limite=5, relogio=Relogio(0.0)).verificar("segredo-123")

    chaves = servidor.keys("*")
    assert len(chaves) == 1
    assert b"segredo-123" not in chaves[0]
    assert 0 < servidor.ttl(chaves[0]) <= 60


def test_redis_fora_libera_a_requisicao_e_loga(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    assert LimitadorDeTaxa(RedisFora(), limite=1).verificar("k") is None
    assert any(r.getMessage() == "rate_limit_indisponivel" for r in caplog.records)


# ---------- integração: a API ----------


@pytest.fixture
def limite_3(app):
    app.dependency_overrides[get_settings] = lambda: Settings(api_key=API_KEY_TESTE, rate_limit_por_minuto=3)


def test_post_acima_do_limite_retorna_429_com_retry_after(client: TestClient, limite_3, db: Session):
    respostas = [client.post("/api/v1/consultas", json=PAYLOAD) for _ in range(4)]

    assert [r.status_code for r in respostas] == [202, 202, 202, 429]
    excedida = respostas[-1]
    assert excedida.json() == {
        "error": {"code": "RATE_LIMITED", "message": "Limite de requisições excedido. Tente novamente mais tarde."}
    }
    assert 1 <= int(excedida.headers["Retry-After"]) <= 60
    assert db.scalar(select(func.count()).select_from(Consulta)) == 3


def test_get_nao_e_limitado(client: TestClient, limite_3):
    assert {client.get("/api/v1/consultas").status_code for _ in range(10)} == {200}


def test_requisicao_sem_chave_nao_consome_o_limite(client: TestClient, limite_3, redis_fake):
    client.post("/api/v1/consultas", json=PAYLOAD, headers={"X-API-Key": "errada"})

    assert redis_fake.keys("*") == []


def test_api_continua_funcionando_com_redis_fora(app, client: TestClient, caplog: pytest.LogCaptureFixture):
    from customer_lookup.api.deps import get_redis

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    app.dependency_overrides[get_redis] = RedisFora

    resp = client.post("/api/v1/consultas", json=PAYLOAD)

    assert resp.status_code == 202
    assert any(r.getMessage() == "rate_limit_indisponivel" for r in caplog.records)
