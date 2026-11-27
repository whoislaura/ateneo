"""Regresión de seguridad: búsqueda de texto acotada, cuota de IA y borrado de exámenes."""

# ruff: noqa: F811  (fixtures `client` y `factory` importadas de test_queries / test_exams_ai)
import logging

import pytest
from alembic import command
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from test_exams_ai import client, create_exam, db, factory, pdfs  # noqa: F401
from test_models import BACKEND, TEST_DATABASE_URL, alembic_config

from app import auth, query
from app.api import ai_unavailable
from app.models import Citation, Exam, ExamQuestion, HistoryAction, HistoryEntry, Role
from app.rag import vector

QUESTION = "¿Qué conserva la biblioteca?"


@pytest.fixture
def pg(monkeypatch):
    if not TEST_DATABASE_URL:
        pytest.skip("Requiere ATENEO_TEST_DATABASE_URL")
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config = alembic_config()
    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()
    command.downgrade(config, "base")


def test_text_search_runs_at_most_12_counts(pg):
    # 190 términos distintos caben en el tope de 1000 caracteres de la pregunta.
    words = [f"zq{chr(97 + n // 26)}{chr(97 + n % 26)}" for n in range(190)]
    counts = []

    @event.listens_for(pg, "before_cursor_execute")
    def count(conn, cursor, statement, *args):
        if "count(" in statement.lower() and "websearch_to_tsquery" in statement:
            counts.append(statement)

    with Session(pg) as session:
        assert vector.text_search(session, " ".join(words)) == []
    assert len(counts) == vector.MAX_TEXT_TERMS == 12


def test_text_search_timeout_is_an_empty_result_not_an_error(pg, monkeypatch, caplog):
    monkeypatch.setattr(vector, "TEXT_SEARCH_TIMEOUT_MS", 100)

    def slow(session, *args):
        session.execute(text("select pg_sleep(2)"))
        return [{"never": "returned"}]

    monkeypatch.setattr(vector, "_text_search", slow)
    with Session(pg) as session, caplog.at_level(logging.WARNING, "ateneo.rag"):
        assert vector.text_search(session, "biblioteca") == []
        assert "text_search_timeout" in caplog.text
        assert session.scalar(select(1)) == 1  # la sesión sigue usable


def test_ai_endpoints_return_429_per_user(client, monkeypatch):
    monkeypatch.setattr(auth, "AI_MAX_REQUESTS", 2)
    student, teacher = client.headers_for[Role.STUDENT], client.headers_for[Role.TEACHER]
    paths = ["/queries", "/conversations"]
    for path in paths:
        auth.ai_limiter.hits.clear()
        for _ in range(2):
            assert (
                client.post(
                    f"/api/v1{path}", json={"question": QUESTION}, headers=student
                ).status_code
                == 201
            )
        blocked = client.post(f"/api/v1{path}", json={"question": QUESTION}, headers=student)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0
        assert blocked.json()["error"]["code"] == "too_many_requests"
        # El tope es compartido entre endpoints y por usuario: el profesor no se ve afectado.
        other = client.post("/api/v1/queries", json={"question": QUESTION}, headers=student)
        assert other.status_code == 429
        assert (
            client.post(f"/api/v1{path}", json={"question": QUESTION}, headers=teacher).status_code
            == 201
        )


def test_ai_limiter_window_slides():
    now = [0.0]
    limiter = auth.AiLimiter(clock=lambda: now[0])
    assert [limiter.acquire(1) for _ in range(auth.AI_MAX_REQUESTS)] == [0] * auth.AI_MAX_REQUESTS
    assert limiter.acquire(1) == auth.AI_WINDOW_SECONDS
    assert limiter.acquire(2) == 0
    now[0] = auth.AI_WINDOW_SECONDS
    assert limiter.acquire(1) == 0


def test_provider_error_log_redacts_keys(caplog):
    class Failure(Exception):
        code = 401

        def read(self):
            return b'{"error": "Incorrect API key: sk-or-v1-abc_DEF-123 / Bearer tok.en=="}'

    with caplog.at_level(logging.WARNING, "ateneo.ai"):
        ai_unavailable(Failure(), "no disponible")
    logged = caplog.records[-1].error
    assert "sk-or" not in logged and "tok.en" not in logged and "[redactado]" in logged


def test_chat_value_error_is_500_not_503(client, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("ATENEO_RETRIEVAL inválido")

    monkeypatch.setattr(query, "ask", boom)
    response = client.post(
        "/api/v1/conversations",
        json={"question": QUESTION},
        headers=client.headers_for[Role.STUDENT],
    )
    assert response.status_code == 500


def test_delete_exam_is_author_only_and_removes_key_and_history(client, db):
    created = create_exam(client, question_count=2)
    path = f"/api/v1/exams/{created['id']}"
    student, teacher = client.headers_for[Role.STUDENT], client.headers_for[Role.TEACHER]
    assert client.delete(path, headers=teacher).status_code == 404
    assert client.delete(path).status_code == 401
    assert client.delete(path, headers=student).status_code == 204
    assert client.get(path, headers=student).status_code == 404
    assert client.delete(path, headers=student).status_code == 404
    assert db.scalar(select(ExamQuestion.id)) is None
    assert db.scalar(select(Citation.id).where(Citation.question_id.is_not(None))) is None
    assert (
        db.scalar(select(HistoryEntry.id).where(HistoryEntry.action == HistoryAction.EXAM)) is None
    )


def test_history_deletes_cover_exams(client, db):
    first, second = create_exam(client, question_count=2), create_exam(client, question_count=2)
    student = client.headers_for[Role.STUDENT]
    entry = db.scalar(select(HistoryEntry).where(HistoryEntry.exam_id == first["id"]))
    assert (
        client.delete(
            f"/api/v1/history/{entry.id}", headers=client.headers_for[Role.TEACHER]
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/history/{entry.id}", headers=student).status_code == 204
    db.expire_all()
    assert [e.id for e in db.scalars(select(Exam))] == [second["id"]]
    assert client.delete("/api/v1/history", headers=student).status_code == 204
    db.expire_all()
    assert db.scalar(select(Exam.id)) is None and db.scalar(select(ExamQuestion.id)) is None
