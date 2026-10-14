"""Schemas de entrada e saída (RF-01, RF-07, RF-08)."""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from customer_lookup.core.dominio import StatusConsulta, TipoDocumento
from customer_lookup.schemas.consulta import ConsultaCreate, ConsultaRead


def test_create_aceita_payload_valido():
    c = ConsultaCreate.model_validate({"documento": "529.982.247-25", "tipo": "CNPJ"})

    assert c.documento == "529.982.247-25"
    assert c.tipo is TipoDocumento.CNPJ


def test_create_nao_valida_digitos_do_documento():
    # A regra do documento (INVALID_DOCUMENT) fica no service; o schema só valida a forma.
    assert ConsultaCreate.model_validate({"documento": "52998224799", "tipo": "CPF"}).documento == "52998224799"


@pytest.mark.parametrize(
    ("payload", "tipo_erro"),
    [
        ({"tipo": "CPF"}, "missing"),
        ({"documento": "52998224725"}, "missing"),
        ({"documento": "52998224725", "tipo": "RG"}, "enum"),
        ({"documento": "52998224725", "tipo": "cpf"}, "enum"),
        ({"documento": 52998224725, "tipo": "CPF"}, "string_type"),
        ({"documento": "52998224725", "tipo": "CPF", "status": "SUCCESS"}, "extra_forbidden"),
        ({"documento": "1" * 33, "tipo": "CPF"}, "string_too_long"),
    ],
)
def test_create_rejeita_payload_malformado(payload: dict[str, object], tipo_erro: str):
    with pytest.raises(ValidationError) as exc:
        ConsultaCreate.model_validate(payload)

    assert tipo_erro in {e["type"] for e in exc.value.errors()}


def _linha(**sobrescrever: object) -> SimpleNamespace:
    agora = datetime(2026, 10, 14, 12, 0, 0)  # naive, como o SQLite devolve
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "documento": "52998224725",
        "tipo": TipoDocumento.CPF,
        "status": StatusConsulta.SUCCESS,
        "tentativas": 1,
        "resultado": {"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"},
        "ultimo_erro": None,
        "criado_em": agora,
        "atualizado_em": agora,
        "processado_em": agora,
    }
    campos.update(sobrescrever)
    return SimpleNamespace(**campos)


def test_read_le_atributos_do_modelo_e_trata_data_naive_como_utc():
    lida = ConsultaRead.model_validate(_linha())

    assert lida.criado_em.tzinfo is UTC
    assert lida.model_dump(mode="json")["criado_em"] == "2026-10-14T12:00:00Z"


def test_read_converte_data_com_fuso_para_utc():
    brasilia = timezone(timedelta(hours=-3))
    lida = ConsultaRead.model_validate(_linha(criado_em=datetime(2026, 10, 14, 9, 0, tzinfo=brasilia)))

    assert lida.criado_em == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    assert lida.model_dump(mode="json")["criado_em"] == "2026-10-14T12:00:00Z"


def test_read_aceita_processado_em_nulo():
    lida = ConsultaRead.model_validate(_linha(status=StatusConsulta.PENDING, processado_em=None, resultado=None))

    assert lida.processado_em is None
    assert lida.resultado is None
