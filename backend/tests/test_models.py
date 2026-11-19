import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.models import Base, Chunk, Citation
from app.rag.ingestion import ChunkSettings, DocumentMetadata, Page, chunk_page

BACKEND = Path(__file__).resolve().parents[1]
# Variable propia: la prueba crea y elimina todas las tablas de esa base.
TEST_DATABASE_URL = os.environ.get("ATENEO_TEST_DATABASE_URL")


def alembic_config(buffer=None) -> Config:
    return Config(toml_file=str(BACKEND / "pyproject.toml"), output_buffer=buffer)


def test_migration_sql_creates_every_model_table(monkeypatch):
    monkeypatch.chdir(BACKEND)
    buffer = io.StringIO()
    command.upgrade(alembic_config(buffer), "head", sql=True)
    sql = buffer.getvalue()
    for table in Base.metadata.tables:
        assert f"CREATE TABLE {table} (" in sql
    assert "embedding VECTOR" in sql
    assert "CHECK ((answer_id IS NULL) <> (question_id IS NULL))" in sql


def test_chunk_model_matches_ingestion_shape():
    metadata = DocumentMetadata(document_id="d", title="T", year=1, subject="S", topic="T")
    page = Page(1, None, "Texto de prueba.", "text")
    [chunk] = chunk_page(page, metadata.document_id, "v" * 64, ChunkSettings())
    row = Chunk(
        id=chunk.chunk_id,
        document_id=metadata.document_id,
        document_version="v" * 64,
        page_number=chunk.page_number,
        start_offset=chunk.start,
        end_offset=chunk.end,
        text=chunk.text,
    )
    assert len(row.id) <= Chunk.__table__.c.id.type.length
    assert {"document_id", "document_version", "page_number", "start_offset", "end_offset"} <= set(
        Citation.__table__.c.keys()
    )


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL")
def test_migration_matches_models_on_postgres(monkeypatch):
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config = alembic_config()
    command.upgrade(config, "head")
    try:
        with create_engine(TEST_DATABASE_URL).connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    finally:
        command.downgrade(config, "base")
