"""Conexión PostgreSQL. La URL se toma de DATABASE_URL (postgresql+psycopg://...)."""

import os
from collections.abc import Iterator
from functools import cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@cache
def session_factory() -> sessionmaker[Session]:
    # Perezoso: importar la app (tests, OpenAPI) no exige base de datos.
    # hide_parameters: los errores (y sus logs) no incluyen contraseñas, tokens ni preguntas.
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://")
    return sessionmaker(create_engine(url, hide_parameters=True))


def get_db() -> Iterator[Session]:
    """Dependencia FastAPI: una sesión por petición."""
    with session_factory()() as db:
        yield db
