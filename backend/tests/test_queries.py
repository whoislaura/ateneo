"""CU-01 y CU-05 sin PostgreSQL: SQLite en memoria y recuperación falsa en lugar de pgvector."""

from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_models import BACKEND, TEST_DATABASE_URL, alembic_config

from app import auth, citations, query
from app.db import get_db
from app.main import app
from app.models import (
    Answer,
    Base,
    Chunk,
    Citation,
    Document,
    DocumentStatus,
    HistoryEntry,
    Page,
    PageStatus,
    Role,
)
from app.rag import vector
from app.rag.ingestion import DocumentMetadata, extract_pdf
from app.rag.sample import create_sample

PASSWORD = "clave-de-prueba"
VERSION = "v" * 64
TEXT = "La biblioteca conserva un catálogo de leyes. El préstamo dura una semana."
SENTENCE = TEXT[: TEXT.index(".") + 1]


def make_client(factory):
    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    client.headers_for = {}
    with factory() as db:
        for role in Role:
            auth.create_user(db, f"{role.value}@ateneo.cu", role.value, PASSWORD, role)
    for role in Role:
        body = {"email": f"{role.value}@ateneo.cu", "password": PASSWORD}
        token = client.post("/api/v1/auth/login", json=body).json()["access_token"]
        client.headers_for[role] = {"Authorization": f"Bearer {token}"}
    return client


@pytest.fixture
def factory(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add(
            Document(
                id="doc",
                title="Documento",
                filename="doc.pdf",
                version=VERSION,
                year=1,
                subject="Civil",
                topic="Bienes",
                status=DocumentStatus.INDEXED,
                chunk_settings={},
                pages=[Page(number=1, label="i", text=TEXT, status=PageStatus.TEXT)],
            )
        )
        db.flush()
        db.add(
            Chunk(
                id="c1",
                document_id="doc",
                document_version=VERSION,
                page_number=1,
                start_offset=0,
                end_offset=len(TEXT),
                text=TEXT,
            )
        )
        db.commit()

    def retrieve(question, *, year, subject, topic, limit):
        if year not in (None, 1):
            return []
        passage = {"chunk_id": "c1", "document_id": "doc", "title": "Documento"}
        return [
            passage
            | {"version": VERSION, "page_number": 1, "start": 0, "end": len(TEXT)}
            | {"text": TEXT}
        ]

    # pgvector no existe en SQLite: se sustituye solo la recuperación, no el adaptador.
    monkeypatch.setattr(query, "retriever", lambda db: retrieve)
    monkeypatch.delenv("ATENEO_LLM_PROVIDER", raising=False)
    return factory


@pytest.fixture
def client(factory):
    with make_client(factory) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def ask(client, role=Role.STUDENT, **body):
    return client.post("/api/v1/queries", json=body, headers=client.headers_for[role])


def test_query_answers_with_verified_citation_and_history(client, factory):
    response = ask(client, question="¿Qué conserva la biblioteca?", year=1, subject=" Civil ")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "answered" and body["kind"] == "query"
    assert body["content"] == f"{SENTENCE} [1]"
    assert (body["year"], body["subject"], body["topic"]) == (1, "Civil", None)
    [citation] = body["citations"]
    assert citation | {"quote": None} == {
        "position": 1,
        "chunk_id": "c1",
        "document_id": "doc",
        "document_title": "Documento",
        "document_version": VERSION,
        "page_number": 1,
        "page_label": "i",
        "start": 0,
        "end": len(TEXT),
        "quote": None,
    }
    assert citation["quote"] == TEXT[citation["start"] : citation["end"]]
    with factory() as db:
        [entry] = db.scalars(select(HistoryEntry)).all()
        assert (entry.action, entry.answer_id) == ("query", body["id"])
        assert db.scalar(select(func.count()).select_from(Citation)) == 1

    path = f"/api/v1/answers/{body['id']}"
    assert client.get(path, headers=client.headers_for[Role.STUDENT]).json() == body
    for role in (Role.TEACHER, Role.ADMIN):
        response = client.get(path, headers=client.headers_for[role])
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert (
        client.get("/api/v1/answers/999", headers=client.headers_for[Role.STUDENT]).status_code
        == 404
    )
    assert client.get(path).status_code == 401


def test_query_without_evidence_is_persisted_without_citations(client, factory):
    for body in ({"question": "¿Qué conserva la biblioteca?", "year": 2}, {"question": "¿De qué?"}):
        response = ask(client, Role.TEACHER, **body)
        assert response.status_code == 201
        assert response.json() | {"id": 0, "created_at": 0} == {
            "id": 0,
            "kind": "query",
            "status": "no_evidence",
            "question": body["question"],
            "year": body.get("year"),
            "subject": None,
            "topic": None,
            "content": citations.NO_EVIDENCE,
            "citations": [],
            "created_at": 0,
        }
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(HistoryEntry)) == 2


