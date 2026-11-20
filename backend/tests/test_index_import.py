import sqlite3

import pytest

from app.rag.__main__ import ingest_index, main
from app.rag.index import index_document, read_documents
from app.rag.ingestion import (
    ChunkSettings,
    Document,
    DocumentMetadata,
    IngestionError,
    Page,
    chunk_page,
)
from app.rag.vector import fake_embedder


def make_document(identifier="ocr"):
    metadata = DocumentMetadata(
        document_id=identifier, title="OCR revisado", year=1, subject="Derecho", topic="Fuentes"
    )
    pages = [
        Page(1, "i", "Texto jurídico recuperado por OCR: obligación.", "text"),
        Page(2, None, "", "no_text"),
    ]
    settings = ChunkSettings(max_chars=30, overlap=5)
    version = "a" * 64
    chunks = [c for p in pages for c in chunk_page(p, identifier, version, settings)]
    return Document(metadata, "escaneado.pdf", version, settings, pages, chunks)


def test_index_round_trip_preserves_ocr_labels_and_offsets(tmp_path):
    path = tmp_path / "corpus.sqlite"
    document = make_document()
    index_document(path, document)
    assert list(read_documents(path)) == [document]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE chunks SET text = 'alterado'",
        "UPDATE chunks SET start = -1",
        "UPDATE chunks SET version = 'otra'",
        "DELETE FROM chunks",
        "UPDATE pages SET status = 'desconocido'",
        "UPDATE documents SET version = 'invalida'",
    ],
)
def test_corrupt_index_is_rejected(tmp_path, sql):
    path = tmp_path / "corpus.sqlite"
    index_document(path, make_document())
    with sqlite3.connect(path) as connection:
        connection.execute(sql)
    with pytest.raises(IngestionError, match="inconsistentes"):
        list(read_documents(path))


def test_missing_index_does_not_create_file(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        list(read_documents(path))
    assert not path.exists()


def test_import_rolls_back_failed_document_and_continues(tmp_path, monkeypatch, capsys):
    path = tmp_path / "corpus.sqlite"
    index_document(path, make_document("a"))
    index_document(path, make_document("b"))
    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rollback(self):
            calls.append("rollback")

    def store(session, document, embedder):
        calls.append(document.metadata.document_id)
        assert embedder is fake_embedder
        if document.metadata.document_id == "a":
            raise ValueError("fallo de embeddings")
        assert document == make_document("b")
        return {"document_id": "b", "status": "partial"}

    monkeypatch.setattr("app.rag.__main__.database_session", Session)
    monkeypatch.setattr("app.rag.__main__.vector.store_document", store)
    results = ingest_index(path, fake_embedder)
    assert calls == ["a", "rollback", "b"]
    assert [r["status"] for r in results] == ["error", "partial"]
    assert main(["ingest-index", "--index", str(path)]) == 1
    assert '"status": "error"' in capsys.readouterr().out
