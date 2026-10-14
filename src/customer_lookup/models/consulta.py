"""Tabela `consultas` (spec §5)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Index, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from customer_lookup.core.dominio import StatusConsulta, TipoDocumento
from customer_lookup.db.base import Base


def agora() -> datetime:
    return datetime.now(UTC)


class Consulta(Base):
    __tablename__ = "consultas"
    __table_args__ = (Index(None, "status", "criado_em"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    documento: Mapped[str] = mapped_column(String(14), index=True)
    # native_enum=False: texto + validação na aplicação; adicionar um status não exige ALTER TYPE no Postgres.
    tipo: Mapped[TipoDocumento] = mapped_column(Enum(TipoDocumento, native_enum=False, length=4))
    status: Mapped[StatusConsulta] = mapped_column(
        Enum(StatusConsulta, native_enum=False, length=10), default=StatusConsulta.PENDING
    )
    tentativas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    resultado: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    ultimo_erro: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, server_default=func.now())
    # onupdate vale para o ORM e para UPDATE Core sem valor explícito para a coluna.
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora, onupdate=agora, server_default=func.now()
    )
    processado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
