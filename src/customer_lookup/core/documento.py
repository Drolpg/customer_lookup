"""CPF e CNPJ: normalização, validação (módulo 11) e máscara para logs (RN-01)."""

import re

from customer_lookup.core.dominio import TipoDocumento
from customer_lookup.core.errors import DocumentoInvalido

TAMANHOS = {TipoDocumento.CPF: 11, TipoDocumento.CNPJ: 14}

# `str.isdigit()` aceitaria dígitos unicode (ex.: "５"); só aceitamos 0-9 ASCII e a máscara usual.
_PERMITIDOS = re.compile(r"[0-9.\-/ ]*")
_MASCARA = re.compile(r"[.\-/ ]")

_PESOS_CNPJ = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def normalizar(documento: str) -> str:
    if not _PERMITIDOS.fullmatch(documento):
        raise DocumentoInvalido("contém caracteres inválidos")
    return _MASCARA.sub("", documento)


def _digito(digitos: str, pesos: list[int]) -> str:
    resto = sum(int(d) * p for d, p in zip(digitos, pesos, strict=True)) % 11
    return "0" if resto < 2 else str(11 - resto)


def calcular_dv(base: str, tipo: TipoDocumento) -> str:
    """Os dois dígitos verificadores para a base (9 dígitos no CPF, 12 no CNPJ)."""
    if tipo is TipoDocumento.CPF:
        pesos1, pesos2 = list(range(10, 1, -1)), list(range(11, 1, -1))
    else:
        pesos1, pesos2 = _PESOS_CNPJ, [6, *_PESOS_CNPJ]
    dv1 = _digito(base, pesos1)
    return dv1 + _digito(base + dv1, pesos2)


def validar(documento: str, tipo: TipoDocumento, *, validar_dv: bool = True) -> str:
    """Devolve o documento só com dígitos ou levanta `DocumentoInvalido` com o motivo."""
    digitos = normalizar(documento)
    tamanho = TAMANHOS[tipo]
    if len(digitos) != tamanho:
        raise DocumentoInvalido(f"{tipo} deve ter {tamanho} dígitos")
    if len(set(digitos)) == 1:
        raise DocumentoInvalido("sequência de dígitos repetidos")
    if validar_dv and digitos[-2:] != calcular_dv(digitos[:-2], tipo):
        raise DocumentoInvalido("dígitos verificadores inválidos")
    return digitos


def mascarar(documento: str) -> str:
    """Versão segura para logs: esconde o início e os dígitos verificadores."""
    d = documento
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    if len(d) == 14:
        return f"**.{d[2:5]}.{d[5:8]}/{d[8:12]}-**"
    return "***"
