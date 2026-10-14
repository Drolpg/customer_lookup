"""RNF-06: o schema é criado só pelo Alembic e as migrações acompanham os models.

Roda em SQLite temporário, sem Docker.
"""

import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_cfg(tmp_path) -> tuple[Config, str]:
    url = f"sqlite:///{tmp_path / 'migracao.db'}"
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, url


def test_upgrade_head_cria_tabela_com_colunas_da_spec(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")

    inspetor = inspect(create_engine(url))
    colunas = {c["name"]: c for c in inspetor.get_columns("consultas")}
    assert set(colunas) == {
        "id",
        "documento",
        "tipo",
        "status",
        "tentativas",
        "resultado",
        "ultimo_erro",
        "request_id",
        "criado_em",
        "atualizado_em",
        "processado_em",
    }
    obrigatorias = {nome for nome, c in colunas.items() if not c["nullable"]}
    assert obrigatorias == {"id", "documento", "tipo", "status", "tentativas", "criado_em", "atualizado_em"}


def test_upgrade_head_cria_indices_da_listagem(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")

    indices = {tuple(i["column_names"]) for i in inspect(create_engine(url)).get_indexes("consultas")}
    assert ("documento",) in indices
    assert ("status", "criado_em") in indices


def test_migracoes_estao_sincronizadas_com_os_models(alembic_cfg):
    """Se alguém muda um model e esquece de gerar a migração, este teste falha."""
    import customer_lookup.models  # noqa: F401
    from customer_lookup.db.base import Base

    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")

    with create_engine(url).connect() as conexao:
        diferencas = compare_metadata(MigrationContext.configure(conexao), Base.metadata)
    assert diferencas == []


def test_downgrade_base_remove_a_tabela(alembic_cfg):
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    assert "consultas" not in inspect(create_engine(url)).get_table_names()


def test_rodar_migracao_nao_desliga_os_loggers_da_aplicacao(alembic_cfg):
    # O fileConfig padrão do env.py desligaria loggers existentes (disable_existing_loggers=True).
    from customer_lookup.core.logging import LOGGER_NAME

    logger = logging.getLogger(LOGGER_NAME)
    cfg, _ = alembic_cfg
    command.upgrade(cfg, "head")

    assert logger.disabled is False
