"""CU-01: recuperación, respuesta en español restringida al corpus y citas verificadas (CU-05)."""

import json
import os
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.rag import index, vector
from app.rag.citations import db_sources, sqlite_sources, verify_citations
from app.rag.index import content_terms
from app.rag.rotation import rotating

NOT_FOUND = "No encontrado en el corpus."

SYSTEM_PROMPT = f"""Eres Ateneo, asistente académico de la Licenciatura en Derecho.
Responde en español usando únicamente los fragmentos del corpus que recibes.
- No uses conocimiento externo ni supongas datos ausentes en los fragmentos.
- Cada afirmación debe terminar con la marca del fragmento que la respalda, copiada de su \
encabezado, por ejemplo [F1]. Una marca por corchete.
- Usa solo marcas que aparecen en los fragmentos.
- Si los fragmentos no permiten responder, responde exactamente: {NOT_FOUND}"""

MARKER = re.compile(r"\[F(\d+)\]")
SEPARATOR = "\n---\n"
# shortcut: oración = hasta . ! ? o salto de línea; abreviaturas como "art." la cortan.
SENTENCE = re.compile(r"[^\s.!?][^.!?\n]*[.!?]?")

Provider = Callable[[str, str], str]


def build_prompt(question: str, passages: list[dict]) -> str:
    blocks = [
        f"[F{n}] {p['title']}, p. {p['page_number']}\n{p['text']}"
        for n, p in enumerate(passages, 1)
    ]
    return "Fragmentos:\n" + SEPARATOR.join(blocks) + f"{SEPARATOR}Pregunta: {question}"


def fake_provider(system: str, user: str) -> str:
    """Determinista para pruebas y CI: devuelve la oración con más términos de la pregunta."""
    body, _, question = user.rpartition(f"{SEPARATOR}Pregunta: ")
    wanted = set(content_terms(question))
    best, best_score = NOT_FOUND, 0
    for block in body.removeprefix("Fragmentos:\n").split(SEPARATOR):
        header, _, text = block.partition("\n")
        marker = MARKER.match(header)
        for sentence in SENTENCE.findall(text):
            score = len(wanted & set(content_terms(sentence)))
            if marker and score > best_score:
                best, best_score = f"{sentence.strip()} {marker.group(0)}", score
    return best


def openai_compatible_provider(system: str, user: str, key: str | None = None) -> str:
    """API de chat compatible con OpenAI; la clave viene del entorno (o de `rotation`)."""
    key, model = key or os.environ.get("ATENEO_LLM_API_KEY"), os.environ.get("ATENEO_LLM_MODEL")
    if not key or not model:
        raise ValueError(
            "Definir ATENEO_LLM_API_KEY (o ATENEO_LLM_API_KEYS) y ATENEO_LLM_MODEL "
            "para el proveedor real."
        )
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


PROVIDERS: dict[str, Provider] = {
    "fake": fake_provider,
    "openai": rotating(openai_compatible_provider, "ATENEO_LLM"),
}


def retrieve(
    source: Path | Session,
    question: str,
    embedder: vector.Embedder,
    *,
    year: int | None,
    subject: str | None,
    topic: str | None,
    limit: int,
) -> list[dict]:
    """FTS5 con una ruta de índice; pgvector con una sesión, descartando vecinos sin relación."""
    terms = content_terms(question)
    if not terms:
        return []
    filters = {"year": year, "subject": subject, "topic": topic, "limit": limit}
    if isinstance(source, Path):
        return index.search(source, " ".join(terms), **filters)
    # Híbrido simple: se acepta un vecino si comparte un término con la pregunta o está muy cerca.
    wanted, threshold = set(terms), vector.max_distance()
    return [
        p
        for p in vector.search(source, question, embedder, **filters)
        if p["score"] <= threshold or wanted & set(content_terms(p["text"]))
    ]


def claim_before(text: str, position: int) -> str:
    """Última oración antes de una marca: la afirmación que esa marca respalda."""
    before = MARKER.sub("", text[:position]).strip()
    return re.split(r"(?<=[.!?])\s+", before)[-1]


