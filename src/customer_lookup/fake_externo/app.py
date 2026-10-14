"""API externa fake de clientes (spec §8).

Simula um serviço de terceiros instável. Aplicação independente do restante do pacote, roda em outro container.
O cenário é escolhido pelo último dígito do documento, para a demonstração ser reproduzível:

    0  → 500 sempre
    1  → 503 nas N primeiras chamadas do documento, depois 200
    2  → lento (acima do timeout do cliente) nas N primeiras chamadas, depois 200
    3  → 404 cliente não encontrado
    4-9 → 200
"""

import asyncio
from collections import Counter
from typing import Annotated, Any

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FakeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAKE_")

    falhas_antes_de_recuperar: int = Field(default=2, ge=0)
    lentidao_segundos: float = Field(default=5.0, ge=0)


class ConsultaCliente(BaseModel):
    documento: Annotated[str, Field(pattern=r"^\d{11}$|^\d{14}$")]


def create_app(falhas_antes_de_recuperar: int | None = None, lentidao_segundos: float | None = None) -> FastAPI:
    padrao = FakeSettings()
    falhas = padrao.falhas_antes_de_recuperar if falhas_antes_de_recuperar is None else falhas_antes_de_recuperar
    lentidao = padrao.lentidao_segundos if lentidao_segundos is None else lentidao_segundos

    app = FastAPI(title="API externa fake de clientes", version="1.0.0")
    # Estado por instância (não global) e em memória: some ao reiniciar o container (limitação aceita).
    chamadas: Counter[str] = Counter()

    @app.post("/fake/customer", response_model=None)
    async def consultar_cliente(dados: ConsultaCliente) -> dict[str, Any] | JSONResponse:
        documento = dados.documento
        # Um único event loop e nenhum await antes do incremento: não há corrida entre requisições.
        chamadas[documento] += 1
        n = chamadas[documento]

        match documento[-1]:
            case "0":
                return _erro(status.HTTP_500_INTERNAL_SERVER_ERROR, "erro interno simulado")
            case "1" if n <= falhas:
                return _erro(status.HTTP_503_SERVICE_UNAVAILABLE, "serviço temporariamente indisponível")
            case "2" if n <= falhas:
                await asyncio.sleep(lentidao)  # não bloqueia outras requisições do fake
            case "3":
                return _erro(status.HTTP_404_NOT_FOUND, "cliente não encontrado")
        return {"nome": "Cliente Teste", "score": 300 + int(documento) % 601, "situacao": "REGULAR"}

    @app.post("/fake/reset", status_code=status.HTTP_204_NO_CONTENT)
    async def reset() -> None:
        chamadas.clear()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/fake/chamadas")
    async def contadores() -> dict[str, int]:
        return dict(chamadas)

    return app


def _erro(codigo: int, mensagem: str) -> JSONResponse:
    return JSONResponse(status_code=codigo, content={"detail": mensagem})


app = create_app()
