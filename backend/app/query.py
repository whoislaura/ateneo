"""CU-01: adaptador único entre la API y el RAG.

Proveedor y embeddings se eligen por entorno: `ATENEO_LLM_PROVIDER` y `ATENEO_EMBEDDER`
(`fake` por defecto, sin red; `openai` usa las variables de docs/rag-prototype.md).
"""

import os
from functools import partial

from sqlalchemy.orm import Session

from app.rag import vector
from app.rag.answer import CITATION, PROVIDERS, Retriever, answer_question


def setting(choices: dict, variable: str):
    name = os.environ.get(variable, "fake")
    if name not in choices:
        raise ValueError(f"{variable} debe ser uno de: {', '.join(choices)}.")
    return choices[name]


def retriever(db: Session) -> Retriever:
    return partial(vector.search, db, embedder=setting(vector.EMBEDDERS, "ATENEO_EMBEDDER"))


def ask(
    db: Session,
    question: str,
    *,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
) -> dict:
    """Único punto de llamada al RAG. Devuelve, sin validar (lo hace `app.citations.validate`):

    {"status": "answered" | "no_evidence",
     "answer": texto con marcas [n], donde n remite a citations[n - 1],
     "citations": [{"document_id", "title", "version", "page", "start", "end", "quote",
                    "chunk_id"}]}

    Al integrar el resultado estructurado de AT-15 basta con devolverlo aquí.
    """
    provider = setting(PROVIDERS, "ATENEO_LLM_PROVIDER")
    search, passages = retriever(db), []

    def capture(query: str, **filters) -> list[dict]:
        found = search(query, **filters)
        passages.extend(found)
        return found

    result = answer_question(capture, question, provider, year=year, subject=subject, topic=topic)
    if not result["supported"]:
        return {"status": "no_evidence", "answer": result["answer"], "citations": []}
    # shortcut: el prototipo cita páginas, no frases; se cita el primer fragmento recuperado
    # de cada página hasta que AT-15 devuelva la frase exacta.
    first: dict[tuple[str, int], dict] = {}
    for p in passages:
        first.setdefault((p["document_id"], p["page_number"]), p)
    order: list[tuple[str, int]] = []

    def mark(match) -> str:
        key = (match.group(1).strip(), int(match.group(2)))
        if key not in order:
            order.append(key)
        return f"[{order.index(key) + 1}]"

    answer = CITATION.sub(mark, result["answer"])
    citations = [
        {
            "document_id": p["document_id"],
            "title": p["title"],
            "version": p["version"],
            "page": p["page_number"],
            "start": p["start"],
            "end": p["end"],
            "quote": p["text"],
            "chunk_id": p["chunk_id"],
        }
        for p in (first[key] for key in order)
    ]
    return {"status": "answered", "answer": answer, "citations": citations}
