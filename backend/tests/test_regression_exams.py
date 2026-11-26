"""Regresión CU-06: deduplicación de enunciados enmascarados con respuestas distintas."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.exams import make_questions
from app.models import Base, Document, DocumentStatus, Page, PageStatus
from app.schemas import ExamRequest

VERSION = "v" * 64
TEN = "El plazo legal es de diez días."
TWENTY = "El plazo legal es de veinte días."


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db, texts):
    db.add(
        Document(
            id="plazos",
            title="Plazos",
            filename="plazos.pdf",
            version=VERSION,
            year=1,
            subject="Civil",
            topic="Plazos",
            status=DocumentStatus.INDEXED,
            chunk_settings={},
            pages=[
                Page(number=number, label=None, text=text, status=PageStatus.TEXT)
                for number, text in enumerate(texts, 1)
            ],
        )
    )
    db.commit()


def request(count):
    return ExamRequest(year=1, subject="Civil", question_count=count, difficulty="medium")


def test_masked_statements_with_distinct_answers_are_both_returned(db):
    seed(db, [TEN, TWENTY])

    questions = make_questions(db, request(2))

    assert len(questions) == 2
    assert {question.answer for question in questions} == {
        "legal es de diez",
        "legal es de veinte",
    }
    assert len({question.statement for question in questions}) == 1


def test_identical_statements_are_still_deduplicated(db):
    seed(db, [TEN, TEN, TWENTY])

    questions = make_questions(db, request(2))

    assert len(questions) == 2
    assert sorted(question.answer for question in questions) == [
        "legal es de diez",
        "legal es de veinte",
    ]
