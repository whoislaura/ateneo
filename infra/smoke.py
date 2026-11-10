"""Comprueba el stack arrancado: python infra/smoke.py [URL]."""

import json
import os
import subprocess
import sys
from urllib.request import urlopen


def main():
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
    with urlopen(base_url, timeout=10) as response:
        assert response.status == 200
        assert "Ateneo" in response.read().decode()
    with urlopen(f"{base_url}/api/v1/health", timeout=10) as response:
        assert response.status == 200
        assert json.load(response) == {"status": "ok"}
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
    print("Smoke OK: web, API y pgvector disponibles.")


if __name__ == "__main__":
    main()
