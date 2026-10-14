"""Implementações falsas das portas, para testar sem Redis/Celery."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NoReturn

import redis
from sqlalchemy.orm import Session, sessionmaker

from customer_lookup.core.dominio import StatusConsulta
from customer_lookup.models import Consulta
from customer_lookup.ports import ErroIntegracao, FalhaAoPublicar

API_KEY_TESTE = "chave-de-teste"  # o conftest define API_KEY com este valor antes de importar a aplicação


@dataclass
class Publicacao:
    consulta_id: uuid.UUID
    request_id: str | None
    status_visivel_no_banco: StatusConsulta | None


@dataclass
class PublicadorFake:
    """Registra as publicações e o que outra conexão enxerga no banco naquele instante."""

    session_factory: sessionmaker[Session]
    falhar: bool = False
    publicacoes: list[Publicacao] = field(default_factory=list)

    def publicar_processamento(self, consulta_id: uuid.UUID, request_id: str | None) -> None:
        if self.falhar:
            raise FalhaAoPublicar("broker recusou a conexão em redis://10.0.0.5:6379") from ConnectionError()
        # Sessão nova = outra conexão: só enxerga a consulta se ela já foi commitada (como o worker).
        with self.session_factory() as outra_sessao:
            consulta = outra_sessao.get(Consulta, consulta_id)
            status = consulta.status if consulta else None
        self.publicacoes.append(Publicacao(consulta_id, request_id, status))


@dataclass
class ChamadaExterna:
    documento: str
    transacao_aberta: bool


@dataclass
class ClienteExternoFake:
    """Devolve as respostas do roteiro, em ordem (dict = sucesso; ErroIntegracao = falha).

    `ao_chamar` permite simular algo acontecendo durante a chamada (ex.: outro worker finalizando a consulta).
    """

    roteiro: list[dict[str, object] | ErroIntegracao]
    sessao_observada: Session | None = None
    ao_chamar: Callable[[], None] | None = None
    chamadas: list[ChamadaExterna] = field(default_factory=list)

    def consultar_cliente(self, documento: str) -> dict[str, object]:
        aberta = self.sessao_observada.in_transaction() if self.sessao_observada else False
        self.chamadas.append(ChamadaExterna(documento, aberta))
        if self.ao_chamar:
            self.ao_chamar()
        resposta = self.roteiro[min(len(self.chamadas), len(self.roteiro)) - 1]
        if isinstance(resposta, ErroIntegracao):
            raise resposta
        return resposta


class RedisFora:
    """Redis indisponível que falha na hora (uma conexão recusada de verdade leva segundos no Windows)."""

    def pipeline(self) -> NoReturn:
        raise redis.ConnectionError("Error 111 connecting to redis:6379. Connection refused.")

    def ping(self) -> NoReturn:
        raise redis.ConnectionError("Error 111 connecting to redis:6379. Connection refused.")
