"""CU-06: examen mixto con IA (ver app.rag.exam) y sus citas verificadas."""

import random

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Citation, ExamQuestion
from app.query import setting
from app.rag import vector
from app.rag.exam import PROVIDERS, generate_exam, load_passages, plan, points_and_minutes
from app.schemas import ExamRequest


def make_questions(db: Session, request: ExamRequest) -> tuple[list[ExamQuestion], int]:
    """Preguntas del examen (con citas) y duración en minutos. 422 si no se logra la cantidad."""
    provider = setting(PROVIDERS, "ATENEO_LLM_PROVIDER")
    setting(vector.EMBEDDERS, "ATENEO_EMBEDDER")  # misma validación de entorno que el resto
    passages = load_passages(
        db,
        year=request.year,
        subject=request.subject,
        topic=request.topic,
        count=request.question_count,
        rng=random.Random(),
    )
    if not passages:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "El corpus vigente no tiene material con esos filtros.",
        )
    kinds = plan(request.question_count, request.types)
    questions = generate_exam(db, kinds, passages, request.difficulty, provider)
    if len(questions) < len(kinds):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"El corpus vigente permite {len(questions)} preguntas con respaldo verificable "
            "con esos filtros; reduce la cantidad o cambia los tipos.",
        )
    points, minutes = points_and_minutes([q["kind"] for q in questions])
    rows = [
        ExamQuestion(
            position=position,
            kind=q["kind"],
            statement=q["statement"],
            options=q["options"],
            answer=q["answer"],
            criteria=q["criteria"],
            points=score,
            citations=[
                Citation(
                    position=n,
                    chunk_id=c["chunk_id"],
                    document_id=c["document_id"],
                    document_title=c["title"],
                    document_version=c["version"],
                    page_number=c["page"],
                    page_label=c["page_label"],
                    start_offset=c["start"],
                    end_offset=c["end"],
                    quote=c["quote"],
                )
                for n, c in enumerate(q["citations"], 1)
            ],
        )
        for position, (q, score) in enumerate(zip(questions, points, strict=True), 1)
    ]
    return rows, minutes
