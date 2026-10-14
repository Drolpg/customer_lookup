"""Task do worker: casca fina. Monta as dependências, restaura o contexto e traduz a decisão em retry do Celery."""

import logging
import uuid
from functools import cache

from celery import Task
from sqlalchemy.exc import OperationalError

from customer_lookup.adapters.cliente_http import ClienteHttpExterno
from customer_lookup.core import contexto
from customer_lookup.core.config import get_settings
from customer_lookup.core.logging import LOGGER_NAME
from customer_lookup.db.session import SessionLocal
from customer_lookup.ports import ClienteExterno
from customer_lookup.services.politica_retry import PoliticaRetry
from customer_lookup.services.processamento import processar_consulta
from customer_lookup.worker.celery_app import celery_app

logger = logging.getLogger(LOGGER_NAME)

NOME_TASK = "customer_lookup.processar_consulta"
# Banco fora do ar não é falha da integração: reagenda com espera própria, limitada.
MAX_RETRIES_BANCO = 10
ESPERA_BANCO_SEGUNDOS = 5


@cache
def cliente_externo() -> ClienteExterno:
    s = get_settings()
    return ClienteHttpExterno(
        s.externo_url, timeout_conexao_s=s.externo_timeout_conexao_s, timeout_leitura_s=s.externo_timeout_leitura_s
    )


@cache
def politica_retry() -> PoliticaRetry:
    return PoliticaRetry.de_settings(get_settings())


@celery_app.task(
    bind=True,
    name=NOME_TASK,  # nome estável: renomear o módulo não quebra mensagens já na fila
    rate_limit=get_settings().tarefa_rate_limit,
    max_retries=None,  # o limite de tentativas é do domínio (banco + política)
)
def processar_consulta_task(self: Task, consulta_id: str, request_id: str | None = None) -> None:
    token = contexto.request_id.set(request_id)
    try:
        with SessionLocal() as db:
            decisao = processar_consulta(db, cliente_externo(), politica_retry(), uuid.UUID(consulta_id))
    except OperationalError as exc:
        logger.error("banco_indisponivel", extra={"consulta_id": consulta_id, "erro": type(exc.orig).__name__})
        espera = ESPERA_BANCO_SEGUNDOS * (self.request.retries + 1)
        raise self.retry(exc=exc, countdown=espera, max_retries=MAX_RETRIES_BANCO) from exc
    finally:
        contexto.request_id.reset(token)

    if decisao is not None:
        raise self.retry(countdown=decisao.delay_s)
