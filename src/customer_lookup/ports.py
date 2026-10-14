"""Portas: o que o domínio precisa do mundo externo, sem saber quem implementa (D01)."""

import uuid
from typing import Any, Protocol


class FalhaAoPublicar(Exception):
    """A tarefa não chegou à fila. Adaptadores convertem erros do broker nesta exceção."""


class PublicadorDeTarefas(Protocol):
    def publicar_processamento(self, consulta_id: uuid.UUID, request_id: str | None) -> None: ...


class ErroIntegracao(Exception):
    """Falha ao consultar o serviço externo, já classificada pelo adaptador.

    `motivo` vai para `ultimo_erro` (curto, sem dados pessoais); `tipo` vai para os logs.
    """

    def __init__(self, motivo: str, *, tipo: str, retentavel: bool) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.tipo = tipo
        self.retentavel = retentavel


class ClienteExterno(Protocol):
    def consultar_cliente(self, documento: str) -> dict[str, Any]:
        """Dados do cliente ou `ErroIntegracao`."""
        ...
