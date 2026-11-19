from app.rag.citations import sqlite_sources, verify_citations
from app.rag.index import index_document
from app.rag.ingestion import ChunkSettings, Document, DocumentMetadata, Page, chunk_page

TEXT = "Primera oración del artículo. Segunda oración con el plazo de diez días."
METADATA = DocumentMetadata(document_id="doc", title="Doc", year=1, subject="S", topic="T")


def document(version: str, text: str = TEXT) -> Document:
    page = Page(1, "i", text, "text")
    settings = ChunkSettings(max_chars=40, overlap=0)
    chunks = chunk_page(page, "doc", version, settings)
    return Document(METADATA, "doc.pdf", version, settings, [page], chunks)


def citation(chunk, version="v1", **changes) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": "doc",
        "version": version,
        "page": 1,
        "start": chunk.start,
        "end": chunk.end,
        "quote": TEXT[chunk.start : chunk.end],
    } | changes


def sources_for(doc: Document) -> dict:
    return {
        c.chunk_id: {
            "chunk_id": c.chunk_id,
            "document_id": "doc",
            "version": doc.version,
            "page_number": c.page_number,
            "chunk_start": c.start,
            "chunk_end": c.end,
            "page_text": doc.pages[0].text,
        }
        for c in doc.chunks
    }


def test_verify_keeps_exact_quotes_and_reports_the_rest():
    doc = document("v1")
    first, second = doc.chunks[:2]
    inner = citation(second, start=second.start + 8, quote=TEXT[second.start + 8 : second.end])
    cases = {
        "ok": citation(first),
        "inner": inner,
        "quote": citation(first, quote="Primera oración del artículo"),
        "outside": citation(first, end=second.end, quote=TEXT[first.start : second.end]),
        "version": citation(first, version="v0"),
        "page": citation(first, page=2),
        "missing": citation(first, chunk_id=None),
    }
    valid, invalid = verify_citations(list(cases.values()), sources_for(doc))
    assert valid == [cases["ok"], cases["inner"]]
    assert [c["quote"] for c in invalid] == [cases[k]["quote"] for k in list(cases)[2:]]
    assert all(c["reason"] for c in invalid)


def test_sqlite_sources_only_return_the_current_version(tmp_path):
    path = tmp_path / "index.sqlite"
    old = document("v1")
    index_document(path, old)
    sources = sqlite_sources(path, [c.chunk_id for c in old.chunks] + ["otro"])
    assert sources == sources_for(old)

    new = document("v2", TEXT.replace("diez", "quince"))
    index_document(path, new)
    assert sqlite_sources(path, [c.chunk_id for c in old.chunks]) == {}
    stale = old.chunks[0]
    valid, invalid = verify_citations([citation(stale)], sqlite_sources(path, [stale.chunk_id]))
    assert not valid and invalid[0]["reason"].startswith("El fragmento no existe")
