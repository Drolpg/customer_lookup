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


class NaoAutorizado(AppError):
    def __init__(self) -> None:
        super().__init__("Chave de API ausente ou inválida.", code="UNAUTHORIZED", status_code=401)


class LimiteExcedido(AppError):
    def __init__(self, retry_after_s: int) -> None:
        super().__init__(
            "Limite de requisições excedido. Tente novamente mais tarde.",
            code="RATE_LIMITED",
            status_code=429,
            headers={"Retry-After": str(retry_after_s)},
        )


class ServicoIndisponivel(AppError):
    def __init__(self, componentes: list[str]) -> None:
        super().__init__(
            "Serviço indisponível.",
            code="SERVICE_UNAVAILABLE",
            status_code=503,
            details=[{"component": c, "status": "indisponível"} for c in componentes],
        )


class DocumentoInvalido(AppError):
    def __init__(self, motivo: str) -> None:
        super().__init__(
            "Documento informado é inválido.",
            code="INVALID_DOCUMENT",
            status_code=422,
            details=[{"field": "documento", "message": motivo}],
        )
