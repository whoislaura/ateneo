import io
import json
from urllib.error import HTTPError

import pytest

from app.rag import answer, rotation, vector


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    monkeypatch.setattr(rotation, "_next", {})
    monkeypatch.setenv("ATENEO_LLM_API_KEYS", "clave-a, clave-b ,clave-c")
    monkeypatch.setenv("ATENEO_LLM_MODEL", "modelo")


def fake_urlopen(outcomes, used):
    """Cada llamada consume un resultado: un código HTTP de error, una excepción o "ok"."""

    def urlopen(request, timeout):
        used.append(request.get_header("Authorization").removeprefix("Bearer "))
        outcome = outcomes.pop(0)
        if isinstance(outcome, int):
            raise HTTPError(request.full_url, outcome, "error", {}, None)
        if isinstance(outcome, Exception):
            raise outcome
        reply = {"choices": [{"message": {"content": "respuesta"}}]}
        return io.BytesIO(json.dumps(reply).encode())

    return urlopen


def test_rotates_on_429_5xx_and_timeout_and_never_logs_keys(monkeypatch, caplog):
    used = []
    monkeypatch.setattr(answer.urllib.request, "urlopen", fake_urlopen([429, 503, "ok"], used))
    assert answer.PROVIDERS["openai"]("s", "u") == "respuesta"
    assert used == ["clave-a", "clave-b", "clave-c"]
    assert "clave" not in caplog.text and [r.key_index for r in caplog.records] == [0, 1]

    # La siguiente petición empieza por la última clave que funcionó.
    monkeypatch.setattr(
        answer.urllib.request, "urlopen", fake_urlopen([TimeoutError(), "ok"], used)
    )
    assert answer.PROVIDERS["openai"]("s", "u") == "respuesta"
    assert used[3:] == ["clave-c", "clave-a"]


def test_gives_up_after_one_attempt_per_key(monkeypatch):
    used = []
    monkeypatch.setattr(answer.urllib.request, "urlopen", fake_urlopen([500, 502, 504], used))
    # HTTPError es OSError: api.create_query lo traduce a 503.
    with pytest.raises(HTTPError) as error:
        answer.PROVIDERS["openai"]("s", "u")
    assert error.value.code == 504 and len(used) == 3


def test_single_key_retries_once(monkeypatch):
    monkeypatch.delenv("ATENEO_LLM_API_KEYS")
    monkeypatch.setenv("ATENEO_LLM_API_KEY", "unica")
    used = []
    monkeypatch.setattr(answer.urllib.request, "urlopen", fake_urlopen([429, "ok"], used))
    assert answer.PROVIDERS["openai"]("s", "u") == "respuesta"
    assert used == ["unica", "unica"]


def test_client_errors_are_not_retried(monkeypatch):
    used = []
    monkeypatch.setattr(answer.urllib.request, "urlopen", fake_urlopen([401], used))
    with pytest.raises(HTTPError):
        answer.PROVIDERS["openai"]("s", "u")
    assert used == ["clave-a"]


def test_without_keys_the_provider_explains_what_is_missing(monkeypatch):
    monkeypatch.delenv("ATENEO_LLM_API_KEYS")
    monkeypatch.delenv("ATENEO_LLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ATENEO_LLM_API_KEYS"):
        answer.PROVIDERS["openai"]("s", "u")


def test_embedder_rotates_too(monkeypatch):
    monkeypatch.setenv("ATENEO_EMBED_API_KEYS", "e1,e2")
    monkeypatch.setenv("ATENEO_EMBED_MODEL", "modelo")
    monkeypatch.setenv("ATENEO_EMBED_DIM", "2")
    used = []

    def urlopen(request, timeout):
        used.append(request.get_header("Authorization"))
        if len(used) == 1:
            raise HTTPError(request.full_url, 429, "error", {}, None)
        return io.BytesIO(json.dumps({"data": [{"index": 0, "embedding": [1.0, 0.0]}]}).encode())

    monkeypatch.setattr(vector.urllib.request, "urlopen", urlopen)
    assert vector.EMBEDDERS["openai"](["x"]) == [[1.0, 0.0]]
    assert used == ["Bearer e1", "Bearer e2"]
