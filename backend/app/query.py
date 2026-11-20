"""CU-01: adaptador único entre la API y el RAG.

Proveedor y embeddings se eligen por entorno: `ATENEO_LLM_PROVIDER` y `ATENEO_EMBEDDER`
(`fake` por defecto, sin red; `openai` usa las variables de docs/rag-prototype.md).
"""

import os

from sqlalchemy.orm import Session

from app.rag import vector
from app.rag.answer import PROVIDERS, answer_question


def setting(choices: dict, variable: str):
    name = os.environ.get(variable, "fake")
    if name not in choices:
        raise ValueError(f"{variable} debe ser uno de: {', '.join(choices)}.")
    return choices[name]


def ask(
    db: Session,
    question: str,
    *,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
    mode: str = "breve",
) -> dict:
    """Único punto de llamada al RAG. Devuelve, sin validar (lo hace `app.citations.validate`):

    {"status": "answered" | "no_evidence",
     "answer": texto con marcas [n], donde n remite a citations[n - 1],
     "citations": [{"document_id", "title", "version", "page", "start", "end", "quote",
                    "chunk_id", ...}]}
    """
    return answer_question(
        db,
        question,
        setting(PROVIDERS, "ATENEO_LLM_PROVIDER"),
        embedder=setting(vector.EMBEDDERS, "ATENEO_EMBEDDER"),
        year=year,
        subject=subject,
        topic=topic,
        mode=mode,
    )
