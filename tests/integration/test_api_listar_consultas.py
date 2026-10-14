"""GET /api/v1/consultas (RF-08)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from customer_lookup.core.dominio import StatusConsulta, TipoDocumento

URL = "/api/v1/consultas"
BASE = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _ids(resp) -> list[str]:
    return [item["id"] for item in resp.json()["items"]]


def test_lista_vazia(client: TestClient):
    resp = client.get(URL)

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}


def test_ordena_da_mais_recente_para_a_mais_antiga(client: TestClient, criar_consulta):
    antiga = criar_consulta(criado_em=BASE)
    nova = criar_consulta(criado_em=BASE + timedelta(minutes=5))
    meio = criar_consulta(criado_em=BASE + timedelta(minutes=1))

    assert _ids(client.get(URL)) == [str(nova.id), str(meio.id), str(antiga.id)]


def test_pagina_com_total_e_ultima_pagina_parcial(client: TestClient, criar_consulta):
    criadas = [criar_consulta(criado_em=BASE + timedelta(minutes=i)) for i in range(5)]
    esperado = [str(c.id) for c in reversed(criadas)]

    pagina2 = client.get(URL, params={"page": 2, "page_size": 2}).json()
    pagina3 = client.get(URL, params={"page": 3, "page_size": 2}).json()

    assert [i["id"] for i in pagina2["items"]] == esperado[2:4]
    assert (pagina2["page"], pagina2["page_size"], pagina2["total"]) == (2, 2, 5)
    assert [i["id"] for i in pagina3["items"]] == esperado[4:]


def test_empate_de_data_usa_id_como_desempate_estavel(client: TestClient, criar_consulta):
    # Sem desempate, a ordem de itens com o mesmo criado_em é indefinida e um item pode repetir entre páginas.
    # Inserimos em ordem crescente de id; o contrato exige id decrescente.
    ids = sorted((uuid.uuid4() for _ in range(4)), key=lambda u: u.hex)
    for consulta_id in ids:
        criar_consulta(id=consulta_id, criado_em=BASE)

    vistos = _ids(client.get(URL, params={"page": 1, "page_size": 2}))
    vistos += _ids(client.get(URL, params={"page": 2, "page_size": 2}))

    assert vistos == [str(i) for i in reversed(ids)]


def test_pagina_alem_do_fim_vem_vazia_com_total(client: TestClient, criar_consulta):
    criar_consulta()

    corpo = client.get(URL, params={"page": 5}).json()

    assert corpo["items"] == []
    assert corpo["total"] == 1


def test_filtra_por_status(client: TestClient, criar_consulta):
    erro = criar_consulta(status=StatusConsulta.ERROR)
    criar_consulta(status=StatusConsulta.SUCCESS)

    resp = client.get(URL, params={"status": "ERROR"})

    assert _ids(resp) == [str(erro.id)]
    assert resp.json()["total"] == 1


def test_filtra_por_documento_com_ou_sem_mascara(client: TestClient, criar_consulta):
    cnpj = criar_consulta(documento="11222333000181", tipo=TipoDocumento.CNPJ)
    criar_consulta(documento="52998224725")

    assert _ids(client.get(URL, params={"documento": "11.222.333/0001-81"})) == [str(cnpj.id)]
    assert _ids(client.get(URL, params={"documento": "11222333000181"})) == [str(cnpj.id)]


def test_combina_filtros(client: TestClient, criar_consulta):
    alvo = criar_consulta(documento="52998224725", status=StatusConsulta.SUCCESS)
    criar_consulta(documento="52998224725", status=StatusConsulta.ERROR)
    criar_consulta(documento="39053345264", status=StatusConsulta.SUCCESS)

    resp = client.get(URL, params={"documento": "529.982.247-25", "status": "SUCCESS"})

    assert _ids(resp) == [str(alvo.id)]


@pytest.mark.parametrize(
    ("params", "campo"),
    [
        ({"page": 0}, "page"),
        ({"page_size": 0}, "page_size"),
        ({"page_size": 101}, "page_size"),
        ({"page": "abc"}, "page"),
        ({"status": "DONE"}, "status"),
        ({"documento": "abc"}, "documento"),
    ],
)
def test_parametros_invalidos_retornam_422(client: TestClient, params: dict[str, object], campo: str):
    resp = client.get(URL, params=params)

    assert resp.status_code == 422
    erro = resp.json()["error"]
    assert erro["code"] == "VALIDATION_ERROR"
    assert erro["details"][0]["field"] == campo
