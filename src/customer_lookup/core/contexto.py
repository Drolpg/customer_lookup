"""Contexto de correlação da execução atual (requisição HTTP ou tarefa do worker).

`ContextVar` é isolado por thread e por tarefa asyncio, então requisições simultâneas não se misturam.
"""

from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
consulta_id: ContextVar[str | None] = ContextVar("consulta_id", default=None)
