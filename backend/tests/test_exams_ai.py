"""CU-06: examen mixto con IA, citas verificadas, descarte de preguntas y PDF."""

import io
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_corpus
from alembic import command
from pypdf import PdfReader
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from test_corpus import get, upload
from test_models import BACKEND, TEST_DATABASE_URL, alembic_config

from app.exam_pdf import INSTITUTION
from app.models import Chunk, Document, Exam, Role
from app.models import Page as PageRow
from app.rag import exam
from app.rag.exam import generate_exam, load_passages, parse_questions, plan, points_and_minutes
from app.rag.rotation import ProviderError


def test_plan_covers_every_type_and_respects_selection():
    assert set(plan(10, None)) == {"multiple_choice", "true_false", "development", "case"}
    assert plan(10, None).count("case") >= 1
    assert plan(6, ["true_false", "case"]) == ["true_false"] * 3 + ["case"] * 3 or set(
        plan(6, ["true_false", "case"])
    ) == {"true_false", "case"}
    assert plan(3, ["development"]) == ["development"] * 3
    points, minutes = points_and_minutes(plan(7, None))
    assert round(sum(points), 6) == 10 and minutes % 5 == 0


def test_parse_questions_is_tolerant_but_never_invents():
    payload = {"questions": [{"kind": "development"}, "basura", 3]}
    fenced = "Aquí está:\n```json\n" + json.dumps(payload) + "\n```"
    assert parse_questions(fenced) == [{"kind": "development"}]
    assert parse_questions("sin json") == [] and parse_questions('{"questions": 5}') == []
    assert parse_questions('{"questions": [') == []


client, factory, pdfs = test_corpus.client, test_corpus.factory, test_corpus.pdfs

CORPUS = [
    "La propiedad confiere al titular facultades de uso, disfrute y disposición del bien.",
    "La posesión de buena fe se presume mientras no se pruebe lo contrario.",
    "El usufructo concede el derecho de disfrutar bienes ajenos con la obligación de conservarlos.",
    "Las servidumbres prediales gravan un fundo en beneficio de otro fundo vecino.",
    "La usucapión permite adquirir la propiedad mediante la posesión continuada y pacífica.",
    "El contrato obliga a las partes al cumplimiento de lo expresamente pactado.",
    "La obligación se extingue por pago, compensación, confusión o condonación de la deuda.",
    "El propietario puede reivindicar la cosa frente a cualquier poseedor sin título.",
    "La hipoteca recae sobre bienes inmuebles y asegura el cumplimiento de una obligación.",
    "La donación transmite gratuitamente la propiedad cuando el donatario la acepta.",
    "El comodato obliga al comodatario a devolver la cosa prestada tras el uso convenido.",
    "La responsabilidad civil exige reparar el daño causado por acción u omisión culpable.",
]


@pytest.fixture
def db(factory, pdfs, client):
    """Documento «manual» (Civil, 1.º) cuyo único texto son las frases de CORPUS, una por chunk."""
    assert upload(client, pdfs["muestra-b"], topic="Bienes").status_code == 201
    with factory() as session:
        document = session.get(Document, "manual")
        session.get(PageRow, ("manual", 1)).text = "\n".join(CORPUS)
        session.query(Chunk).filter_by(document_id="manual").delete()
        offset = 0
        for n, line in enumerate(CORPUS):
            end = offset + len(line)
            session.add(
                Chunk(
                    id=f"c{n}",
                    document_id="manual",
                    document_version=document.version,
                    page_number=1,
                    start_offset=offset,
                    end_offset=end,
                    text=line,
                )
            )
            offset = end + 1
        session.commit()
        yield session


def test_questions_without_verifiable_citation_are_discarded(db):
    passages = load_passages(db, year=1, subject="Civil", topic=None, count=3, rng=random.Random(0))
    real = passages[0]
    sentence = real["text"]
    valid = {"kind": "development", "statement": "P1", "answer": f"{sentence} [F1]"}
    invented = {"kind": "development", "statement": "P2", "answer": "El plazo es de 99 días. [F1]"}
    uncited = {"kind": "development", "statement": "P3", "answer": sentence}
    wrong_marker = {"kind": "development", "statement": "P4", "answer": f"{sentence} [F99]"}
    calls = []

    def provider(system, user, **_):
        calls.append(user)
        return json.dumps({"questions": [valid, invented, uncited, wrong_marker]})

    result = generate_exam(db, ["development"] * 2, passages, "easy", provider)
    assert [q["statement"] for q in result] == [
        "P1"
    ]  # solo una; la segunda llamada repite lo mismo
    assert len(calls) == 2  # un reintento acotado, no más
    assert "Tipos solicitados: development" in calls[1]
    [citation] = result[0]["citations"]
    assert citation["quote"] in real["text"]
    assert result[0]["answer"].endswith("[1]")


