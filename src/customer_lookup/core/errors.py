"""Erros previstos da aplicação. Cada um vira o envelope `{"error": {...}}` com status HTTP próprio."""

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        self.headers = headers


class ConsultaNaoEncontrada(AppError):
    def __init__(self) -> None:
        super().__init__("Consulta não encontrada.", code="CONSULTA_NOT_FOUND", status_code=404)


class FilaIndisponivel(AppError):
    def __init__(self, consulta_id: str) -> None:
        super().__init__(
            "Fila de processamento indisponível. A consulta foi registrada com erro; tente novamente.",
            code="QUEUE_UNAVAILABLE",
            status_code=503,
            details=[{"id": consulta_id}],
        )


class DocumentoInvalido(AppError):
    def __init__(self, motivo: str) -> None:
        super().__init__(
            "Documento informado é inválido.",
            code="INVALID_DOCUMENT",
            status_code=422,
            details=[{"field": "documento", "message": motivo}],
        )
