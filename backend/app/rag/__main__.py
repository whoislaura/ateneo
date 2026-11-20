"""Comandos locales de la muestra de ingestión."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import session_factory
from app.rag import vector
from app.rag.answer import PROVIDERS, answer_question, evaluate
from app.rag.index import index_document, search
from app.rag.ingestion import ChunkSettings, DocumentMetadata, extract_pdf


def database_session() -> Session:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("Indica --index o define DATABASE_URL (postgresql+psycopg://...).")
    return session_factory()()


def ingest_folder(folder: Path, settings: ChunkSettings, embedder: vector.Embedder) -> list[dict]:
    """Cada PDF necesita su JSON de metadatos al lado; un documento fallido no detiene el resto."""
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No hay PDFs en {folder}.")
    results = []
    with database_session() as session:
        for pdf in pdfs:
            try:
                metadata = DocumentMetadata.model_validate_json(
                    pdf.with_suffix(".json").read_text(encoding="utf-8")
                )
                document = extract_pdf(pdf, metadata, settings)
                results.append(vector.store_document(session, document, embedder))
            except (ValueError, OSError, SQLAlchemyError) as exc:
                results.append({"pdf": pdf.name, "status": "error", "error": str(exc)})
    return results


def eval_report(report: dict) -> str:
    """Una línea por pregunta (estado, citas, respuesta o error) y el total."""
    lines = []
    for r in report["results"]:
        cited = ", ".join(f"{c['document_id']} p. {c['page']}" for c in r.get("citations", []))
        detail = r.get("error") or " ".join(r["answer"].split())[:160]
        lines.append(
            f"{'OK   ' if r['passed'] else 'FALLA'} {r['id']} {r['status']} [{cited}] {detail}"
        )
        lines += [f"      cita inválida: {i.get('reason')}" for i in r.get("invalid_citations", [])]
    return "\n".join(lines + [f"Total: {report['passed']}/{report['total']} correctas"])


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
    folder = commands.add_parser(
        "ingest-dir", help="Ingerir en PostgreSQL (DATABASE_URL) cada PDF de una carpeta"
    )
    folder.add_argument("--folder", type=Path, required=True)
    folder.add_argument("--chunk-size", type=int, default=1200)
    folder.add_argument("--overlap", type=int, default=200)
    folder.add_argument("--embedder", choices=vector.EMBEDDERS, default="fake")
    lookup = commands.add_parser("search", help="Buscar fragmentos con referencia de origen")
    lookup.add_argument("--index", type=Path)
    lookup.add_argument("--query", required=True)
    lookup.add_argument("--year", type=int, choices=range(1, 5))
    lookup.add_argument("--subject")
    lookup.add_argument("--topic")
    lookup.add_argument("--limit", type=int, default=5)
    ask = commands.add_parser("ask", help="Responder con citas verificadas usando solo el corpus")
    ask.add_argument("--index", type=Path)
    ask.add_argument("--question", required=True)
    ask.add_argument("--year", type=int, choices=range(1, 5))
    ask.add_argument("--subject")
    ask.add_argument("--topic")
    ask.add_argument("--provider", choices=PROVIDERS, default="fake")
    golden = commands.add_parser("eval", help="Evaluar las preguntas doradas")
    golden.add_argument("--index", type=Path)
    golden.add_argument(
        "--golden", type=Path, default=Path(__file__).with_name("golden_questions.json")
    )
    golden.add_argument("--provider", choices=PROVIDERS, default="fake")
    golden.add_argument("--json", action="store_true", help="Resultado completo en JSON")
    for command in (lookup, ask, golden):
        command.add_argument("--embedder", choices=vector.EMBEDDERS, default="fake")
    args = parser.parse_args(argv)
    try:
        if args.command in ("search", "ask", "eval"):
            embedder = vector.EMBEDDERS[args.embedder]
            # Sin --index se usa PostgreSQL con recuperación vectorial (DATABASE_URL).
            source = args.index or database_session()
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
        elif args.command == "ingest-dir":
            settings = ChunkSettings(max_chars=args.chunk_size, overlap=args.overlap)
            result = ingest_folder(args.folder, settings, vector.EMBEDDERS[args.embedder])
        elif args.command == "ask":
            result = answer_question(
                source,
                args.question,
                PROVIDERS[args.provider],
                embedder=embedder,
                year=args.year,
                subject=args.subject,
                topic=args.topic,
            )
        elif args.command == "eval":
            questions = json.loads(args.golden.read_text(encoding="utf-8"))
            result = evaluate(source, questions, PROVIDERS[args.provider], embedder)
        elif args.index is None:
            result = vector.search(
                source,
                args.query,
                embedder,
                year=args.year,
                subject=args.subject,
                topic=args.topic,
                limit=args.limit,
            )
        else:
            result = search(
                args.index,
                args.query,
                year=args.year,
                subject=args.subject,
                topic=args.topic,
                limit=args.limit,
            )
    except (ValueError, OSError, sqlite3.Error, SQLAlchemyError) as exc:
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
    if args.command == "eval" and not args.json:
        print(eval_report(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "ingest-dir":
        return int(any(item["status"] == "error" for item in result))
    return 1 if args.command == "eval" and result["passed"] < result["total"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
