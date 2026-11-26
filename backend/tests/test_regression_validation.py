"""Regresión: ids acotados a INTEGER, 422 sin datos sensibles, guarda de admin en la CLI."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app.db import get_db
from app.main import app
from app.models import AuthSession, Role, User

PASSWORD = "clave-de-prueba"
BIG = 99999999999999
TEST_DATABASE_URL = os.environ.get("ATENEO_TEST_DATABASE_URL")


def make_factory(url=None):
    if url:
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    User.metadata.drop_all(engine)
    User.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        for role in (Role.ADMIN, Role.STUDENT):
            auth.create_user(db, f"{role.value}@ateneo.cu", role.value, PASSWORD, role)
    return factory


def client_for(factory):
    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def headers_for(client, role="admin"):
    body = {"email": f"{role}@ateneo.cu", "password": PASSWORD}
    token = client.post("/api/v1/auth/login", json=body).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL"
            ),
        ),
    ]
)
def factory(request, monkeypatch):
    monkeypatch.setattr(auth, "login_limiter", auth.LoginLimiter())
    monkeypatch.setattr("app.api.login_limiter", auth.login_limiter)
    factory = make_factory(TEST_DATABASE_URL if request.param == "postgres" else None)
    yield factory
    app.dependency_overrides.clear()
    User.metadata.drop_all(factory.kw["bind"])  # no dejar tablas a las pruebas de migración


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/answers/{BIG}",
        f"/api/v1/exams/{BIG}",
        f"/api/v1/exams/{BIG}/answers",
        f"/api/v1/documents/x/pages/{BIG}",
        f"/api/v1/admin/answers/{BIG}",
        f"/api/v1/admin/answers?user_id={BIG}",
        "/api/v1/admin/users?offset=2000000",
        "/api/v1/exams/0",
    ],
)
def test_oversized_ids_are_422_not_500(factory, path):
    with client_for(factory) as client:
        assert (
            client.get(
                path, headers=headers_for(client, "admin" if "/admin/" in path else "student")
            ).status_code
            == 422
        )


def test_oversized_ids_in_routes_and_bodies(factory):
    with client_for(factory) as client:
        admin, student = headers_for(client), headers_for(client, "student")
        assert client.delete(f"/api/v1/history/{BIG}", headers=student).status_code == 422
        assert client.patch(f"/api/v1/admin/users/{BIG}", json={}, headers=admin).status_code == 422
        feedback = {"kind": "answer", "rating": 3, "answer_id": BIG}
        assert client.post("/api/v1/feedback", json=feedback, headers=student).status_code == 422


def test_422_hides_input_and_ctx(factory):
    with client_for(factory) as client:
        body = {"email": "a@b.cu", "password": ["clave-secreta"]}
        response = client.post("/api/v1/auth/login", json=body)
    assert response.status_code == 422
    assert "clave-secreta" not in response.text
    for detail in response.json()["error"]["details"]:
        assert set(detail) == {"type", "loc", "msg"}


def test_cli_keeps_last_active_admin(monkeypatch, capsys):
    factory = make_factory()
    monkeypatch.setattr(auth, "session_factory", lambda: factory)
    for argv in (
        ["set-role", "admin@ateneo.cu", "--role", "teacher"],
        ["deactivate", "admin@ateneo.cu"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            auth.main(argv)
        assert exit_info.value.code == 1
    assert "al menos un administrador activo" in capsys.readouterr().err
    with factory() as db:
        admin = auth.find_user(db, "admin@ateneo.cu")
        assert admin.role == Role.ADMIN and admin.is_active

    with factory() as db:
        auth.create_user(db, "otro@ateneo.cu", "Otro", PASSWORD, Role.ADMIN)
    auth.main(["set-role", "admin@ateneo.cu", "--role", "teacher"])
    auth.main(["deactivate", "student@ateneo.cu"])  # no es admin: sin guarda
    with factory() as db:
        assert auth.find_user(db, "admin@ateneo.cu").role == Role.TEACHER
        assert db.scalars(select(AuthSession)).all() == []
