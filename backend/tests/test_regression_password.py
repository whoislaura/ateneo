"""Regresión: las contraseñas conservan espacios aunque el resto de campos se recorten."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app.models import Role, User
from app.schemas import AdminUserCreate, LoginRequest, PasswordReset


def test_login_request_preserves_password_spaces():
    body = LoginRequest(email="  a@b.com  ", password="  pass123  ")
    assert body.password == "  pass123  "
    assert body.email == "a@b.com"


def test_admin_schemas_preserve_password_spaces():
    created = AdminUserCreate(
        email="a@b.com", full_name="  Nombre  ", role=Role.STUDENT, password="  12345678  "
    )
    assert created.password == "  12345678  "
    assert created.full_name == "Nombre"
    assert PasswordReset(password="1234    ").password == "1234    "


def test_create_user_and_authenticate_with_spaced_password():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    User.metadata.create_all(engine)
    factory = sessionmaker(engine)
    password = "  clave-segura  "

    with factory() as db:
        user = auth.create_user(db, "  a@b.com  ", "  Nombre  ", password, Role.STUDENT)
        assert user.email == "a@b.com" and user.full_name == "Nombre"
        assert auth.authenticate(db, "a@b.com", password).id == user.id
        assert auth.authenticate(db, "a@b.com", password.strip()) is None
