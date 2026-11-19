import io
import json
import math
from dataclasses import replace
from functools import partial

import pytest
from alembic import command
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from test_models import BACKEND, TEST_DATABASE_URL, alembic_config
from test_rag_answer import GOLDEN

from app.models import Chunk, Document
from app.rag import vector
from app.rag.__main__ import ingest_folder, main
from app.rag.answer import answer_question, evaluate
from app.rag.ingestion import ChunkSettings, DocumentMetadata, extract_pdf
from app.rag.sample import create_sample


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(
        sum(x * x for x in a) * sum(y * y for y in b)
    )


def test_fake_embedder_is_deterministic_and_uses_configured_dimension(monkeypatch):
    monkeypatch.setenv("ATENEO_EMBED_DIM", "64")
    texts = ["La biblioteca conserva libros.", "Catálogo de la biblioteca", "Rúbrica de colores"]
    vectors = vector.fake_embedder(texts)
    assert vectors == vector.fake_embedder(texts)
    assert all(len(v) == 64 for v in vectors)
    assert cosine(vectors[0], vectors[1]) > cosine(vectors[0], vectors[2])
    monkeypatch.setenv("ATENEO_EMBED_DIM", "0")
    with pytest.raises(ValueError):
        vector.fake_embedder(["x"])


def test_real_embedder_batches_and_checks_dimension(monkeypatch):
    monkeypatch.delenv("ATENEO_EMBED_API_KEY", raising=False)
    with pytest.raises(ValueError):
        vector.openai_compatible_embedder(["x"])

    requests = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        requests.append((request.full_url, request.get_header("Authorization"), body))
        data = [{"index": i, "embedding": [float(i)] * 3} for i in range(len(body["input"]))]
        return io.BytesIO(json.dumps({"data": data[::-1]}).encode())

    monkeypatch.setenv("ATENEO_EMBED_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("ATENEO_EMBED_MODEL", "modelo")
    monkeypatch.setenv("ATENEO_EMBED_BASE_URL", "http://127.0.0.1:9/v1/")
    monkeypatch.setenv("ATENEO_EMBED_DIM", "3")
    monkeypatch.setattr(vector.urllib.request, "urlopen", fake_urlopen)
    vectors = vector.openai_compatible_embedder([f"t{i}" for i in range(70)])
    assert len(vectors) == 70 and vectors[1] == [1.0] * 3
    assert [len(body["input"]) for *_, body in requests] == [64, 6]
    assert requests[0][:2] == ("http://127.0.0.1:9/v1/embeddings", "Bearer clave-de-prueba")
    monkeypatch.setenv("ATENEO_EMBED_DIM", "4")
    with pytest.raises(ValueError, match="dimensión 4"):
        vector.openai_compatible_embedder(["x"])


def test_answer_uses_retriever_callable():
    passage = {
        "chunk_id": "c1",
        "document_id": "doc",
        "title": "Doc",
        "page_number": 2,
        "text": "La biblioteca conserva un catálogo.",
    }
    calls = []

    def retriever(question, **filters):
        calls.append((question, filters))
        return [passage]

    result = answer_question(retriever, "¿Qué conserva la biblioteca?", year=1)
    assert result["supported"] and result["citations"][0]["page"] == 2
    assert calls == [
        ("¿Qué conserva la biblioteca?", {"year": 1, "subject": None, "topic": None, "limit": 5})
    ]


def test_cli_without_index_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main(["ask", "--question", "¿Qué conserva la biblioteca?"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL")
def test_postgres_ingestion_reindex_and_vector_search(monkeypatch, tmp_path):
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ATENEO_EMBED_DIM", "128")
    config = alembic_config()
    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        folder = tmp_path / "sample"
        create_sample(folder)
        reports = ingest_folder(folder, ChunkSettings(), vector.fake_embedder)
        assert [(r["document_id"], r["status"]) for r in reports] == [
            ("muestra-a", "partial"),
            ("muestra-b", "indexed"),
        ]

        with Session(engine) as session:
            retrieve = partial(vector.search, session, embedder=vector.fake_embedder)
            report = evaluate(retrieve, json.loads(GOLDEN.read_text(encoding="utf-8")))
            assert report["passed"] == report["total"], [
                r for r in report["results"] if not r["passed"]
            ]
            [hit] = retrieve("azafrán", limit=1)
            assert (hit["document_id"], hit["page_number"], hit["page_label"]) == (
                "muestra-a",
                1,
                None,
            )
            assert "azafrán" in hit["text"] and 0 <= hit["score"] < 1
            assert {
                h["document_id"] for h in retrieve("biblioteca", subject=" asignatura FICTICIA b")
            } == {"muestra-b"}
            assert retrieve("biblioteca", year=2) == []
            session.rollback()

            # Reindexar sustituye la versión vigente sin duplicar el documento.
            metadata = DocumentMetadata.model_validate_json(
                (folder / "muestra-b.json").read_text(encoding="utf-8")
            )
            document = extract_pdf(
                folder / "muestra-b.pdf", metadata, ChunkSettings(max_chars=60, overlap=0)
            )
            vector.store_document(session, document, vector.fake_embedder)
            rows = session.scalars(select(Chunk.id).where(Chunk.document_id == "muestra-b")).all()
            assert sorted(rows) == sorted(c.chunk_id for c in document.chunks)
            assert session.get(Document, "muestra-b").chunk_settings["max_chars"] == 60
            session.rollback()

            # Un fallo al escribir conserva la versión anterior.
            broken = replace(document, chunks=[replace(c, start=-1) for c in document.chunks[:1]])
            with pytest.raises(Exception):
                vector.store_document(session, broken, vector.fake_embedder)
            session.rollback()
            count = select(func.count()).select_from(Chunk).where(Chunk.document_id == "muestra-b")
            assert session.scalar(count) == len(document.chunks)
    finally:
        engine.dispose()
        command.downgrade(config, "base")
