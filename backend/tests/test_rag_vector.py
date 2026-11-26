import io
import json
import math
from dataclasses import replace
from functools import partial

import pytest
from alembic import command
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from test_models import BACKEND, TEST_DATABASE_URL, alembic_config
from test_rag_answer import GOLDEN

from app.models import Chunk, Document, DocumentStatus
from app.rag import vector
from app.rag.__main__ import ingest_folder, main
from app.rag.answer import NOT_FOUND, answer_question, evaluate, retrieve
from app.rag.citations import db_sources
from app.rag.ingestion import ChunkSettings, DocumentMetadata, Page, chunk_page, extract_pdf
from app.rag.ingestion import Document as IngestedDocument
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


def test_vector_neighbours_need_a_shared_term_or_a_close_distance(monkeypatch):
    def passage(chunk_id, text, score):
        return {"chunk_id": chunk_id, "text": text, "score": score}

    hits = [
        passage("lexico", "La biblioteca conserva un catálogo.", 0.9),
        passage("cercano", "Fondo documental custodiado.", 0.3),
        passage("lejano", "Rúbrica de colores.", 0.7),
    ]
    calls = []

    def search(session, question, embedder, **filters):
        calls.append((session, question, embedder, filters))
        return hits

    monkeypatch.setattr(vector, "search", search)
    monkeypatch.setenv("ATENEO_RETRIEVAL", "vector")
    monkeypatch.setenv("ATENEO_MAX_DISTANCE", "0.5")
    kept = retrieve(
        "sesión",
        "¿Qué conserva la biblioteca?",
        vector.fake_embedder,
        year=1,
        subject=None,
        topic=None,
        limit=5,
    )
    assert [p["chunk_id"] for p in kept] == ["lexico", "cercano"]
    assert calls == [
        (
            "sesión",
            "¿Qué conserva la biblioteca?",
            vector.fake_embedder,
            {"year": 1, "subject": None, "topic": None, "limit": 5},
        )
    ]
    monkeypatch.setenv("ATENEO_MAX_DISTANCE", "3")
    with pytest.raises(ValueError):
        retrieve(
            "sesión",
            "biblioteca",
            vector.fake_embedder,
            year=None,
            subject=None,
            topic=None,
            limit=5,
        )


def test_hybrid_retrieval_fuses_text_and_vector_ranks(monkeypatch):
    def passage(chunk_id, score):
        return {"chunk_id": chunk_id, "text": "Ley forestal.", "score": score}

    monkeypatch.setattr(vector, "search", lambda *a, **k: [passage("v1", 0.1), passage("t2", 0.2)])
    monkeypatch.setattr(vector, "text_search", lambda *a, **k: [passage("t1", 3), passage("t2", 2)])
    ask = partial(retrieve, "sesión", "ley forestal", vector.fake_embedder, year=None)
    ask = partial(ask, subject=None, topic=None)
    monkeypatch.delenv("ATENEO_RETRIEVAL", raising=False)
    hits = ask(limit=2)
    # t2 aparece en ambas listas y supera a los primeros de cada una.
    assert [h["chunk_id"] for h in hits] == ["t2", "t1"]
    assert hits[0]["score"] == pytest.approx(1 / 62 + 1 / 62)
    monkeypatch.setenv("ATENEO_RETRIEVAL", "text")
    assert [h["chunk_id"] for h in ask(limit=5)] == ["t1", "t2"]
    monkeypatch.setenv("ATENEO_RETRIEVAL", "vector")
    assert [h["chunk_id"] for h in ask(limit=5)] == ["v1", "t2"]
    monkeypatch.setenv("ATENEO_RETRIEVAL", "bm25")
    with pytest.raises(ValueError):
        ask(limit=5)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL")
