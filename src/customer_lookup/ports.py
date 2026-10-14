"""Portas: o que o domínio precisa do mundo externo, sem saber quem implementa (D01)."""

import uuid
from typing import Protocol


class FalhaAoPublicar(Exception):
    """A tarefa não chegou à fila. Adaptadores convertem erros do broker nesta exceção."""


class PublicadorDeTarefas(Protocol):
    def publicar_processamento(self, consulta_id: uuid.UUID, request_id: str | None) -> None: ...
