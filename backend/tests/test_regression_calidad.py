"""Calidad del RAG: razonamiento del proveedor, exámenes truncados y fidelidad de las citas."""

import io
import json
import random

import pytest
from test_exams_ai import client, db, factory, pdfs  # noqa: F401  (fixtures)
from test_rag_answer import index  # noqa: F401  (fixture)

from app.models import Role
from app.rag import answer, exam
from app.rag.answer import answer_question, openai_compatible_provider, quote_citation
from app.rag.exam import generate_exam, load_passages, parse_questions


@pytest.fixture
def sent(monkeypatch):
    payloads = []

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        reply = {"choices": [{"message": {"content": "ok"}}]}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setenv("ATENEO_LLM_API_KEY", "k")
    monkeypatch.setenv("ATENEO_LLM_MODEL", "m")
    monkeypatch.setattr(answer.urllib.request, "urlopen", fake_urlopen)
    return payloads


def test_reasoning_is_sent_only_when_configured(sent, monkeypatch):
    monkeypatch.delenv("ATENEO_LLM_REASONING", raising=False)
    openai_compatible_provider("s", "u")
    monkeypatch.setenv("ATENEO_LLM_REASONING", "high")
    openai_compatible_provider("s", "u")
    openai_compatible_provider(answer.REWRITE_PROMPT, "u")
    assert "reasoning" not in sent[0]
    assert sent[1]["reasoning"] == {"effort": "high"}
    assert sent[2]["reasoning"] == {"effort": "low"}  # la reformulación siempre es low
    monkeypatch.setenv("ATENEO_LLM_REASONING", "extreme")
    with pytest.raises(ValueError):
        openai_compatible_provider("s", "u")


def test_max_tokens_override_only_for_that_call(sent, monkeypatch):
    monkeypatch.delenv("ATENEO_LLM_MAX_TOKENS", raising=False)
    openai_compatible_provider("s", "u")
    openai_compatible_provider("s", "u", max_tokens=5000)
    assert [p["max_tokens"] for p in sent] == [3000, 5000]
    assert exam.exam_tokens(6) == 5200 and exam.exam_tokens(20) == 15000
    assert exam.exam_tokens(100) == 16000


def test_exam_call_passes_proportional_max_tokens(db):  # noqa: F811
    passages = load_passages(db, year=1, subject="Civil", topic=None, count=2, rng=random.Random(0))
    seen = []

    def provider(system, user, **kwargs):
        seen.append(kwargs)
        return exam.fake_provider(system, user)

    generate_exam(db, ["development", "true_false"], passages, "easy", provider)
    assert seen[0] == {"max_tokens": 2400}


def test_parse_questions_recovers_complete_items_of_a_truncated_json():
    full = json.dumps({"questions": [{"kind": "case", "statement": "a"}, {"kind": "case"}]})
    cut = full[: full.rindex("{") + 12]  # corta a mitad del segundo objeto
    assert parse_questions(cut) == [{"kind": "case", "statement": "a"}]
    assert parse_questions('{"questions": [{"kind": "case"}, {"ki') == [{"kind": "case"}]
    assert parse_questions('```json\n{"questions": [{"a": "}"}, ') == [{"a": "}"}]


def question(db, passages, **changes):  # noqa: F811
    sentence = passages[0]["text"]
    base = {"kind": "multiple_choice", "statement": "P", "answer": f"{sentence} [F1]"}
    return base | changes


def test_unbacked_correct_option_or_verdict_discards_the_question(db):  # noqa: F811
    passages = load_passages(db, year=1, subject="Civil", topic=None, count=2, rng=random.Random(0))
    sentence = passages[0]["text"]
    options = ["Opción sin relación alguna", "Otra distinta", "Tercera diferente", sentence]
    bad_test = question(db, passages, options=options, correct="A")
    good_test = question(db, passages, options=options, correct="D", statement="Q")
    bad_tf = {
        "kind": "true_false",
        "statement": "La luna orbita alrededor de Marte",
        "correct": True,
        "answer": f"{sentence} [F1]",
    }
    good_tf = {**bad_tf, "statement": sentence}

    def run(item, kind):
        reply = json.dumps({"questions": [item]})
        return generate_exam(db, [kind], passages, "easy", lambda s, u, **_: reply)

    assert run(bad_test, "multiple_choice") == []
    assert len(run(good_test, "multiple_choice")) == 1
    assert run(bad_tf, "true_false") == []
    assert len(run(good_tf, "true_false")) == 1


def passage(text):
    return {
        "chunk_id": "c1",
        "document_id": "d",
        "title": "T",
        "version": 1,
        "page_number": 1,
        "page_label": "1",
        "start": 0,
        "end": len(text),
        "text": text,
    }


def test_quote_prefers_the_sentence_with_the_figure_and_keeps_it_whole():
    text = (
        "La ley protege especies forestales arbóreas. "
        "En su art. 5 reconoce 60 especies forestales arbóreas en todo el territorio."
    )
    cite = quote_citation(passage(text), "La ley reconoce 60 especies forestales arbóreas.")
    assert cite["quote"].startswith("En su art. 5 reconoce 60 especies")
    assert cite["quote"].endswith("territorio.")


def test_long_sentence_is_trimmed_around_the_figure():
    text = "Preámbulo " + "relleno jurídico " * 60 + "establece 60 especies forestales arbóreas."
    cite = quote_citation(passage(text), "Se establecen 60 especies forestales arbóreas")
    assert "60" in cite["quote"] and len(cite["quote"]) <= answer.MAX_QUOTE
    assert text[cite["start"] : cite["end"]] == cite["quote"]


def test_quote_needs_two_shared_terms_unless_the_claim_is_short():
    p = passage("El registro conserva los libros de hipotecas antiguas.")
    assert quote_citation(p, "El registro prescribe plazos mercantiles largos") is None
    assert quote_citation(p, "Los libros hipotecas") is not None  # 3 términos o menos: basta 1
    assert quote_citation(p, "El registro conserva libros distintos") is not None


def test_long_unmarked_sentence_is_dropped_but_link_sentences_stay(index):  # noqa: F811
    long_claim = (
        "Los operadores jurídicos deben considerar sistemáticamente instituciones registrales "
        "hipotecarias mercantiles procesales administrativas tributarias notariales laborales "
        "ambientales concursales sucesorias societarias contractuales."
    )
    reply = f"Veamos el asunto. {long_claim}\nLa biblioteca conserva fondos. [F1]"
    result = answer_question(index, "¿Qué conserva la biblioteca?", lambda s, u: reply, mode="chat")
    assert "Veamos el asunto." in result["answer"]
    assert "operadores" not in result["answer"]
    assert any("operadores" in i.get("claim", "") for i in result["invalid_citations"])


def test_exam_question_count_above_20_is_422(client):  # noqa: F811
    body = {"year": 1, "subject": "Civil", "question_count": 21, "difficulty": "easy"}
    response = client.post("/api/v1/exams", headers=client.headers_for[Role.STUDENT], json=body)
    assert response.status_code == 422
