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
            "Conserva un catálogo [F1] [2]. Su término exclusivo es azafrán [F1]. "
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
    assert result["invalid_citations"] == []


def test_answer_with_valid_and_unknown_markers_drops_only_that_sentence(index):
    def provider(system, user):
        return "Conserva un catálogo [F1]. Afirmación inventada [F9]."

    result = answer_question(index, "¿Qué conserva la biblioteca?", provider, year=1)
    assert result["status"] == "answered" and result["answer"] == "Conserva un catálogo [1]."
    assert [item["marker"] for item in result["invalid_citations"] if "marker" in item] == ["[F9]"]
    assert [i["claim"] for i in result["invalid_citations"] if "claim" in i] == [
        "Afirmación inventada [F9]."
    ]


def test_citation_that_fails_verification_is_dropped(index, monkeypatch):
    real = answer.quote_citation

    def tampered(passage, claim):
        return real(passage, claim) | {"quote": "texto inventado"}

    monkeypatch.setattr(answer, "quote_citation", tampered)
    result = answer_question(index, "¿Qué conserva la biblioteca?", year=1)
    assert result["status"] == "no_evidence" and result["citations"] == []
    [invalid, dropped] = result["invalid_citations"]
    assert "claim" in dropped
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
        sent["timeout"] = timeout
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
    assert sent["timeout"] == 100 and sent["body"]["max_tokens"] == 3000
    monkeypatch.setenv("ATENEO_LLM_TIMEOUT", "110")
    openai_compatible_provider("s", "u")
    assert sent["timeout"] == 110
    monkeypatch.setenv("ATENEO_LLM_TIMEOUT", "0")
    with pytest.raises(ValueError):
        openai_compatible_provider("s", "u")


# --- Modo «desarrollada» ---

PARAGRAPHS = "¿Qué dice el párrafo 20 sobre conservación?"


def assert_exact(index, citations):
    for c in citations:
        assert c["quote"] == page_text(index, c["document_id"], c["page"])[c["start"] : c["end"]]


def test_developed_answer_is_structured_and_cited(index):
    seen = {}

    def provider(system, user):
        seen["system"] = system
        return answer.fake_provider(system, user)

    question = "Explica qué conserva la biblioteca ficticia y qué rúbrica utiliza la evaluación"
    result = answer_question(index, question, provider, mode="desarrollada")
    assert seen["system"] == answer.DEVELOPED_PROMPT
    assert result["status"] == "answered" and result["invalid_citations"] == []
    for heading in answer.HEADINGS:
        assert f"## {heading}\n" in result["answer"] + "\n"
    assert {c["document_id"] for c in result["citations"]} == {"muestra-a", "muestra-b"}
    assert_exact(index, result["citations"])
    # El modo breve sigue igual: una oración con su cita.
    brief = answer_question(index, question, provider)
    assert seen["system"] == answer.SYSTEM_PROMPT and "##" not in brief["answer"]
    with pytest.raises(ValueError):
        answer_question(index, question, mode="larga")


def developed(index, question, **env):
    with pytest.MonkeyPatch.context() as patch:
        for name, value in env.items():
            patch.setenv(f"ATENEO_DEVELOPED_{name}", value)
        filters = {"year": None, "subject": None, "topic": None}
        return answer.retrieve_developed(index, question, None, **filters)


def test_developed_retrieval_limit_and_diversity(index):
    question = "biblioteca catálogo rúbrica evaluación ejercicio página párrafo conservación"
    hits = developed(index, question)
    assert len(hits) > 5 and len({h["document_id"] for h in hits}) >= 2
    assert len(developed(index, question, FRAGMENTS="2")) == 2
    capped = [h["document_id"] for h in developed(index, question, PER_DOCUMENT="1")]
    assert len(capped) == len(set(capped)) == 2  # muestra-a y muestra-b, uno de cada uno
    with pytest.raises(ValueError):
        developed(index, question, FRAGMENTS="0")


