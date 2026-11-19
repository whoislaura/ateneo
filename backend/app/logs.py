"""Logs JSON por línea en stdout.

Solo se registran método, ruta (sin query string), estado, duración e id de petición:
nunca cuerpos, cabeceras, tokens, contraseñas ni el texto de las preguntas.
"""

import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime

from fastapi import Request

log = logging.getLogger("ateneo.request")
FIELDS = ("request_id", "method", "path", "status", "duration_ms")
EXTRA = (*FIELDS, "prefix", "key_index", "attempt", "error")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry |= {name: getattr(record, name) for name in EXTRA if hasattr(record, name)}
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup() -> None:
    """Todo a stdout en JSON, también los logs de uvicorn (su access log se desactiva)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True


async def request_logging(request: Request, call_next, on_error):
    """Middleware HTTP: id de petición, línea de log y 500 con el formato del contrato."""
    request_id = uuid.uuid4().hex
    start = time.perf_counter()
    fields = {"request_id": request_id, "method": request.method, "path": request.url.path}
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled_error", extra=fields)
        response = on_error(request_id)
    duration = round((time.perf_counter() - start) * 1000, 1)
    log.info("request", extra=fields | {"status": response.status_code, "duration_ms": duration})
    response.headers["X-Request-ID"] = request_id
    return response
