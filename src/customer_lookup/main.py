"""Aplicação FastAPI: middleware de correlação, tratamento global de erros e rotas."""

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from customer_lookup.api import health
from customer_lookup.core import contexto
from customer_lookup.core.config import get_settings
from customer_lookup.core.errors import AppError
from customer_lookup.core.logging import LOGGER_NAME, configure_logging
from customer_lookup.schemas.erro import Erro, ErroResponse

logger = logging.getLogger(LOGGER_NAME)

REQUEST_ID_HEADER = "X-Request-ID"
# O valor vai para os logs: só aceitamos um formato curto e seguro vindo do cliente.
_REQUEST_ID_VALIDO = re.compile(r"[A-Za-z0-9._-]{1,64}")

_MENSAGENS_VALIDACAO = {
    "missing": "campo obrigatório",
    "extra_forbidden": "campo não permitido",
    "json_invalid": "JSON malformado",
    "uuid_parsing": "UUID inválido",
    "enum": "valor não permitido",
    "string_type": "deve ser texto",
    "string_too_long": "texto longo demais",
    "int_parsing": "deve ser um número inteiro",
    "greater_than_equal": "valor abaixo do mínimo",
    "less_than_equal": "valor acima do máximo",
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _resposta_erro(
    request: Request, status_code: int, erro: Erro, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErroResponse(error=erro).model_dump(exclude_none=True),
        headers={**(headers or {}), REQUEST_ID_HEADER: _request_id(request)},
    )


async def request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    recebido = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = recebido if _REQUEST_ID_VALIDO.fullmatch(recebido) else str(uuid.uuid4())
    request.state.request_id = request_id
    token = contexto.request_id.set(request_id)
    try:
        response = await call_next(request)
    finally:
        contexto.request_id.reset(token)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    erro = Erro(code=exc.code, message=exc.message, details=exc.details)
    return _resposta_erro(request, exc.status_code, erro, exc.headers)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = []
    for e in exc.errors():
        loc = [str(parte) for parte in e.get("loc", ())]
        # loc = ("body" | "query" | "path", campo...); no JSON malformado o 2º item é a posição do erro.
        campo = "body" if e["type"] == "json_invalid" else ".".join(loc[1:]) or (loc[0] if loc else "body")
        details.append({"field": campo, "message": _MENSAGENS_VALIDACAO.get(e["type"], e["msg"])})
    erro = Erro(code="VALIDATION_ERROR", message="Payload inválido.", details=details)
    return _resposta_erro(request, 422, erro)


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        erro = Erro(code="NOT_FOUND", message="Recurso não encontrado.")
    elif exc.status_code == 405:
        erro = Erro(code="METHOD_NOT_ALLOWED", message="Método não permitido.")
    else:
        erro = Erro(code="HTTP_ERROR", message=str(exc.detail))
    return _resposta_erro(request, exc.status_code, erro, dict(exc.headers or {}))


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Roda fora do middleware (o contexto já foi limpo), por isso o request_id vai explícito no log.
    request_id = _request_id(request)
    logger.error("erro_inesperado", exc_info=exc, extra={"request_id": request_id})
    erro = Erro(code="INTERNAL_ERROR", message="Erro interno do servidor.", request_id=request_id)
    return _resposta_erro(request, 500, erro)


def create_app() -> FastAPI:
    app = FastAPI(title="Serviço de Consultas de Clientes", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(request_id_middleware)

    handlers: dict[Any, Callable[[Request, Exception], Awaitable[JSONResponse]]] = {
        AppError: app_error_handler,
        RequestValidationError: validation_error_handler,
        StarletteHTTPException: http_error_handler,
        Exception: unexpected_error_handler,
    }
    for tipo, handler in handlers.items():
        app.add_exception_handler(tipo, handler)

    app.include_router(health.router)
    return app


app = create_app()
