"""Cuentas IA rotativas: `<PREFIJO>_API_KEYS` (separadas por comas) o `<PREFIJO>_API_KEY`.

Ante 401/402/403 (clave revocada o sin saldo), 429, 5xx o fallo de red se reintenta con la
clave siguiente; tras `max(claves, 2)` intentos se relanza el último error (la API responde 503).
Tras un timeout no se reintenta: otro intento superaría los 120 s de Nginx.
Las claves nunca se registran: solo su posición en la lista.
"""

import functools
import http.client
import logging
import os
from urllib.error import HTTPError, URLError

log = logging.getLogger("ateneo.ai")
# Posición de la próxima clave por prefijo; una carrera entre hilos solo cambia el orden.
_next: dict[str, int] = {}


def api_keys(prefix: str) -> list[str]:
    raw = os.environ.get(f"{prefix}_API_KEYS") or os.environ.get(f"{prefix}_API_KEY", "")
    return [key.strip() for key in raw.split(",") if key.strip()]


def transient(error: Exception) -> bool:
    if isinstance(error, HTTPError):
        return error.code in (401, 402, 403, 429) or error.code >= 500
    return isinstance(error, (URLError, TimeoutError, ConnectionError, http.client.HTTPException))


def timed_out(error: Exception) -> bool:
    return isinstance(error, TimeoutError) or isinstance(
        getattr(error, "reason", None), TimeoutError
    )


def rotating(call, prefix: str):
    """Envuelve `call(*args, key=...)`; sin claves, `call` explica qué variable falta."""

    @functools.wraps(call)
    def wrapper(*args):
        keys = api_keys(prefix)
        if not keys:
            return call(*args)
        attempts, first = max(len(keys), 2), _next.get(prefix, 0)
        for attempt in range(attempts):
            index = (first + attempt) % len(keys)
            try:
                result = call(*args, key=keys[index])
            except (URLError, TimeoutError, ConnectionError, http.client.HTTPException) as error:
                _next[prefix] = index + 1
                if not transient(error) or timed_out(error) or attempt == attempts - 1:
                    if isinstance(error, http.client.HTTPException):
                        # No es OSError: se traduce para que la API responda 503 y no 500.
                        raise URLError(f"{type(error).__name__}") from error
                    raise
                # shortcut: sin espera entre intentos; añadir backoff si el proveedor lo exige.
                log.warning(
                    "ai_retry",
                    extra={
                        "prefix": prefix,
                        "key_index": index,
                        "attempt": attempt + 1,
                        "error": getattr(error, "code", type(error).__name__),
                    },
                )
            else:
                _next[prefix] = index
                return result

    return wrapper
