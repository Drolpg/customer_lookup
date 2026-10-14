import json
import logging

import pytest

from customer_lookup.core import contexto
from customer_lookup.core.logging import LOGGER_NAME, ContextoFilter, JsonFormatter, configure_logging


def _record(msg: str = "evento", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(LOGGER_NAME, logging.INFO, __file__, 1, msg, None, None)
    for chave, valor in extra.items():
        setattr(record, chave, valor)
    return record


def test_formatter_gera_uma_linha_json_com_campos_basicos_e_extras():
    saida = JsonFormatter().format(_record("consulta_criada", tipo="CPF", tentativa=2))

    assert "\n" not in saida
    payload = json.loads(saida)
    assert payload["message"] == "consulta_criada"
    assert payload["level"] == "INFO"
    assert payload["logger"] == LOGGER_NAME
    assert payload["timestamp"].endswith("+00:00")
    assert payload["tipo"] == "CPF"
    assert payload["tentativa"] == 2


def test_formatter_inclui_stack_trace_em_uma_unica_linha():
    try:
        raise ValueError("falhou")
    except ValueError:
        import sys

        record = logging.LogRecord(LOGGER_NAME, logging.ERROR, __file__, 1, "erro_inesperado", None, sys.exc_info())

    saida = JsonFormatter().format(record)

    assert "\n" not in saida
    assert "ValueError: falhou" in json.loads(saida)["exception"]


def test_filtro_anexa_request_id_e_consulta_id_do_contexto():
    token_r = contexto.request_id.set("req-123")
    token_c = contexto.consulta_id.set("cons-456")
    try:
        record = _record()
        ContextoFilter().filter(record)
    finally:
        contexto.request_id.reset(token_r)
        contexto.consulta_id.reset(token_c)

    assert record.request_id == "req-123"  # type: ignore[attr-defined]
    assert record.consulta_id == "cons-456"  # type: ignore[attr-defined]


def test_filtro_nao_sobrescreve_valor_passado_explicitamente():
    token = contexto.request_id.set("do-contexto")
    try:
        record = _record(request_id="explicito")
        ContextoFilter().filter(record)
    finally:
        contexto.request_id.reset(token)

    assert record.request_id == "explicito"  # type: ignore[attr-defined]


def test_sem_contexto_nao_adiciona_campos():
    record = _record()
    ContextoFilter().filter(record)

    payload = json.loads(JsonFormatter().format(record))
    assert "request_id" not in payload
    assert "consulta_id" not in payload


def test_logs_da_aplicacao_saem_com_contexto(caplog: pytest.LogCaptureFixture):
    configure_logging("INFO")
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    token = contexto.request_id.set("req-789")
    try:
        logging.getLogger(LOGGER_NAME).info("qualquer_evento")
    finally:
        contexto.request_id.reset(token)

    assert caplog.records[-1].request_id == "req-789"


def test_configure_logging_e_idempotente():
    configure_logging("INFO")
    configure_logging("DEBUG")

    logger = logging.getLogger(LOGGER_NAME)
    assert sum(isinstance(h.formatter, JsonFormatter) for h in logger.handlers) == 1
    assert sum(isinstance(f, ContextoFilter) for f in logger.filters) == 1
    assert logger.level == logging.DEBUG
