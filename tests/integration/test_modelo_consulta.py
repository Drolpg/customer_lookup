"""Comportamento do modelo `Consulta` no banco (spec §5)."""

import time
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from customer_lookup.core.dominio import StatusConsulta, TipoDocumento
from customer_lookup.models import Consulta


def _nova(db: Session, **campos: object) -> Consulta:
    consulta = Consulta(id=uuid.uuid4(), documento="52998224725", tipo=TipoDocumento.CPF, **campos)
    db.add(consulta)
    db.commit()
    db.refresh(consulta)
    return consulta


def test_valores_padrao_de_uma_nova_consulta(db: Session):
    consulta = _nova(db)

    assert consulta.status is StatusConsulta.PENDING
    assert consulta.tentativas == 0
    assert consulta.resultado is None
    assert consulta.ultimo_erro is None
    assert consulta.processado_em is None
    assert consulta.criado_em is not None
    assert consulta.atualizado_em is not None


def test_resultado_json_faz_ida_e_volta(db: Session):
    resultado = {"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"}
    consulta = _nova(db, resultado=resultado)

    db.expire_all()
    assert db.get(Consulta, consulta.id).resultado == resultado


def test_update_core_atualiza_atualizado_em(db: Session):
    # O worker usa UPDATE ... WHERE (Core), não o ORM: o onupdate precisa valer também nesse caminho.
    consulta = _nova(db)
    antes, criado = consulta.atualizado_em, consulta.criado_em
    time.sleep(0.01)

    db.execute(update(Consulta).where(Consulta.id == consulta.id).values(tentativas=Consulta.tentativas + 1))
    db.commit()
    db.refresh(consulta)

    assert consulta.tentativas == 1
    assert consulta.atualizado_em > antes
    assert consulta.criado_em == criado


def test_enums_sao_gravados_como_texto(db: Session):
    consulta = _nova(db, status=StatusConsulta.PROCESSING)

    linha = db.connection().exec_driver_sql(f"SELECT tipo, status FROM consultas WHERE id = '{consulta.id.hex}'").one()
    assert tuple(linha) == ("CPF", "PROCESSING")
