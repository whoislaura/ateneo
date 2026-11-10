import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter

from app.rag.index import index_document, search
from app.rag.ingestion import (
    ChunkSettings,
    DocumentMetadata,
    IngestionError,
    Page,
    chunk_page,
    extract_pdf,
    normalize_text,
)
from app.rag.sample import create_sample


@pytest.fixture
def sample(tmp_path):
    paths = create_sample(tmp_path / "sample")
    return [
        (
            Path(item["pdf"]),
            DocumentMetadata.model_validate_json(
                Path(item["metadata"]).read_text(encoding="utf-8")
            ),
        )
        for item in paths
    ]


def test_extract_preserves_pages_accents_and_origins(sample):
    pdf, metadata = sample[0]
    document = extract_pdf(pdf, metadata)
    assert [p.number for p in document.pages] == [1, 2, 3]
    assert [p.status for p in document.pages] == ["text", "no_text", "text"]
    assert document.pages[1].text == ""
    assert "azafrán" in document.pages[0].text
    assert len(document.version) == 64
    assert document.filename == pdf.name
    assert all(page.label is None for page in document.pages)
    assert {c.page_number for c in document.chunks} == {1, 3}
    for chunk in document.chunks:
        page = document.pages[chunk.page_number - 1]
        assert chunk.text == page.text[chunk.start : chunk.end]
        assert 0 < len(chunk.text) <= 1200
    assert document == extract_pdf(pdf, metadata)


def test_embedded_page_labels_do_not_replace_physical_numbers(sample, tmp_path):
    writer = PdfWriter()
    writer.append(sample[0][0])
    writer.set_page_label(0, 2, style="/r")
    path = tmp_path / "labels.pdf"
    writer.write(path)
    document = extract_pdf(path, sample[0][1])
    assert [p.number for p in document.pages] == [1, 2, 3]
    assert [p.label for p in document.pages] == ["i", "ii", "iii"]


@pytest.mark.parametrize(
    "changes",
    [
        {"year": 0},
        {"year": 5},
        {"year": "1"},
        {"year": True},
        {"subject": "  "},
        {"document_id": ""},
        {"unexpected": "value"},
    ],
)
def test_invalid_metadata(sample, changes):
    data = sample[0][1].model_dump()
    data.update(changes)
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(data)


def test_required_metadata(sample):
    data = sample[0][1].model_dump()
    del data["topic"]
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(data)


@pytest.mark.parametrize("size,overlap", [(0, 0), (20, -1), (20, 20), (20, 21)])
def test_invalid_chunk_settings(size, overlap):
    with pytest.raises(ValidationError):
        ChunkSettings(max_chars=size, overlap=overlap)


def test_normalization_retains_paragraphs():
    assert normalize_text("  Pa\u0301gina\r\n\r\n\r\n texto\t  español  ") == (
        "Página\n\ntexto español"
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "  ",
        "una palabra",
        "a" * 4000,
        ("Documento con acentos, páginas y revisión.\n\n" * 100),
    ],
)
@pytest.mark.parametrize("size,overlap", [(1, 0), (40, 10), (1200, 200)])
def test_chunk_boundaries_and_coverage(text, size, overlap):
    page = Page(1, None, normalize_text(text), "text")
    chunks = chunk_page(page, "example", "version", ChunkSettings(max_chars=size, overlap=overlap))
    covered = set()
    for chunk in chunks:
        assert 0 < len(chunk.text) <= size
        assert chunk.text == page.text[chunk.start : chunk.end]
        covered.update(range(chunk.start, chunk.end))
    assert all(i in covered for i, char in enumerate(page.text) if not char.isspace())
    assert all(a.start < b.start for a, b in zip(chunks, chunks[1:]))
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_overlap_is_present():
    page = Page(7, None, "palabra " * 100, "text")
    chunks = chunk_page(page, "example", "version", ChunkSettings(max_chars=100, overlap=20))
    assert all(a.start < b.start < a.end for a, b in zip(chunks, chunks[1:]))
    assert all(c.page_number == 7 for c in chunks)


def test_index_search_filters_and_page_provenance(sample, tmp_path):
    index = tmp_path / "index.sqlite"
    for pdf, meta in sample:
        report = index_document(index, extract_pdf(pdf, meta))
        assert report["chunks"] > 0
    assert report["status"] == "indexed"
    found = search(index, "AZAFRAN")
    assert len(found) == 1
    hit = found[0]
    assert hit["document_id"] == "muestra-a"
    assert hit["page_number"] == 1
    assert hit["version"] == extract_pdf(*sample[0]).version
    with sqlite3.connect(index) as connection:
        text = connection.execute(
            "SELECT text FROM pages WHERE document_id=? AND number=?",
            (hit["document_id"], hit["page_number"]),
        ).fetchone()[0]
        assert text[hit["start"] : hit["end"]] == hit["text"]
        assert connection.execute("SELECT count(*) FROM pages").fetchone()[0] == 5
    assert len(search(index, "biblioteca")) == 2
    assert (
        len(
            search(
                index,
                "biblioteca",
                year=4,
                subject="ASIGNATURA FICTICIA B",
                topic="EVALUACIO\u0301N",
            )
        )
        == 1
    )
    assert search(index, "azafrán", year=4) == []
    assert search(index, "azafrán", topic="Biblioteca' OR 1=1 --") == []
    assert search(index, "ornitorrinco") == []
    assert search(index, '"()*-') == []
    assert search(index, '" OR "azafrán"')[0]["page_number"] == 1
    assert search(index, "documentos") == search(index, "documentos")
    assert len(search(index, "documentos", limit=1)) == 1


