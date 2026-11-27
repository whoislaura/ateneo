"""Comprueba el stack arrancado: python infra/smoke.py [URL].

Con ATENEO_SMOKE_EMAIL y ATENEO_SMOKE_PASSWORD (cuenta de profesor) recorre además el flujo
autenticado sobre el corpus de muestra (ver infra/demo_corpus.py). Solo usa HTTP(S).
"""

import json
import os
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener

# Los tests lo sustituyen por un opener que envía las peticiones a la app en proceso.
opener = build_opener()
QUESTION = "¿Dónde aparece azafrán?"


def call(base_url, method, path, *, token=None, body=None, form=None, timeout=60):
    """Petición a la API; devuelve (código, JSON o None) sin lanzar por errores HTTP."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data, headers["Content-Type"] = multipart(form)
    request = Request(f"{base_url}/api/v1{path}", data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except HTTPError as error:
        status, raw = error.code, error.read()
    return status, json.loads(raw) if raw else None


def multipart(fields):
    """Codifica un formulario; un valor (nombre, bytes) es un archivo."""
    boundary = "ateneo-smoke-boundary"
    parts = []
    for name, value in fields.items():
        if isinstance(value, tuple):
            filename, content = value
            head = (
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                "Content-Type: application/pdf"
            )
        else:
            head, content = f'Content-Disposition: form-data; name="{name}"', str(value).encode()
        parts.append(f"--{boundary}\r\n{head}\r\n\r\n".encode() + content + b"\r\n")
    data = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return data, f"multipart/form-data; boundary={boundary}"


def expect(result, status, what):
    code, payload = result
    if code != status:
        detail = payload.get("error", {}).get("message", "") if isinstance(payload, dict) else ""
        raise AssertionError(f"{what} devolvió {code}, se esperaba {status}. {detail}".strip())
    return payload


def step(name, check):
    try:
        result = check()
    except Exception as error:  # noqa: BLE001  cualquier fallo del paso es un FAIL legible
        print(f"FAIL {name}: {error}")
        raise SystemExit(1) from None
    print(f"OK   {name}")
    return result


def login(base_url, email, password):
    body = {"email": email, "password": password}
    code, payload = call(base_url, "POST", "/auth/login", body=body)
    if code == 429:
        raise AssertionError("demasiados intentos de login; esperar a que acabe la ventana")
    return expect((code, payload), 200, "el login")["access_token"]


def logout(base_url, token):
    expect(call(base_url, "POST", "/auth/logout", token=token), 204, "el logout")


def check_authenticated(base_url, email, password):
    """Flujo de profesor sobre el corpus de muestra; termina cerrando la sesión."""
    token = step("login de profesor", lambda: login(base_url, email, password))

    def me():
        user = expect(call(base_url, "GET", "/auth/me", token=token), 200, "/auth/me")
        assert user["role"] in ("teacher", "admin"), f"rol {user['role']}, se esperaba teacher"

    def documents():
        listed = expect(call(base_url, "GET", "/documents", token=token), 200, "/documents")
        ids = {document["id"] for document in listed}
        assert "muestra-a" in ids, "falta muestra-a; cargarla con infra/demo_corpus.py"

    def query():
        answer = expect(
            call(base_url, "POST", "/queries", token=token, body={"question": QUESTION}),
            201,
            "la consulta",
        )
        assert answer["status"] == "answered", f"la consulta respondió {answer['status']}"
        assert any(c["quote"].strip() for c in answer["citations"]), "ninguna cita con texto"
        return answer["id"]

    def generation():
        body = {"format": "summary", "prompt": "azafrán"}
        result = call(base_url, "POST", "/generations", token=token, body=body)
        answer = expect(result, 201, "la generación")
        assert answer["status"] in ("answered", "no_evidence")

    def exam():
        body = {
            "year": 1,
            "subject": "Asignatura ficticia A",
            "question_count": 1,
            "difficulty": "easy",
        }
        created = expect(call(base_url, "POST", "/exams", token=token, body=body), 202, "el examen")
        for _ in range(60):  # la generación es asíncrona
            state = expect(
                call(base_url, "GET", f"/exams/{created['id']}", token=token), 200, "el examen"
            )
            if state["status"] != "pending":
                break
            time.sleep(2)
        assert state["status"] == "ready", f"examen no listo: {state['status']} {state['error']}"
        path = f"/exams/{created['id']}/answers"
        answers = expect(call(base_url, "GET", path, token=token), 200, "las soluciones")
        assert answers and all(a["citations"] for a in answers), "soluciones sin citas"

    def history():
        entries = expect(call(base_url, "GET", "/history", token=token), 200, "/history")
        assert any(e["answer_id"] == answer_id for e in entries), "la consulta no está"

    def feedback():
        body = {"kind": "rating", "rating": 5, "answer_id": answer_id}
        expect(call(base_url, "POST", "/feedback", token=token, body=body), 201, "el feedback")

    step("GET /auth/me", me)
    step("listar documentos", documents)
    answer_id = step("consulta con cita", query)
    step("generación (resumen)", generation)
    step("examen y soluciones", exam)
    step("historial con la consulta", history)
    step("feedback", feedback)
    step("logout", lambda: logout(base_url, token))
    step(
        "token revocado",
        lambda: expect(call(base_url, "GET", "/auth/me", token=token), 401, "/auth/me tras logout"),
    )


def wait_health(base_url, attempts=8, timeout=60):
    """Render duerme la API: la primera petición puede tardar alrededor de un minuto."""
    for attempt in range(attempts):
        try:
            code, payload = call(base_url, "GET", "/health", timeout=timeout)
            if code == 200:
                assert payload == {"status": "ok"}, f"salud inesperada: {payload}"
                return
        except (URLError, TimeoutError, ValueError):
            code = "sin respuesta"
        if attempt == attempts - 1:
            raise AssertionError(f"la salud devolvió {code}")
        time.sleep(10)


def check_web(base_url):
    with opener.open(base_url, timeout=60) as response:
        assert response.status == 200
        assert "Ateneo" in response.read().decode()
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


def check_login_401(base_url):
    # Un 401 JSON (no 500) prueba que la API llega a la base y que las migraciones corrieron.
    body = {"email": "smoke@example.com", "password": "no-existe"}
    payload = expect(call(base_url, "POST", "/auth/login", body=body), 401, "el login falso")
    assert payload["error"]["code"] == "unauthorized"


def check_upload_limit(base_url):
    # 2 MB supera el 1 MB por defecto de Nginx: debe llegar a la API (400/401/422), no 413.
    upload = Request(
        f"{base_url}/api/v1/documents",
        data=b"x" * (2 * 1024 * 1024),
        headers={"Content-Type": "multipart/form-data; boundary=smoke"},
    )
    try:
        opener.open(upload, timeout=60)
        raise AssertionError("la subida sin sesión fue aceptada")
    except HTTPError as error:
        expected = (400, 401, 422)
        assert error.code in expected, f"la subida devolvió {error.code}, se esperaba {expected}"


def check_pgvector():
    command = ["docker", "compose"]
    if env_file := os.environ.get("COMPOSE_ENV_FILE"):
        command += ["--env-file", env_file]
    command += [
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        (
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc '
            "\"SELECT extname FROM pg_extension WHERE extname = 'vector';\""
        ),
    ]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    assert result.stdout.strip() == "vector", "pgvector no está habilitado"


def main():
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    step("salud de la API", lambda: wait_health(base_url))
    step("web y cabeceras", lambda: check_web(base_url))
    step("login falso devuelve 401 (base migrada)", lambda: check_login_401(base_url))
    step("subida >1 MB llega a la API", lambda: check_upload_limit(base_url))
    # En remoto no hay docker ni acceso a PostgreSQL; el flujo autenticado ya ejercita pgvector.
    if urlparse(base_url).hostname in ("127.0.0.1", "localhost"):
        step("pgvector en la base (docker compose)", check_pgvector)
    email, password = os.environ.get("ATENEO_SMOKE_EMAIL"), os.environ.get("ATENEO_SMOKE_PASSWORD")
    if email and password:
        check_authenticated(base_url, email, password)
        print("Smoke OK: comprobaciones técnicas y flujo autenticado de profesor.")
    else:
        print("Smoke OK: web y cabeceras, API, subida >1 MB, base migrada (login 401) y pgvector.")


if __name__ == "__main__":
    main()
