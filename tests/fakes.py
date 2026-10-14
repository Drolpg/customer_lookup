"""Implementações falsas das portas, para testar sem Redis/Celery."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from customer_lookup.core.dominio import StatusConsulta
from customer_lookup.models import Consulta
from customer_lookup.ports import FalhaAoPublicar


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
