import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from redis import Redis, RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from customer_lookup.api.deps import get_redis
from customer_lookup.core.errors import ServicoIndisponivel
from customer_lookup.core.logging import LOGGER_NAME
from customer_lookup.db.session import get_db

logger = logging.getLogger(LOGGER_NAME)
router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: o processo está de pé")
def health() -> dict[str, str]:
    # Sem dependências de propósito: banco fora não é motivo para reiniciar a API.
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness: banco e Redis respondem")
def ready(db: Annotated[Session, Depends(get_db)], redis: Annotated[Redis, Depends(get_redis)]) -> dict[str, object]:
    falhas = []
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        falhas.append("database")
    try:
        redis.ping()
    except RedisError:
        falhas.append("redis")

    if falhas:
        logger.warning("readiness_falhou", extra={"componentes": falhas})
        raise ServicoIndisponivel(falhas)
    return {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}
