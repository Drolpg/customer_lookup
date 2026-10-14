"""Vocabulário do domínio, compartilhado por schemas, modelo e services."""

from enum import StrEnum


class TipoDocumento(StrEnum):
    CPF = "CPF"
    CNPJ = "CNPJ"


class StatusConsulta(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


STATUS_TERMINAIS = frozenset({StatusConsulta.SUCCESS, StatusConsulta.ERROR})
