"""Conexión PostgreSQL. La URL se toma de DATABASE_URL (postgresql+psycopg://...)."""

import os
from collections.abc import Iterator
from functools import cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@cache
def session_factory() -> sessionmaker[Session]:
    # Perezoso: importar la app (tests, OpenAPI) no exige base de datos.
    return sessionmaker(create_engine(os.environ.get("DATABASE_URL", "postgresql+psycopg://")))


def get_db() -> Iterator[Session]:
    """Dependencia FastAPI: una sesión por petición."""
    with session_factory()() as db:
        yield db
