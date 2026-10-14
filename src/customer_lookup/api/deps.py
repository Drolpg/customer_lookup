"""Dependências injetadas nas rotas."""

from functools import cache

from customer_lookup.adapters.publicador_celery import PublicadorCelery
from customer_lookup.ports import PublicadorDeTarefas


@cache
def get_publicador() -> PublicadorDeTarefas:
    return PublicadorCelery()
