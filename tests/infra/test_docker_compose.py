"""Contrato da infraestrutura (RNF-04, RNF-05, RNF-06): lê os arquivos, não precisa de Docker."""

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
SERVICOS = {"api", "worker", "externo", "db", "redis"}


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def servicos(compose: dict) -> dict:
    return compose["services"]


def _comando(servico: dict) -> str:
    comando = servico.get("command", "")
    return comando if isinstance(comando, str) else " ".join(comando)


def test_cinco_servicos_com_nome_de_projeto_fixo(compose: dict, servicos: dict):
    assert set(servicos) == SERVICOS
    assert compose["name"] == "customer-lookup"


def test_sobe_sem_arquivo_env(compose: dict):
    # Variável obrigatória (${VAR:?erro}) ou env_file exigiriam um .env: o enunciado pede subir sem configuração extra.
    texto = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    assert ":?" not in texto
    assert all("env_file" not in s for s in compose["services"].values())


def test_toda_variavel_do_compose_tem_valor_padrao():
    texto = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
    # $${VAR} é escape: a variável é resolvida dentro do container, não pelo compose.
    sem_padrao = [v for v in re.findall(r"(?<!\$)\$\{([^}]+)\}", texto) if ":-" not in v]
    assert sem_padrao == []


def test_banco_e_redis_nao_sao_expostos_ao_host(servicos: dict):
    assert "ports" not in servicos["db"]
    assert "ports" not in servicos["redis"]
    assert "ports" not in servicos["worker"]


@pytest.mark.parametrize(("servico", "porta"), [("api", "8000"), ("externo", "9000")])
def test_portas_publicadas_so_em_localhost_por_padrao(servicos: dict, servico: str, porta: str):
    portas = [str(p) for p in servicos[servico]["ports"]]
    assert len(portas) == 1
    assert portas[0].startswith("${") and "127.0.0.1" in portas[0]
    assert portas[0].endswith(f":{porta}")


def test_todos_os_servicos_tem_healthcheck(servicos: dict):
    assert {nome for nome, s in servicos.items() if "healthcheck" in s} == SERVICOS


def test_somente_a_api_aplica_migracoes_e_antes_do_uvicorn(servicos: dict):
    comando = _comando(servicos["api"])
    assert comando.index("alembic upgrade head") < comando.index("uvicorn")
    assert all("alembic" not in _comando(s) for nome, s in servicos.items() if nome != "api")


def test_dependencias_esperam_servicos_saudaveis(servicos: dict):
    for nome in ("api", "worker"):
        depende = servicos[nome]["depends_on"]
        assert {"db", "redis"} <= set(depende), nome
        assert all(d["condition"] == "service_healthy" for d in depende.values()), nome
    # O worker só sobe depois da API saudável = migrações aplicadas.
    assert servicos["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert servicos["worker"]["depends_on"]["externo"]["condition"] == "service_healthy"


def test_worker_e_fake_rodam_os_comandos_certos(servicos: dict):
    assert "celery -A customer_lookup.worker.celery_app worker" in _comando(servicos["worker"])
    externo = _comando(servicos["externo"])
    assert "customer_lookup.fake_externo.app:app" in externo
    assert "--workers" not in externo  # contadores em memória: um processo só


def test_api_e_worker_usam_a_mesma_configuracao(servicos: dict):
    assert servicos["api"]["environment"] == servicos["worker"]["environment"]
    env = servicos["api"]["environment"]
    assert env["EXTERNO_URL"] == "http://externo:9000"
    assert "@db:5432/" in env["DATABASE_URL"]
    assert env["REDIS_URL"].startswith("redis://redis:6379/")


def test_redis_persiste_a_fila(servicos: dict):
    assert "--appendonly" in _comando(servicos["redis"])
    assert servicos["redis"]["volumes"]


def test_dockerfile_multi_stage_com_lock_e_usuario_nao_root():
    texto = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert len(re.findall(r"^FROM ", texto, flags=re.MULTILINE)) == 2
    assert "uv sync --locked" in texto
    assert "--no-dev" in texto
    assert re.search(r"^USER (?!root)\w+", texto, flags=re.MULTILINE)


def test_dockerignore_nao_envia_segredos_nem_material_local():
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8").split()
    assert {".env", ".git", ".venv", "tests", "docs"} <= set(ignorados)


def test_env_example_documenta_as_variaveis_das_settings():
    from customer_lookup.core.config import Settings

    exemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
    documentadas = set(re.findall(r"^#?\s*([A-Z_]+)=", exemplo, flags=re.MULTILINE))
    assert {campo.upper() for campo in Settings.model_fields} <= documentadas