def test_retry_asks_only_for_missing_questions_after_invalid_json(db):
    passages = load_passages(db, year=1, subject="Civil", topic=None, count=2, rng=random.Random(0))
    replies = iter(["Lo siento, no puedo", exam.fake_provider])

    def provider(system, user, **_):
        reply = next(replies)
        return reply if isinstance(reply, str) else reply(system, user)

    result = generate_exam(db, ["multiple_choice", "true_false"], passages, "medium", provider)
    assert [q["kind"] for q in result] == ["multiple_choice", "true_false"]
    assert result[0]["answer"].startswith("Opción correcta: ")
    assert result[1]["answer"].startswith(("Verdadero.", "Falso."))
    assert len(result[0]["options"]) == 4


def test_malformed_test_questions_are_dropped(db):
    passages = load_passages(db, year=1, subject="Civil", topic=None, count=2, rng=random.Random(0))
    sentence = passages[0]["text"]
    base = {"kind": "multiple_choice", "statement": "P", "answer": f"{sentence} [F1]"}
    bad = [
        base | {"options": ["a", "b", "c"], "correct": "A"},
        base | {"options": ["a", "b", "c", "c"], "correct": "A"},
        base | {"options": ["a", "b", "c", "d"], "correct": "E"},
    ]
    result = generate_exam(
        db, ["multiple_choice"], passages, "easy", lambda s, u, **_: json.dumps({"questions": bad})
    )
    assert result == []


def create_exam(client, **changes):
    body = {"year": 1, "subject": "Civil", "question_count": 6, "difficulty": "medium"} | changes
    response = client.post("/api/v1/exams", headers=client.headers_for[Role.STUDENT], json=body)
    assert response.status_code == 202, response.json()
    return get(client, f"/exams/{response.json()['id']}", Role.STUDENT).json()


def test_exam_is_pending_then_ready_and_pdfs_are_409_while_pending(client, db, monkeypatch):
    from app.api import run_exam

    jobs = []
    monkeypatch.setattr("app.api.run_exam", lambda *args: jobs.append(args))  # sin ejecutar aún
    body = {"year": 1, "subject": "Civil", "question_count": 4, "difficulty": "easy"}
    response = client.post("/api/v1/exams", headers=client.headers_for[Role.STUDENT], json=body)
    assert response.status_code == 202
    path = f"/exams/{response.json()['id']}"
    pending = get(client, path, Role.STUDENT).json()
    assert (pending["status"], pending["error"], pending["questions"]) == ("pending", None, [])
    for suffix in ("pdf", "answers/pdf"):
        assert get(client, f"{path}/{suffix}", Role.STUDENT).status_code == 409
    run_exam(*jobs[0])
    ready = get(client, path, Role.STUDENT).json()
    assert ready["status"] == "ready" and len(ready["questions"]) == 4
    for suffix in ("pdf", "answers/pdf"):
        assert get(client, f"{path}/{suffix}", Role.STUDENT).status_code == 200


def test_provider_failure_marks_exam_failed_with_readable_message(client, db, monkeypatch):
    def broken(*args):
        raise ProviderError("caída del proveedor")

    monkeypatch.setattr("app.exams.generate_exam", broken)
    failed = create_exam(client)
    assert failed["status"] == "failed" and failed["questions"] == []
    assert "no está disponible" in failed["error"] and "caída" not in failed["error"]
    assert get(client, f"/exams/{failed['id']}/pdf", Role.STUDENT).status_code == 409


def test_stale_pending_exam_is_reported_failed(client, db, factory, monkeypatch):
    monkeypatch.setattr("app.api.run_exam", lambda *args: None)
    body = {"year": 1, "subject": "Civil", "question_count": 2, "difficulty": "easy"}
    response = client.post("/api/v1/exams", headers=client.headers_for[Role.STUDENT], json=body)
    exam_id = response.json()["id"]
    with factory() as session:
        session.get(Exam, exam_id).created_at = datetime.now(UTC) - timedelta(minutes=11)
        session.commit()
    listed = get(client, "/exams", Role.STUDENT).json()
    assert listed[0]["status"] == "failed" and "interrumpió" in listed[0]["error"]


def pdf_text(response) -> str:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)


