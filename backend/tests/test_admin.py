"""Panel de administración (/api/v1/admin) con SQLite en memoria."""

import json
import logging
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_queries import PASSWORD, VERSION, make_client

from app.main import app
from app.models import (
    Answer,
    AnswerKind,
    AnswerStatus,
    Base,
    Citation,
    Difficulty,
    Document,
    DocumentStatus,
    Exam,
    Feedback,
    FeedbackKind,
    Page,
    PageStatus,
    Role,
    User,
)

ADMIN = "/api/v1/admin"
ROUTES = [
    ("get", "/stats"),
    ("get", "/users"),
    ("post", "/users"),
    ("patch", "/users/1"),
    ("post", "/users/1/password"),
    ("delete", "/users/1/sessions"),
    ("get", "/answers"),
    ("get", "/answers/1"),
    ("get", "/feedback"),
    ("get", "/logs"),
]


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(engine)


@pytest.fixture
def client(factory):
    with make_client(factory) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def user_id(factory, role: Role) -> int:
    with factory() as db:
        return db.query(User).filter_by(email=f"{role.value}@ateneo.cu").one().id


def login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def seed_activity(factory) -> dict[str, int]:
    """Dos documentos (uno retirado), tres respuestas, un examen y dos feedback."""
    student, teacher = user_id(factory, Role.STUDENT), user_id(factory, Role.TEACHER)
    old = datetime.now(UTC) - timedelta(days=8)
    with factory() as db:
        for doc_id, doc_status, pages in (
            ("doc", DocumentStatus.PARTIAL, [PageStatus.TEXT, PageStatus.NO_TEXT]),
            ("viejo", DocumentStatus.RETIRED, [PageStatus.TEXT]),
        ):
            db.add(
                Document(
                    id=doc_id,
                    title=doc_id,
                    filename=f"{doc_id}.pdf",
                    version=VERSION,
                    year=1,
                    subject="Civil",
                    topic="Bienes",
                    status=doc_status,
                    chunk_settings={},
                    pages=[Page(number=n, text="Texto", status=s) for n, s in enumerate(pages, 1)],
                )
            )
        answered = Answer(
            user_id=student,
            kind=AnswerKind.QUERY,
            status=AnswerStatus.ANSWERED,
            question="¿Dónde aparece azafrán?",
            content="Texto [1].",
            citations=[
                Citation(
                    position=1,
                    document_id="doc",
                    document_title="doc",
                    document_version=VERSION,
                    page_number=1,
                    start_offset=0,
                    end_offset=5,
                    quote="Texto",
                )
            ],
        )
        empty = Answer(
            user_id=teacher,
            kind=AnswerKind.QUERY,
            status=AnswerStatus.NO_EVIDENCE,
            question="¿Nada?",
            content="Sin evidencia.",
        )
        summary = Answer(
            user_id=student,
            kind=AnswerKind.SUMMARY,
            status=AnswerStatus.NO_EVIDENCE,
            question="Resumen",
            content="Sin evidencia.",
            created_at=old,  # fuera de los últimos 7 días
        )
        exam = Exam(
            user_id=student,
            year=1,
            subject="Civil",
            difficulty=Difficulty.EASY,
            question_count=1,
        )
        db.add_all([answered, empty, summary, exam])
        db.flush()
        rating = Feedback(
            user_id=student, kind=FeedbackKind.RATING, rating=4, answer_id=answered.id
        )
        orphan = Feedback(user_id=None, kind=FeedbackKind.SUGGESTION, comment="Más temas.")
        db.add_all([rating, orphan])
        db.commit()
        return {"answered": answered.id, "empty": empty.id, "summary": summary.id}


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_admin_routes_are_admin_only(client, method, path):
    assert client.request(method, ADMIN + path).status_code == 401
    for role in (Role.STUDENT, Role.TEACHER):
        response = client.request(method, ADMIN + path, headers=client.headers_for[role])
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


def test_stats_counts(client, factory):
    seed_activity(factory)
    body = client.get(f"{ADMIN}/stats", headers=client.headers_for[Role.ADMIN]).json()
    assert body["users"] == {
        "total": 3,
        "active": 3,
        "by_role": {"student": 1, "teacher": 1, "admin": 1},
    }
    assert body["documents"] == {
        "total": 2,
        "active": 1,
        "retired": 1,
        "pages": 3,
        "pages_without_text": 1,
    }
    days = body["activity"].pop("last_7_days")
    assert body["activity"] == {
        "queries": 2,
        "generations": 1,
        "exams": 1,
        "feedback": 2,
        "no_evidence": 2,
    }
    today = datetime.now(UTC).date()
    assert [day["date"] for day in days] == [
        (today - timedelta(days=n)).isoformat() for n in range(6, -1, -1)
    ]
    assert days[-1] | {"date": None} == {"date": None, "queries": 2, "generations": 0, "exams": 1}
    assert all(day["queries"] == day["generations"] == day["exams"] == 0 for day in days[:-1])


