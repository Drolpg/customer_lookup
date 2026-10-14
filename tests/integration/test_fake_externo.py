"""API externa fake: cenários determinísticos pelo último dígito do documento (RF-09, spec §8)."""

import time

import pytest
from fastapi.testclient import TestClient

from customer_lookup.fake_externo.app import create_app

URL = "/fake/customer"
LENTIDAO = 0.3


@pytest.fixture
def fake() -> TestClient:
    with TestClient(create_app(falhas_antes_de_recuperar=2, lentidao_segundos=LENTIDAO)) as c:
        yield c


def _chamar(fake: TestClient, documento: str) -> int:
    return fake.post(URL, json={"documento": documento}).status_code


@pytest.mark.parametrize("documento", ["52998224725", "39053345264", "11222333000424"])
def test_demais_digitos_retornam_sucesso_deterministico(fake: TestClient, documento: str):
    primeira = fake.post(URL, json={"documento": documento})
    segunda = fake.post(URL, json={"documento": documento})

    assert primeira.status_code == 200
    corpo = primeira.json()
    assert corpo == segunda.json()
    assert set(corpo) == {"nome", "score", "situacao"}
    assert corpo["nome"] == "Cliente Teste"
    assert corpo["situacao"] == "REGULAR"
    assert 300 <= corpo["score"] <= 900


def test_score_depende_do_documento(fake: TestClient):
    a = fake.post(URL, json={"documento": "52998224725"}).json()["score"]
    b = fake.post(URL, json={"documento": "39053345264"}).json()["score"]

    assert a == 300 + 52998224725 % 601
    assert a != b


def test_final_0_falha_sempre_com_500(fake: TestClient):
    assert [_chamar(fake, "11144478030") for _ in range(5)] == [500] * 5


def test_final_1_responde_503_nas_primeiras_chamadas_e_depois_recupera(fake: TestClient):
    assert [_chamar(fake, "11144478111") for _ in range(4)] == [503, 503, 200, 200]


def test_final_2_e_lento_nas_primeiras_chamadas_e_depois_rapido(fake: TestClient):
    duracoes = []
    for _ in range(3):
        inicio = time.perf_counter()
        assert _chamar(fake, "11144479002") == 200
        duracoes.append(time.perf_counter() - inicio)

    assert duracoes[0] >= LENTIDAO
    assert duracoes[1] >= LENTIDAO
    assert duracoes[2] < LENTIDAO


def test_final_3_retorna_404_cliente_nao_encontrado(fake: TestClient):
    resp = fake.post(URL, json={"documento": "11144478383"})

    assert resp.status_code == 404
    assert resp.json() == {"detail": "cliente não encontrado"}


def test_contadores_sao_independentes_por_documento(fake: TestClient):
    assert _chamar(fake, "11144478111") == 503
    assert _chamar(fake, "11222333000181") == 503  # outro documento terminado em 1 começa do zero
    assert _chamar(fake, "11144478111") == 503
    assert _chamar(fake, "11144478111") == 200


def test_reset_zera_os_contadores(fake: TestClient):
    for _ in range(3):
        _chamar(fake, "11144478111")

    assert fake.post("/fake/reset").status_code == 204
    assert _chamar(fake, "11144478111") == 503


def test_chamadas_mostra_quantas_vezes_cada_documento_foi_consultado(fake: TestClient):
    for _ in range(3):
        _chamar(fake, "11144478111")
    _chamar(fake, "52998224725")

    assert fake.get("/fake/chamadas").json() == {"11144478111": 3, "52998224725": 1}


def test_instancias_nao_compartilham_estado():
    with TestClient(create_app(falhas_antes_de_recuperar=1, lentidao_segundos=0)) as a:
        assert _chamar(a, "11144478111") == 503
        assert _chamar(a, "11144478111") == 200
    with TestClient(create_app(falhas_antes_de_recuperar=1, lentidao_segundos=0)) as b:
        assert _chamar(b, "11144478111") == 503


@pytest.mark.parametrize("payload", [{}, {"documento": "abc"}, {"documento": "123"}, {"documento": 52998224725}])
def test_payload_invalido_retorna_422(fake: TestClient, payload: object):
    assert fake.post(URL, json=payload).status_code == 422


def test_health(fake: TestClient):
    assert fake.get("/health").json() == {"status": "ok"}


def test_configuracao_padrao_vem_do_ambiente(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_FALHAS_ANTES_DE_RECUPERAR", "1")
    monkeypatch.setenv("FAKE_LENTIDAO_SEGUNDOS", "0")

    with TestClient(create_app()) as c:
        assert [_chamar(c, "11144478111") for _ in range(2)] == [503, 200]


def test_lentidao_nao_bloqueia_outras_requisicoes():
    import asyncio

    import httpx

    async def cenario() -> list[str]:
        app = create_app(falhas_antes_de_recuperar=1, lentidao_segundos=LENTIDAO)
        terminou: list[str] = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fake") as cliente:

            async def chamar(documento: str, nome: str) -> None:
                await cliente.post(URL, json={"documento": documento})
                terminou.append(nome)

            await asyncio.gather(chamar("11144479002", "lenta"), chamar("52998224725", "rapida"))
        return terminou

    assert asyncio.run(cenario()) == ["rapida", "lenta"]
