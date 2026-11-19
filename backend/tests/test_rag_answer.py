import io
import json
from pathlib import Path

import pytest

from app.rag import answer
from app.rag.answer import NOT_FOUND, answer_question, evaluate, openai_compatible_provider
from app.rag.index import index_document
from app.rag.ingestion import DocumentMetadata, extract_pdf
from app.rag.sample import create_sample

GOLDEN = Path(answer.__file__).with_name("golden_questions.json")


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    directory = tmp_path_factory.mktemp("rag")
    path = directory / "index.sqlite"
    for item in create_sample(directory / "sample"):
        metadata = DocumentMetadata.model_validate_json(Path(item["metadata"]).read_text("utf-8"))
        index_document(path, extract_pdf(Path(item["pdf"]), metadata))
    return path


def test_golden_questions_pass_with_fake_provider(index):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert any(not item["expected"] for item in golden)
    report = evaluate(index, golden)
    assert report["passed"] == report["total"] == len(golden), [
        r for r in report["results"] if not r["passed"]
    ]


def test_out_of_corpus_does_not_call_provider(index):
    def provider(system, user):
        raise AssertionError("no debe llamarse sin fragmentos")

    result = answer_question(index, "¿Cuál es la capital de Francia?", provider)
    assert result["answer"] == NOT_FOUND and not result["supported"]


def test_invalid_citations_are_dropped(index):
    def provider(system, user):
        assert "únicamente los fragmentos" in system and "[muestra-a, p. 1]" in user
        return "Conserva un catálogo [muestra-a, p. 1] [muestra-a, p. 9] [inventado, p. 1]."

    result = answer_question(index, "¿Qué conserva la biblioteca?", provider, year=1)
    assert result["supported"]
    assert result["answer"] == "Conserva un catálogo [muestra-a, p. 1]."
    assert [(c["document_id"], c["page"]) for c in result["citations"]] == [("muestra-a", 1)]
    assert result["citations"][0]["chunk_ids"]
    assert result["invalid_citations"] == ["[muestra-a, p. 9]", "[inventado, p. 1]"]


@pytest.mark.parametrize(
    "reply", ["Conserva un catálogo.", "Conserva un catálogo [otro, p. 2].", NOT_FOUND]
)
def test_answer_without_valid_citation_is_rejected(index, reply):
    result = answer_question(index, "¿Qué conserva la biblioteca?", lambda s, u: reply)
    assert result["answer"] == NOT_FOUND
    assert not result["supported"] and result["citations"] == []


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