def test_student_pdf_has_exam_format_and_no_solutions_and_key_has_them(client, db):
    created = create_exam(client, topic="Bienes")
    solutions = get(client, f"/exams/{created['id']}/answers", Role.STUDENT).json()

    student = pdf_text(get(client, f"/exams/{created['id']}/pdf", Role.STUDENT))
    flat = " ".join(student.split())
    assert "Universidad de Pinar del Río" in flat
    assert "Facultad de Ciencias Sociales y Humanísticas" in flat and "Carrera de Derecho" in flat
    for label in ("Asignatura: Civil", "Año: 1.º", "Tema: Bienes", "Fecha:", "Duración:"):
        assert label in flat
    assert f"{created['duration_minutes']} minutos" in flat
    assert "Nombre y apellidos" in flat and "Grupo" in flat and "Instrucciones generales" in flat
    assert "Puntuación total: 10 pts" in flat
    assert "Página 1 de" in flat
    for question in created["questions"]:
        assert question["statement"].splitlines()[0] in flat
    for solution in solutions:
        assert " ".join(solution["answer"].split())[:40] not in flat
        assert solution["criteria"] not in flat
    for secret in ("Opción correcta", "Criterio de corrección", "Fuentes", "CLAVE"):
        assert secret not in flat
    assert any(q["kind"] == "multiple_choice" for q in created["questions"])
    assert "A) " in flat and "Verdadero" in flat

    key = " ".join(
        pdf_text(get(client, f"/exams/{created['id']}/answers/pdf", Role.STUDENT)).split()
    )
    assert "CLAVE DE CORRECCIÓN" in key and "Criterio de corrección" in key
    for solution in solutions:
        assert " ".join(solution["answer"].split())[:40] in key
        assert solution["criteria"] in key
        for citation in solution["citations"]:
            page = citation["page_label"] or citation["page_number"]
            assert f"{citation['document_title']}, p. {page}" in key
    assert INSTITUTION.split(" · ")[0] in key


def test_pdf_access_is_limited_to_the_author(client, db):
    created = create_exam(client, question_count=2)
    for suffix in ("pdf", "answers/pdf"):
        path = f"/api/v1/exams/{created['id']}/{suffix}"
        assert client.get(path).status_code == 401
        assert get(client, f"/exams/{created['id']}/{suffix}", Role.TEACHER).status_code == 404
        assert get(client, f"/exams/{created['id']}/{suffix}", Role.ADMIN).status_code == 403
        assert get(client, f"/exams/9999/{suffix}", Role.STUDENT).status_code == 404
        assert get(client, f"/exams/{created['id']}/{suffix}", Role.STUDENT).status_code == 200


def test_pdf_renders_spanish_characters(client, db):
    created = create_exam(client, question_count=1)
    assert created["questions"][0]["kind"] == "case"
    text_ = pdf_text(get(client, f"/exams/{created['id']}/pdf", Role.STUDENT))
    for token in ("Río", "Humanísticas", "Duración", "¿Qué", "«Manual»", "Página", "1.º"):
        assert token in text_, token


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL")
def test_migration_0006_keeps_old_exams_readable(monkeypatch):
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config = alembic_config()
    command.upgrade(config, "0004")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, role) "
                    "VALUES (1, 'a@b.c', 'A', 'x', 'student')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO exams (id, user_id, year, subject, difficulty, question_count) "
                    "VALUES (1, 1, 1, 'Civil', 'easy', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO exam_questions (exam_id, position, statement, answer) "
                    "VALUES (1, 1, 'Completa el fragmento: «a […] b»', 'x')"
                )
            )
        command.upgrade(config, "0007")
        with sessionmaker(engine)() as session:
            from app.models import Exam

            [old] = session.get(Exam, 1).questions
            assert (old.kind, old.points, old.options, old.criteria) == (
                "completion",
                1,
                None,
                None,
            )
            assert session.get(Exam, 1).duration_minutes == 30
        command.downgrade(config, "0004")
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def test_fake_exam_pdf_examples_are_written_when_requested(client, db, tmp_path):
    """Sirve a la vez de prueba de humo y de generador de los ejemplos (variable de entorno)."""
    import os

    created = create_exam(client, question_count=8, topic="Bienes")
    folder = Path(os.environ.get("ATENEO_EXAM_SAMPLES", tmp_path))
    for name, suffix in (("examen-ejemplo.pdf", "pdf"), ("clave-ejemplo.pdf", "answers/pdf")):
        response = get(client, f"/exams/{created['id']}/{suffix}", Role.STUDENT)
        assert response.status_code == 200
        (folder / name).write_bytes(response.content)
