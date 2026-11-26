"""CU-03 y reindexación (AT-10, AT-18) sin PostgreSQL: SQLite en memoria con claves foráneas.

`vector.store_document` es el real; solo la búsqueda pgvector se sustituye por una por términos
con el mismo filtro de documentos retirados.
"""

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_models import BACKEND, TEST_DATABASE_URL, alembic_config
from test_queries import make_client

from app.main import app
from app.models import (
    Base,
    Chunk,
    Document,
    DocumentStatus,
    Exam,
    Feedback,
    HistoryEntry,
    Role,
)
from app.models import Page as PageRow
from app.rag import vector
from app.rag.index import content_terms
from app.rag.sample import create_sample

FORM = {"title": "Manual", "year": "1", "subject": "Civil", "topic": "Bienes"}
OLD_QUESTION = "¿Dónde aparece azafrán?"
NEW_QUESTION = "¿Dónde aparece turquesa?"


@pytest.fixture(scope="module")
def pdfs(tmp_path_factory) -> dict[str, bytes]:
    folder = tmp_path_factory.mktemp("sample")
    return {Path(i["pdf"]).stem: Path(i["pdf"]).read_bytes() for i in create_sample(folder)}


def fake_search(db, question, embedder, *, year, subject, topic, limit):
    wanted = set(content_terms(question))
    rows = db.execute(
        select(Chunk, Document, PageRow)
        .join(Document, Document.id == Chunk.document_id)
        .join(
            PageRow,
            (PageRow.document_id == Chunk.document_id) & (PageRow.number == Chunk.page_number),
        )
        .where(Document.status != DocumentStatus.RETIRED)
        .order_by(Chunk.id)
    ).all()
    return [
        {
            "chunk_id": chunk.id,
            "document_id": document.id,
            "title": document.title,
            "version": chunk.document_version,
            "page_number": chunk.page_number,
            "page_label": page.label,
            "start": chunk.start_offset,
            "end": chunk.end_offset,
            "text": chunk.text,
            "score": 0.0,
        }
        for chunk, document, page in rows
        if wanted & set(content_terms(chunk.text))
    ][:limit]


