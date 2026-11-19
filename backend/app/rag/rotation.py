"""Cuentas IA rotativas: `<PREFIJO>_API_KEYS` (separadas por comas) o `<PREFIJO>_API_KEY`.

Ante 429, 5xx, timeout o fallo de red se reintenta con la clave siguiente; tras
`max(claves, 2)` intentos se relanza el último error (la API responde 503).
Las claves nunca se registran: solo su posición en la lista.
"""

import functools
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
        return error.code == 429 or error.code >= 500
    return isinstance(error, (URLError, TimeoutError))


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
            except (URLError, TimeoutError) as error:
                _next[prefix] = index + 1
                if not transient(error) or attempt == attempts - 1:
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
