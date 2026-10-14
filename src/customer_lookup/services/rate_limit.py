"""Rate limit por janela fixa no Redis (RF-11)."""

import hashlib
import logging
import math
import time
from collections.abc import Callable

from redis import Redis, RedisError

from customer_lookup.core.logging import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)

JANELA_SEGUNDOS = 60


class LimitadorDeTaxa:
    def __init__(self, redis: Redis, limite: int, relogio: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._limite = limite
        self._relogio = relogio

    def verificar(self, chave: str) -> int | None:
        """Conta mais uma requisição. Devolve os segundos para o `Retry-After` se passou do limite; senão `None`."""
        agora = self._relogio()
        janela = int(agora // JANELA_SEGUNDOS)
        # Hash: a API key nunca é gravada em claro no Redis.
        identificador = hashlib.sha256(chave.encode()).hexdigest()[:16]
        contador = f"rl:{identificador}:{janela}"
        try:
            # INCR e EXPIRE na mesma ida (pipeline transacional); a chave some sozinha depois da janela.
            pipe = self._redis.pipeline()
            pipe.incr(contador)
            pipe.expire(contador, JANELA_SEGUNDOS)
            total, _ = pipe.execute()
        except RedisError:
            # Fail-open: o limite protege a API, não pode derrubá-la quando o Redis cai.
            logger.warning("rate_limit_indisponivel")
            return None

        if int(total) <= self._limite:
            return None
        fim_da_janela = (janela + 1) * JANELA_SEGUNDOS
        return max(1, math.ceil(fim_da_janela - agora))
