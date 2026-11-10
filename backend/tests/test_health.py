from fastapi.testclient import TestClient

from app.main import app


def test_health_contract():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_documented():
    schema = app.openapi()
    assert "200" in schema["paths"]["/api/v1/health"]["get"]["responses"]
