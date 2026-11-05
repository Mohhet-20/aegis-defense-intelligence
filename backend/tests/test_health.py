"""Startup and health/readiness checks."""
from __future__ import annotations


def test_liveness(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_database_ok(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


def test_readiness_reports_tracker_runtime_ok(client):
    """Confirms scipy's Hungarian-assignment dependency is
    actually importable and callable in this process -- not just that
    the API process is up (an available process is never,
    by itself, proof that tracking works)."""
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["tracker_runtime"] == "ok"


def test_openapi_schema_is_served(client):
    """Confirms the app actually starts and wires up routing -- a basic
    startup smoke test distinct from the liveness probe."""
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "AEGIS"
    assert "/api/v1/health/live" in schema["paths"]