def test_create_user(client, caplog):
    caplog.set_level(logging.INFO, "ateneo.admin")
    admin = client.headers_for[Role.ADMIN]
    body = {
        "email": " Nueva@Ateneo.cu",
        "full_name": "Nueva",
        "role": "teacher",
        "password": "otra-clave-larga",
    }
    response = client.post(f"{ADMIN}/users", json=body, headers=admin)
    assert response.status_code == 201
    created = response.json()
    assert created | {"id": 0, "created_at": None} == {
        "id": 0,
        "email": "nueva@ateneo.cu",
        "full_name": "Nueva",
        "role": "teacher",
        "is_active": True,
        "created_at": None,
        "active_sessions": 0,
    }
    assert login(client, "nueva@ateneo.cu", "otra-clave-larga").status_code == 200

    duplicate = client.post(
        f"{ADMIN}/users", json=body | {"email": "NUEVA@ateneo.cu"}, headers=admin
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"
    for changes in ({"password": "corta"}, {"email": "sin-arroba"}):
        response = client.post(f"{ADMIN}/users", json=body | changes, headers=admin)
        assert response.status_code == 422

    [record] = [r for r in caplog.records if r.getMessage() == "admin_action"]
    assert (record.action, record.target_user_id) == ("user_create", created["id"])
    assert "nueva@" not in caplog.text.lower() and "otra-clave-larga" not in caplog.text


def test_list_users_filters_and_counts_sessions(client, factory):
    admin = client.headers_for[Role.ADMIN]
    rows = client.get(f"{ADMIN}/users", headers=admin).json()
    assert len(rows) == 3 and all(row["active_sessions"] == 1 for row in rows)
    by_q = client.get(f"{ADMIN}/users", params={"q": "TEACH"}, headers=admin).json()
    assert [row["email"] for row in by_q] == ["teacher@ateneo.cu"]
    by_role = client.get(f"{ADMIN}/users", params={"role": "student"}, headers=admin).json()
    assert [row["role"] for row in by_role] == ["student"]
    page = client.get(f"{ADMIN}/users", params={"limit": 1, "offset": 1}, headers=admin).json()
    assert page == [rows[1]]
    assert client.get(f"{ADMIN}/users", params={"limit": 101}, headers=admin).status_code == 422


def test_patch_user_rules(client, factory):
    admin = client.headers_for[Role.ADMIN]
    me = user_id(factory, Role.ADMIN)
    for change in ({"is_active": False}, {"role": "teacher"}):
        response = client.patch(f"{ADMIN}/users/{me}", json=change, headers=admin)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"
    assert client.patch(f"{ADMIN}/users/9999", json={}, headers=admin).status_code == 404

    student = user_id(factory, Role.STUDENT)
    response = client.patch(
        f"{ADMIN}/users/{student}", json={"full_name": "Alumna", "role": "teacher"}, headers=admin
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Alumna" and response.json()["role"] == "teacher"

    student_token = client.headers_for[Role.STUDENT]
    assert client.get("/api/v1/auth/me", headers=student_token).status_code == 200
    response = client.patch(f"{ADMIN}/users/{student}", json={"is_active": False}, headers=admin)
    assert response.json()["is_active"] is False and response.json()["active_sessions"] == 0
    assert client.get("/api/v1/auth/me", headers=student_token).status_code == 401
    assert login(client, "student@ateneo.cu").status_code == 401

    # Con otro admin activo, sí se puede retirar el rol a uno de ellos.
    other = client.post(
        f"{ADMIN}/users",
        json={"email": "b@ateneo.cu", "full_name": "B", "role": "admin", "password": PASSWORD},
        headers=admin,
    ).json()
    response = client.patch(f"{ADMIN}/users/{other['id']}", json={"role": "student"}, headers=admin)
    assert response.status_code == 200


def test_password_reset_revokes_sessions(client, factory):
    admin = client.headers_for[Role.ADMIN]
    student = user_id(factory, Role.STUDENT)
    path = f"{ADMIN}/users/{student}/password"
    assert client.post(path, json={"password": "corta"}, headers=admin).status_code == 422
    assert client.post(path, json={"password": "nueva-clave-1"}, headers=admin).status_code == 204
    assert (
        client.get("/api/v1/auth/me", headers=client.headers_for[Role.STUDENT]).status_code == 401
    )
    assert login(client, "student@ateneo.cu").status_code == 401
    assert login(client, "student@ateneo.cu", "nueva-clave-1").status_code == 200
    response = client.post(
        f"{ADMIN}/users/9999/password", json={"password": "nueva-clave-1"}, headers=admin
    )
    assert response.status_code == 404


def test_revoke_sessions(client, factory):
    admin = client.headers_for[Role.ADMIN]
    teacher = user_id(factory, Role.TEACHER)
    assert client.delete(f"{ADMIN}/users/{teacher}/sessions", headers=admin).status_code == 204
    assert (
        client.get("/api/v1/auth/me", headers=client.headers_for[Role.TEACHER]).status_code == 401
    )
    [row] = client.get(f"{ADMIN}/users", params={"role": "teacher"}, headers=admin).json()
    assert row["active_sessions"] == 0
    assert client.delete(f"{ADMIN}/users/9999/sessions", headers=admin).status_code == 404


def test_answers_listing_and_detail(client, factory):
    ids = seed_activity(factory)
    admin = client.headers_for[Role.ADMIN]
    rows = client.get(f"{ADMIN}/answers", headers=admin).json()
    assert [row["id"] for row in rows] == [ids["empty"], ids["answered"], ids["summary"]]
    first = next(row for row in rows if row["id"] == ids["answered"])
    assert first | {"created_at": None} == {
        "id": ids["answered"],
        "kind": "query",
        "status": "answered",
        "question": "¿Dónde aparece azafrán?",
        "user": {
            "id": user_id(factory, Role.STUDENT),
            "email": "student@ateneo.cu",
            "full_name": "student",
        },
        "citations": 1,
        "created_at": None,
    }

    def ids_for(**params):
        response = client.get(f"{ADMIN}/answers", params=params, headers=admin)
        return [row["id"] for row in response.json()]

    assert ids_for(kind="summary") == [ids["summary"]]
    assert ids_for(status="no_evidence") == [ids["empty"], ids["summary"]]
    assert ids_for(user_id=user_id(factory, Role.TEACHER)) == [ids["empty"]]
    assert ids_for(limit=1, offset=1) == [ids["answered"]]

    detail = client.get(f"{ADMIN}/answers/{ids['answered']}", headers=admin).json()
    assert detail["citations"][0]["quote"] == "Texto" and detail["content"] == "Texto [1]."
    assert client.get(f"{ADMIN}/answers/9999", headers=admin).status_code == 404


def test_feedback_listing(client, factory):
    ids = seed_activity(factory)
    admin = client.headers_for[Role.ADMIN]
    rows = client.get(f"{ADMIN}/feedback", headers=admin).json()
    assert [row["kind"] for row in rows] == ["suggestion", "rating"]
    assert rows[0]["user"] is None and rows[0]["comment"] == "Más temas."
    assert rows[1] | {"id": 0, "created_at": None} == {
        "id": 0,
        "kind": "rating",
        "rating": 4,
        "comment": None,
        "answer_id": ids["answered"],
        "exam_id": None,
        "user": {
            "id": user_id(factory, Role.STUDENT),
            "email": "student@ateneo.cu",
            "full_name": "student",
        },
        "created_at": None,
    }
    rated = client.get(f"{ADMIN}/feedback", params={"kind": "rating"}, headers=admin).json()
    assert [row["kind"] for row in rated] == ["rating"]


def test_logs_show_recent_entries_without_secrets(client):
    admin = client.headers_for[Role.ADMIN]
    secret = "clave-que-no-debe-salir"
    assert login(client, "student@ateneo.cu", secret).status_code == 401
    logging.getLogger("ateneo.test").error("fallo de prueba")

    entries = client.get(f"{ADMIN}/logs", headers=admin).json()
    assert secret not in json.dumps(entries)
    failed = next(
        e for e in entries if e.get("path") == "/api/v1/auth/login" and e["status"] == 401
    )
    assert failed["method"] == "POST" and failed["request_id"]
    stamps = [e["ts"] for e in entries]
    assert stamps == sorted(stamps, reverse=True)

    errors = client.get(f"{ADMIN}/logs", params={"level": "ERROR"}, headers=admin).json()
    assert errors and {e["level"] for e in errors} <= {"ERROR", "CRITICAL"}
    assert errors[0]["message"] == "fallo de prueba"
    found = client.get(f"{ADMIN}/logs", params={"q": failed["request_id"]}, headers=admin).json()
    assert [e["request_id"] for e in found] == [failed["request_id"]]
    assert len(client.get(f"{ADMIN}/logs", params={"limit": 1}, headers=admin).json()) == 1
    assert client.get(f"{ADMIN}/logs", params={"limit": 501}, headers=admin).status_code == 422
    assert client.get(f"{ADMIN}/logs", params={"level": "DEBUG"}, headers=admin).status_code == 422


def test_stats_last_7_days_groups_in_sql_by_utc_day(client, factory):
    midnight = datetime.combine(datetime.now(UTC).date(), time(), UTC)
    with factory() as db:
        for created, kind in (
            (midnight - timedelta(seconds=1), AnswerKind.QUERY),  # ayer 23:59:59 UTC
            (midnight - timedelta(seconds=2), AnswerKind.SUMMARY),
            (midnight - timedelta(days=7, seconds=1), AnswerKind.QUERY),  # fuera de la ventana
        ):
            db.add(
                Answer(
                    user_id=user_id(factory, Role.STUDENT),
                    kind=kind,
                    status=AnswerStatus.NO_EVIDENCE,
                    question="q",
                    content="c",
                    citations=[],
                    created_at=created,
                )
            )
        db.commit()
    body = client.get(f"{ADMIN}/stats", headers=client.headers_for[Role.ADMIN]).json()
    yesterday = (midnight - timedelta(days=1)).date().isoformat()
    [day] = [d for d in body["activity"]["last_7_days"] if d["date"] == yesterday]
    assert (day["queries"], day["generations"]) == (1, 1)
