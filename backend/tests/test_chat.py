"""Chat con memoria: propiedad, seguimiento con contexto, paginación, historial y migración."""

# ruff: noqa: F811  (fixtures `client` y `factory` importadas de test_queries)
import pytest
from alembic import command
from sqlalchemy import create_engine, func, select
from test_models import BACKEND, TEST_DATABASE_URL, alembic_config
from test_queries import client, factory, make_client  # noqa: F401

from app.models import Answer, Citation, Conversation, HistoryEntry, Message, Role
from app.rag import answer, vector

FIRST = "¿Qué conserva la biblioteca?"
FOLLOW_UP = "¿Y el préstamo dura una semana o más?"


@pytest.fixture(autouse=True)
def only_library_questions(factory, monkeypatch):
    """La recuperación falsa solo encuentra el fragmento si la pregunta nombra la biblioteca."""
    real = vector.search

    def search(db, question, embedder, **filters):
        return real(db, question, embedder, **filters) if "biblioteca" in question else []

    monkeypatch.setattr(vector, "search", search)


def headers(client, role=Role.STUDENT):
    return client.headers_for[role]


def start(client, question=FIRST, role=Role.STUDENT):
    response = client.post(
        "/api/v1/conversations", json={"question": question}, headers=headers(client, role)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_follow_up_uses_previous_turns_as_context(client):
    first = start(client)
    conversation_id = first["conversation"]["id"]
    assert first["conversation"]["title"] == FIRST
    asked, reply = first["messages"]
    assert (asked["role"], asked["content"], asked["status"]) == ("user", FIRST, None)
    assert reply["role"] == "assistant" and reply["status"] == "answered"
    assert reply["citations"][0]["position"] == 1 and reply["content"].endswith("[1]")

    # Sin hilo, la pregunta de seguimiento no nombra la biblioteca: no hay evidencia.
    alone = client.post("/api/v1/queries", json={"question": FOLLOW_UP}, headers=headers(client))
    assert alone.json()["status"] == "no_evidence"

    second = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"question": FOLLOW_UP},
        headers=headers(client),
    )
    assert second.status_code == 201
    follow_up = second.json()["messages"][1]
    assert follow_up["status"] == "answered" and "semana" in follow_up["content"]

    detail = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers(client)).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
    assert detail["messages"][3]["citations"] == follow_up["citations"]
    assert detail["title"] == FIRST


def test_conversations_belong_to_their_owner(client, factory):
    conversation_id = start(client)["conversation"]["id"]
    url = f"/api/v1/conversations/{conversation_id}"
    other = headers(client, Role.TEACHER)
    assert client.get(url, headers=other).status_code == 404
    assert client.delete(url, headers=other).status_code == 404
    post = client.post(f"{url}/messages", json={"question": FIRST}, headers=other)
    assert post.status_code == 404
    assert client.get("/api/v1/conversations", headers=other).json() == []
    assert client.get(url, headers=headers(client, Role.ADMIN)).status_code == 403
    assert client.get(url).status_code == 401
    with factory() as db:  # el 404 no guardó nada en el hilo ajeno
        assert db.scalar(select(func.count()).select_from(Message)) == 2
    assert client.get(f"/api/v1/conversations/{2**31}", headers=other).status_code == 422


def test_conversations_are_paginated_most_recent_first(client):
    ids = [start(client, f"{FIRST} {n}")["conversation"]["id"] for n in range(3)]
    # Un mensaje nuevo sube la conversación más antigua al primer lugar.
    client.post(
        f"/api/v1/conversations/{ids[0]}/messages",
        json={"question": FOLLOW_UP},
        headers=headers(client),
    )

    def listing(query):
        response = client.get(f"/api/v1/conversations{query}", headers=headers(client))
        assert response.status_code == 200
        return [c["id"] for c in response.json()]

    assert listing("") == [ids[0], ids[2], ids[1]]
    assert listing("?limit=2") == [ids[0], ids[2]]
    assert listing("?limit=2&offset=2") == [ids[1]]
    assert listing("?offset=3") == []
    for query in ("?limit=0", "?limit=101", "?offset=-1"):
        assert (
            client.get(f"/api/v1/conversations{query}", headers=headers(client)).status_code == 422
        )


