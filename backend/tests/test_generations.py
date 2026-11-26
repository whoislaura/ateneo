"""CU-02 sin PostgreSQL: generadores con el proveedor fake y POST /generations sobre SQLite."""

# ruff: noqa: F811  (fixtures `client` y `factory` importadas de test_queries)

from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_queries import SENTENCE, TEXT, cite, client, factory  # noqa: F401

from app import citations, generation
from app.models import Answer, HistoryEntry, Role
from app.rag.generate import generate_material, well_formed
from app.rag.index import index_document
from app.rag.ingestion import DocumentMetadata, extract_pdf
from app.rag.sample import create_sample

A = "La biblioteca ficticia conserva un catálogo de libros y páginas."
B = "Esta evaluación ficticia utiliza una rúbrica de colores."
C = "La biblioteca sirve como ejemplo."
SOURCE_A, SOURCE_B = "Muestra sintética muestra-a, p. 1", "Muestra sintética muestra-b, p. 1"

# Casos dorados: salida exacta del proveedor fake sobre la muestra sintética.
GOLDEN = {
    "summary": f"{A} [1] {B} [2] {C} [3]",
    "outline": f"- biblioteca ficticia\n  - {A} [1]\n  - {B} [2]\n  - {C} [3]",
    "table": "\n".join(
        [
            "| Fuente | Contenido |",
            "|---|---|",
            f"| {SOURCE_A} | {A} [1] |",
            f"| {SOURCE_B} | {B} [2] |",
            f"| {SOURCE_B} | {C} [3] |",
        ]
    ),
    "diagram": "\n".join(
        [
            f"biblioteca ficticia -> {SOURCE_A}: {A} [1]",
            f"biblioteca ficticia -> {SOURCE_B}: {B} [2]",
            f"biblioteca ficticia -> {SOURCE_B}: {C} [3]",
        ]
    ),
}


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    directory = tmp_path_factory.mktemp("generate")
    path = directory / "index.sqlite"
    for item in create_sample(directory / "sample"):
        metadata = DocumentMetadata.model_validate_json(Path(item["metadata"]).read_text("utf-8"))
        index_document(path, extract_pdf(Path(item["pdf"]), metadata))
    return path


@pytest.mark.parametrize("format", GOLDEN)
def test_golden_generation_with_fake_provider(index, format):
    result = generate_material(index, format, "biblioteca ficticia")
    assert (result["status"], result["answer"], result["invalid_citations"]) == (
        "answered",
        GOLDEN[format],
        [],
    )
    assert [(c["document_id"], c["page"], c["quote"]) for c in result["citations"]] == [
        ("muestra-a", 1, A),
        ("muestra-b", 1, B),
        ("muestra-b", 1, C),
    ]
    assert well_formed(format, result["answer"])


@pytest.mark.parametrize("format", GOLDEN)
def test_out_of_corpus_generation_is_no_evidence(index, format):
    result = generate_material(index, format, "capital de Francia")
    assert (result["status"], result["citations"]) == ("no_evidence", [])


@pytest.mark.parametrize(
    ("format", "reply"),
    [
        ("summary", f"{A} [F1]\nSin fuente."),
        ("outline", f"* {A} [F1]"),
        ("outline", f"- Tema\n    - {A} [F1]"),
        ("outline", f"- {A} [F1]\n- Hoja sin fuente"),
        ("table", f"| Fuente | {A} [F1] |"),
        ("table", f"| A | B |\n|---|---|\n| x | {A} [F1] | extra |"),
        ("table", "| A | B |\n|---|---|\n| x | sin marca |\n" + f"| y | {A} [F1] |"),
        ("diagram", f"{A} [F1]"),
        ("diagram", f"x -> {A} [F1]\nx -> z"),
    ],
)
def test_malformed_output_becomes_no_evidence(index, format, reply):
    result = generate_material(index, format, "biblioteca ficticia", lambda system, user: reply)
    assert (result["status"], result["answer"], result["citations"]) == (
        "no_evidence",
        citations.NO_EVIDENCE,
        [],
    )
    assert result["error"]


