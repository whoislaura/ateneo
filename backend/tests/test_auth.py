"""CU-00 sin PostgreSQL: usuarios y sesiones en SQLite en memoria vía dependency_overrides."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
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
    User.metadata.create_all(engine)
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


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """Limitador de login limpio y con reloj manual: las pruebas avanzan el tiempo sin dormir."""
    now = [1000.0]
    monkeypatch.setattr(auth, "login_limiter", auth.LoginLimiter(clock=lambda: now[0]))
    monkeypatch.setattr("app.api.login_limiter", auth.login_limiter)
    return now


def login(client, email, password=PASSWORD, **kwargs):
    body = {"email": email, "password": password}
    return client.post("/api/v1/auth/login", json=body, **kwargs)


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
    "history": ("get", "/api/v1/history", {}),
    "exams": ("get", "/api/v1/exams", {}),
    "documents": ("get", "/api/v1/documents", {}),
    "retired": ("get", "/api/v1/documents?include_retired=true", {}),
    "upload": ("post", "/api/v1/documents", PDF),
    "retire": ("delete", "/api/v1/documents/a", {}),
    "page": ("get", "/api/v1/documents/a/pages/1", {}),
    "feedback": ("post", "/api/v1/feedback", {"json": {"kind": "rating", "rating": 5}}),
}
# Rutas ya implementadas: código esperado con permiso (sin documentos en la base).
ALLOWED = {
    "history": 200,
    "exams": 200,
    "feedback": 201,
    "documents": 200,
    "retired": 200,
    "upload": 422,
    "retire": 404,
    "page": 404,
}
FORBIDDEN = {
    Role.STUDENT: {"retired", "upload", "retire"},
    Role.TEACHER: set(),
    Role.ADMIN: {"history", "exams"},
}


@pytest.mark.parametrize("role", list(Role))
def test_role_matrix(client, role):
    auth_headers = headers(client, role)
    for name, (method, path, kwargs) in ROUTES.items():
        assert client.request(method, path, **kwargs).status_code == 401, name
        response = client.request(method, path, headers=auth_headers, **kwargs)
        expected = 403 if name in FORBIDDEN[role] else ALLOWED.get(name, 501)
        assert response.status_code == expected, name


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


def test_user_management_cli(db_factory, monkeypatch, capsys):
    monkeypatch.setattr(auth, "session_factory", lambda: db_factory)
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt: "nueva-clave")
    with db_factory() as db:
        token = auth.create_session(db, auth.find_user(db, "student@ateneo.cu"))
        assert token and db.scalars(select(AuthSession)).all()

    auth.main(["set-password", "student@ateneo.cu"])
    with db_factory() as db:
        assert auth.authenticate(db, "student@ateneo.cu", "nueva-clave").role == Role.STUDENT
        assert db.scalars(select(AuthSession)).all() == [], "las sesiones deben revocarse"

    auth.main(["set-role", "student@ateneo.cu", "--role", "teacher"])
    with db_factory() as db:
        assert auth.find_user(db, "student@ateneo.cu").role == Role.TEACHER

    auth.main(["deactivate", "student@ateneo.cu"])
    with db_factory() as db:
        assert auth.authenticate(db, "student@ateneo.cu", "nueva-clave") is None

    auth.main(["activate", "student@ateneo.cu"])
    with db_factory() as db:
        assert auth.authenticate(db, "student@ateneo.cu", "nueva-clave").role == Role.TEACHER

    auth.main(["list-users"])
    output = capsys.readouterr().out
    assert "student@ateneo.cu" in output and "teacher" in output

    with pytest.raises(SystemExit):
        auth.main(["set-role", "nadie@ateneo.cu", "--role", "admin"])


def test_login_rate_limit_per_account(client, clock, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(auth, "LOGIN_WINDOW_SECONDS", 600)
    for _ in range(3):
        assert login(client, "student@ateneo.cu", "incorrecta").status_code == 401
    # Bloqueada aunque la contraseña sea correcta y el correo cambie de mayúsculas.
    response = login(client, " Student@Ateneo.cu")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "600"
    assert response.json()["error"] == {
        "code": "too_many_requests",
        "message": "Demasiados intentos fallidos. Vuelva a intentarlo en 10 min.",
        "details": None,
    }
    assert login(client, "teacher@ateneo.cu").status_code == 200  # otra cuenta, misma IP
    clock[0] += 599
    assert login(client, "student@ateneo.cu").headers["Retry-After"] == "1"
    clock[0] += 1
    assert login(client, "student@ateneo.cu").status_code == 200


def test_successful_login_resets_account_counter(client, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_MAX_ATTEMPTS", 3)
    for _ in range(2):
        login(client, "student@ateneo.cu", "incorrecta")
    assert login(client, "student@ateneo.cu").status_code == 200
    for _ in range(2):
        assert login(client, "student@ateneo.cu", "incorrecta").status_code == 401
    assert login(client, "student@ateneo.cu").status_code == 200


def test_login_rate_limit_per_ip(client, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_IP_MAX_ATTEMPTS", 3)
    for number in range(3):
        assert login(client, f"nadie{number}@ateneo.cu").status_code == 401
    response = login(client, "student@ateneo.cu")
    assert response.status_code == 429 and "Retry-After" in response.headers


def test_forwarded_for_only_trusted_when_configured(client, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_IP_MAX_ATTEMPTS", 2)
    # Sin proxies de confianza, inventar X-Forwarded-For no esquiva el límite por IP.
    for number in range(2):
        spoofed = {"X-Forwarded-For": f"10.0.0.{number}"}
        assert login(client, f"nadie{number}@ateneo.cu", headers=spoofed).status_code == 401
    assert (
        login(client, "student@ateneo.cu", headers={"X-Forwarded-For": "10.0.0.9"}).status_code
        == 429
    )

    # Con un salto (Nginx), cuenta la última entrada; lo que el cliente antepone se ignora.
    monkeypatch.setattr(auth, "TRUSTED_PROXY_HOPS", 1)
    for number in range(2):
        spoofed = {"X-Forwarded-For": f"1.2.3.{number}, 203.0.113.7"}
        assert login(client, f"nadie{number}@ateneo.cu", headers=spoofed).status_code == 401
    other = {"X-Forwarded-For": "203.0.113.8"}
    assert login(client, "student@ateneo.cu", headers=other).status_code == 200
    blocked = {"X-Forwarded-For": "1.2.3.9, 203.0.113.7"}
    assert login(client, "teacher@ateneo.cu", headers=blocked).status_code == 429


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        (0, "1.1.1.1", "testclient"),
        (1, None, "testclient"),
        (1, "1.1.1.1, 2.2.2.2", "2.2.2.2"),
        (2, "1.1.1.1, 2.2.2.2, 3.3.3.3", "2.2.2.2"),
        (3, "2.2.2.2", "2.2.2.2"),
    ],
)
def test_client_ip(monkeypatch, hops, forwarded, expected):
    from starlette.requests import Request

    monkeypatch.setattr(auth, "TRUSTED_PROXY_HOPS", hops)
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    request = Request({"type": "http", "headers": headers, "client": ("testclient", 50000)})
    assert auth.client_ip(request) == expected
