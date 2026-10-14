"""Dependências injetadas nas rotas."""

from customer_lookup.ports import PublicadorDeTarefas


def get_publicador() -> PublicadorDeTarefas:
    # Implementação real (Celery) entra no M7; os testes sobrescrevem esta dependência.
    raise NotImplementedError("publicador de tarefas ainda não configurado")
