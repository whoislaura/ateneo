"""Índice de muestra local. El modelo de producción de Pedro queda separado."""

import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

from app.rag.ingestion import Document, IngestionError

SCHEMA = (
    "CREATE TABLE ateneo_meta (schema_version INTEGER NOT NULL)",
    "INSERT INTO ateneo_meta VALUES (1)",
    """CREATE TABLE documents (
        document_id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
        version TEXT NOT NULL, year INTEGER NOT NULL, subject TEXT NOT NULL,
        topic TEXT NOT NULL, subject_key TEXT NOT NULL, topic_key TEXT NOT NULL,
        settings TEXT NOT NULL)""",
    """CREATE TABLE pages (
        document_id TEXT NOT NULL, number INTEGER NOT NULL, label TEXT,
        text TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(document_id, number))""",
    """CREATE VIRTUAL TABLE chunks USING fts5(
        chunk_id UNINDEXED, document_id UNINDEXED, version UNINDEXED,
        page_number UNINDEXED, start UNINDEXED, end UNINDEXED, text,
        tokenize='unicode61 remove_diacritics 2')""",
)


def metadata_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def check_schema(connection: sqlite3.Connection, *, create: bool = False) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not tables and create:
        for statement in SCHEMA:
            connection.execute(statement)
        return
    required = {"ateneo_meta", "documents", "pages", "chunks"}
    if not required <= tables:
        raise IngestionError("El archivo no es un índice de muestra de Ateneo.")
    if connection.execute("SELECT schema_version FROM ateneo_meta").fetchall() != [(1,)]:
        raise IngestionError("Versión de índice incompatible; utiliza otro archivo de muestra.")


def index_document(path: Path, document: Document) -> dict:
    if not document.chunks:
        raise IngestionError("No hay fragmentos para indexar.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            check_schema(connection, create=True)
            identifier = document.metadata.document_id
            for table in ("chunks", "pages", "documents"):
                connection.execute(f"DELETE FROM {table} WHERE document_id = ?", (identifier,))
            meta = document.metadata
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    meta.title,
                    document.filename,
                    document.version,
                    meta.year,
                    meta.subject,
                    meta.topic,
                    metadata_key(meta.subject),
                    metadata_key(meta.topic),
                    document.settings.model_dump_json(),
                ),
            )
            connection.executemany(
                "INSERT INTO pages VALUES (?, ?, ?, ?, ?)",
                [(identifier, p.number, p.label, p.text, p.status) for p in document.pages],
            )
            connection.executemany(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.chunk_id,
                        identifier,
                        document.version,
                        c.page_number,
                        c.start,
                        c.end,
                        c.text,
                    )
                    for c in document.chunks
                ],
            )
    missing = [page.number for page in document.pages if page.status == "no_text"]
    return {
        "document_id": identifier,
        "version": document.version,
        "status": "partial" if missing else "indexed",
        "pages": len(document.pages),
        "chunks": len(document.chunks),
        "no_text_pages": missing,
        "warnings": ["Hay páginas sin texto extraíble; revisar si están vacías o requieren OCR."]
        if missing
        else [],
        "chunk_settings": json.loads(document.settings.model_dump_json()),
    }


def search(
    path: Path,
    query: str,
    *,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
    limit: int = 5,
) -> list[dict]:
    if year is not None and (type(year) is not int or year not in range(1, 5)):
        raise IngestionError("El año debe estar entre 1 y 4.")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise IngestionError("El límite debe estar entre 1 y 5.")
    if len(query) > 1000:
        raise IngestionError("La consulta admite hasta 1000 caracteres.")
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", unicodedata.normalize("NFC", query))))
    expression = " OR ".join('"' + term + '"' for term in terms)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        check_schema(connection)
        if not terms:
            return []
        conditions, parameters = ["chunks MATCH ?"], [expression]
        for column, value in (("year", year), ("subject_key", subject), ("topic_key", topic)):
            if value is not None:
                conditions.append(f"d.{column} = ?")
                parameters.append(value if column == "year" else metadata_key(value))
        parameters.append(limit)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT c.chunk_id, d.document_id, d.title, d.filename, c.version,
                      d.year, d.subject, d.topic, c.page_number, p.label AS page_label,
                      c.start, c.end, c.text, bm25(chunks) AS score
               FROM chunks AS c JOIN documents AS d ON d.document_id = c.document_id
               JOIN pages AS p ON p.document_id = c.document_id AND p.number = c.page_number
               WHERE """
            + " AND ".join(conditions)
            + " ORDER BY score, c.chunk_id LIMIT ?",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]
