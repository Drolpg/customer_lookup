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


@pytest.fixture
def app() -> FastAPI:
    from customer_lookup.main import create_app

    return create_app()


@pytest.fixture
def client(app):
    # raise_server_exceptions=False: queremos ver a resposta 500 produzida pelo handler global
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
