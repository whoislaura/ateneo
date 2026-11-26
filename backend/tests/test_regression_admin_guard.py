"""Regresión: la guarda del último administrador activo es atómica."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admin import guard_last_admin, update_account
from app.models import Base, Role, User
from app.schemas import AdminUserUpdate

MESSAGE = "Debe quedar al menos un administrador activo."


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine)
    with maker() as db:
        db.add_all(
            [
                User(email=f"{role}@ateneo.cu", full_name=role, password_hash="x", role=Role.ADMIN)
                for role in ("a", "b")
            ]
        )
        db.commit()
    yield maker
    engine.dispose()


def test_interleaved_demotions_keep_an_admin(factory):
    with factory() as first, factory() as second:
        a_first, b_first = first.scalars(select(User).order_by(User.id)).all()
        a_second, b_second = second.scalars(select(User).order_by(User.id)).all()

        with patch.object(first, "commit"):
            update_account(b_first.id, AdminUserUpdate(role=Role.STUDENT), a_first, first)

        with pytest.raises(HTTPException) as error:
            update_account(a_second.id, AdminUserUpdate(role=Role.STUDENT), b_second, second)
        assert error.value.status_code == 409
        assert error.value.detail == MESSAGE
        assert dict(second.execute(select(User.id, User.role)).all()) == {
            a_first.id: Role.ADMIN,
            b_first.id: Role.STUDENT,
        }
        second.rollback()


def test_guard_still_blocks_the_last_admin(factory):
    with factory() as db:
        admin, other = db.scalars(select(User).order_by(User.id)).all()
        other.is_active = False
        db.commit()
        with pytest.raises(HTTPException) as error:
            guard_last_admin(db, admin.id)
        assert error.value.status_code == 409
        assert error.value.detail == MESSAGE
        db.rollback()
