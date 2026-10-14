"""Validação de CPF/CNPJ (RN-01)."""

import pytest

from customer_lookup.core.documento import calcular_dv, mascarar, normalizar, validar
from customer_lookup.core.dominio import TipoDocumento
from customer_lookup.core.errors import DocumentoInvalido

CPF = TipoDocumento.CPF
CNPJ = TipoDocumento.CNPJ


@pytest.mark.parametrize(
    ("entrada", "tipo", "esperado"),
    [
        ("52998224725", CPF, "52998224725"),
        ("529.982.247-25", CPF, "52998224725"),
        (" 529 982 247 25 ", CPF, "52998224725"),
        ("12345678909", CPF, "12345678909"),
        ("11222333000181", CNPJ, "11222333000181"),
        ("11.222.333/0001-81", CNPJ, "11222333000181"),
    ],
)
def test_documentos_validos_sao_normalizados(entrada: str, tipo: TipoDocumento, esperado: str):
    assert validar(entrada, tipo) == esperado


def test_cpf_do_exemplo_do_enunciado_tem_dv_invalido():
    # 12345678901 é o exemplo do enunciado: o segundo DV correto seria 9 (12345678909).
    with pytest.raises(DocumentoInvalido) as exc:
        validar("12345678901", CPF)

    assert exc.value.details == [{"field": "documento", "message": "dígitos verificadores inválidos"}]


@pytest.mark.parametrize(
    ("entrada", "tipo", "motivo"),
    [
        ("52998224724", CPF, "dígitos verificadores inválidos"),
        ("52998224735", CPF, "dígitos verificadores inválidos"),
        ("11222333000182", CNPJ, "dígitos verificadores inválidos"),
        ("11222333000191", CNPJ, "dígitos verificadores inválidos"),
        ("11111111111", CPF, "sequência de dígitos repetidos"),
        ("00000000000000", CNPJ, "sequência de dígitos repetidos"),
        ("5299822472", CPF, "CPF deve ter 11 dígitos"),
        ("", CPF, "CPF deve ter 11 dígitos"),
        ("11222333000181", CPF, "CPF deve ter 11 dígitos"),
        ("52998224725", CNPJ, "CNPJ deve ter 14 dígitos"),
        ("529A8224725", CPF, "contém caracteres inválidos"),
        ("529,982,247-25", CPF, "contém caracteres inválidos"),
        ("５２９９８２２４７２５", CPF, "contém caracteres inválidos"),  # dígitos unicode de largura total
    ],
)
def test_documentos_invalidos_informam_o_motivo(entrada: str, tipo: TipoDocumento, motivo: str):
    with pytest.raises(DocumentoInvalido) as exc:
        validar(entrada, tipo)

    assert exc.value.code == "INVALID_DOCUMENT"
    assert exc.value.status_code == 422
    assert exc.value.message == "Documento informado é inválido."
    assert exc.value.details == [{"field": "documento", "message": motivo}]


def test_sem_validar_dv_aceita_dv_errado_mas_mantem_as_demais_regras():
    assert validar("12345678901", CPF, validar_dv=False) == "12345678901"

    with pytest.raises(DocumentoInvalido):
        validar("1234567890", CPF, validar_dv=False)
    with pytest.raises(DocumentoInvalido):
        validar("1234567890A", CPF, validar_dv=False)
    with pytest.raises(DocumentoInvalido):
        validar("11111111111", CPF, validar_dv=False)


@pytest.mark.parametrize(
    ("base", "tipo", "dv"),
    [("529982247", CPF, "25"), ("123456789", CPF, "09"), ("112223330001", CNPJ, "81")],
)
def test_calcular_dv(base: str, tipo: TipoDocumento, dv: str):
    assert calcular_dv(base, tipo) == dv


@pytest.mark.parametrize(
    "documento",
    ["52998224725", "11144478111", "11144479002", "11144478030", "11144478383"],
)
def test_cpfs_de_demonstracao_da_spec_sao_validos(documento: str):
    assert validar(documento, CPF) == documento


def test_normalizar_remove_somente_a_mascara():
    assert normalizar("11.222.333/0001-81") == "11222333000181"
    with pytest.raises(DocumentoInvalido):
        normalizar("123abc")


@pytest.mark.parametrize(
    ("documento", "mascarado"),
    [
        ("52998224725", "***.982.247-**"),
        ("11222333000181", "**.222.333/0001-**"),
        ("123", "***"),
    ],
)
def test_mascarar_esconde_inicio_e_digitos_verificadores(documento: str, mascarado: str):
    assert mascarar(documento) == mascarado
