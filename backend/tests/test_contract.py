from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import current_user
from app.main import app
from app.models import Role, User
from app.rag.index import index_document
from app.rag.ingestion import DocumentMetadata, extract_pdf
from app.rag.sample import create_sample
from app.schemas import AnswerOut, CitationOut, FeedbackRequest, IngestionReport, PageOut

CONTRACT = {
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/auth/me"),
    ("post", "/api/v1/queries"),
    ("post", "/api/v1/generations"),
    ("get", "/api/v1/answers/{answer_id}"),
    ("get", "/api/v1/documents"),
    ("post", "/api/v1/documents"),
    ("get", "/api/v1/documents/{document_id}"),
    ("put", "/api/v1/documents/{document_id}"),
    ("delete", "/api/v1/documents/{document_id}"),
    ("get", "/api/v1/documents/{document_id}/pages/{page_number}"),
    ("get", "/api/v1/history"),
    ("delete", "/api/v1/history"),
    ("delete", "/api/v1/history/{entry_id}"),
    ("post", "/api/v1/exams"),
    ("get", "/api/v1/exams"),
    ("get", "/api/v1/exams/{exam_id}"),
    ("get", "/api/v1/exams/{exam_id}/answers"),
    ("get", "/api/v1/exams/{exam_id}/pdf"),
    ("get", "/api/v1/exams/{exam_id}/answers/pdf"),
    ("post", "/api/v1/feedback"),
    ("get", "/api/v1/admin/stats"),
    ("get", "/api/v1/admin/users"),
    ("post", "/api/v1/admin/users"),
    ("patch", "/api/v1/admin/users/{user_id}"),
    ("post", "/api/v1/admin/users/{user_id}/password"),
    ("delete", "/api/v1/admin/users/{user_id}/sessions"),
    ("get", "/api/v1/admin/answers"),
    ("get", "/api/v1/admin/answers/{answer_id}"),
    ("get", "/api/v1/admin/feedback"),
    ("get", "/api/v1/admin/logs"),
}

CITATION = {
    "position": 1,
    "chunk_id": "c" * 64,
    "document_id": "muestra-a",
    "document_title": "Muestra",
    "document_version": "v" * 64,
    "page_number": 1,
    "page_label": None,
    "start": 0,
    "end": 7,
    "quote": "Párrafo",
}


@pytest.fixture(scope="module")
def client():
    # Profesor: el único rol con acceso a todos los stubs. Los permisos se prueban en test_auth.
    app.dependency_overrides[current_user] = lambda: User(id=1, role=Role.TEACHER)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_openapi_describes_whole_contract():
    schema = app.openapi()
    operations = {
        (method, path)
        for path, item in schema["paths"].items()
        for method in item
        if path != "/api/v1/health"
    }
    assert operations == CONTRACT
    for method, path in CONTRACT:
        responses = schema["paths"][path][method]["responses"]
        assert responses["501"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
        if "{" in path:
            assert "404" in responses
    for path in ("/api/v1/documents", "/api/v1/documents/{document_id}"):
        method = "post" if path.endswith("documents") else "put"
        assert "multipart/form-data" in schema["paths"][path][method]["requestBody"]["content"]
    assert "security" not in schema["paths"]["/api/v1/auth/login"]["post"]
    assert schema["paths"]["/api/v1/queries"]["post"]["security"] == [{"HTTPBearer": []}]


def test_validation_and_not_found_use_error_format(client):
    response = client.post("/api/v1/queries", json={"question": "x", "year": 5})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["loc"] == ["body", "year"]
    response = client.get("/api/v1/unknown")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "details": None}
    }


def answer(**changes):
    data = {
        "id": 1,
        "kind": "query",
        "status": "answered",
        "question": "¿Qué?",
        "year": 1,
        "subject": None,
        "topic": None,
        "content": "Texto [1].",
        "citations": [CITATION],
        "created_at": datetime.now(UTC),
    }
    return AnswerOut.model_validate(data | changes)


def test_answers_require_citations_unless_no_evidence():
    assert answer().citations[0].page_number == 1
    assert answer(status="no_evidence", citations=[]).citations == []
    with pytest.raises(ValidationError):
        answer(citations=[])
    with pytest.raises(ValidationError):
        answer(status="no_evidence")
    with pytest.raises(ValidationError):
        CitationOut.model_validate(CITATION | {"page_number": 0})


@pytest.mark.parametrize(
    ("data", "valid"),
    [
        ({"kind": "rating", "rating": 4, "answer_id": 1}, True),
        ({"kind": "rating"}, False),
        ({"kind": "error", "comment": "La cita no coincide."}, True),
        ({"kind": "error", "rating": 2, "comment": "x"}, False),
        ({"kind": "suggestion"}, False),
    ],
)
def test_feedback_kinds(data, valid):
    if valid:
        FeedbackRequest.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            FeedbackRequest.model_validate(data)


def test_ingestion_output_fits_contract(tmp_path):
    item = create_sample(tmp_path / "sample")[0]
    metadata = DocumentMetadata.model_validate_json(Path(item["metadata"]).read_text("utf-8"))
    document = extract_pdf(Path(item["pdf"]), metadata)
    report = IngestionReport.model_validate(index_document(tmp_path / "i.sqlite", document))
    assert report.status == "partial"
    page = document.pages[0]
    PageOut(
        document_id=metadata.document_id,
        version=document.version,
        number=page.number,
        label=page.label,
        text=page.text,
        status=page.status,
    )
    chunk = document.chunks[0]
    citation = CitationOut.model_validate(
        CITATION
        | {"chunk_id": chunk.chunk_id, "start": chunk.start, "end": chunk.end, "quote": chunk.text}
    )
    assert page.text[citation.start : citation.end] == citation.quote
