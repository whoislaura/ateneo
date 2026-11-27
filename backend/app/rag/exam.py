"""CU-06: examen mixto generado con IA y respaldado por citas verificadas (mismo `cite_reply`).

Una sola llamada al proveedor devuelve el JSON con todas las preguntas: varias llamadas (una por
pregunta) superarían los 120 s del proxy. Si faltan preguntas (JSON inválido o preguntas sin cita
verificable) hay como mucho una segunda llamada, solo por las que faltan y solo si queda tiempo.
"""

import json
import random
import re
import time
from collections import Counter

from sqlalchemy import literal
from sqlalchemy.orm import Session

from app.models import Chunk, QuestionKind
from app.models import Document as DocumentRow
from app.rag import answer, vector
from app.rag.answer import (
    MARKER,
    SENTENCE,
    SEPARATOR,
    Provider,
    cite_reply,
    claim_in_line,
    release_connection,
)
from app.rag.generate import CITED
from app.rag.index import content_terms

KINDS = (
    QuestionKind.MULTIPLE_CHOICE,
    QuestionKind.TRUE_FALSE,
    QuestionKind.DEVELOPMENT,
    QuestionKind.CASE,
)
# Orden de reparto: con pocas preguntas empieza por el caso, luego domina el test.
PATTERN = (
    QuestionKind.CASE,
    QuestionKind.DEVELOPMENT,
    QuestionKind.MULTIPLE_CHOICE,
    QuestionKind.TRUE_FALSE,
    QuestionKind.MULTIPLE_CHOICE,
    QuestionKind.TRUE_FALSE,
    QuestionKind.DEVELOPMENT,
    QuestionKind.MULTIPLE_CHOICE,
    QuestionKind.TRUE_FALSE,
    QuestionKind.MULTIPLE_CHOICE,
)
WEIGHT = {"multiple_choice": 1, "true_false": 1.5, "development": 3, "case": 5}
MINUTES = {"multiple_choice": 2, "true_false": 3, "development": 10, "case": 20}
TOTAL_POINTS = 10
LETTERS = "ABCD"
MAX_CHARS = 24000
RETRY_BEFORE_SECONDS = 45  # la segunda llamada solo empieza si la primera tardó menos

SYSTEM_PROMPT = f"""Eres Ateneo, asistente académico de la Licenciatura en Derecho.
Redactas un examen en español usando únicamente los fragmentos del corpus que recibes.
{answer.RULES}
- Responde solo con un objeto JSON, sin texto antes ni después ni bloques de código:
{{"questions": [{{"kind": "...", "statement": "...", "options": ["...", "...", "...", "..."], \
"correct": "...", "answer": "...", "criteria": "..."}}]}}
- Genera exactamente una pregunta por cada tipo de la lista «Tipos solicitados», en ese orden.
- kind es uno de: multiple_choice, true_false, development, case.
- multiple_choice: statement es la pregunta; options son cuatro opciones plausibles, solo una \
correcta, sin letras delante; correct es la letra A, B, C o D; answer explica por qué es correcta.
- true_false: statement es una afirmación que se debe valorar y justificar; correct es true o \
false; answer es la justificación. Sin options.
- development: statement es una pregunta de desarrollo; answer es el modelo de respuesta, una idea \
por línea. Sin options ni correct.
- case: statement es un supuesto de hecho (hechos ficticios) seguido de dos o tres preguntas, una \
por línea con la forma «a) ...»; answer es la solución, una línea por pregunta con la forma \
«a) ...». Sin options ni correct.
- answer (en todos los tipos) se apoya en los fragmentos: cada línea termina con su marca [F1]. No \
pongas cifras en answer que no estén en los fragmentos.
- criteria: criterio de corrección en una o dos frases (qué ideas puntúan), sin marcas.
- El enunciado no debe revelar la respuesta. No repitas preguntas ni uses el mismo fragmento \
para todas.
- Dificultad: {{difficulty}}.
- Si los fragmentos no permiten preguntas, responde {{"questions": []}}."""

DIFFICULTY = {
    "easy": "baja (conceptos básicos y definiciones)",
    "medium": "media (aplicación de conceptos y relación entre ellos)",
    "hard": "alta (análisis, matices y excepciones)",
}


def plan(count: int, types: list[str] | None) -> list[str]:
    """Tipos de las `count` preguntas, en el orden del examen (test, V/F, desarrollo, caso)."""
    wanted = set(types or KINDS)
    pattern = [kind for kind in PATTERN if kind in wanted]
    chosen = [pattern[i % len(pattern)] for i in range(count)]
    return sorted(chosen, key=KINDS.index)


