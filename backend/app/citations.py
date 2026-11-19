"""CU-05: validación central de citas antes de guardar o devolver respuestas de CU-01 y CU-02."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnswerStatus, Chunk, Citation, Document, DocumentStatus, Page

NO_EVIDENCE = "No encontrado en el corpus."
MARK = re.compile(r"\s*\[(\d+)\]")


def verified(db: Session, item: dict) -> Citation | None:
    """Copia de la cita si `quote == pages.text[start:end]` en la versión vigente; si no, None."""
    page_number, start, end, quote = (item.get(k) for k in ("page", "start", "end", "quote"))
    if not all(type(v) is int for v in (page_number, start, end)) or not 0 <= start < end:
        return None
    document = db.get(Document, str(item.get("document_id")))
    if (
        document is None
        or document.status == DocumentStatus.RETIRED
        or document.version != item.get("version")
    ):
        return None
    page = db.get(Page, (document.id, page_number))
    if page is None or not quote or page.text[start:end] != quote:
        return None
    chunk_id = item.get("chunk_id") and db.scalar(
        select(Chunk.id).where(
            Chunk.id == item["chunk_id"],
            Chunk.document_id == document.id,
            Chunk.page_number == page.number,
        )
    )
    return Citation(
        chunk_id=chunk_id or None,
        document_id=document.id,
        document_title=document.title,
        document_version=document.version,
        page_number=page.number,
        page_label=page.label,
        start_offset=start,
        end_offset=end,
        quote=quote,
    )


def validate(db: Session, result: dict) -> tuple[AnswerStatus, str, list[Citation]]:
    """Aplica el contrato CU-05 a un resultado RAG (forma en `app.query.ask`).

    Se descartan las citas no verificables y las que ninguna marca `[n]` del texto referencia;
    las marcas restantes se renumeran 1..k. Sin citas válidas: `no_evidence` sin afirmaciones.
    """
    if result.get("status") == AnswerStatus.ANSWERED:
        candidates = {
            n: citation
            for n, item in enumerate(result.get("citations") or [], 1)
            if (citation := verified(db, item))
        }
        positions: dict[int, int] = {}

        def renumber(match: re.Match) -> str:
            n = int(match.group(1))
            if n not in candidates:
                return ""
            return f" [{positions.setdefault(n, len(positions) + 1)}]"

        content = MARK.sub(renumber, result.get("answer") or "").strip()
        if positions:
            for n, position in positions.items():
                candidates[n].position = position
            return AnswerStatus.ANSWERED, content, [candidates[n] for n in positions]
    return AnswerStatus.NO_EVIDENCE, NO_EVIDENCE, []