def quote_citation(passage: dict, claim: str) -> dict:
    """Cita sobre la oración del fragmento más parecida a la afirmación (o el fragmento entero)."""
    text, wanted = passage["text"], set(content_terms(claim))
    span, best = (0, len(text)), 0
    for match in SENTENCE.finditer(text):
        score = len(wanted & set(content_terms(match.group())))
        if score > best:
            span, best = (match.start(), match.start() + len(match.group().rstrip())), score
    # El texto del fragmento es page.text[start:end], así que los offsets pasan a la página.
    return {
        "chunk_id": passage["chunk_id"],
        "document_id": passage["document_id"],
        "title": passage["title"],
        "version": passage["version"],
        "page": passage["page_number"],
        "page_label": passage["page_label"],
        "start": passage["start"] + span[0],
        "end": passage["start"] + span[1],
        "quote": text[span[0] : span[1]],
    }


def answer_question(
    source: Path | Session,
    question: str,
    provider: Provider = fake_provider,
    *,
    embedder: vector.Embedder = vector.fake_embedder,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
    limit: int = 5,
) -> dict:
    """Responde CU-01. Ver docs/rag-prototype.md para la forma del resultado."""
    passages = retrieve(
        source, question, embedder, year=year, subject=subject, topic=topic, limit=limit
    )
    result = {
        "question": question,
        "status": "no_evidence",
        "answer": NOT_FOUND,
        "citations": [],
        "invalid_citations": [],
    }
    if not passages:
        return result
    # Las marcas [n] del contrato solo las pone el backend.
    reply = re.sub(r"\[\d+\]", "", provider(SYSTEM_PROMPT, build_prompt(question, passages)))
    return result | cite_reply(source, passages, reply)


def cite_reply(
    source: Path | Session,
    passages: list[dict],
    reply: str,
    claim: Callable[[str, int], str] = claim_before,
) -> dict:
    """Resuelve las marcas [Fn] de `reply` en citas verificadas y las renumera [n] (CU-01, CU-02).

    Devuelve `invalid_citations` y solo devuelve la respuesta si todas sus citas son válidas.
    """
    candidates, invalid = {}, []
    for match in MARKER.finditer(reply):
        number = int(match.group(1))
        if 1 <= number <= len(passages):
            citation = quote_citation(passages[number - 1], claim(reply, match.start()))
            candidates[match.start()] = citation
        else:
            invalid.append({"marker": match.group(0), "reason": "Fragmento no recuperado."})
    unique = {(c["chunk_id"], c["start"], c["end"]): c for c in candidates.values()}
    load_sources = sqlite_sources if isinstance(source, Path) else db_sources
    sources = load_sources(source, (c["chunk_id"] for c in unique.values()))
    _, rejected = verify_citations(list(unique.values()), sources)
    result = {"invalid_citations": invalid + rejected}
    if result["invalid_citations"] or not candidates or NOT_FOUND.casefold() in reply.casefold():
        return result

    positions: dict[tuple, int] = {}

    def renumber(match: re.Match) -> str:
        citation = candidates[match.start()]
        key = citation["chunk_id"], citation["start"], citation["end"]
        return f"[{positions.setdefault(key, len(positions) + 1)}]"

    content = re.sub(r"[ \t]+([.,;:])", r"\1", MARKER.sub(renumber, reply)).strip()
    return result | {
        "status": "answered",
        "answer": content,
        # positions se asigna en orden de inserción: la marca [n] es citations[n - 1].
        "citations": list(map(unique.get, positions)),
    }


def evaluate(
    source: Path | Session,
    golden: list[dict],
    provider: Provider = fake_provider,
    embedder: vector.Embedder = vector.fake_embedder,
) -> dict:
    """Ejecuta las preguntas doradas; una pregunta sin fuentes esperadas debe rechazarse."""
    results = []
    for item in golden:
        response = answer_question(
            source, item["question"], provider, embedder=embedder, **item.get("filters", {})
        )
        quoted = {(c["document_id"], c["page"], c["quote"]) for c in response["citations"]}
        cited = {key[:2] for key in quoted}
        if item["expected"]:
            passed = not response["invalid_citations"] and any(
                (e["document_id"], e["page"]) in cited
                and ("quote" not in e or (e["document_id"], e["page"], e["quote"]) in quoted)
                for e in item["expected"]
            )
        else:
            passed = response["status"] == "no_evidence"
        results.append({"id": item["id"], "passed": passed, **response})
    return {"passed": sum(r["passed"] for r in results), "total": len(results), "results": results}
