"""Ambiente do Alembic: a URL vem das settings da aplicação e o metadata dos models."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import customer_lookup.models  # noqa: F401  (registra as tabelas no metadata)
from customer_lookup.core.config import get_settings
from customer_lookup.db.base import Base

config = context.config

# disable_existing_loggers=False: o padrão (True) desligaria os loggers da aplicação já criados.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    secao = config.get_section(config.config_ini_section, {})
    secao["sqlalchemy.url"] = _url()
    conectavel = engine_from_config(secao, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with conectavel.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