def test_postgres_text_search_finds_literal_fragment_buried_by_vector_noise(monkeypatch):
    """Regresión: «60 especies» quedaba ~56.º por coseno con embeddings `fake` y no llegaba."""
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    question = "¿Cuántas especies forestales arbóreas protege la Ley Forestal cubana?"
    target = "Se declaran protegidas 60 especies forestales arbóreas de la flora cubana."
    [close] = vector.fake_embedder([question])
    [far] = vector.fake_embedder(["Rúbrica de colores para evaluar exposiciones orales."])
    pages = [
        Page(n, None, f"Disposición {n}: régimen de tributos municipales.", "text")
        for n in range(1, 61)
    ]
    pages[4] = Page(5, None, target, "text")
    metadata = DocumentMetadata(
        document_id="ley-forestal",
        title="Ley Forestal",
        year=1,
        subject="Derecho",
        topic="Ambiental",
    )
    chunks = [
        c for p in pages for c in chunk_page(p, metadata.document_id, "v" * 64, ChunkSettings())
    ]
    document = IngestedDocument(metadata, "ley.pdf", "v" * 64, ChunkSettings(), pages, chunks)

    def embedder(texts):
        # Ruido casi idéntico a la pregunta; el fragmento correcto, lejos.
        return [
            far if t == target else close[:-1] + [close[-1] + 0.01 * i] for i, t in enumerate(texts)
        ]

    config = alembic_config()
    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with Session(engine) as session:
            vector.store_document(session, document, embedder)
            ask = partial(
                retrieve, session, question, vector.fake_embedder, year=1, subject=None, topic=None
            )
            for mode in ("hybrid", "text"):
                monkeypatch.setenv("ATENEO_RETRIEVAL", mode)
                assert target in [h["text"] for h in ask(limit=5)], mode
            monkeypatch.setenv("ATENEO_RETRIEVAL", "vector")
            assert target not in [h["text"] for h in ask(limit=5)]
            # Sin tildes ni mayúsculas, con el filtro y fuera del corpus.
            [hit] = vector.text_search(session, "ARBOREAS", limit=5)
            assert (hit["page_number"], hit["score"] > 0) == (5, True)
            assert vector.text_search(session, "arbóreas", year=2) == []
            assert vector.text_search(session, "usucapión") == []
    finally:
        engine.dispose()
        command.downgrade(config, "base")


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
    # La CLI comparte la fábrica de la API, que otras pruebas pueden haber inicializado.
    monkeypatch.setattr("app.rag.__main__.session_factory", lambda: sessionmaker(engine))
    try:
        folder = tmp_path / "sample"
        create_sample(folder)
        reports = ingest_folder(folder, ChunkSettings(), vector.fake_embedder)
        assert all(report["status"] != "error" for report in reports), reports
        assert [(r["document_id"], r["status"]) for r in reports] == [
            ("muestra-a", "partial"),
            ("muestra-b", "indexed"),
            ("muestra-c", "indexed"),
        ]

        with Session(engine) as session:
            report = evaluate(session, json.loads(GOLDEN.read_text(encoding="utf-8")))
            assert report["passed"] == report["total"], [
                r for r in report["results"] if not r["passed"]
            ]
            cited = report["results"][0]["citations"][0]
            [source] = db_sources(session, [cited["chunk_id"]]).values()
            assert source["page_text"][cited["start"] : cited["end"]] == cited["quote"]

            # Fuera del corpus: los vecinos sin relación se descartan antes del modelo.
            def provider(system, user):
                raise AssertionError("no debe llamarse sin fragmentos relevantes")

            for question in ("¿Cuál es la capital de Francia?", "¿Qué dice sobre la usucapión?"):
                assert vector.search(session, question, vector.fake_embedder)
                result = answer_question(session, question, provider)
                assert (result["status"], result["answer"]) == ("no_evidence", NOT_FOUND)

            retrieve = partial(vector.search, session, embedder=vector.fake_embedder)
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
            # Una cita de la versión anterior deja de verificarse.
            stale = report["results"][2]["citations"][0]
            assert stale["document_id"] == "muestra-b"
            assert db_sources(session, [stale["chunk_id"]]) == {}
            session.rollback()

            # Un fallo al escribir conserva la versión anterior.
            broken = replace(document, chunks=[replace(c, start=-1) for c in document.chunks[:1]])
            with pytest.raises(Exception):
                vector.store_document(session, broken, vector.fake_embedder)
            session.rollback()
            count = select(func.count()).select_from(Chunk).where(Chunk.document_id == "muestra-b")
            assert session.scalar(count) == len(document.chunks)

            # Retirar un documento invalida sus citas.
            session.get(Document, "muestra-a").status = DocumentStatus.RETIRED
            session.flush()
            assert db_sources(session, [cited["chunk_id"]]) == {}
            session.rollback()
    finally:
        engine.dispose()
        command.downgrade(config, "base")
