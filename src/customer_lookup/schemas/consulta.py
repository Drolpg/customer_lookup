"""Contratos de entrada e saída da API de consultas (spec §6)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from customer_lookup.core.dominio import StatusConsulta, TipoDocumento


class ConsultaCreate(BaseModel):
    """Só a forma do pedido; a validade do documento é regra do service (`INVALID_DOCUMENT`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"documento": "529.982.247-25", "tipo": "CPF"}]},
    )

    documento: str = Field(max_length=32, description="CPF ou CNPJ, com ou sem máscara.")
    tipo: TipoDocumento


class ConsultaCriada(BaseModel):
    id: uuid.UUID
    status: StatusConsulta


class ConsultaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    documento: str = Field(description="Somente dígitos.")
    tipo: TipoDocumento
    status: StatusConsulta
    tentativas: int = Field(description="Chamadas feitas ao serviço externo.")
    resultado: dict[str, Any] | None = Field(description="Resposta do serviço externo, quando houver sucesso.")
    ultimo_erro: str | None
    criado_em: datetime
    atualizado_em: datetime
    processado_em: datetime | None = Field(description="Momento em que a consulta chegou a SUCCESS ou ERROR.")

    @field_validator("criado_em", "atualizado_em", "processado_em")
    @classmethod
    def _em_utc(cls, valor: datetime | None) -> datetime | None:
        # O SQLite devolve datas sem fuso; tudo é gravado em UTC, então a ausência de fuso significa UTC.
        if valor is None:
            return None
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor.astimezone(UTC)


class PaginaConsultas(BaseModel):
    items: list[ConsultaRead]
    page: int
    page_size: int
    total: int
