"""Logs estruturados em JSON, uma linha por evento, com o contexto de correlação anexado."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from customer_lookup.core import contexto

LOGGER_NAME = "customer_lookup"

# Atributos padrão do LogRecord: tudo que não está aqui veio de `extra={...}` ou do filtro de contexto.
_ATRIBUTOS_PADRAO = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class ContextoFilter(logging.Filter):
    """Anexa `request_id` e `consulta_id` do contexto atual, sem sobrescrever valores explícitos."""

    def filter(self, record: logging.LogRecord) -> bool:
        for nome, var in (("request_id", contexto.request_id), ("consulta_id", contexto.consulta_id)):
            valor = var.get()
            if valor is not None and not hasattr(record, nome):
                setattr(record, nome, valor)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for chave, valor in vars(record).items():
            if chave not in _ATRIBUTOS_PADRAO and not chave.startswith("_"):
                payload[chave] = valor
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: int | str = logging.INFO, outros: tuple[str, ...] = ()) -> None:
    """Configura o logger da aplicação (e `outros`, ex.: "celery") sem mexer no root logger.

    `propagate` continua ligado para o `caplog` dos testes.
    """
    nivel = level.upper() if isinstance(level, str) else level
    for nome in (LOGGER_NAME, *outros):
        logger = logging.getLogger(nome)
        logger.setLevel(nivel)
        logger.propagate = True
        if not any(isinstance(f, ContextoFilter) for f in logger.filters):
            logger.addFilter(ContextoFilter())
        if not any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
