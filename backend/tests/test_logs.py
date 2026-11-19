import json
import logging

from fastapi.testclient import TestClient

from app.db import get_db
from app.logs import JsonFormatter
from app.main import app


def test_request_is_logged_without_body_or_headers(caplog):
    caplog.set_level(logging.INFO, "ateneo.request")
    response = TestClient(app).get(
        "/api/v1/health?token=secreto", headers={"Authorization": "Bearer secreto"}
    )
    [record] = [r for r in caplog.records if r.name == "ateneo.request"]
    line = json.loads(JsonFormatter().format(record))
    assert line["request_id"] == response.headers["X-Request-ID"]
    assert (line["method"], line["path"], line["status"]) == ("GET", "/api/v1/health", 200)
    assert line["duration_ms"] >= 0 and "secreto" not in json.dumps(line)


def test_unhandled_error_returns_contract_500_and_is_logged(caplog):
    def broken_db():
        raise RuntimeError("fallo simulado")

    app.dependency_overrides[get_db] = broken_db
    try:
        response = TestClient(app).post(
            "/api/v1/auth/login", json={"email": "a@upr.edu.cu", "password": "contraseña-secreta"}
        )
    finally:
        app.dependency_overrides.clear()
    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Error interno del servidor.",
            "details": {"request_id": request_id},
        }
    }
    [error] = [r for r in caplog.records if r.getMessage() == "unhandled_error"]
    assert error.request_id == request_id and "RuntimeError" in caplog.text
    assert "contraseña-secreta" not in caplog.text
