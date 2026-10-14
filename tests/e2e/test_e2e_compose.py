"""Ponta a ponta contra o `docker compose up` em execução (Postgres, Redis, worker e fake reais).

Rode com:  docker compose up -d --build  &&  uv run pytest -m e2e
"""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.e2e

API = os.environ.get("E2E_API_URL", "http://localhost:8000")
FAKE = os.environ.get("E2E_FAKE_URL", "http://localhost:9000")
API_KEY = os.environ.get("E2E_API_KEY", "chave-local-de-desenvolvimento")
TERMINAIS = {"SUCCESS", "ERROR"}


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    with httpx.Client(base_url=API, headers={"X-API-Key": API_KEY}, timeout=10) as cliente:
        yield cliente


@pytest.fixture(autouse=True)
def fake_zerado() -> None:
    httpx.post(f"{FAKE}/fake/reset", timeout=5).raise_for_status()


def _criar(api: httpx.Client, documento: str, tipo: str = "CPF") -> str:
    resp = api.post("/api/v1/consultas", json={"documento": documento, "tipo": tipo})
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "PENDING"
    return resp.json()["id"]


def _aguardar(api: httpx.Client, consulta_id: str, limite_s: float = 90) -> dict:
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        consulta = api.get(f"/api/v1/consultas/{consulta_id}").json()
        if consulta["status"] in TERMINAIS:
            return consulta
        time.sleep(0.5)
    pytest.fail(f"consulta {consulta_id} não terminou em {limite_s}s")


def _chamadas_no_fake(documento: str) -> int:
    return httpx.get(f"{FAKE}/fake/chamadas", timeout=5).json().get(documento, 0)


def test_readiness_com_tudo_no_ar():
    assert httpx.get(f"{API}/health/ready", timeout=5).json()["checks"] == {"database": "ok", "redis": "ok"}


def test_sem_chave_retorna_401():
    assert httpx.get(f"{API}/api/v1/consultas", timeout=5).status_code == 401


def test_sucesso(api: httpx.Client):
    consulta = _aguardar(api, _criar(api, "529.982.247-25"))

    assert consulta["status"] == "SUCCESS"
    assert consulta["tentativas"] == 1
    assert consulta["resultado"]["nome"] == "Cliente Teste"
    assert consulta["processado_em"] is not None


def test_falha_temporaria_se_recupera_no_retry(api: httpx.Client):
    consulta = _aguardar(api, _criar(api, "111.444.781-11"))

    assert consulta["status"] == "SUCCESS"
    assert consulta["tentativas"] == 3
    assert consulta["ultimo_erro"] is None
    assert _chamadas_no_fake("11144478111") == 3


def test_lentidao_vira_timeout_e_se_recupera(api: httpx.Client):
    consulta = _aguardar(api, _criar(api, "111.444.790-02"))

    assert consulta["status"] == "SUCCESS"
    assert consulta["tentativas"] == 3


def test_falha_persistente_esgota_as_tentativas(api: httpx.Client):
    consulta = _aguardar(api, _criar(api, "111.444.780-30"))

    assert consulta["status"] == "ERROR"
    assert consulta["tentativas"] == 5
    assert consulta["ultimo_erro"] == "serviço externo respondeu HTTP 500"
    assert _chamadas_no_fake("11144478030") == 5


def test_erro_permanente_nao_tem_retry(api: httpx.Client):
    consulta = _aguardar(api, _criar(api, "111.444.783-83"))

    assert consulta["status"] == "ERROR"
    assert consulta["tentativas"] == 1
    assert consulta["ultimo_erro"] == "cliente não encontrado no serviço externo"


def test_listagem_filtra_por_documento_e_status(api: httpx.Client):
    consulta_id = _criar(api, "11.222.333/0004-24", tipo="CNPJ")
    _aguardar(api, consulta_id)

    pagina = api.get("/api/v1/consultas", params={"documento": "11.222.333/0004-24", "status": "SUCCESS"}).json()

    assert consulta_id in [item["id"] for item in pagina["items"]]
