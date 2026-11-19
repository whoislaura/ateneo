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
    Citation,
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
    monkeypatch.delenv("ATENEO_EMBED_API_KEY", raising=False)
    unavailable = upload(client, pdfs["muestra-a"])
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "service_unavailable"
    with factory() as db:
        assert db.scalars(select(Document)).all() == []
        assert db.scalars(select(HistoryEntry)).all() == []


def test_exam_uses_current_corpus_and_keeps_solutions_private(client, factory, pdfs):
    assert upload(client, pdfs["muestra-b"]).status_code == 201
    request = {"year": 1, "subject": "Civil", "topic": "Bienes", "question_count": 1}
    student = client.headers_for[Role.STUDENT]
    exams = []
    for difficulty in ("easy", "medium", "hard"):
        response = client.post(
            "/api/v1/exams", headers=student, json=request | {"difficulty": difficulty}
        )
        assert response.status_code == 201, response.json()
        exam = response.json()
        [question] = exam["questions"]
        assert question.keys() == {"id", "position", "statement"}
        assert "…" in question["statement"]
        exams.append(exam)

    assert len({exam["questions"][0]["statement"] for exam in exams}) == 3
    assert get(client, "/exams", Role.STUDENT).json() == list(reversed(exams))
    assert get(client, "/exams").json() == []
    path = f"/exams/{exams[0]['id']}"
    assert get(client, path, Role.STUDENT).json() == exams[0]
    assert get(client, path).status_code == 404
    assert get(client, path + "/answers").status_code == 404
    assert get(client, path + "/answers", Role.ADMIN).status_code == 403
    [solution] = get(client, path + "/answers", Role.STUDENT).json()
    [citation] = solution["citations"]
    page = get(client, f"/documents/manual/pages/{citation['page_number']}").json()
    assert citation["quote"] == page["text"][citation["start"] : citation["end"]]
    assert solution["answer"] in citation["quote"]
    assert solution["question_id"] == exams[0]["questions"][0]["id"]

    body = request | {"difficulty": "easy"}
    for filters in ({"topic": "Otro"}, {"year": 2}, {"question_count": 50}):
        response = client.post("/api/v1/exams", headers=student, json=body | filters)
        assert response.status_code == 422
        assert "El corpus vigente permite" in response.json()["error"]["message"]
    retired = client.delete("/api/v1/documents/manual", headers=client.headers_for[Role.TEACHER])
    assert retired.status_code == 204
    assert client.post("/api/v1/exams", headers=student, json=body).status_code == 422
    assert get(client, path + "/answers", Role.STUDENT).json() == [solution]
    with factory() as db:
        assert len(db.scalars(select(Exam)).all()) == 3
        history = db.scalars(select(HistoryEntry).where(HistoryEntry.action == "exam")).all()
        assert {item.exam_id for item in history} == {exam["id"] for exam in exams}


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
        page = db.get(PageRow, ("manual", 1))
        page.text = "\n".join(
            f"La revisión documental requiere consultar la regla procesal número {number}."
            for number in range(1, 61)
        )
        db.commit()
    headers = client.headers_for[Role.STUDENT]
    response = client.post(
        "/api/v1/exams",
        headers=headers,
        json={"year": 1, "subject": "Civil", "question_count": 50, "difficulty": "hard"},
    )
    assert response.status_code == 201, response.json()
    exam = response.json()
    assert len({question["statement"] for question in exam["questions"]}) == 50
    assert len(get(client, f"/exams/{exam['id']}/answers", Role.STUDENT).json()) == 50


def test_replace_reindexes_and_keeps_old_citations_as_copies(client, factory, pdfs):
    old_version = upload(client, pdfs["muestra-a"]).json()["version"]
    old = ask(client, OLD_QUESTION).json()
    assert old["status"] == "answered", old
    assert old["citations"][0]["document_version"] == old_version

    assert replace(client, pdfs["muestra-a"], Role.ADMIN, document_id="otro").status_code == 404
    response = replace(client, pdfs["muestra-b"], Role.ADMIN, title="Manual 2", year="4")
    assert response.status_code == 200, response.json()
    report = response.json()
    assert report["status"] == "indexed" and report["version"] != old_version

    with factory() as db:
        assert {c.document_version for c in db.scalars(select(Chunk))} == {report["version"]}
        document = db.get(Document, "manual")
        assert (document.title, document.year, document.filename) == ("Manual 2", 4, "nuevo.pdf")
        [citation] = db.scalars(select(Citation)).all()
        assert citation.chunk_id is None  # el fragmento ya no existe; la copia sí
        actions = [e.action for e in db.scalars(select(HistoryEntry).order_by(HistoryEntry.id))]
        assert actions[-1] == "document_update"

    assert ask(client, OLD_QUESTION).json()["status"] == "no_evidence"
    new = ask(client, NEW_QUESTION).json()
    assert new["status"] == "answered"
    assert {c["document_version"] for c in new["citations"]} == {report["version"]}
    # La respuesta antigua conserva su cita verificable como copia.
    reopened = get(client, f"/answers/{old['id']}", Role.STUDENT).json()
    assert reopened["citations"][0] | {"chunk_id": "x"} == old["citations"][0] | {"chunk_id": "x"}
    page = get(client, "/documents/manual/pages/1").json()
    assert page["version"] == report["version"]


def test_retire_excludes_from_search_and_citations(client, factory, pdfs):
    upload(client, pdfs["muestra-b"])
    assert ask(client, NEW_QUESTION).json()["status"] == "answered"
    assert client.delete("/api/v1/documents/manual").status_code == 401
    student = client.headers_for[Role.STUDENT]
    assert client.delete("/api/v1/documents/manual", headers=student).status_code == 403
    teacher = client.headers_for[Role.TEACHER]
    assert client.delete("/api/v1/documents/otro", headers=teacher).status_code == 404
    for _ in range(2):  # idempotente
        assert client.delete("/api/v1/documents/manual", headers=teacher).status_code == 204

    assert ask(client, NEW_QUESTION).json()["status"] == "no_evidence"
    assert get(client, "/documents").json() == []
    [retired] = get(client, "/documents?include_retired=true", Role.ADMIN).json()
    assert retired["status"] == "retired"
    assert get(client, "/documents/manual", Role.STUDENT).status_code == 404
    assert get(client, "/documents/manual/pages/1", Role.STUDENT).status_code == 404
    assert get(client, "/documents/manual/pages/1").status_code == 200
    with factory() as db:
        assert db.scalars(select(Chunk)).all()  # se conservan las filas
        actions = [e.action for e in db.scalars(select(HistoryEntry))]
        assert actions.count("document_retire") == 1

    # Sustituir un documento retirado lo vuelve a poner en vigor.
    assert replace(client, pdfs["muestra-b"]).status_code == 200
    assert ask(client, NEW_QUESTION).json()["status"] == "answered"


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
