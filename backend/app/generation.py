"""CU-02: adaptador único entre la API y los generadores (mismo entorno que `app.query`)."""

from sqlalchemy.orm import Session

from app.query import setting
from app.rag import vector
from app.rag.generate import PROVIDERS, generate_material, well_formed

__all__ = ["generate", "well_formed"]


def generate(
    db: Session,
    format: str,
    prompt: str,
    *,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
) -> dict:
    """Único punto de llamada al RAG de CU-02. Devuelve la forma de `app.query.ask` sin validar."""
    return generate_material(
        db,
        format,
        prompt,
        setting(PROVIDERS, "ATENEO_LLM_PROVIDER"),
        embedder=setting(vector.EMBEDDERS, "ATENEO_EMBEDDER"),
        year=year,
        subject=subject,
        topic=topic,
    )
