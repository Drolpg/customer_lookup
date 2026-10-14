"""Liveness (RF-12)."""

from fastapi.testclient import TestClient


def test_health_responde_ok(client: TestClient):
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
