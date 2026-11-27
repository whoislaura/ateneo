"""CU-03: gestión del corpus (AT-10) y reindexación al subir, actualizar o retirar (AT-18).

Límite de subida en `ATENEO_MAX_UPLOAD_MB` (20 por defecto). Embeddings con `ATENEO_EMBEDDER`,
el mismo que usa la consulta (`app.query`).
"""

import dataclasses
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus, HistoryAction, HistoryEntry, Page, Role, User
from app.query import setting
from app.rag import vector
from app.rag.index import document_report
from app.rag.ingestion import DocumentMetadata, IngestionError, extract_pdf
from app.rag.rotation import ProviderError
from app.schemas import DocumentReplace, IngestionReport


def max_upload_bytes() -> int:
    value = os.environ.get("ATENEO_MAX_UPLOAD_MB", "20")
    if not value.isdigit() or int(value) < 1:
        raise ValueError("ATENEO_MAX_UPLOAD_MB debe ser un entero positivo.")
    return int(value) * 2**20


def read_pdf(file: UploadFile) -> bytes:
    """Bytes del PDF subido; 413 si supera el límite y 422 si no es un PDF."""
    limit = max_upload_bytes()
    # shortcut: Starlette ya recibió el cuerpo entero; el límite de red lo pone el proxy
    # (client_max_body_size en Nginx). Pasar a subida en streaming si se aceptan PDFs grandes.
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"El PDF supera el límite de {limit // 2**20} MB.",
        )
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "El archivo debe ser un PDF.")
    return data


def ingest(
    db: Session, document_id: str, form: DocumentReplace, user: User, action: HistoryAction
) -> dict:
    """Extrae, reindexa en una transacción (`vector.store_document`) y registra el historial.

    La versión anterior se conserva si falla la extracción (422) o el proveedor de embeddings
    (503). Un documento retirado vuelve a estar vigente al sustituirlo. Sustituir con el mismo
    PDF (mismo SHA-256) solo actualiza los metadatos: ni embeddings ni fragmentos nuevos.
    """
    data = read_pdf(form.file)
    metadata = {"title": form.title, "year": form.year, "subject": form.subject}
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "upload.pdf"
            path.write_bytes(data)
            document = extract_pdf(
                path,
                DocumentMetadata(document_id=document_id, topic=form.topic, **metadata),
            )
    except IngestionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    filename = Path(form.file.filename or "documento.pdf").name
    document = dataclasses.replace(document, filename=filename)
    user_id = user.id
    report = document_report(document)
    current = (
        db.get(Document, document_id, with_for_update=True, populate_existing=True)
        if action == HistoryAction.DOCUMENT_UPDATE
        else None
    )
    if current is not None and (current.version, current.chunk_settings) == (
        document.version,
        report["chunk_settings"],
    ):
        # Mismo PDF: solo cambian los metadatos. Reindexar dejaría sin enlace las citas vigentes.
        current.title, current.filename, current.year = form.title, filename, form.year
        current.subject, current.topic = form.subject, form.topic
        current.status = DocumentStatus(report["status"])  # reactiva un retirado
    else:
        # store_document abre su propia transacción: se cierra la que abrió la autenticación.
        db.commit()
        try:
            report = vector.store_document(
                db,
                document,
                setting(vector.EMBEDDERS, "ATENEO_EMBEDDER"),
                create_only=action == HistoryAction.DOCUMENT_UPLOAD,
            )
        except IntegrityError as exc:  # alta concurrente del mismo identificador
            raise HTTPException(status.HTTP_409_CONFLICT, "El documento ya existe.") from exc
        except (ProviderError, OSError) as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "El servicio de embeddings no está disponible.",
            ) from exc
    db.get(Document, document_id).uploaded_by = user_id
    db.add(
        HistoryEntry(user_id=user_id, action=action, summary=form.title, document_id=document_id)
    )
    db.commit()
    return {field: report[field] for field in IngestionReport.model_fields}


def visible(db: Session, document_id: str, user: User) -> Document:
    """Documento vigente; los retirados solo los ven Profesor y Administrador. Si no, 404."""
    document = db.get(Document, document_id)
    if document is None or (
        document.status == DocumentStatus.RETIRED and user.role == Role.STUDENT
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado.")
    return document


def existing(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado.")
    return document


def documents(
    db: Session,
    *,
    year: int | None,
    subject: str | None,
    topic: str | None,
    include_retired: bool,
) -> list[Document]:
    statement = select(Document).order_by(Document.year, Document.subject, Document.title)
    if not include_retired:
        statement = statement.where(Document.status != DocumentStatus.RETIRED)
    if year is not None:
        statement = statement.where(Document.year == year)
    # Misma comparación que la recuperación: sin mayúsculas ni espacios extremos.
    for column, value in ((Document.subject, subject), (Document.topic, topic)):
        if value is not None:
            statement = statement.where(func.lower(func.trim(column)) == vector.filter_key(value))
    return list(db.scalars(statement))


def retire(db: Session, document_id: str, user: User) -> None:
    """Deja de recuperarse y de validar citas; páginas, fragmentos y citas se conservan."""
    document = existing(db, document_id)
    if document.status == DocumentStatus.RETIRED:
        return
    document.status = DocumentStatus.RETIRED
    db.add(
        HistoryEntry(
            user_id=user.id,
            action=HistoryAction.DOCUMENT_RETIRE,
            summary=document.title,
            document_id=document.id,
        )
    )
    db.commit()


def page(db: Session, document_id: str, number: int, user: User) -> Page:
    document = visible(db, document_id, user)
    row = db.get(Page, (document.id, number))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Página no encontrada.")
    return row
