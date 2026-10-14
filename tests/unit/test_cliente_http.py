"""Adaptador httpx do serviço externo: classificação de respostas e falhas (RN-04, RN-05)."""

import json
from collections.abc import Callable

import httpx
import pytest

from customer_lookup.adapters.cliente_http import ClienteHttpExterno
from customer_lookup.ports import ErroIntegracao

DOCUMENTO = "52998224725"
SUCESSO = {"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"}


def _cliente(handler: Callable[[httpx.Request], httpx.Response]) -> ClienteHttpExterno:
    return ClienteHttpExterno(
        "http://externo:9000", timeout_conexao_s=2.0, timeout_leitura_s=3.0, transport=httpx.MockTransport(handler)
    )


def _erro(handler: Callable[[httpx.Request], httpx.Response]) -> ErroIntegracao:
    with pytest.raises(ErroIntegracao) as exc:
        _cliente(handler).consultar_cliente(DOCUMENTO)
    return exc.value


def test_sucesso_envia_o_contrato_e_devolve_os_dados():
    recebidas: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recebidas.append(request)
        return httpx.Response(200, json=SUCESSO)

    assert _cliente(handler).consultar_cliente(DOCUMENTO) == SUCESSO
    assert recebidas[0].method == "POST"
    assert str(recebidas[0].url) == "http://externo:9000/fake/customer"
    assert json.loads(recebidas[0].content) == {"documento": DOCUMENTO}


def test_campos_extras_na_resposta_sao_descartados():
    resposta = {**SUCESSO, "cpf_completo": DOCUMENTO}

    assert _cliente(lambda r: httpx.Response(200, json=resposta)).consultar_cliente(DOCUMENTO) == SUCESSO


@pytest.mark.parametrize("codigo", [500, 502, 503, 504, 408, 429])
def test_5xx_408_e_429_sao_transitorios(codigo: int):
    erro = _erro(lambda r: httpx.Response(codigo))

    assert erro.retentavel is True
    assert erro.motivo == f"serviço externo respondeu HTTP {codigo}"
    assert erro.tipo == f"http_{codigo}"


def test_404_e_permanente_com_motivo_de_negocio():
    erro = _erro(lambda r: httpx.Response(404, json={"detail": "cliente não encontrado"}))

    assert erro.retentavel is False
    assert erro.motivo == "cliente não encontrado no serviço externo"
    assert erro.tipo == "http_404"


@pytest.mark.parametrize("codigo", [400, 401, 403, 422, 301])
def test_demais_codigos_sao_permanentes(codigo: int):
    erro = _erro(lambda r: httpx.Response(codigo))

    assert erro.retentavel is False
    assert erro.motivo == f"serviço externo respondeu HTTP {codigo}"


@pytest.mark.parametrize(
    "corpo",
    [
        b"<html>ok</html>",
        json.dumps({"nome": "Cliente Teste"}).encode(),
        json.dumps({**SUCESSO, "score": "alto"}).encode(),
        json.dumps([SUCESSO]).encode(),
    ],
)
def test_200_com_corpo_invalido_e_permanente(corpo: bytes):
    erro = _erro(lambda r: httpx.Response(200, content=corpo))

    assert erro.retentavel is False
    assert erro.tipo == "resposta_invalida"
    assert erro.motivo == "resposta inválida do serviço externo"


@pytest.mark.parametrize("excecao", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_timeout_e_transitorio(excecao: type[httpx.TimeoutException]):
    def handler(request: httpx.Request) -> httpx.Response:
        raise excecao("estourou", request=request)

    erro = _erro(handler)

    assert erro.retentavel is True
    assert erro.tipo == "timeout"
    assert erro.motivo == "timeout na chamada ao serviço externo"


def test_falha_de_conexao_e_transitoria():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    erro = _erro(handler)

    assert erro.retentavel is True
    assert erro.tipo == "conexao"
    assert erro.motivo == "falha de conexão com o serviço externo"


def test_motivo_nunca_contem_o_documento():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout consultando {DOCUMENTO}", request=request)

    assert DOCUMENTO not in _erro(handler).motivo


def test_timeouts_configurados_no_cliente():
    cliente = _cliente(lambda r: httpx.Response(200, json=SUCESSO))

    timeout = cliente.timeout
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (2.0, 3.0, 3.0, 2.0)