def test_developed_context_expands_with_neighbours_and_keeps_offsets(index):
    [passage] = developed(index, PARAGRAPHS, FRAGMENTS="1")
    text = page_text(index, "muestra-a", 3)
    # El fragmento del párrafo 20 se amplía con sus dos vecinos: toda la página 3.
    assert (passage["start"], passage["end"]) == (0, len(text)) and len(passage["chunks"]) == 3
    assert passage["text"] == text[passage["start"] : passage["end"]]
    # Sin presupuesto para los vecinos, queda solo el fragmento recuperado.
    [alone] = developed(index, PARAGRAPHS, FRAGMENTS="1", CONTEXT_CHARS="1500")
    assert alone["chunks"] == [(alone["chunk_id"], alone["start"], alone["end"])]
    assert developed(index, PARAGRAPHS, FRAGMENTS="1", CONTEXT_CHARS="1000") == []

    # Una afirmación sobre el texto vecino se cita con el fragmento que de verdad lo contiene.
    def provider(system, user):
        return "## Desarrollo\nEl párrafo 33 trata la conservación [F1]."

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ATENEO_DEVELOPED_FRAGMENTS", "1")
        result = answer_question(index, PARAGRAPHS, provider, mode="desarrollada")
    [citation] = result["citations"]
    assert citation["quote"].startswith("Párrafo 33:")
    assert citation["chunk_id"] == passage["chunks"][-1][0] != passage["chunk_id"]
    assert_exact(index, result["citations"])


def test_developed_drops_only_unverifiable_sentences(index, monkeypatch):
    reply = (
        "## Planteamiento\nSe analiza la biblioteca.\n## Desarrollo\n"
        "La biblioteca ficticia conserva un catálogo [F1]. Fue fundada en 1850 [F1]. "
        "Presta tabletas [F9].\nTiene 42 salas.\n## Límites del corpus\n" + NOT_FOUND
    )
    question = "¿Qué conserva la biblioteca ficticia?"
    result = answer_question(index, question, lambda s, u: reply, mode="desarrollada", year=1)
    assert result["status"] == "answered"
    assert result["answer"] == (
        "## Planteamiento\nSe analiza la biblioteca.\n## Desarrollo\n"
        "La biblioteca ficticia conserva un catálogo [1].\n## Límites del corpus\n" + NOT_FOUND
    )
    assert_exact(index, result["citations"])
    dropped = [i["claim"] for i in result["invalid_citations"] if "claim" in i]
    assert dropped == ["Fue fundada en 1850 [F1].", "Presta tabletas [F9].", "Tiene 42 salas."]
    assert {i.get("marker") for i in result["invalid_citations"]} >= {"[F1]", "[F9]"}
    # El modo breve también descarta solo las oraciones sin verificar.
    brief = answer_question(index, question, lambda s, u: reply, year=1)
    assert brief["status"] == "answered" and brief["answer"] == result["answer"]

    # Una cita que falla la verificación elimina solo su oración.
    real = answer.quote_citation

    def tampered(passage, claim):
        citation = real(passage, claim)
        return citation | ({"quote": "inventado"} if "azafrán" in claim else {})

    monkeypatch.setattr(answer, "quote_citation", tampered)
    reply = "Conserva un catálogo [F1]. Su término exclusivo es azafrán [F1]."
    result = answer_question(index, question, lambda s, u: reply, mode="desarrollada", year=1)
    assert result["answer"] == "Conserva un catálogo [1]."
    assert [c["quote"] for c in result["citations"]] == [
        "La biblioteca ficticia conserva un catálogo de libros y páginas."
    ]


@pytest.mark.parametrize(
    "reply", [NOT_FOUND, "Sin marcas.", "Inventado [F9].", "## Desarrollo\nFundada en 1850 [F1]."]
)
def test_developed_without_verifiable_claims_is_no_evidence(index, reply):
    result = answer_question(
        index, "¿Qué conserva la biblioteca?", lambda s, u: reply, mode="desarrollada"
    )
    assert (result["status"], result["answer"], result["citations"]) == (
        "no_evidence",
        NOT_FOUND,
        [],
    )


@pytest.mark.parametrize(
    "reply",
    ["", "A [F1]. B.\n\n## T\nC 1.850 [F2] [F3]! ¿D? E.[F1]", "art. 5 [F1]", "x.y. z"],
)
def test_segments_cover_the_whole_reply(reply):
    assert "".join(m.group() for m in answer.SEGMENT.finditer(reply)) == reply
