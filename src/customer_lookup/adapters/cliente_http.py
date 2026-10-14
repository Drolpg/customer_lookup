"""Adaptador httpx da porta `ClienteExterno`: traduz HTTP e rede em `ErroIntegracao` classificado (RN-05)."""

from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from customer_lookup.ports import ErroIntegracao

# Repetir pode dar certo: o serviço está sobrecarregado, reiniciando ou pediu para esperar.
_CODIGOS_TRANSITORIOS = frozenset({408, 429})


class _DadosCliente(BaseModel):
    """Contrato mínimo da resposta; campos extras são descartados (não guardamos o que não pedimos)."""

    nome: str
    score: int
    situacao: str


class ClienteHttpExterno:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_conexao_s: float,
        timeout_leitura_s: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # Um Client por processo: reaproveita conexões (keep-alive) entre consultas.
        self._http = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_leitura_s, connect=timeout_conexao_s, pool=timeout_conexao_s),
            transport=transport,
        )

    @property
    def timeout(self) -> httpx.Timeout:
        return self._http.timeout

    def consultar_cliente(self, documento: str) -> dict[str, Any]:
        try:
            resposta = self._http.post("/fake/customer", json={"documento": documento})
        except httpx.TimeoutException as exc:
            raise ErroIntegracao("timeout na chamada ao serviço externo", tipo="timeout", retentavel=True) from exc
        except httpx.TransportError as exc:
            raise ErroIntegracao("falha de conexão com o serviço externo", tipo="conexao", retentavel=True) from exc

        if resposta.status_code == 200:
            return _validar(resposta)
        raise _classificar(resposta.status_code)

    def close(self) -> None:
        self._http.close()


def _validar(resposta: httpx.Response) -> dict[str, Any]:
    try:
        return _DadosCliente.model_validate_json(resposta.content).model_dump()
    except ValidationError as exc:
        # 200 com corpo fora do contrato: repetir não muda nada.
        raise ErroIntegracao(
            "resposta inválida do serviço externo", tipo="resposta_invalida", retentavel=False
        ) from exc


def _classificar(codigo: int) -> ErroIntegracao:
    if codigo == 404:
        return ErroIntegracao("cliente não encontrado no serviço externo", tipo="http_404", retentavel=False)
    retentavel = codigo >= 500 or codigo in _CODIGOS_TRANSITORIOS
    return ErroIntegracao(f"serviço externo respondeu HTTP {codigo}", tipo=f"http_{codigo}", retentavel=retentavel)
