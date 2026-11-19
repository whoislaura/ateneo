"""Verificador de citas CU-05: cada cita debe existir tal cual en la página vigente."""

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, DocumentStatus
from app.models import Document as DocumentRow
from app.models import Page as PageRow
from app.rag.index import check_schema

# Fuente de un fragmento vigente: chunk_id -> document_id, version, page_number,
# chunk_start, chunk_end y page_text (texto normalizado completo de la página).
Sources = dict[str, dict]


def citation_error(citation: dict, sources: Sources) -> str | None:
    """Motivo por el que la cita no es verificable, o None si es válida."""
    source = sources.get(citation.get("chunk_id"))
    if source is None:
        return "El fragmento no existe o su documento no está vigente."
    if (citation["document_id"], citation["version"], citation["page"]) != (
        source["document_id"],
        source["version"],
        source["page_number"],
    ):
        return "El fragmento no corresponde al documento, versión o página citados."
    start, end = citation["start"], citation["end"]
    if not source["chunk_start"] <= start < end <= source["chunk_end"]:
        return "Los offsets quedan fuera del fragmento."
    if source["page_text"][start:end] != citation["quote"]:
        return "El texto citado no coincide con la página."
    return None


def verify_citations(citations: list[dict], sources: Sources) -> tuple[list[dict], list[dict]]:
    """Separa citas válidas e inválidas; cada inválida lleva su motivo en `reason`."""
    valid, invalid = [], []
    for citation in citations:
        error = citation_error(citation, sources)
        if error:
            invalid.append(citation | {"reason": error})
        else:
            valid.append(citation)
    return valid, invalid


def sqlite_sources(path: Path, chunk_ids: Iterable[str]) -> Sources:
    """Adaptador del índice SQLite de muestra (siempre guarda solo la versión vigente)."""
    ids = list(dict.fromkeys(chunk_ids))
    if not ids:
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        check_schema(connection)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"""SELECT c.chunk_id, d.document_id, d.version, c.page_number,
                       c.start AS chunk_start, c.end AS chunk_end, p.text AS page_text
                FROM chunks AS c JOIN documents AS d ON d.document_id = c.document_id
                JOIN pages AS p ON p.document_id = c.document_id AND p.number = c.page_number
                WHERE c.version = d.version AND c.chunk_id IN ({",".join("?" * len(ids))})""",
            ids,
        ).fetchall()
    return {row["chunk_id"]: dict(row) for row in rows}


def db_sources(session: Session, chunk_ids: Iterable[str]) -> Sources:
    """Adaptador PostgreSQL: excluye documentos retirados y fragmentos de otra versión."""
    ids = list(dict.fromkeys(chunk_ids))
    if not ids:
        return {}
    statement = (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id,
            DocumentRow.version,
            Chunk.page_number,
            Chunk.start_offset.label("chunk_start"),
            Chunk.end_offset.label("chunk_end"),
            PageRow.text.label("page_text"),
        )
        .join(DocumentRow, DocumentRow.id == Chunk.document_id)
        .join(
            PageRow,
            (PageRow.document_id == Chunk.document_id) & (PageRow.number == Chunk.page_number),
        )
        .where(
            Chunk.id.in_(ids),
            Chunk.document_version == DocumentRow.version,
            DocumentRow.status != DocumentStatus.RETIRED,
        )
    )
    return {row["chunk_id"]: dict(row) for row in session.execute(statement).mappings()}
