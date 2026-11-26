"""Regresiones del CLI RAG: términos de contenido y errores sin mensaje."""

import json

import pytest

from app.rag import vector
from app.rag.__main__ import eval_report, main
from app.rag.answer import retrieve
from app.rag.index import index_document
from app.rag.index import search as index_search
from app.rag.ingestion import ChunkSettings, Document, DocumentMetadata, Page, chunk_page

QUESTION = "¿Qué conserva la biblioteca ficticia?"


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "index.sqlite"
    settings = ChunkSettings()
    version = "a" * 64
    for identifier, text in (
        ("biblioteca", "La biblioteca ficticia conserva un catálogo de libros."),
        ("ruido", "La de que es la y o, sin tema alguno."),
    ):
        metadata = DocumentMetadata(
            document_id=identifier,
            title=identifier,
            year=1,
            subject="Derecho",
            topic="Biblioteca",
        )
        page = Page(1, None, text, "text")
        document = Document(
            metadata,
            f"{identifier}.pdf",
            version,
            settings,
            [page],
            chunk_page(page, identifier, version, settings),
        )
        index_document(path, document)
    return path


def cli_search(index, capsys, *extra):
    assert main(["search", "--index", str(index), "--query", QUESTION, *extra]) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_search_uses_the_same_content_terms_as_answers(index, capsys):
    found = cli_search(index, capsys)
    assert [item["document_id"] for item in found] == ["biblioteca"]

    retrieved = retrieve(
        index, QUESTION, vector.fake_embedder, year=None, subject=None, topic=None, limit=5
    )
    assert [item["document_id"] for item in found] == [
        item["document_id"] for item in retrieved
    ]


def test_cli_search_keeps_literal_queries_available(index, capsys):
    literal = cli_search(index, capsys, "--literal")
    assert {item["document_id"] for item in literal} == {"biblioteca", "ruido"}
    assert {item["document_id"] for item in index_search(index, QUESTION)} == {
        item["document_id"] for item in literal
    }


def test_eval_report_handles_errors_without_message():
    report = {
        "passed": 0,
        "total": 1,
        "results": [{"id": "g01", "passed": False, "status": "error", "error": ""}],
    }
    assert eval_report(report).splitlines() == [
        "FALLA g01 error [] sin detalle",
        "Total: 0/1 correctas",
    ]
