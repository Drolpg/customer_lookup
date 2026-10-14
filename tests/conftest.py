"""Fixtures compartilhadas.

A suíte principal não depende de Postgres nem de Redis: as variáveis de ambiente são definidas
ANTES de importar a aplicação, para que nada tente conectar na infraestrutura do Docker.
"""

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["API_KEY"] = "chave-de-teste"  # mesmo valor de API_KEY_TESTE

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
def publicador(session_factory):
    from tests.fakes import PublicadorFake

    return PublicadorFake(session_factory)


@pytest.fixture
def redis_fake():
    import fakeredis

    return fakeredis.FakeRedis()


@pytest.fixture
def client(app, session_factory, publicador, redis_fake):
    from customer_lookup.api.deps import get_publicador, get_redis
    from customer_lookup.db.session import get_db
    from tests.fakes import API_KEY_TESTE

    def _get_db_teste():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_teste
    app.dependency_overrides[get_publicador] = lambda: publicador
    app.dependency_overrides[get_redis] = lambda: redis_fake
    # raise_server_exceptions=False: queremos ver a resposta 500 produzida pelo handler global
    with TestClient(app, raise_server_exceptions=False, headers={"X-API-Key": API_KEY_TESTE}) as c:
        yield c


@pytest.fixture
def criar_consulta(db):
    """Insere consultas direto no banco (sem passar pela API)."""
    import uuid
    from datetime import UTC, datetime

    from customer_lookup.core.dominio import StatusConsulta, TipoDocumento
    from customer_lookup.models import Consulta

    def _criar(
        *,
        documento: str = "52998224725",
        tipo: TipoDocumento = TipoDocumento.CPF,
        status: StatusConsulta = StatusConsulta.PENDING,
        criado_em: datetime | None = None,
        **outros: object,
    ) -> Consulta:
        outros.setdefault("id", uuid.uuid4())
        consulta = Consulta(
            documento=documento,
            tipo=tipo,
            status=status,
            criado_em=criado_em or datetime.now(UTC),
            **outros,
        )
        db.add(consulta)
        db.commit()
        return consulta

    return _criar
