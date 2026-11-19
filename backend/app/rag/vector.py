"""Embeddings, persistencia en PostgreSQL (modelos de AT-02) y recuperación pgvector."""

import hashlib
import json
import math
import os
import unicodedata
import urllib.request
from collections.abc import Callable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.models import Chunk, DocumentStatus, PageStatus
from app.models import Document as DocumentRow
from app.models import Page as PageRow
from app.rag.index import content_terms, document_report
from app.rag.ingestion import Document, IngestionError

Embedder = Callable[[list[str]], list[list[float]]]


def embedding_dimension() -> int:
    """Dimensión configurada; debe coincidir con el modelo de embeddings elegido."""
    value = os.environ.get("ATENEO_EMBED_DIM", "256")
    if not value.isdigit() or int(value) < 1:
        raise ValueError("ATENEO_EMBED_DIM debe ser un entero positivo.")
    return int(value)


def max_distance() -> float:
    """Distancia coseno máxima para aceptar un fragmento sin términos comunes con la pregunta."""
    # shortcut: 0.5 es una hipótesis; calibrar con preguntas doradas al elegir el modelo.
    value = os.environ.get("ATENEO_MAX_DISTANCE", "0.5")
    try:
        distance = float(value)
    except ValueError:
        distance = -1.0
    if not 0 <= distance <= 2:
        raise ValueError("ATENEO_MAX_DISTANCE debe ser un número entre 0 y 2.")
    return distance


def fake_embedder(texts: list[str]) -> list[list[float]]:
    """Determinista para pruebas y CI: bolsa de términos con hashing, sin red ni claves."""
    dimension, vectors = embedding_dimension(), []
    for text in texts:
        vector = [0.0] * dimension
        for term in content_terms(text):
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:8]) % dimension] += 1.0 if digest[8] & 1 else -1.0
        vectors.append(vector)
    return vectors


def openai_compatible_embedder(texts: list[str]) -> list[list[float]]:
    """Endpoint `/embeddings` compatible con OpenAI; la clave solo se lee del entorno."""
    key, model = os.environ.get("ATENEO_EMBED_API_KEY"), os.environ.get("ATENEO_EMBED_MODEL")
    if not key or not model:
        raise ValueError("Definir ATENEO_EMBED_API_KEY y ATENEO_EMBED_MODEL para embeddings.")
    base_url = os.environ.get("ATENEO_EMBED_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    dimension, vectors = embedding_dimension(), []
    for start in range(0, len(texts), 64):
        request = urllib.request.Request(
            base_url + "/embeddings",
            data=json.dumps({"model": model, "input": texts[start : start + 64]}).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = sorted(json.load(response)["data"], key=lambda item: item["index"])
        vectors += [item["embedding"] for item in data]
    if len(vectors) != len(texts) or any(len(v) != dimension for v in vectors):
        raise ValueError(f"El modelo no devolvió {len(texts)} vectores de dimensión {dimension}.")
    return vectors


EMBEDDERS: dict[str, Embedder] = {"fake": fake_embedder, "openai": openai_compatible_embedder}


def store_document(session: Session, document: Document, embedder: Embedder) -> dict:
    """Sustituye en una transacción las páginas y fragmentos vigentes del documento."""
    if not document.chunks:
        raise IngestionError("No hay fragmentos para indexar.")
    # Los embeddings se calculan antes de abrir la transacción: un fallo de red no toca la base.
    embeddings = embedder([chunk.text for chunk in document.chunks])
    report = document_report(document)
    meta, identifier = document.metadata, document.metadata.document_id
    with session.begin():
        # Se actualiza la fila en lugar de borrarla para conservar historial y autoría.
        row = session.get(DocumentRow, identifier, with_for_update=True) or DocumentRow(
            id=identifier
        )
        row.title, row.filename, row.version = meta.title, document.filename, document.version
        row.year, row.subject, row.topic = meta.year, meta.subject, meta.topic
        row.status = DocumentStatus(report["status"])
        row.chunk_settings = report["chunk_settings"]
        session.add(row)
        session.flush()
        # ON DELETE CASCADE elimina también los fragmentos; las citas conservan su copia.
        session.execute(delete(PageRow).where(PageRow.document_id == identifier))
        session.execute(
            insert(PageRow),
            [
                {
                    "document_id": identifier,
                    "number": p.number,
                    "label": p.label,
                    "text": p.text,
                    "status": PageStatus(p.status),
                }
                for p in document.pages
            ],
        )
        session.execute(
            insert(Chunk),
            [
                {
                    "id": c.chunk_id,
                    "document_id": identifier,
                    "document_version": document.version,
                    "page_number": c.page_number,
                    "start_offset": c.start,
                    "end_offset": c.end,
                    "text": c.text,
                    "embedding": embedding,
                }
                for c, embedding in zip(document.chunks, embeddings, strict=True)
            ],
        )
    return report | {"embedding_dimension": len(embeddings[0])}


def filter_key(value: str) -> str:
    # shortcut: lower() de PostgreSQL frente a casefold(); basta para español, revisar con ICU.
    return unicodedata.normalize("NFC", value).strip().lower()


def search(
    session: Session,
    query: str,
    embedder: Embedder,
    *,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Fragmentos más cercanos por distancia coseno, con el mismo formato que el índice SQLite."""
    if year is not None and (type(year) is not int or year not in range(1, 5)):
        raise IngestionError("El año debe estar entre 1 y 4.")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise IngestionError("El límite debe estar entre 1 y 5.")
    if len(query) > 1000:
        raise IngestionError("La consulta admite hasta 1000 caracteres.")
    [vector] = embedder([query])
    if not math.fsum(x * x for x in vector):
        return []  # el coseno con un vector nulo no está definido
    distance = Chunk.embedding.cosine_distance(vector).label("score")
    statement = (
        select(
            Chunk.id.label("chunk_id"),
            DocumentRow.id.label("document_id"),
            DocumentRow.title,
            DocumentRow.filename,
            Chunk.document_version.label("version"),
            DocumentRow.year,
            DocumentRow.subject,
            DocumentRow.topic,
            Chunk.page_number,
            PageRow.label.label("page_label"),
            Chunk.start_offset.label("start"),
            Chunk.end_offset.label("end"),
            Chunk.text,
            distance,
        )
        .join(DocumentRow, DocumentRow.id == Chunk.document_id)
        .join(
            PageRow,
            (PageRow.document_id == Chunk.document_id) & (PageRow.number == Chunk.page_number),
        )
        .where(
            DocumentRow.status != DocumentStatus.RETIRED,
            # La columna no tiene dimensión fija; se ignoran vectores de otro modelo.
            func.vector_dims(Chunk.embedding) == len(vector),
        )
        .order_by(distance, Chunk.id)
        .limit(limit)
    )
    if year is not None:
        statement = statement.where(DocumentRow.year == year)
    for column, value in ((DocumentRow.subject, subject), (DocumentRow.topic, topic)):
        if value is not None:
            statement = statement.where(func.lower(func.trim(column)) == filter_key(value))
    return [dict(row) for row in session.execute(statement).mappings()]
