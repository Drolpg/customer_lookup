"""Envelope único de erro (spec §6.4)."""

from typing import Any

from pydantic import BaseModel, Field


class Erro(BaseModel):
    code: str = Field(description="Código estável, para o cliente tratar programaticamente.", examples=["NOT_FOUND"])
    message: str = Field(description="Mensagem legível, em português.", examples=["Recurso não encontrado."])
    details: list[dict[str, Any]] | None = Field(default=None, description="Detalhes, como os campos inválidos.")
    request_id: str | None = Field(default=None, description="Identificador para localizar o erro nos logs.")


class ErroResponse(BaseModel):
    error: Erro
