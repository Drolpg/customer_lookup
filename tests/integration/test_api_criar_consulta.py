"""POST /api/v1/consultas (RF-01 a RF-05)."""

import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from customer_lookup.core.config import Settings, get_settings
from customer_lookup.core.dominio import StatusConsulta, TipoDocumento
from customer_lookup.core.logging import LOGGER_NAME, JsonFormatter
from customer_lookup.models import Consulta
from tests.fakes import PublicadorFake

URL = "/api/v1/consultas"


def _total(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Consulta)) or 0


def test_cria_consulta_responde_202_com_location(client: TestClient, db: Session):
    resp = client.post(URL, json={"documento": "529.982.247-25", "tipo": "CPF"}, headers={"X-Request-ID": "req-1"})

    assert resp.status_code == 202
    corpo = resp.json()
    assert set(corpo) == {"id", "status"}
    assert corpo["status"] == "PENDING"
    assert resp.headers["Location"] == f"{URL}/{corpo['id']}"

    consulta = db.get(Consulta, uuid.UUID(corpo["id"]))
    assert consulta is not None
    assert consulta.documento == "52998224725"
    assert consulta.tipo is TipoDocumento.CPF
    assert consulta.status is StatusConsulta.PENDING
    assert consulta.tentativas == 0
    assert consulta.request_id == "req-1"


def test_publica_uma_vez_somente_depois_do_commit(client: TestClient, publicador: PublicadorFake):
    resp = client.post(URL, json={"documento": "11.222.333/0001-81", "tipo": "CNPJ"}, headers={"X-Request-ID": "r-2"})

    assert len(publicador.publicacoes) == 1
    publicacao = publicador.publicacoes[0]
    assert publicacao.consulta_id == uuid.UUID(resp.json()["id"])
    assert publicacao.request_id == "r-2"
    # Outra conexão já enxergava a consulta no momento da publicação: o commit veio antes.
    assert publicacao.status_visivel_no_banco is StatusConsulta.PENDING


def test_documento_invalido_retorna_422_e_nao_grava_nem_publica(
    client: TestClient, db: Session, publicador: PublicadorFake
):
    resp = client.post(URL, json={"documento": "529.982.247-24", "tipo": "CPF"})

    assert resp.status_code == 422
    assert resp.json()["error"] == {
        "code": "INVALID_DOCUMENT",
        "message": "Documento informado é inválido.",
        "details": [{"field": "documento", "message": "dígitos verificadores inválidos"}],
    }
    assert _total(db) == 0
    assert publicador.publicacoes == []


def test_tipo_divergente_do_tamanho_retorna_invalid_document(client: TestClient):
    resp = client.post(URL, json={"documento": "52998224725", "tipo": "CNPJ"})

    assert resp.status_code == 422
    assert resp.json()["error"]["details"] == [{"field": "documento", "message": "CNPJ deve ter 14 dígitos"}]


def test_com_validacao_fraca_aceita_documento_com_dv_errado(app, client: TestClient, db: Session):
    app.dependency_overrides[get_settings] = lambda: Settings(api_key="x", documento_validar_dv=False)

    resp = client.post(URL, json={"documento": "52998224799", "tipo": "CPF"})

    assert resp.status_code == 202
    assert _total(db) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"tipo": "CPF"},
        {"documento": "52998224725"},
        {"documento": "52998224725", "tipo": "RG"},
        {"documento": 52998224725, "tipo": "CPF"},
        {"documento": "52998224725", "tipo": "CPF", "status": "SUCCESS"},
        [],
    ],
)
def test_payload_malformado_retorna_validation_error_e_nao_grava(
    client: TestClient, db: Session, publicador: PublicadorFake, payload: object
):
    resp = client.post(URL, json=payload)

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _total(db) == 0
    assert publicador.publicacoes == []


def test_fila_indisponivel_marca_erro_e_responde_503(client: TestClient, db: Session, publicador: PublicadorFake):
    publicador.falhar = True

    resp = client.post(URL, json={"documento": "52998224725", "tipo": "CPF"})

    assert resp.status_code == 503
    erro = resp.json()["error"]
    assert erro["code"] == "QUEUE_UNAVAILABLE"
    consulta_id = uuid.UUID(erro["details"][0]["id"])
    assert "redis" not in resp.text
    assert "10.0.0.5" not in resp.text

    consulta = db.get(Consulta, consulta_id)
    assert consulta.status is StatusConsulta.ERROR
    assert consulta.ultimo_erro == "fila indisponível"
    assert consulta.processado_em is not None


def test_logs_registram_criacao_e_enfileiramento_sem_o_documento(client: TestClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    resp = client.post(URL, json={"documento": "529.982.247-25", "tipo": "CPF"}, headers={"X-Request-ID": "req-log"})
    consulta_id = resp.json()["id"]

    eventos = {r.getMessage(): r for r in caplog.records}
    assert eventos["consulta_criada"].consulta_id == consulta_id
    assert eventos["consulta_criada"].request_id == "req-log"
    assert eventos["consulta_enfileirada"].consulta_id == consulta_id

    linhas = [JsonFormatter().format(r) for r in caplog.records]
    assert all("52998224725" not in linha and "529.982.247-25" not in linha for linha in linhas)
    assert json.loads(linhas[0])  # cada evento continua sendo JSON válido


def test_falha_ao_enfileirar_e_logada_com_a_causa(
    client: TestClient, publicador: PublicadorFake, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    publicador.falhar = True

    client.post(URL, json={"documento": "52998224725", "tipo": "CPF"})

    registro = next(r for r in caplog.records if r.getMessage() == "falha_ao_enfileirar")
    assert registro.levelno == logging.ERROR
    assert registro.erro == "ConnectionError"
