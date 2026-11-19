"""Comprueba el stack arrancado: python infra/smoke.py [URL]."""

import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    with urlopen(base_url, timeout=10) as response:
        assert response.status == 200
        assert "Ateneo" in response.read().decode()
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
    with urlopen(f"{base_url}/api/v1/health", timeout=10) as response:
        assert response.status == 200
        assert json.load(response) == {"status": "ok"}
    # Un 401 JSON (no 500) prueba que la API llega a la base y que las migraciones corrieron.
    login = Request(
        f"{base_url}/api/v1/auth/login",
        data=json.dumps({"email": "smoke@example.com", "password": "no-existe"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urlopen(login, timeout=10)
        raise AssertionError("el login con credenciales falsas no devolvió 401")
    except HTTPError as error:
        assert error.code == 401, f"login devolvió {error.code}, se esperaba 401"
        assert json.load(error)["error"]["code"] == "unauthorized"
    # 2 MB supera el 1 MB por defecto de Nginx: debe llegar a la API (400/401/422), no 413.
    upload = Request(
        f"{base_url}/api/v1/documents",
        data=b"x" * (2 * 1024 * 1024),
        headers={"Content-Type": "multipart/form-data; boundary=smoke"},
    )
    try:
        urlopen(upload, timeout=10)
        raise AssertionError("la subida sin sesión fue aceptada")
    except HTTPError as error:
        assert error.code in (400, 401, 422), f"la subida devolvió {error.code}, se esperaba 400/401/422"
    command = ["docker", "compose"]
    if env_file := os.environ.get("COMPOSE_ENV_FILE"):
        command += ["--env-file", env_file]
    command += [
        "exec", "-T", "db", "sh", "-c",
        (
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc '
            '"SELECT extname FROM pg_extension WHERE extname = \'vector\';"'
        ),
    ]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    assert result.stdout.strip() == "vector", "pgvector no está habilitado"
    print("Smoke OK: web y cabeceras, API, subida >1 MB, base migrada (login 401) y pgvector.")


if __name__ == "__main__":
    main()