def points_and_minutes(kinds: list[str]) -> tuple[list[float], int]:
    """Puntuación por pregunta (suma exacta TOTAL_POINTS) y duración en múltiplos de 5 min."""
    total = sum(WEIGHT[k] for k in kinds)
    # Décimas enteras por el método del mayor resto: la suma es exactamente TOTAL_POINTS.
    shares = [TOTAL_POINTS * 10 * WEIGHT[k] / total for k in kinds]
    tenths = [int(share) for share in shares]
    by_remainder = sorted(range(len(kinds)), key=lambda i: tenths[i] - shares[i])
    for i in by_remainder[: TOTAL_POINTS * 10 - sum(tenths)]:
        tenths[i] += 1
    minutes = max(15, -(-sum(MINUTES[k] for k in kinds) // 5) * 5)
    return [t / 10 for t in tenths], minutes


def load_passages(
    db: Session, *, year: int, subject: str, topic: str | None, count: int, rng: random.Random
) -> list[dict]:
    """Fragmentos vigentes de la clasificación pedida, con la misma forma que `retrieve`.

    El examen se acota por año, asignatura y tema, no por una pregunta: se reparte la muestra
    entre todo el material y solo se baraja si hay más del que cabe en el contexto.
    """
    statement = vector.select_chunks(
        literal(0.0), year=year, subject=subject, topic=topic, limit=5000
    ).order_by(DocumentRow.id, Chunk.page_number, Chunk.start_offset)
    rows = [dict(row) for row in db.execute(statement).mappings()]
    rows = [r for r in rows if len(content_terms(r["text"])) >= 5]
    wanted = min(60, max(12, 2 * count))  # más preguntas, más material
    if len(rows) > wanted:
        rows = [rows[i] for i in sorted(rng.sample(range(len(rows)), wanted))]
    passages, used = [], 0
    for row in rows:
        if used + len(row["text"]) <= MAX_CHARS:
            used += len(row["text"])
            passages.append(row)
    return passages


def build_prompt(passages: list[dict], kinds: list[str]) -> str:
    base = answer.build_prompt("", passages).removesuffix(f"{SEPARATOR}Pregunta: ")
    return f"{base}{SEPARATOR}Tipos solicitados: {', '.join(kinds)}"


# --- Proveedor determinista (pruebas, CI y demo sin clave) ---


def fake_provider(system: str, user: str, *, max_tokens: int | None = None) -> str:
    """Un examen válido de cada tipo pedido; una oración distinta por pregunta (hasta agotarlas)."""
    body, _, wanted = user.rpartition(f"{SEPARATOR}Tipos solicitados: ")
    flat = []  # (marca, título, oración)
    for block in body.removeprefix("Fragmentos:\n").split(SEPARATOR):
        header, _, text = block.partition("\n")
        marker = MARKER.match(header)
        title = header[marker.end() :].strip().rsplit(", p.", 1)[0] if marker else ""
        flat += [
            (marker.group(0), title, s.strip())
            for s in SENTENCE.findall(text)
            if marker and len(content_terms(s)) >= 5 and not s.isupper()
        ]
    # Los fragmentos se solapan: una misma oración no debe dar dos preguntas.
    flat = list({sentence: (m, t, sentence) for m, t, sentence in reversed(flat)}.values())[::-1]
    distractors = (
        "La norma no regula esta materia.",
        "Solo se aplica a supuestos excepcionales.",
        "Depende exclusivamente de la voluntad de las partes.",
    )
    questions = []
    for i, kind in enumerate(wanted.split(", ")[: len(flat)]):
        marker, title, sentence = flat[i]
        cited = f"{sentence} {marker}"
        topic = " ".join(content_terms(sentence)[:4])
        if kind == "multiple_choice":
            options = list(distractors)
            options.insert(i % 4, sentence)
            question = {
                "statement": f"Según «{title}», ¿qué afirmación sobre {topic} es correcta?",
                "options": options,
                "correct": LETTERS[i % 4],
                "answer": cited,
            }
        elif kind == "true_false":
            true = i % 2 == 0
            statement = (
                sentence if true else f"No es cierto que {sentence[0].lower()}{sentence[1:]}"
            )
            question = {"statement": statement, "correct": true, "answer": cited}
        elif kind == "development":
            other = flat[(i + 1) % len(flat)]
            question = {
                "statement": f"Desarrolla el contenido de «{title}» sobre: {topic}.",
                "answer": f"{cited}\n{other[2]} {other[0]}",
            }
        else:
            other = flat[(i + 1) % len(flat)]
            question = {
                "statement": (
                    f"Supuesto de hecho: un ciudadano consulta a un letrado sobre {topic}.\n"
                    f"a) ¿Qué establece «{title}» al respecto?\n"
                    "b) ¿Qué consecuencia se deriva para el consultante?"
                ),
                "answer": f"a) {cited}\nb) {other[2]} {other[0]}",
            }
        criteria = "Puntúa recoger las ideas del modelo de respuesta con sus citas."
        questions.append({"kind": kind, **question, "criteria": criteria})
    return json.dumps({"questions": questions})


PROVIDERS: dict[str, Provider] = {"fake": fake_provider, "openai": answer.PROVIDERS["openai"]}

# --- Validación de la respuesta del modelo ---


def partial_questions(reply: str) -> list:
    """Objetos de `questions` completos antes del corte de un JSON truncado."""
    opening = re.search(r'"questions"\s*:\s*\[', reply)
    items, position, decoder = [], opening.end() if opening else len(reply), json.JSONDecoder()
    while match := re.compile(r"[\s,]*").match(reply, position):
        try:
            item, position = decoder.raw_decode(reply, match.end())
        except ValueError:
            break
        items.append(item)
    return items


def parse_questions(reply: str) -> list[dict]:
    """Extrae el objeto JSON (con o sin cercas de código) y descarta los elementos mal formados.

    Si el JSON está cortado (el modelo agotó `max_tokens`) recupera las preguntas ya cerradas.
    """
    start = reply.find("{")
    try:
        data, _ = json.JSONDecoder().raw_decode(reply[start:]) if start >= 0 else ([], 0)
    except ValueError:
        return [i for i in partial_questions(reply) if isinstance(i, dict)]
    items = data.get("questions") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def clean_item(item: dict, kind: str) -> dict | None:
    """Estructura mínima por tipo; None si no es válida."""
    statement, body = item.get("statement"), item.get("answer")
    if not (isinstance(statement, str) and statement.strip() and isinstance(body, str)):
        return None
    out = {"statement": statement.strip(), "body": re.sub(r"\[\d+\]", "", body).strip()}
    criteria = item.get("criteria")
    out["criteria"] = criteria.strip() if isinstance(criteria, str) and criteria.strip() else None
    out["options"], out["verdict"], out["correct_option"] = None, "", ""
    if kind == "multiple_choice":
        options = item.get("options")
        letter = str(item.get("correct", "")).strip().upper()[:1]
        if not (
            isinstance(options, list)
            and len(options) == 4
            and all(isinstance(o, str) and o.strip() for o in options)
            and len({o.strip().casefold() for o in options}) == 4
            and letter in LETTERS
        ):
            return None
        out["options"] = [o.strip() for o in options]
        out["correct_option"] = out["options"][LETTERS.index(letter)]
        out["verdict"] = f"Opción correcta: {letter}) {out['correct_option']}\n"
    elif kind == "true_false":
        value = str(item.get("correct", "")).strip().casefold()
        if value not in ("true", "false", "verdadero", "falso"):
            return None
        out["verdict"] = "Verdadero.\n" if value in ("true", "verdadero") else "Falso.\n"
    return out


def backed(text: str, quotes: str) -> bool:
    """El texto comparte al menos 2 términos de contenido (1 si tiene 2 o menos) con las citas."""
    terms = set(content_terms(text))
    return bool(terms) and len(terms & set(content_terms(quotes))) >= min(2, len(terms))


def cite_question(db: Session, passages: list[dict], clean: dict) -> dict | None:
    """Cita la solución como en CU-01 (modo estricto); None si alguna línea no se respalda."""
    cited = cite_reply(db, passages, clean["body"], claim_in_line)
    if cited.get("status") != "answered" or cited["invalid_citations"]:
        return None
    # La opción correcta y el veredicto V/F deben salir de lo citado, no solo del modelo.
    quotes = " ".join(c["quote"] for c in cited["citations"])
    if clean["options"] and not backed(clean["correct_option"], quotes):
        return None
    if clean["verdict"] and not clean["options"] and not backed(clean["statement"], quotes):
        return None
    lines = [line for line in cited["answer"].splitlines() if line.strip()]
    if not lines or not all(CITED.search(line) for line in lines):
        return None
    return {**clean, "answer": clean["verdict"] + cited["answer"], "citations": cited["citations"]}


def exam_tokens(count: int) -> int:
    return min(1000 + 700 * count, 16000)


def generate_exam(
    db: Session,
    kinds: list[str],
    passages: list[dict],
    difficulty: str,
    provider: Provider,
) -> list[dict]:
    """Preguntas válidas y citadas, en el orden de `kinds`; puede devolver menos de las pedidas."""
    system = SYSTEM_PROMPT.replace("{difficulty}", DIFFICULTY[difficulty])
    seen: set[str] = set()
    pending, found, started = Counter(kinds), {k: [] for k in KINDS}, time.monotonic()
    for attempt in range(2):
        if attempt and time.monotonic() - started > RETRY_BEFORE_SECONDS:
            break
        wanted = sorted(pending.elements(), key=KINDS.index)
        if not wanted:
            break
        release_connection(db)
        # Un examen largo no cabe en el tope de una consulta: proporcional a las preguntas.
        prompt, tokens = build_prompt(passages, wanted), exam_tokens(len(wanted))
        reply = provider(system, prompt, max_tokens=tokens)
        for item in parse_questions(reply):
            kind = item.get("kind")
            if kind not in pending or pending[kind] <= 0:
                continue
            clean = clean_item(item, kind)
            if clean is None or clean["body"].casefold() in seen:
                continue
            question = cite_question(db, passages, clean)
            if question:
                seen.add(clean["body"].casefold())
                found[kind].append(question | {"kind": kind})
                pending[kind] -= 1
    return [q for kind in KINDS for q in found[kind]]
