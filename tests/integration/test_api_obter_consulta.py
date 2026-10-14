"""GET /api/v1/consultas/{id} (RF-07)."""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from customer_lookup.core.dominio import StatusConsulta


def test_retorna_consulta_com_todos_os_campos(client: TestClient, criar_consulta):
    momento = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
    consulta = criar_consulta(
        status=StatusConsulta.SUCCESS,
        tentativas=2,
        resultado={"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"},
        ultimo_erro="serviço externo respondeu HTTP 503",
        criado_em=momento,
        processado_em=momento,
    )

    resp = client.get(f"/api/v1/consultas/{consulta.id}")

    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["id"] == str(consulta.id)
    assert corpo["documento"] == "52998224725"
    assert corpo["tipo"] == "CPF"
    assert corpo["status"] == "SUCCESS"
    assert corpo["tentativas"] == 2
    assert corpo["resultado"] == {"nome": "Cliente Teste", "score": 742, "situacao": "REGULAR"}
    assert corpo["ultimo_erro"] == "serviço externo respondeu HTTP 503"
    assert corpo["criado_em"] == "2026-10-14T12:00:00Z"
    assert corpo["processado_em"] == "2026-10-14T12:00:00Z"
    assert corpo["atualizado_em"].endswith("Z")
    assert "request_id" not in corpo


def test_consulta_pendente_tem_resultado_e_processado_em_nulos(client: TestClient, criar_consulta):
    consulta = criar_consulta()

    corpo = client.get(f"/api/v1/consultas/{consulta.id}").json()

    assert corpo["status"] == "PENDING"
    assert corpo["resultado"] is None
    assert corpo["processado_em"] is None


def test_consulta_inexistente_retorna_404(client: TestClient):
    resp = client.get(f"/api/v1/consultas/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json() == {"error": {"code": "CONSULTA_NOT_FOUND", "message": "Consulta não encontrada."}}


def test_id_que_nao_e_uuid_retorna_422(client: TestClient):
    resp = client.get("/api/v1/consultas/123")

    assert resp.status_code == 422
    assert resp.json()["error"]["details"] == [{"field": "consulta_id", "message": "UUID inválido"}]
