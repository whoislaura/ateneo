"""CU-02: resumen, esquema, cuadro comparativo y diagrama en texto con el pipeline de CU-01.

La estructura de cada formato (texto por líneas, con marcas [n]) está en docs/api-contract.md.
"""

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.rag import answer, vector
from app.rag.answer import (
    MARKER,
    NOT_FOUND,
    SENTENCE,
    SEPARATOR,
    Provider,
    build_prompt,
    cite_reply,
    claim_in_line,
    release_connection,
    retrieve,
)
from app.rag.index import content_terms

INSTRUCTIONS = {
    "summary": (
        "Escribe un resumen en uno o varios párrafos, uno por línea, sin títulos ni viñetas."
    ),
    "outline": (
        "Escribe un esquema jerárquico: una línea por elemento, con la forma «- elemento», "
        "sangrando dos espacios por nivel. Un elemento sin hijos debe llevar marca."
    ),
    "table": (
        "Escribe un cuadro comparativo como tabla Markdown: fila de encabezados, fila separadora "
        "«|---|---|» y una fila por aspecto comparado, todas con el mismo número de columnas "
        "(al menos dos). Cada fila de datos debe llevar marca. No uses «|» dentro de las celdas."
    ),
    "diagram": (
        "Escribe un diagrama en texto: una relación por línea con la forma "
        "«Origen -> Destino: relación [F1]» (la relación es opcional). "
        "Cada línea debe llevar marca."
    ),
}

SYSTEM_PROMPT = """Eres Ateneo, asistente académico de la Licenciatura en Derecho.
Genera material de estudio en español usando únicamente los fragmentos del corpus que recibes.
{rules}
- Responde solo con el material, sin introducción ni comentarios.
- Si los fragmentos no permiten generarlo, responde exactamente: {not_found}
Formato: {instructions}"""

CITED = re.compile(r"\[\d+\]")
OUTLINE_ITEM = re.compile(r"((?:  )*)- \S.*")
TABLE_SEPARATOR = re.compile(r":?-+:?")


def system_prompt(format: str) -> str:
    return SYSTEM_PROMPT.format(
        rules=answer.RULES, not_found=NOT_FOUND, instructions=INSTRUCTIONS[format]
    )


def fake_provider(system: str, user: str) -> str:
    """Determinista para pruebas y CI: hasta tres oraciones con más términos del tema."""
    format = next(name for name, text in INSTRUCTIONS.items() if text in system)
    body, _, topic = user.rpartition(f"{SEPARATOR}Pregunta: ")
    topic, wanted = " ".join(topic.split()), set(content_terms(topic))
    scored = []
    for block in body.removeprefix("Fragmentos:\n").split(SEPARATOR):
        header, _, text = block.partition("\n")
        marker = MARKER.match(header)
        for sentence in SENTENCE.findall(text):
            score = len(wanted & set(content_terms(sentence)))
            if marker and score:
                source = header[marker.end() :].strip()
                scored.append((-score, sentence.strip(), marker.group(0), source))
    best = sorted(scored, key=lambda item: item[0])[:3]
    if not best:
        return NOT_FOUND
    if format == "summary":
        return " ".join(f"{sentence} {marker}" for _, sentence, marker, _ in best)
    if format == "outline":
        return "\n".join([f"- {topic}"] + [f"  - {s} {m}" for _, s, m, _ in best])
    if format == "table":
        rows = [f"| {source} | {s} {m} |" for _, s, m, source in best]
        return "\n".join(["| Fuente | Contenido |", "|---|---|", *rows])
    return "\n".join(f"{topic} -> {source}: {s} {m}" for _, s, m, source in best)


# El proveedor real es el mismo de CU-01 (con su envoltorio de rotación de claves, si lo tiene).
PROVIDERS: dict[str, Provider] = {"fake": fake_provider, "openai": answer.PROVIDERS["openai"]}


def well_formed(format: str, content: str) -> bool:
    """Comprueba la estructura del formato y que cada elemento lleve al menos una marca [n]."""
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if not lines:
        return False
    if format == "summary":
        return all(CITED.search(line) for line in lines)
    if format == "outline":
        matches = [OUTLINE_ITEM.fullmatch(line) for line in lines]
        if not all(matches):
            return False
        levels = [len(m.group(1)) // 2 for m in matches] + [0]
        return levels[0] == 0 and all(
            levels[i + 1] <= levels[i] + 1 and (CITED.search(line) or levels[i + 1] > levels[i])
            for i, line in enumerate(lines)
        )
    if format == "table":
        rows = [line.strip() for line in lines]
        if len(rows) < 3 or not all(len(r) > 1 and r[0] == r[-1] == "|" for r in rows):
            return False
        cells = [[cell.strip() for cell in row[1:-1].split("|")] for row in rows]
        return (
            len(cells[0]) >= 2
            and all(cells[0])
            and all(len(row) == len(cells[0]) for row in cells)
            and all(TABLE_SEPARATOR.fullmatch(cell) for cell in cells[1])
            and all(CITED.search(row) for row in rows[2:])
        )
    if format == "diagram":
        return all(CITED.search(line) and re.fullmatch(r"\s*\S.*? -> \S.*", line) for line in lines)
    raise ValueError(f"Formato desconocido: {format}")


def generate_material(
    source: Path | Session,
    format: str,
    prompt: str,
    provider: Provider = fake_provider,
    *,
    embedder: vector.Embedder = vector.fake_embedder,
    year: int | None = None,
    subject: str | None = None,
    topic: str | None = None,
    limit: int = 5,
) -> dict:
    """Genera CU-02; mismo resultado que `answer_question` más `format` (y `error` si falla)."""
    instructions = system_prompt(format)
    passages = retrieve(
        source, prompt, embedder, year=year, subject=subject, topic=topic, limit=limit
    )
    result = {
        "question": prompt,
        "format": format,
        "status": "no_evidence",
        "answer": NOT_FOUND,
        "citations": [],
        "invalid_citations": [],
    }
    if not passages:
        return result
    release_connection(source)
    reply = re.sub(r"\[\d+\]", "", provider(instructions, build_prompt(prompt, passages)))
    cited = result | cite_reply(source, passages, reply, claim_in_line)
    if cited["status"] == "answered" and not well_formed(format, cited["answer"]):
        return result | {
            "invalid_citations": cited["invalid_citations"],
            "error": "La salida no sigue la estructura del formato.",
        }
    return cited
