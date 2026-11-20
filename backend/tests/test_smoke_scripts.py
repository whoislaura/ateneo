"""infra/demo_corpus.py e infra/smoke.py (flujo autenticado) contra la app en proceso.

Mismo entorno que test_corpus: SQLite en memoria y búsqueda por términos en lugar de pgvector.
"""

import io
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest
from test_corpus import factory  # noqa: F401  (fixture)
from test_queries import PASSWORD, make_client

from app.main import app

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))
import demo_corpus  # noqa: E402
import smoke  # noqa: E402

BASE = "http://ateneo.test"
EMAIL = "teacher@ateneo.cu"


class Response(io.BytesIO):
    def __init__(self, status, body, headers):
        super().__init__(body)
        self.status, self.headers = status, headers


class Opener:
    """Traduce las peticiones de urllib a un TestClient."""

    def __init__(self, client):
        self.client = client

    def open(self, request, timeout):
        response = self.client.request(
            request.get_method(),
            request.full_url.removeprefix(BASE),
            content=request.data,
            headers=dict(request.header_items()),
        )
        if response.status_code >= 400:
            body = io.BytesIO(response.content)
            raise HTTPError(request.full_url, response.status_code, "", response.headers, body)
        return Response(response.status_code, response.content, response.headers)


@pytest.fixture
def opener(factory, monkeypatch):  # noqa: F811
    with make_client(factory) as client:
        monkeypatch.setattr(smoke, "opener", Opener(client))
        yield
    app.dependency_overrides.clear()


def test_demo_corpus_is_idempotent_and_smoke_passes(opener, tmp_path, capsys):
    demo_corpus.load(BASE, EMAIL, PASSWORD, tmp_path / "a")
    assert "subido" in capsys.readouterr().out
    demo_corpus.load(BASE, EMAIL, PASSWORD, tmp_path / "b")
    output = capsys.readouterr().out
    assert output.count("sustituido") == 2 and "muestra-c" not in output

    smoke.check_authenticated(BASE, EMAIL, PASSWORD)
    output = capsys.readouterr().out
    assert "FAIL" not in output and "OK   token revocado" in output
    assert PASSWORD not in output


def test_smoke_fails_with_clear_step_without_corpus(opener, capsys):
    with pytest.raises(SystemExit) as exit_info:
        smoke.check_authenticated(BASE, EMAIL, PASSWORD)
    assert exit_info.value.code == 1
    assert "FAIL listar documentos: falta muestra-a" in capsys.readouterr().out


def test_demo_corpus_requires_url_and_credentials(monkeypatch):
    monkeypatch.delenv("ATENEO_SMOKE_PASSWORD", raising=False)
    monkeypatch.setattr(sys, "argv", ["demo_corpus.py", BASE])
    with pytest.raises(SystemExit, match="Uso:"):
        demo_corpus.main()