def test_reingestion_replaces_and_does_not_duplicate(sample, tmp_path):
    index = tmp_path / "index.sqlite"
    original = extract_pdf(*sample[0])
    other = extract_pdf(*sample[1])
    report = index_document(index, original)
    assert report["status"] == "partial"
    assert report["no_text_pages"] == [2]
    assert report["warnings"]
    index_document(index, other)
    index_document(index, original)
    with sqlite3.connect(index) as connection:
        assert connection.execute("SELECT count(*) FROM chunks").fetchone()[0] == (
            len(original.chunks) + len(other.chunks)
        )
    replacement = extract_pdf(sample[1][0], sample[0][1], ChunkSettings(max_chars=80, overlap=10))
    index_document(index, replacement)
    assert search(index, "azafrán") == []
    assert {hit["document_id"] for hit in search(index, "turquesa")} == {"muestra-a", "muestra-b"}
    with sqlite3.connect(index) as connection:
        assert connection.execute("SELECT count(*) FROM pages").fetchone()[0] == 4
        settings = connection.execute(
            "SELECT settings FROM documents WHERE document_id='muestra-a'"
        ).fetchone()[0]
        assert json.loads(settings) == {"max_chars": 80, "overlap": 10}


def test_failed_transaction_restores_old_document_pages_and_fts(sample, tmp_path):
    index = tmp_path / "index.sqlite"
    document = extract_pdf(*sample[0])
    index_document(index, document)
    before = search(index, "azafrán")
    with sqlite3.connect(index) as connection:
        connection.execute("""CREATE TRIGGER reject_bad BEFORE INSERT ON documents
            WHEN NEW.version = 'bad' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        index_document(index, replace(document, version="bad"))
    assert search(index, "azafrán") == before
    with sqlite3.connect(index) as connection:
        assert connection.execute("SELECT count(*) FROM pages").fetchone()[0] == 3


def test_rejects_unrelated_database(sample, tmp_path):
    index = tmp_path / "other.sqlite"
    with sqlite3.connect(index) as connection:
        connection.execute("CREATE TABLE valuable (value TEXT)")
        connection.execute("INSERT INTO valuable VALUES ('keep')")
    with pytest.raises(IngestionError, match="no es un índice"):
        index_document(index, extract_pdf(*sample[0]))
    with sqlite3.connect(index) as connection:
        assert connection.execute("SELECT value FROM valuable").fetchone()[0] == "keep"


def test_invalid_encrypted_and_empty_pdfs(sample, tmp_path):
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(IngestionError, match="extraer"):
        extract_pdf(path, sample[0][1])
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(path)
    with pytest.raises(IngestionError, match="no contiene texto"):
        extract_pdf(path, sample[0][1])
    writer = PdfWriter()
    writer.append(PdfReader(sample[0][0]))
    writer.encrypt("password")
    writer.write(path)
    with pytest.raises(IngestionError, match="cifrado"):
        extract_pdf(path, sample[0][1])


def test_cli_roundtrip_and_invalid_replacement(tmp_path):
    directory, index = tmp_path / "demo", tmp_path / "demo.sqlite"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "app.rag", *map(str, args)],
            cwd=Path(__file__).parents[1],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    sample = run("sample", "--output", directory)
    assert sample.returncode == 0, sample.stderr
    paths = json.loads(sample.stdout)
    ingest_args = (
        "ingest",
        "--pdf",
        paths[0]["pdf"],
        "--metadata",
        paths[0]["metadata"],
        "--index",
        index,
    )
    ingest = run(*ingest_args)
    assert ingest.returncode == 0, ingest.stderr
    assert json.loads(ingest.stdout)["no_text_pages"] == [2]
    result = run("search", "--index", index, "--query", "azafrán")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["page_number"] == 1
    Path(paths[0]["pdf"]).write_bytes(b"broken")
    assert run(*ingest_args).returncode == 1
    assert search(index, "azafrán")
    assert run("sample", "--output", directory).returncode == 1
    absent = tmp_path / "absent.sqlite"
    assert run("search", "--index", absent, "--query", "texto").returncode == 1
    assert not absent.exists()
