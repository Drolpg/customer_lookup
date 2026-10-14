"""Dependências injetadas nas rotas: autenticação, rate limit, Redis e publicador."""

import secrets
from functools import cache
from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from redis import Redis

from customer_lookup.adapters.publicador_celery import PublicadorCelery
from customer_lookup.core.config import Settings, get_settings
from customer_lookup.core.errors import LimiteExcedido, NaoAutorizado
from customer_lookup.ports import PublicadorDeTarefas
from customer_lookup.services.rate_limit import LimitadorDeTaxa

# auto_error=False: o erro é nosso (envelope padrão), não o 403 genérico do FastAPI.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@cache
def get_publicador() -> PublicadorDeTarefas:
    return PublicadorCelery()


@cache
def get_redis() -> Redis:
    # Timeouts curtos: readiness e rate limit não podem pendurar a requisição se o Redis cair.
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1)


def exigir_api_key(
    recebida: Annotated[str | None, Security(_api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    esperada = settings.api_key.get_secret_value()
    # compare_digest leva o mesmo tempo acerte ou erre: não dá pistas da chave por medição de tempo.
    if recebida is None or not secrets.compare_digest(recebida.encode(), esperada.encode()):
        raise NaoAutorizado()
    return recebida


def limitar_taxa(
    api_key: Annotated[str, Depends(exigir_api_key)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    retry_after = LimitadorDeTaxa(redis, settings.rate_limit_por_minuto).verificar(api_key)
    if retry_after is not None:
        raise LimiteExcedido(retry_after)