@pytest.fixture
def factory(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # ON DELETE CASCADE / SET NULL como en PostgreSQL.
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(vector, "search", fake_search)
    # SQLite no tiene texto completo de PostgreSQL; la prueba cubre la API, no la recuperación.
    monkeypatch.setenv("ATENEO_RETRIEVAL", "vector")
    for variable in ("ATENEO_LLM_PROVIDER", "ATENEO_EMBEDDER", "ATENEO_MAX_UPLOAD_MB"):
        monkeypatch.delenv(variable, raising=False)
    return sessionmaker(engine)


@pytest.fixture
def client(factory):
    with make_client(factory) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload(client, pdf, role=Role.TEACHER, document_id="manual", **changes):
    return client.post(
        "/api/v1/documents",
        data=FORM | {"document_id": document_id} | changes,
        files={"file": ("manual.pdf", pdf, "application/pdf")},
        headers=client.headers_for[role],
    )


def replace(client, pdf, role=Role.TEACHER, document_id="manual", **changes):
    return client.put(
        f"/api/v1/documents/{document_id}",
        data=FORM | changes,
        files={"file": ("nuevo.pdf", pdf, "application/pdf")},
        headers=client.headers_for[role],
    )


def ask(client, question):
    body = {"question": question}
    return client.post("/api/v1/queries", json=body, headers=client.headers_for[Role.STUDENT])


def get(client, path, role=Role.TEACHER):
    return client.get(f"/api/v1{path}", headers=client.headers_for[role])


def test_upload_list_get_and_page(client, factory, pdfs):
    response = upload(client, pdfs["muestra-a"])
    assert response.status_code == 201, response.json()
    report = response.json()
    assert report["document_id"] == "manual" and report["status"] == "partial"
    assert (report["pages"], report["no_text_pages"]) == (3, [2])

    [document] = get(client, "/documents", Role.STUDENT).json()
    assert document | {"created_at": 0, "updated_at": 0} == {
        "id": "manual",
        "title": "Manual",
        "year": 1,
        "subject": "Civil",
        "topic": "Bienes",
        "filename": "manual.pdf",
        "version": report["version"],
        "status": "partial",
        "created_at": 0,
        "updated_at": 0,
    }
    assert get(client, "/documents/manual", Role.ADMIN).json() == document
    for query in ("?year=1&subject=%20civil%20&topic=BIENES", "?year=2", "?subject=Penal"):
        expected = [document] if query.startswith("?year=1") else []
        assert get(client, "/documents" + query).json() == expected, query

    page = get(client, "/documents/manual/pages/1", Role.STUDENT).json()
    assert (page["version"], page["number"], page["status"]) == (report["version"], 1, "text")
    assert "azafrán" in page["text"]
    assert get(client, "/documents/manual/pages/9").status_code == 404
    assert get(client, "/documents/otro").status_code == 404

    with factory() as db:
        [entry] = db.scalars(select(HistoryEntry)).all()
        assert (entry.action, entry.document_id, entry.summary) == (
            "document_upload",
            "manual",
            "Manual",
        )
        assert db.get(Document, "manual").uploaded_by == entry.user_id

    conflict = upload(client, pdfs["muestra-b"], Role.ADMIN)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"


def test_upload_validation_and_roles(client, factory, pdfs, monkeypatch):
    assert upload(client, pdfs["muestra-a"], Role.STUDENT).status_code == 403
    assert get(client, "/documents?include_retired=true", Role.STUDENT).status_code == 403
    assert client.get("/api/v1/documents").status_code == 401
    for changes in (
        {"year": "5"},
        {"subject": ""},
        {"document_id": "x" * 201},
        {"document_id": "a/b"},
        {"document_id": "-a"},
    ):
        assert upload(client, pdfs["muestra-a"], **changes).status_code == 422, changes

    not_pdf = upload(client, b"hola")
    assert not_pdf.status_code == 422
    assert not_pdf.json()["error"] == {
        "code": "validation_error",
        "message": "El archivo debe ser un PDF.",
        "details": None,
    }
    assert upload(client, b"%PDF-1.4 roto").json()["error"]["code"] == "validation_error"

    monkeypatch.setenv("ATENEO_MAX_UPLOAD_MB", "1")
    too_large = upload(client, b"%PDF-" + b"0" * 2**20)
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "request_entity_too_large"

    monkeypatch.setenv("ATENEO_EMBEDDER", "openai")
    monkeypatch.setenv("ATENEO_EMBED_API_KEY", "k")
    monkeypatch.setenv("ATENEO_EMBED_MODEL", "m")

    def down(*args, **kwargs):
        raise OSError("sin red")

    monkeypatch.setattr("app.rag.vector.urllib.request.urlopen", down)
    unavailable = upload(client, pdfs["muestra-a"])
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "service_unavailable"
    with factory() as db:
        assert db.scalars(select(Document)).all() == []
        assert db.scalars(select(HistoryEntry)).all() == []


def test_exam_uses_current_corpus_and_keeps_solutions_private(client, factory, pdfs):
    assert upload(client, pdfs["muestra-b"]).status_code == 201
    request = {"year": 1, "subject": "Civil", "topic": "Bienes", "difficulty": "medium"}
    student = client.headers_for[Role.STUDENT]
    response = client.post("/api/v1/exams", headers=student, json=request | {"question_count": 4})
    assert response.status_code == 201, response.json()
    exam = response.json()
    assert [q["kind"] for q in exam["questions"]] == [
        "multiple_choice",
        "true_false",
        "development",
        "case",
    ]
    assert all(
        q.keys() == {"id", "position", "kind", "statement", "options", "points"}
        for q in exam["questions"]
    )
    assert exam["total_points"] == 10 and exam["duration_minutes"] % 5 == 0
    assert exam["question_count"] == 4

    only_test = client.post(
        "/api/v1/exams",
        headers=student,
        json=request | {"question_count": 2, "types": ["true_false"]},
    ).json()
    assert [q["kind"] for q in only_test["questions"]] == ["true_false"] * 2
    exams = [only_test, exam]
    assert get(client, "/exams", Role.STUDENT).json() == exams
    assert get(client, "/exams").json() == []
    assert get(client, "/exams?limit=1", Role.STUDENT).json() == exams[:1]
    assert get(client, "/exams?limit=1&offset=1", Role.STUDENT).json() == exams[1:]
    assert get(client, "/exams?offset=2", Role.STUDENT).json() == []
    for bad in ("limit=0", "limit=101", "offset=-1", "offset=1000001"):
        assert get(client, f"/exams?{bad}", Role.STUDENT).status_code == 422
    path = f"/exams/{exam['id']}"
    assert get(client, path, Role.STUDENT).json() == exam
    assert get(client, path).status_code == 404
    assert get(client, path + "/answers").status_code == 404
    assert get(client, path + "/answers", Role.ADMIN).status_code == 403
    solutions = get(client, path + "/answers", Role.STUDENT).json()
    assert [s["question_id"] for s in solutions] == [q["id"] for q in exam["questions"]]
    for solution in solutions:
        assert solution["criteria"] and solution["citations"]
        for citation in solution["citations"]:
            page = get(client, f"/documents/manual/pages/{citation['page_number']}").json()
            assert citation["quote"] == page["text"][citation["start"] : citation["end"]]

    body = request | {"question_count": 1}
    for filters in ({"topic": "Otro"}, {"year": 2}, {"question_count": 50}):
        response = client.post("/api/v1/exams", headers=student, json=body | filters)
        assert response.status_code == 422
        assert "corpus vigente" in response.json()["error"]["message"]
    assert (
        client.post("/api/v1/exams", headers=student, json=body | {"types": []}).status_code == 422
    )
    retired = client.delete("/api/v1/documents/manual", headers=client.headers_for[Role.TEACHER])
    assert retired.status_code == 204
    assert client.post("/api/v1/exams", headers=student, json=body).status_code == 422
    assert get(client, path + "/answers", Role.STUDENT).json() == solutions
    with factory() as db:
        assert len(db.scalars(select(Exam)).all()) == 2
        history = db.scalars(select(HistoryEntry).where(HistoryEntry.action == "exam")).all()
        assert {item.exam_id for item in history} == {e["id"] for e in exams}


def test_feedback_saves_all_types_and_checks_reference_ownership(client, factory, pdfs):
    assert upload(client, pdfs["muestra-b"]).status_code == 201
    answer_id = ask(client, NEW_QUESTION).json()["id"]
    student = client.headers_for[Role.STUDENT]
    exam = client.post(
        "/api/v1/exams",
        headers=student,
        json={"year": 1, "subject": "Civil", "question_count": 1, "difficulty": "easy"},
    )
    assert exam.status_code == 201, exam.json()
    exam_id = exam.json()["id"]
    path = "/api/v1/feedback"
    for body, role in (
        ({"kind": "rating", "rating": 4, "answer_id": answer_id}, Role.STUDENT),
        ({"kind": "error", "comment": "Revisar el enunciado", "exam_id": exam_id}, Role.STUDENT),
        ({"kind": "suggestion", "comment": "Agregar más temas"}, Role.ADMIN),
    ):
        response = client.post(path, headers=client.headers_for[role], json=body)
        assert response.status_code == 201, response.json()
        assert {field: response.json()[field] for field in body} == body

    for target in ({"answer_id": answer_id}, {"exam_id": exam_id}, {"exam_id": 9999}):
        response = client.post(
            path,
            headers=client.headers_for[Role.TEACHER],
            json={"kind": "rating", "rating": 5} | target,
        )
        assert response.status_code == 404
    assert client.post(path, headers=student, json={"kind": "suggestion"}).status_code == 422
    with factory() as db:
        rows = db.scalars(select(Feedback).order_by(Feedback.id)).all()
        assert [row.kind for row in rows] == ["rating", "error", "suggestion"]
        assert [row.rating for row in rows] == [4, None, None]
        assert rows[0].user_id == rows[1].user_id != rows[2].user_id


def test_exam_at_contract_limit_has_unique_questions(client, factory, pdfs):
    assert upload(client, pdfs["muestra-b"]).status_code == 201
    with factory() as db:
        document = db.get(Document, "manual")
        lines = [
            f"La revisión documental requiere consultar la regla procesal número {n}."
            for n in range(1, 61)
        ]
        page = db.get(PageRow, ("manual", 1))
        page.text = "\n".join(lines)
        db.query(Chunk).filter_by(document_id="manual").delete()
        offset = 0
        for n, line in enumerate(lines):
            db.add(
                Chunk(
                    id=f"limit-{n}",
                    document_id="manual",
                    document_version=document.version,
                    page_number=1,
                    start_offset=offset,
                    end_offset=offset + len(line),
                    text=line,
                )
            )
            offset += len(line) + 1
        db.commit()
    headers = client.headers_for[Role.STUDENT]
    response = client.post(
        "/api/v1/exams",
        headers=headers,
        json={"year": 1, "subject": "Civil", "question_count": 50, "difficulty": "hard"},
    )
    assert response.status_code == 201, response.json()
    exam = response.json()
    assert len(exam["questions"]) == 50
    statements = []
    engine = factory.kw["bind"]

    def listener(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert len(get(client, f"/exams/{exam['id']}/answers", Role.STUDENT).json()) == 50
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert len(statements) < 10  # sin N+1: las citas no se cargan pregunta a pregunta


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL")
def test_postgres_reindex_end_to_end(monkeypatch, pdfs):
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    for variable in ("ATENEO_LLM_PROVIDER", "ATENEO_EMBEDDER", "ATENEO_EMBED_DIM"):
        monkeypatch.delenv(variable, raising=False)
    command.upgrade(alembic_config(), "head")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with make_client(sessionmaker(engine)) as client:
            assert upload(client, pdfs["muestra-a"], document_id="pg").status_code == 201
            assert ask(client, OLD_QUESTION).json()["status"] == "answered"
            assert replace(client, pdfs["muestra-b"], document_id="pg").status_code == 200
            same = replace(client, pdfs["muestra-b"], document_id="pg")
            assert same.status_code == 200, same.json()
            assert ask(client, OLD_QUESTION).json()["status"] == "no_evidence"
            assert ask(client, NEW_QUESTION).json()["status"] == "answered"
            student = client.headers_for[Role.STUDENT]
            exam = client.post(
                "/api/v1/exams",
                headers=student,
                json={"year": 1, "subject": "Civil", "question_count": 2, "difficulty": "hard"},
            )
            assert exam.status_code == 201, exam.json()
            exam_id = exam.json()["id"]
            solutions = get(client, f"/exams/{exam_id}/answers", Role.STUDENT).json()
            assert len(solutions) == 2
            assert all(
                citation["document_id"] == "pg"
                for solution in solutions
                for citation in solution["citations"]
            )
            feedback = client.post(
                "/api/v1/feedback",
                headers=student,
                json={"kind": "rating", "rating": 5, "exam_id": exam_id},
            )
            assert feedback.status_code == 201, feedback.json()
            headers = client.headers_for[Role.ADMIN]
            assert client.delete("/api/v1/documents/pg", headers=headers).status_code == 204
            assert ask(client, NEW_QUESTION).json()["status"] == "no_evidence"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        command.downgrade(alembic_config(), "base")