def test_conversations_appear_in_history_and_history_deletion_covers_them(client, factory):
    first, second = start(client)["conversation"]["id"], start(client, f"{FIRST} bis")
    entries = client.get("/api/v1/history", headers=headers(client)).json()
    assert [e["action"] for e in entries] == ["conversation", "conversation"]
    assert entries[1]["conversation_id"] == first and entries[1]["summary"] == FIRST

    deleted = client.delete(f"/api/v1/history/{entries[1]['id']}", headers=headers(client))
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/conversations/{first}", headers=headers(client)).status_code == 404
    remaining = client.get("/api/v1/conversations", headers=headers(client)).json()
    assert [c["id"] for c in remaining] == [second["conversation"]["id"]]

    client.post("/api/v1/queries", json={"question": FIRST}, headers=headers(client))
    assert client.delete("/api/v1/history", headers=headers(client)).status_code == 204
    assert client.get("/api/v1/history", headers=headers(client)).json() == []
    with factory() as db:
        for model in (Conversation, Message, Answer, Citation, HistoryEntry):
            assert db.scalar(select(func.count()).select_from(model)) == 0, model


def test_delete_conversation_removes_thread_answers_and_history(client, factory):
    conversation_id = start(client)["conversation"]["id"]
    url = f"/api/v1/conversations/{conversation_id}"
    assert client.delete(url, headers=headers(client)).status_code == 204
    assert client.get(url, headers=headers(client)).status_code == 404
    assert client.get("/api/v1/history", headers=headers(client)).json() == []
    with factory() as db:
        for model in (Conversation, Message, Answer, Citation):
            assert db.scalar(select(func.count()).select_from(model)) == 0, model


def test_provider_failure_saves_nothing(client, factory, monkeypatch):
    def failing(system, user):
        raise OSError("sin red")

    monkeypatch.setitem(answer.PROVIDERS, "fake", failing)
    response = client.post(
        "/api/v1/conversations", json={"question": FIRST}, headers=headers(client)
    )
    assert response.status_code == 503
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0


def test_validation(client):
    for body in ({}, {"question": ""}, {"question": "x" * 1001}, {"question": "a", "year": 9}):
        response = client.post("/api/v1/conversations", json=body, headers=headers(client))
        assert response.status_code == 422, body


# --- reformulación y prompt (sin base de datos) ---


def test_standalone_question_falls_back_when_the_provider_fails():
    history = [("user", FIRST), ("assistant", "Un catálogo [1].")]

    def failing(system, user):
        raise OSError

    assert answer.standalone_question(FOLLOW_UP, history, failing) == f"{FIRST} {FOLLOW_UP}"
    assert answer.standalone_question(FOLLOW_UP, history, lambda s, u: "  ") == (
        f"{FIRST} {FOLLOW_UP}"
    )
    assert answer.standalone_question(FOLLOW_UP, history, lambda s, u: "Pregunta\nlimpia") == (
        "Pregunta limpia"
    )
    assert answer.standalone_question(FOLLOW_UP, history, answer.fake_provider) == (
        f"{FIRST} {FOLLOW_UP}"
    )


def test_history_is_trimmed_and_reaches_the_answer_prompt():
    long = "palabra " * 200
    history = [("user", f"{n} {long}") for n in range(10)] + [("assistant", "Dice [3]\nhola")]
    trimmed = answer.trim_history(history)
    assert len(trimmed) == answer.HISTORY_MESSAGES
    assert all(len(text) <= answer.HISTORY_CHARS for _, text in trimmed)
    assert trimmed[-1] == ("assistant", "Dice hola")
    passage = {"title": "T", "page_number": 1, "text": "Texto."}
    prompt = answer.build_prompt("¿Pregunta?", [passage], trimmed)
    assert prompt.startswith("Conversación previa:\nUsuario: ")
    assert prompt.endswith("Pregunta: ¿Pregunta?") and "[F1] T, p. 1" in prompt
    assert "Conversación previa" not in answer.build_prompt("¿Pregunta?", [passage])


def test_chat_mode_uses_its_own_prompt_and_keeps_every_verified_sentence():
    assert "chat" in answer.MODES and answer.CHAT_PROMPT != answer.DEVELOPED_PROMPT
    user = "Fragmentos:\n[F1] T, p. 1\nLa ley protege bosques.\n---\nPregunta: ley bosques"
    assert answer.fake_provider(answer.CHAT_PROMPT, user) == "La ley protege bosques. [F1]"


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Requiere ATENEO_TEST_DATABASE_URL")
def test_migration_0005_downgrades_and_upgrades_again(monkeypatch):
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    config = alembic_config()
    command.upgrade(config, "head")
    try:
        command.downgrade(config, "0004")
        with create_engine(TEST_DATABASE_URL).connect() as connection:
            tables = set(
                connection.exec_driver_sql(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                ).scalars()
            )
            values = set(
                connection.exec_driver_sql(
                    "SELECT unnest(enum_range(NULL::history_action))::text"
                ).scalars()
            )
        assert not {"conversations", "messages"} & tables and "conversation" not in values
        command.upgrade(config, "head")
    finally:
        command.downgrade(config, "base")