def test_query_roles_and_validation(client):
    assert client.post("/api/v1/queries", json={"question": "x"}).status_code == 401
    assert ask(client, Role.ADMIN, question="x").status_code == 403
    for body in (
        {"question": "x", "year": 5},
        {"question": "x", "subject": ""},
        {"question": "x", "topic": "t" * 201},
        {"question": ""},
        {"question": "x", "otro": 1},
    ):
        response = ask(client, **body)
        assert response.status_code == 422, body
        assert response.json()["error"]["code"] == "validation_error"


def test_rag_failure_is_503_and_persists_nothing(client, factory, monkeypatch):
    monkeypatch.setenv("ATENEO_LLM_PROVIDER", "openai")
    monkeypatch.delenv("ATENEO_LLM_API_KEY", raising=False)
    response = ask(client, question="¿Qué conserva la biblioteca?")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    monkeypatch.setenv("ATENEO_LLM_PROVIDER", "otro")
    assert ask(client, question="¿Qué conserva la biblioteca?").status_code == 503
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Answer)) == 0


def test_invalid_rag_citations_become_no_evidence_before_persisting(client, factory, monkeypatch):
    bad = {"status": "answered", "answer": "Inventado [1].", "citations": [cite(quote="otra")]}
    monkeypatch.setattr(query, "ask", lambda db, question, **filters: bad)
    body = ask(client, question="¿Qué?").json()
    assert (body["status"], body["content"], body["citations"]) == (
        "no_evidence",
        citations.NO_EVIDENCE,
        [],
    )
    with factory() as db:
        assert db.get(Answer, body["id"]).status == "no_evidence"


def cite(**changes):
    item = {
        "document_id": "doc",
        "title": "Ignorado",
        "version": VERSION,
        "page": 1,
        "start": 0,
        "end": len(SENTENCE),
        "quote": SENTENCE,
        "chunk_id": "c1",
    }
    return item | changes


@pytest.mark.parametrize(
    "changes",
    [
        {"quote": SENTENCE.upper()},
        {"end": len(SENTENCE) + 1},
        {"start": 5, "end": 5},
        {"start": -1},
        {"page": 2},
        {"page": "1"},
        {"version": "x" * 64},
        {"document_id": "otro"},
        {"quote": ""},
    ],
)
def test_validate_drops_unverifiable_citation(factory, changes):
    result = {"status": "answered", "answer": "A [1].", "citations": [cite(**changes)]}
    with factory() as db:
        assert citations.validate(db, result) == ("no_evidence", citations.NO_EVIDENCE, [])


def test_validate_renumbers_and_drops_unreferenced(factory):
    second = TEXT.index("El")
    result = {
        "status": "answered",
        "answer": "Falso [1]. Bien [3]. Otra vez [3] y [9].",
        "citations": [
            cite(quote="x"),
            cite(start=second, end=len(TEXT), quote=TEXT[second:]),  # sin marca
            cite(chunk_id="inexistente", title="Otro"),
        ],
    }
    with factory() as db:
        status, content, valid = citations.validate(db, result)
        assert (status, content) == ("answered", "Falso. Bien [1]. Otra vez [1] y.")
        [citation] = valid
        assert (citation.position, citation.chunk_id, citation.document_title) == (
            1,
            None,
            "Documento",
        )
        db.get(Document, "doc").status = DocumentStatus.RETIRED
        assert citations.validate(db, result)[0] == "no_evidence"
        no_evidence = {"status": "no_evidence", "answer": "Algo [1].", "citations": [cite()]}
        assert citations.validate(db, no_evidence) == ("no_evidence", citations.NO_EVIDENCE, [])


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL")
def test_postgres_query_end_to_end(monkeypatch, tmp_path):
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    for variable in ("ATENEO_LLM_PROVIDER", "ATENEO_EMBEDDER", "ATENEO_EMBED_DIM"):
        monkeypatch.delenv(variable, raising=False)
    config = alembic_config()
    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        factory = sessionmaker(engine)
        with factory() as db:
            for item in create_sample(tmp_path / "sample"):
                metadata = DocumentMetadata.model_validate_json(
                    Path(item["metadata"]).read_text(encoding="utf-8")
                )
                vector.store_document(
                    db, extract_pdf(Path(item["pdf"]), metadata), vector.fake_embedder
                )
        with make_client(factory) as client:
            body = ask(client, question="¿Qué conserva la biblioteca ficticia?").json()
            assert body["status"] == "answered", body
            assert "[1]" in body["content"]
            with factory() as db:
                for c in body["citations"]:
                    page = db.get(Page, (c["document_id"], c["page_number"]))
                    assert page.text[c["start"] : c["end"]] == c["quote"]
                assert db.scalar(select(func.count()).select_from(HistoryEntry)) == 1
            assert ("muestra-a", 1) in {
                (c["document_id"], c["page_number"]) for c in body["citations"]
            }
            path = f"/api/v1/answers/{body['id']}"
            assert client.get(path, headers=client.headers_for[Role.STUDENT]).json() == body
            assert client.get(path, headers=client.headers_for[Role.TEACHER]).status_code == 404
            rejected = ask(client, question="¿Cuál es la capital de Francia?").json()
            assert (rejected["status"], rejected["citations"]) == ("no_evidence", [])
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        command.downgrade(config, "base")
