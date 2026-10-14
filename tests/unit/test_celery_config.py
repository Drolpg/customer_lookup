"""Configuração do Celery e do publicador (RN-07, RNF-02)."""

import logging
import uuid

import pytest

from customer_lookup.adapters.publicador_celery import PublicadorCelery
from customer_lookup.core.config import get_settings
from customer_lookup.core.logging import LOGGER_NAME, JsonFormatter
from customer_lookup.ports import FalhaAoPublicar
from customer_lookup.worker.celery_app import celery_app
from customer_lookup.worker.tasks import NOME_TASK, processar_consulta_task


def test_entrega_pelo_menos_uma_vez():
    conf = celery_app.conf
    assert conf.task_acks_late is True  # confirma só depois de processar
    assert conf.task_reject_on_worker_lost is True  # worker morreu: a mensagem volta para a fila
    assert conf.worker_prefetch_multiplier == 1  # não reserva mensagens que outro worker poderia pegar


def test_serializacao_json_e_sem_backend_de_resultado():
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.task_ignore_result is True


def test_visibility_timeout_maior_que_o_maior_retry_possivel():
    # No Redis, mensagens com countdown ficam reservadas; se o visibility_timeout vencer antes, são reentregues.
    settings = get_settings()
    maior_espera = settings.retry_teto_segundos * 1.5
    assert celery_app.conf.broker_transport_options["visibility_timeout"] > maior_espera


def test_conexao_com_broker_falha_rapido():
    opcoes = celery_app.conf.broker_transport_options
    assert opcoes["socket_connect_timeout"] <= 3
    assert opcoes["socket_timeout"] <= 3
    assert celery_app.conf.broker_connection_timeout <= 3


def test_concorrencia_vem_das_settings():
    assert celery_app.conf.worker_concurrency == get_settings().worker_concorrencia


def test_task_registrada_com_nome_estavel_e_protecoes():
    # O decorator devolve um proxy: comparamos pelo nome registrado.
    assert celery_app.tasks[NOME_TASK].name == processar_consulta_task.name
    assert NOME_TASK == "customer_lookup.processar_consulta"
    assert processar_consulta_task.rate_limit == get_settings().tarefa_rate_limit
    # O limite de tentativas é do domínio (banco + política); o padrão do Celery (3) cortaria antes.
    assert processar_consulta_task.max_retries is None


def test_sinal_setup_logging_configura_logs_json_no_worker():
    from celery.signals import setup_logging

    setup_logging.send(sender=None, loglevel="INFO", logfile=None, format="", colorize=False)

    for nome in (LOGGER_NAME, "celery"):
        assert any(isinstance(h.formatter, JsonFormatter) for h in logging.getLogger(nome).handlers), nome


def test_publicador_envia_id_e_request_id_sem_retry_interno(monkeypatch: pytest.MonkeyPatch):
    chamadas: list[dict[str, object]] = []
    monkeypatch.setattr(processar_consulta_task, "apply_async", lambda **kw: chamadas.append(kw))
    consulta_id = uuid.uuid4()

    PublicadorCelery().publicar_processamento(consulta_id, "req-1")

    assert chamadas == [{"args": [str(consulta_id), "req-1"], "retry": False}]


def test_publicador_converte_erro_do_broker_em_falha_ao_publicar(monkeypatch: pytest.MonkeyPatch):
    def broker_fora(**_: object) -> None:
        raise ConnectionRefusedError("Error 111 connecting to redis:6379")

    monkeypatch.setattr(processar_consulta_task, "apply_async", broker_fora)

    with pytest.raises(FalhaAoPublicar) as exc:
        PublicadorCelery().publicar_processamento(uuid.uuid4(), None)

    assert isinstance(exc.value.__cause__, ConnectionRefusedError)
