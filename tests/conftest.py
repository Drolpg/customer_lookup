"""Fixtures compartilhadas.

A suíte principal não depende de Postgres nem de Redis: as variáveis de ambiente são definidas
ANTES de importar a aplicação, para que nada tente conectar na infraestrutura do Docker.
"""

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["API_KEY"] = "chave-de-teste"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def engine(tmp_path) -> Engine:
    """SQLite em arquivo: cada sessão abre a própria conexão, como no Postgres (isolamento realista)."""
    import customer_lookup.models  # noqa: F401  (registra as tabelas no metadata)
    from customer_lookup.db.base import Base

    eng = create_engine(f"sqlite:///{tmp_path / 'teste.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]):
    with session_factory() as session:
        yield session


@pytest.fixture
def app() -> FastAPI:
    from customer_lookup.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    # raise_server_exceptions=False: queremos ver a resposta 500 produzida pelo handler global
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
