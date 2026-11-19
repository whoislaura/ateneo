"""CU-00 sin PostgreSQL: usuarios y sesiones en SQLite en memoria vía dependency_overrides."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app.db import get_db
from app.main import app
from app.models import AuthSession, Role, User

PASSWORD = "clave-de-prueba"


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    User.metadata.create_all(engine, tables=[User.__table__, AuthSession.__table__])
    factory = sessionmaker(engine)
    with factory() as db:
        for role in Role:
            auth.create_user(db, f"{role.value}@Ateneo.cu ", role.value, PASSWORD, role)
        db.add(
            User(
                email="baja@ateneo.cu",
                full_name="Baja",
                password_hash=auth.hash_password(PASSWORD),
                role=Role.STUDENT,
                is_active=False,
            )
        )
        db.commit()
    return factory


@pytest.fixture
def client(db_factory):
    def override():
        with db_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def headers(client, role: Role):
    token = login(client, f"{role.value}@ateneo.cu").json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_roundtrip():
    stored = auth.hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password(PASSWORD + "x", stored)
    assert not auth.verify_password(PASSWORD, "basura")
    assert auth.hash_password(PASSWORD) != stored  # sal distinta


def test_login_me_logout(client):
    response = login(client, " Student@Ateneo.cu")
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == auth.TOKEN_TTL.total_seconds()
    assert body["user"] | {"id": 0} == {
        "id": 0,
        "email": "student@ateneo.cu",
        "full_name": "student",
        "role": "student",
    }
    bearer = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=bearer).json() == body["user"]
    assert client.post("/api/v1/auth/logout", headers=bearer).status_code == 204
    assert client.get("/api/v1/auth/me", headers=bearer).status_code == 401


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("student@ateneo.cu", "incorrecta"),
        ("nadie@ateneo.cu", PASSWORD),
        ("baja@ateneo.cu", PASSWORD),
    ],
)
def test_bad_credentials_are_indistinguishable(client, email, password):
    response = login(client, email, password)
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "unauthorized",
        "message": "Correo o contraseña incorrectos.",
        "details": None,
    }


@pytest.mark.parametrize("value", [None, "Bearer inventado", "Basic abc"])
def test_missing_or_invalid_token_is_401(client, value):
    response = client.get("/api/v1/auth/me", headers={"Authorization": value} if value else {})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


def test_expired_session_and_inactive_user_are_401(client, db_factory):
    expired = headers(client, Role.STUDENT)
    with db_factory() as db:
        db.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(1)))
        db.commit()
    assert client.get("/api/v1/auth/me", headers=expired).status_code == 401

    disabled = headers(client, Role.TEACHER)
    with db_factory() as db:
        db.execute(update(User).where(User.role == Role.TEACHER).values(is_active=False))
        db.commit()
    assert client.get("/api/v1/auth/me", headers=disabled).status_code == 401


PDF = {
    "data": {"document_id": "a", "title": "T", "year": "2", "subject": "S", "topic": "T"},
    "files": {"file": ("a.pdf", b"%PDF", "application/pdf")},
}
ROUTES = {
    "query": ("post", "/api/v1/queries", {"json": {"question": "¿Qué es?"}}),
    "history": ("get", "/api/v1/history", {}),
    "exams": ("get", "/api/v1/exams", {}),
    "documents": ("get", "/api/v1/documents", {}),
    "retired": ("get", "/api/v1/documents?include_retired=true", {}),
    "upload": ("post", "/api/v1/documents", PDF),
    "retire": ("delete", "/api/v1/documents/a", {}),
    "page": ("get", "/api/v1/documents/a/pages/1", {}),
    "answer": ("get", "/api/v1/answers/1", {}),
    "feedback": ("post", "/api/v1/feedback", {"json": {"kind": "rating", "rating": 5}}),
}
FORBIDDEN = {
    Role.STUDENT: {"retired", "upload", "retire"},
    Role.TEACHER: set(),
    Role.ADMIN: {"query", "history", "exams"},
}


@pytest.mark.parametrize("role", list(Role))
def test_role_matrix(client, role):
    auth_headers = headers(client, role)
    for name, (method, path, kwargs) in ROUTES.items():
        assert client.request(method, path, **kwargs).status_code == 401, name
        response = client.request(method, path, headers=auth_headers, **kwargs)
        assert response.status_code == (403 if name in FORBIDDEN[role] else 501), name


def test_create_user_cli(db_factory, monkeypatch, capsys):
    monkeypatch.setattr(auth, "session_factory", lambda: db_factory)
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt: "otra-clave-segura")
    auth.main(["create-user", "Nuevo@ateneo.cu", "--name", "Nuevo", "--role", "admin"])
    assert "nuevo@ateneo.cu (admin)" in capsys.readouterr().out
    with db_factory() as db:
        assert auth.authenticate(db, "nuevo@ateneo.cu", "otra-clave-segura").role == Role.ADMIN

    with pytest.raises(SystemExit):
        auth.main(["create-user", "nuevo@ateneo.cu", "--name", "Otro", "--role", "student"])
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt: "corta")
    with pytest.raises(SystemExit):
        auth.main(["create-user", "x@ateneo.cu", "--name", "X", "--role", "student"])
