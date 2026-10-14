"""Aplicação Celery: fila no Redis, entrega "pelo menos uma vez" e proteção do serviço externo."""

from typing import Any

from celery import Celery
from celery.signals import setup_logging

from customer_lookup.core.config import get_settings
from customer_lookup.core.logging import configure_logging

settings = get_settings()

celery_app = Celery("customer_lookup", broker=settings.redis_url, include=["customer_lookup.worker.tasks"])

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,  # o resultado vive na tabela consultas; sem backend de resultados
    # Confirma a mensagem só depois de processar; se o worker morrer no meio, ela volta para a fila.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.worker_concorrencia,
    broker_connection_timeout=2,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        # Mensagens com countdown ficam reservadas no Redis; precisa ser maior que a maior espera de retry.
        "visibility_timeout": 3600,
        # Com o Redis fora, o POST precisa falhar rápido (503), não pendurar a requisição.
        "socket_connect_timeout": 2,
        "socket_timeout": 5,
    },
)


@setup_logging.connect
def _configurar_logs_do_worker(**_: Any) -> None:
    # Conectar este sinal impede o Celery de trocar o logging pelo formato dele.
    configure_logging(settings.log_level, outros=("celery",))
