"""Extracción y fragmentación por página, sin acceso a modelos ni a la red."""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader
from pypdf.errors import PyPdfError


class IngestionError(ValueError):
    """Error de entrada o extracción que se puede mostrar al operador."""


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    year: int = Field(ge=1, le=4, strict=True)
    subject: str = Field(min_length=1)
    topic: str = Field(min_length=1)


class ChunkSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_chars: int = Field(default=1200, ge=1, strict=True)
    overlap: int = Field(default=200, ge=0, strict=True)

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.overlap >= self.max_chars:
            raise ValueError("El solapamiento debe ser menor que el tamaño del fragmento.")
        return self


@dataclass(frozen=True)
class Page:
    number: int
    label: str | None
    text: str
    status: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    page_number: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Document:
    metadata: DocumentMetadata
    filename: str
    version: str
    settings: ChunkSettings
    pages: list[Page]
    chunks: list[Chunk]


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text.replace("\x00", ""))
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_page(page: Page, document_id: str, version: str, settings: ChunkSettings) -> list[Chunk]:
    text, start, chunks = page.text, 0, []
    while start < len(text):
        while start < len(text) and text[start].isspace():
            start += 1
        if start == len(text):
            break
        end = min(start + settings.max_chars, len(text))
        if end < len(text) and not text[end].isspace():
            boundary = max(text.rfind(" ", start, end), text.rfind("\n", start, end))
            if boundary > start:
                end = boundary
        while end > start and text[end - 1].isspace():
            end -= 1
        content = text[start:end]
        identity = json.dumps(
            ["ateneo-chunk-v1", document_id, version, page.number, start, end, content],
            ensure_ascii=False,
        ).encode("utf-8")
        chunks.append(Chunk(hashlib.sha256(identity).hexdigest(), page.number, start, end, content))
        if end == len(text):
            break
        next_start = end - settings.overlap if end - start > settings.overlap else end
        if next_start < end:
            boundary = next_start
            while boundary < end and not text[boundary - 1].isspace():
                boundary += 1
            if boundary < end:
                next_start = boundary
        start = next_start
    return chunks


def extract_pdf(
    path: Path, metadata: DocumentMetadata, settings: ChunkSettings | None = None
) -> Document:
    settings = settings or ChunkSettings()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise IngestionError(f"No se pudo leer el PDF: {path.name}.") from exc
    version = hashlib.sha256(raw).hexdigest()
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise IngestionError("El PDF está cifrado. Proporciona una copia sin cifrado.")
        labels = reader.page_labels if "/PageLabels" in reader.trailer["/Root"] else None
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = normalize_text(page.extract_text() or "")
            pages.append(
                Page(
                    number,
                    labels[number - 1] if labels else None,
                    text,
                    "text" if text else "no_text",
                )
            )
    except IngestionError:
        raise
    except (PyPdfError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise IngestionError(
            "No se pudo extraer el PDF; puede estar dañado o no ser compatible."
        ) from exc
    if not any(page.text for page in pages):
        raise IngestionError("El PDF no contiene texto extraíble; puede necesitar OCR.")
    chunks = [
        chunk
        for page in pages
        for chunk in chunk_page(page, metadata.document_id, version, settings)
    ]
    return Document(metadata, path.name, version, settings, pages, chunks)
