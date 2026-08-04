from __future__ import annotations

from fastapi.testclient import TestClient

from app.app_factory import create_api_app


def test_health_and_readiness_are_distinct_and_hardened() -> None:
    client = TestClient(create_api_app("readiness-test"))

    health = client.get("/api/health", headers={"X-Request-ID": "phase5a-request-001"})
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.headers["x-request-id"] == "phase5a-request-001"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert health.headers["cache-control"] == "no-store"

    readiness = client.get("/api/ready")
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "ready"
    assert readiness.json()["dependencies"]["database"] == "ok"


def test_invalid_request_id_is_replaced() -> None:
    client = TestClient(create_api_app("request-id-test"))

    response = client.get("/api/health", headers={"X-Request-ID": "bad id"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad id"
    assert len(response.headers["x-request-id"]) == 32
