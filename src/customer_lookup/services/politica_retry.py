"""Decisão de retry (RN-06): função pura, sem Celery, para ser testada isoladamente."""

import random
from collections.abc import Callable
from dataclasses import dataclass

from customer_lookup.core.config import Settings


@dataclass(frozen=True)
class Retentar:
    delay_s: float


@dataclass(frozen=True)
class PoliticaRetry:
    max_tentativas: int
    base_segundos: float
    teto_segundos: float
    aleatorio: Callable[[], float] = random.random

    @classmethod
    def de_settings(cls, settings: Settings) -> PoliticaRetry:
        return cls(settings.retry_max_tentativas, settings.retry_base_segundos, settings.retry_teto_segundos)

    def calcular_delay(self, tentativa: int) -> float:
        """Exponencial com teto e jitter: espaça a carga e evita retries sincronizados."""
        # Expoente limitado: com muitas tentativas, 2**n cresceria sem necessidade (o teto já manda).
        exponencial = min(self.base_segundos * 2.0 ** min(tentativa - 1, 32), self.teto_segundos)
        return exponencial * (0.5 + self.aleatorio())

    def decidir(self, *, retentavel: bool, tentativa: int) -> Retentar | None:
        """`tentativa` é a que acabou de falhar (1 = primeira). `None` = finalizar com erro."""
        if retentavel and tentativa < self.max_tentativas:
            return Retentar(self.calcular_delay(tentativa))
        return None
