"""Adaptador Celery da porta `PublicadorDeTarefas`."""

import uuid

from customer_lookup.ports import FalhaAoPublicar
from customer_lookup.worker.tasks import processar_consulta_task


class PublicadorCelery:
    def publicar_processamento(self, consulta_id: uuid.UUID, request_id: str | None) -> None:
        try:
            # retry=False: sem as retentativas internas do Celery, o POST falha rápido com o Redis fora.
            processar_consulta_task.apply_async(args=[str(consulta_id), request_id], retry=False)
        except Exception as exc:  # erros variam por transporte (redis, kombu, socket): todos significam "não publicou"
            raise FalhaAoPublicar("não foi possível publicar a tarefa") from exc
