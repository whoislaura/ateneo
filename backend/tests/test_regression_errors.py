"""Regresión: solo los fallos del proveedor y de red dan 503; el resto de ValueError, 500."""

# ruff: noqa: F811  (fixtures `client` y `factory` importadas de test_queries)

from app import query
from app.rag.rotation import ProviderError
from tests.test_queries import ask, client, factory  # noqa: F401


def fail_with(monkeypatch, error):
    def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(query, "ask", boom)


def test_provider_and_network_errors_are_503(client, monkeypatch):
    for error in (ProviderError("Respuesta inválida del proveedor"), OSError("red")):
        fail_with(monkeypatch, error)
        assert ask(client, question="¿Qué conserva la biblioteca?").status_code == 503


def test_internal_value_error_is_500(client, monkeypatch):
    fail_with(monkeypatch, ValueError("ATENEO_RETRIEVAL debe ser text, hybrid o vector."))
    assert ask(client, question="¿Qué conserva la biblioteca?").status_code == 500
