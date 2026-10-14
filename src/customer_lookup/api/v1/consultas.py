"""Rotas HTTP de consultas: só traduzem HTTP ⇄ service."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from customer_lookup.api.deps import get_publicador
from customer_lookup.core import contexto
from customer_lookup.core.config import Settings, get_settings
from customer_lookup.core.dominio import StatusConsulta
from customer_lookup.db.session import get_db
from customer_lookup.ports import PublicadorDeTarefas
from customer_lookup.schemas.consulta import ConsultaCreate, ConsultaCriada, ConsultaRead, PaginaConsultas
from customer_lookup.services import consulta_service

PREFIXO = "/api/v1/consultas"
router = APIRouter(prefix=PREFIXO, tags=["consultas"])

DbDep = Annotated[Session, Depends(get_db)]


@router.post("", status_code=status.HTTP_202_ACCEPTED, summary="Solicita uma consulta de cliente")
def criar_consulta(
    dados: ConsultaCreate,
    response: Response,
    db: DbDep,
    publicador: Annotated[PublicadorDeTarefas, Depends(get_publicador)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConsultaCriada:
    consulta = consulta_service.criar(
        db,
        publicador,
        documento=dados.documento,
        tipo=dados.tipo,
        validar_dv=settings.documento_validar_dv,
        request_id=contexto.request_id.get(),
    )
    response.headers["Location"] = f"{PREFIXO}/{consulta.id}"
    return ConsultaCriada(id=consulta.id, status=consulta.status)


@router.get("/{consulta_id}", summary="Status e resultado de uma consulta")
def obter_consulta(consulta_id: uuid.UUID, db: DbDep) -> ConsultaRead:
    return ConsultaRead.model_validate(consulta_service.obter(db, consulta_id))


@router.get("", summary="Lista consultas com paginação e filtros")
def listar_consultas(
    db: DbDep,
    status: StatusConsulta | None = None,
    documento: Annotated[str | None, Query(pattern=r"^[0-9.\-/ ]{1,32}$", description="Com ou sem máscara.")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginaConsultas:
    itens, total = consulta_service.listar(db, status=status, documento=documento, page=page, page_size=page_size)
    return PaginaConsultas(
        items=[ConsultaRead.model_validate(c) for c in itens], page=page, page_size=page_size, total=total
    )
