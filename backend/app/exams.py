"""CU-06: ejercicios de completar texto basados en páginas vigentes del corpus."""

import re

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Citation, Difficulty, Document, DocumentStatus, ExamQuestion, Page
from app.rag.answer import SENTENCE
from app.rag.index import content_terms
from app.rag.vector import filter_key
from app.schemas import ExamRequest

MISSING_TERMS = {Difficulty.EASY: 1, Difficulty.MEDIUM: 2, Difficulty.HARD: 3}
WORD = re.compile(r"[^\W_]+")


def make_questions(db: Session, request: ExamRequest) -> list[ExamQuestion]:
    pages = (
        select(Page, Document)
        .join(Document, Page.document_id == Document.id)
        .where(
            Document.status != DocumentStatus.RETIRED,
            Document.year == request.year,
            func.lower(func.trim(Document.subject)) == filter_key(request.subject),
        )
        .order_by(Page.document_id, Page.number)
        .execution_options(yield_per=32)
    )
    if request.topic is not None:
        pages = pages.where(func.lower(func.trim(Document.topic)) == filter_key(request.topic))
    missing = MISSING_TERMS[request.difficulty]
    questions: list[ExamQuestion] = []
    seen: set[str] = set()
    with db.execute(pages) as rows:
        for page, document in rows:
            for sentence in SENTENCE.finditer(page.text):
                quote = sentence.group()
                terms = [word for word in WORD.finditer(quote) if content_terms(word.group())]
                if len(terms) < missing + 2 or quote.isupper():
                    continue
                middle = (len(terms) - missing) // 2
                start, end = terms[middle].start(), terms[middle + missing - 1].end()
                fragment = f"{quote[:start]}[…]{quote[end:]}"
                if fragment.casefold() in seen:
                    continue
                seen.add(fragment.casefold())
                questions.append(
                    ExamQuestion(
                        position=len(questions) + 1,
                        statement=f"Completa el fragmento: «{fragment}»",
                        answer=quote[start:end],
                        citations=[
                            Citation(
                                position=1,
                                document_id=document.id,
                                document_title=document.title,
                                document_version=document.version,
                                page_number=page.number,
                                page_label=page.label,
                                start_offset=sentence.start(),
                                end_offset=sentence.end(),
                                quote=quote,
                            )
                        ],
                    )
                )
                if len(questions) == request.question_count:
                    return questions
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        f"El corpus vigente permite {len(questions)} preguntas con esos filtros y dificultad.",
    )
