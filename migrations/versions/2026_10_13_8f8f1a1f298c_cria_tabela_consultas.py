"""cria tabela consultas

Revision ID: 8f8f1a1f298c
Revises:
Create Date: 2026-10-13 22:39:11.504935

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8f8f1a1f298c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consultas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("documento", sa.String(length=14), nullable=False),
        sa.Column("tipo", sa.Enum("CPF", "CNPJ", name="tipodocumento", native_enum=False, length=4), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PROCESSING", "SUCCESS", "ERROR", name="statusconsulta", native_enum=False, length=10),
            nullable=False,
        ),
        sa.Column("tentativas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("resultado", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("ultimo_erro", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processado_em", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultas")),
    )
    op.create_index(op.f("ix_consultas_documento"), "consultas", ["documento"], unique=False)
    op.create_index(op.f("ix_consultas_status_criado_em"), "consultas", ["status", "criado_em"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_consultas_status_criado_em"), table_name="consultas")
    op.drop_index(op.f("ix_consultas_documento"), table_name="consultas")
    op.drop_table("consultas")
