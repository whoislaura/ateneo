"""Prototipo RAG: respuestas restringidas al índice de muestra con citas verificadas."""

import json
import os
import re
import unicodedata
import urllib.request
from collections.abc import Callable
from pathlib import Path

from app.rag.index import search

NOT_FOUND = "No encontrado en el corpus."

SYSTEM_PROMPT = f"""Eres Ateneo, asistente académico de la Licenciatura en Derecho.
Responde en español usando únicamente los fragmentos del corpus que recibes.
- No uses conocimiento externo ni supongas datos ausentes en los fragmentos.
- Cada afirmación debe terminar con su cita exacta, copiada del encabezado del fragmento: \
[documento, p. N].
- Cita solo documentos y páginas que aparecen en los fragmentos.
- Si los fragmentos no permiten responder, responde exactamente: {NOT_FOUND}"""

# Documento: todo hasta la última coma antes de "p. N".
CITATION = re.compile(r"\[([^\[\]]+),\s*p\.\s*(\d+)\]")
SEPARATOR = "\n---\n"

# shortcut: lista mínima de palabras vacías; sustituir al evaluar con preguntas reales.
STOPWORDS = frozenset(
    """a al algo como con cual cuales cuando de del donde el en es esta este esto la las
    lo los mas para por que quien se segun si sobre son su sus un una uno unos y o ya
    hay dice dicen describe menciona corpus documento texto""".split()
)

Provider = Callable[[str, str], str]
# Alternativa al índice SQLite: (pregunta, year=, subject=, topic=, limit=) -> fragmentos.
Retriever = Callable[..., list[dict]]


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def content_terms(text: str) -> list[str]:
    words = re.findall(r"[^\W_]+", fold(text))
    return list(dict.fromkeys(word for word in words if word not in STOPWORDS))


def build_prompt(question: str, passages: list[dict]) -> str:
    blocks = [
        f"[{p['document_id']}, p. {p['page_number']}] {p['title']}\n{p['text']}" for p in passages
    ]
    return "Fragmentos:\n" + SEPARATOR.join(blocks) + f"{SEPARATOR}Pregunta: {question}"


def fake_provider(system: str, user: str) -> str:
    """Determinista para pruebas y CI: devuelve la oración con más términos de la pregunta."""
    body, _, question = user.rpartition(f"{SEPARATOR}Pregunta: ")
    wanted = set(content_terms(question))
    best, best_score = NOT_FOUND, 0
    for block in body.removeprefix("Fragmentos:\n").split(SEPARATOR):
        header, _, text = block.partition("\n")
        citation = CITATION.match(header)
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            score = len(wanted & set(content_terms(sentence)))
            if citation and score > best_score:
                best, best_score = f"{sentence.strip()} {citation.group(0)}", score
    return best


def openai_compatible_provider(system: str, user: str) -> str:
    """API de chat compatible con OpenAI; la clave solo se lee del entorno."""
    key, model = os.environ.get("ATENEO_LLM_API_KEY"), os.environ.get("ATENEO_LLM_MODEL")
    if not key or not model:
        raise ValueError("Definir ATENEO_LLM_API_KEY y ATENEO_LLM_MODEL para el proveedor real.")
    base_url = os.environ.get("ATENEO_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["choices"][0]["message"]["content"]


PROVIDERS: dict[str, Provider] = {"fake": fake_provider, "openai": openai_compatible_provider}


def verify_citations(answer: str, passages: list[dict]) -> tuple[str, list[dict], list[str]]:
    """Conserva solo las citas que corresponden a un fragmento recuperado."""
    retrieved: dict[tuple[str, int], dict] = {}
    for p in passages:
        source = retrieved.setdefault(
            (p["document_id"], p["page_number"]),
            {"document_id": p["document_id"], "title": p["title"], "page": p["page_number"]},
        )
        source.setdefault("chunk_ids", []).append(p["chunk_id"])
    valid, invalid = {}, []

    def check(match: re.Match) -> str:
        key = (match.group(1).strip(), int(match.group(2)))
        if key in retrieved:
            valid[key] = retrieved[key]
            return match.group(0)
        invalid.append(match.group(0))
        return ""

    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", CITATION.sub(check, answer)).strip()
    return cleaned, list(valid.values()), invalid


def answer_question(
    index: Path | Retriever,
    question: str,
    provider: Provider = fake_provider,
    *,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
    limit: int = 5,
) -> dict:
    terms = content_terms(question)
    filters = {"year": year, "subject": subject, "topic": topic, "limit": limit}
    if not terms:
        passages = []
    elif isinstance(index, Path):
        passages = search(index, " ".join(terms), **filters)
    else:
        passages = index(question, **filters)
    result = {"question": question, "answer": NOT_FOUND, "citations": [], "invalid_citations": []}
    if not passages:
        return result | {"supported": False}
    text, citations, invalid = verify_citations(
        provider(SYSTEM_PROMPT, build_prompt(question, passages)), passages
    )
    supported = bool(citations) and NOT_FOUND.casefold() not in text.casefold()
    return result | {
        "answer": text if supported else NOT_FOUND,
        "citations": citations if supported else [],
        "invalid_citations": invalid,
        "supported": supported,
    }


def evaluate(
    index: Path | Retriever, golden: list[dict], provider: Provider = fake_provider
) -> dict:
    """Ejecuta las preguntas doradas; una pregunta sin fuentes esperadas debe rechazarse."""
    results = []
    for item in golden:
        response = answer_question(index, item["question"], provider, **item.get("filters", {}))
        expected = {(source["document_id"], source["page"]) for source in item["expected"]}
        cited = {(source["document_id"], source["page"]) for source in response["citations"]}
        if expected:
            passed = bool(cited & expected) and not response["invalid_citations"]
        else:
            passed = not response["supported"]
        results.append({"id": item["id"], "passed": passed, **response})
    return {"passed": sum(r["passed"] for r in results), "total": len(results), "results": results}
