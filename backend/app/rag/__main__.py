"""Comandos locales de la muestra de ingestión."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from app.rag.index import index_document, search
from app.rag.ingestion import ChunkSettings, DocumentMetadata, extract_pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingestión e índice textual de muestra de Ateneo")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="Generar PDFs ficticios y sus metadatos")
    sample.add_argument("--output", type=Path, required=True)
    ingest = commands.add_parser("ingest", help="Extraer e indexar un PDF con metadatos")
    ingest.add_argument("--pdf", type=Path, required=True)
    ingest.add_argument("--metadata", type=Path, required=True)
    ingest.add_argument("--index", type=Path, required=True)
    ingest.add_argument("--chunk-size", type=int, default=1200)
    ingest.add_argument("--overlap", type=int, default=200)
    lookup = commands.add_parser("search", help="Buscar fragmentos con referencia de origen")
    lookup.add_argument("--index", type=Path, required=True)
    lookup.add_argument("--query", required=True)
    lookup.add_argument("--year", type=int, choices=range(1, 5))
    lookup.add_argument("--subject")
    lookup.add_argument("--topic")
    lookup.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        if args.command == "sample":
            from app.rag.sample import create_sample

            result = create_sample(args.output)
        elif args.command == "ingest":
            metadata = DocumentMetadata.model_validate_json(
                args.metadata.read_text(encoding="utf-8")
            )
            settings = ChunkSettings(max_chars=args.chunk_size, overlap=args.overlap)
            if args.index.resolve() in (args.pdf.resolve(), args.metadata.resolve()):
                raise ValueError("El índice debe ser distinto del PDF y sus metadatos.")
            document = extract_pdf(args.pdf, metadata, settings)
            result = index_document(args.index, document)
        else:
            result = search(
                args.index,
                args.query,
                year=args.year,
                subject=args.subject,
                topic=args.topic,
                limit=args.limit,
            )
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except ModuleNotFoundError as exc:
        if exc.name != "reportlab":
            raise
        print(
            "La muestra requiere dependencias de desarrollo: uv sync --project backend",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
