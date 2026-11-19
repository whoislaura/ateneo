import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.rag import answer
from app.rag.answer import NOT_FOUND, answer_question, evaluate, openai_compatible_provider
from app.rag.index import index_document
from app.rag.ingestion import DocumentMetadata, extract_pdf
from app.rag.sample import create_sample

# Forma que consume app.query (AT-09) más page_label, que CitationOut también exige.
CITATION_KEYS = {"chunk_id", "document_id", "title", "version", "page", "page_label"} | {
    "start",
    "end",
    "quote",
}
GOLDEN = Path(answer.__file__).with_name("golden_questions.json")


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    directory = tmp_path_factory.mktemp("rag")
    path = directory / "index.sqlite"
    for item in create_sample(directory / "sample"):
        metadata = DocumentMetadata.model_validate_json(Path(item["metadata"]).read_text("utf-8"))
        index_document(path, extract_pdf(Path(item["pdf"]), metadata))
    return path


def page_text(index, document_id, number):
    with closing(sqlite3.connect(index)) as connection:
        [(text,)] = connection.execute(
            "SELECT text FROM pages WHERE document_id = ? AND number = ?", (document_id, number)
        )
    return text


def test_golden_questions_pass_with_fake_provider(index):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert any(not item["expected"] for item in golden)
    report = evaluate(index, golden)
    assert report["passed"] == report["total"] == len(golden), [
        r for r in report["results"] if not r["passed"]
    ]
    for result in report["results"]:
        for c in result["citations"]:
            assert (
                c["quote"] == page_text(index, c["document_id"], c["page"])[c["start"] : c["end"]]
            )
            assert c.keys() == CITATION_KEYS


def test_out_of_corpus_does_not_call_provider(index):
    def provider(system, user):
        raise AssertionError("no debe llamarse sin fragmentos")

    result = answer_question(index, "¿Cuál es la capital de Francia?", provider)
    assert result["status"] == "no_evidence" and result["answer"] == NOT_FOUND


def test_markers_are_resolved_to_exact_quotes_and_renumbered(index):
    def provider(system, user):
        assert "únicamente los fragmentos" in system and "[F1] Muestra sintética muestra-a" in user
        return (
            "Conserva un catálogo [F1] [F9] [2]. Su término exclusivo es azafrán [F1]. "
            "De nuevo, conserva un catálogo [F1]."
        )

    result = answer_question(index, "¿Qué conserva la biblioteca?", provider, year=1)
    assert result["status"] == "answered"
    assert result["answer"] == (
        "Conserva un catálogo [1]. Su término exclusivo es azafrán [2]. "
        "De nuevo, conserva un catálogo [1]."
    )
    assert [c["quote"] for c in result["citations"]] == [
        "La biblioteca ficticia conserva un catálogo de libros y páginas.",
        "El término exclusivo de esta página es azafrán.",
    ]
    assert [i["marker"] for i in result["invalid_citations"]] == ["[F9]"]


def test_citation_that_fails_verification_is_dropped(index, monkeypatch):
    real = answer.quote_citation

    def tampered(passage, claim):
        return real(passage, claim) | {"quote": "texto inventado"}

    monkeypatch.setattr(answer, "quote_citation", tampered)
    result = answer_question(index, "¿Qué conserva la biblioteca?", year=1)
    assert result["status"] == "no_evidence" and result["citations"] == []
    [invalid] = result["invalid_citations"]
    assert invalid["quote"] == "texto inventado" and "no coincide" in invalid["reason"]


@pytest.mark.parametrize(
    "reply", ["Conserva un catálogo.", "Conserva un catálogo [F7].", "Conserva [1].", NOT_FOUND]
)
def test_answer_without_valid_citation_is_rejected(index, reply):
    result = answer_question(index, "¿Qué conserva la biblioteca?", lambda s, u: reply)
    assert result["status"] == "no_evidence"
    assert result["answer"] == NOT_FOUND and result["citations"] == []


def test_real_provider_reads_key_from_env(monkeypatch):
    monkeypatch.delenv("ATENEO_LLM_API_KEY", raising=False)
    with pytest.raises(ValueError):
        openai_compatible_provider("s", "u")

    sent = {}

    def fake_urlopen(request, timeout):
        sent["url"], sent["auth"] = request.full_url, request.get_header("Authorization")
        sent["body"] = json.loads(request.data)
        reply = {"choices": [{"message": {"content": "respuesta"}}]}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setenv("ATENEO_LLM_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("ATENEO_LLM_MODEL", "modelo")
    monkeypatch.setenv("ATENEO_LLM_BASE_URL", "http://127.0.0.1:9/v1/")
    monkeypatch.setattr(answer.urllib.request, "urlopen", fake_urlopen)
    assert openai_compatible_provider("s", "u") == "respuesta"
    assert sent["url"] == "http://127.0.0.1:9/v1/chat/completions"
    assert sent["auth"] == "Bearer clave-de-prueba"
    assert sent["body"]["model"] == "modelo" and sent["body"]["temperature"] == 0