def test_well_formed_accepts_documented_structures():
    assert well_formed("summary", "Uno [1].\n\nDos [2] y tres [1].")
    assert well_formed("outline", "- Tema\n  - Rama\n    - Hoja [1]\n  - Otra [2]\n- Fin [1]")
    assert well_formed("table", "| Aspecto | X | Y |\n|:--|---|--:|\n| Plazo | uno [1] | |")
    assert well_formed("diagram", "Costumbre -> Ley [1]\nLey -> Edicto: inspira [2]")
    assert not well_formed("summary", "")
    with pytest.raises(ValueError):
        well_formed("otro", "x [1]")


def generate(client, role=Role.STUDENT, **body):
    return client.post("/api/v1/generations", json=body, headers=client.headers_for[role])


@pytest.mark.parametrize(
    ("format", "content"),
    [
        ("summary", f"{SENTENCE} [1]"),
        ("outline", f"- Catálogo de leyes\n  - {SENTENCE} [1]"),
        ("table", f"| Fuente | Contenido |\n|---|---|\n| Documento, p. 1 | {SENTENCE} [1] |"),
        ("diagram", f"Catálogo de leyes -> Documento, p. 1: {SENTENCE} [1]"),
    ],
)
def test_generation_persists_answer_citations_and_history(client, factory, format, content):
    body = {"format": format, "prompt": " Catálogo de leyes ", "year": 1}
    response = generate(client, **body)
    assert response.status_code == 201
    result = response.json()
    assert (result["kind"], result["status"], result["question"]) == (
        format,
        "answered",
        "Catálogo de leyes",
    )
    assert result["content"] == content
    [citation] = result["citations"]
    assert (citation["position"], citation["chunk_id"], citation["quote"]) == (1, "c1", SENTENCE)
    assert TEXT[citation["start"] : citation["end"]] == citation["quote"]
    with factory() as db:
        [entry] = db.scalars(select(HistoryEntry)).all()
        assert (entry.action, entry.answer_id, entry.summary) == (
            "generation",
            result["id"],
            "Catálogo de leyes",
        )
    path = f"/api/v1/answers/{result['id']}"
    assert client.get(path, headers=client.headers_for[Role.STUDENT]).json() == result


def test_generation_without_evidence(client):
    body = generate(client, Role.TEACHER, format="outline", prompt="catálogo", year=2).json()
    assert (body["kind"], body["status"], body["content"], body["citations"]) == (
        "outline",
        "no_evidence",
        citations.NO_EVIDENCE,
        [],
    )


def test_generation_roles_and_validation(client):
    assert client.post("/api/v1/generations", json={}).status_code == 401
    assert generate(client, Role.ADMIN, format="summary", prompt="x").status_code == 403
    for body in (
        {"format": "mapa", "prompt": "x"},
        {"prompt": "x"},
        {"format": "summary", "prompt": ""},
        {"format": "summary", "prompt": "x", "year": 0},
    ):
        response = generate(client, **body)
        assert response.status_code == 422, body


def test_generation_failure_is_503_and_persists_nothing(client, factory, monkeypatch, caplog):
    monkeypatch.setenv("ATENEO_LLM_PROVIDER", "openai")
    monkeypatch.delenv("ATENEO_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ATENEO_LLM_API_KEYS", raising=False)
    with caplog.at_level("WARNING", logger="ateneo.ai"):
        response = generate(client, format="summary", prompt="catálogo")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    # La causa queda en el log para diagnosticar el proveedor, sin la pregunta.
    [record] = [r for r in caplog.records if r.getMessage() == "ai_error"]
    assert record.error.startswith("ValueError") and "catálogo" not in record.error
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Answer)) == 0


def test_generation_with_an_invalid_citation_is_rejected(client, monkeypatch):
    table = "| A | B |\n|---|---|\n| x | Bien [1] |\n| y | Inventado [2] |"
    result = {"status": "answered", "answer": table, "citations": [cite(), cite(quote="otra")]}
    monkeypatch.setattr(generation, "generate", lambda db, format, prompt, **filters: result)
    body = generate(client, format="table", prompt="catálogo").json()
    assert (body["status"], body["content"], body["citations"]) == (
        "no_evidence",
        citations.NO_EVIDENCE,
        [],
    )
