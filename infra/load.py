"""Carga básica sin dependencias: python infra/load.py [URL] [--requests N] [--concurrency C].

Golpea /api/v1/health y, si existen ATENEO_LOAD_EMAIL y ATENEO_LOAD_PASSWORD, inicia sesión una
vez y envía consultas (POST /api/v1/queries). Cada consulta guarda una respuesta e historial:
usar un usuario de prueba y solo contra un entorno local o de prueba.
"""

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def call(url: str, body: dict | None = None, token: str | None = None) -> tuple[int, float]:
    """Devuelve (código HTTP o 0 si no hubo respuesta, segundos)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    start = time.perf_counter()
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=120) as response:
            response.read()
            code = response.status
    except HTTPError as error:
        code = error.code
    except (URLError, OSError):
        code = 0
    return code, time.perf_counter() - start


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def summary(name: str, results: list[tuple[int, float]], ok: set[int]) -> str:
    times = [seconds * 1000 for _, seconds in results]
    errors = sum(code not in ok for code, _ in results)
    codes = sorted({code for code, _ in results})
    return (
        f"{name}: {len(results)} peticiones, {errors} errores (códigos {codes}), "
        f"p50 {percentile(times, 0.5):.0f} ms, p95 {percentile(times, 0.95):.0f} ms, "
        f"p99 {percentile(times, 0.99):.0f} ms, máx {max(times):.0f} ms, "
        f"media {statistics.fmean(times):.0f} ms"
    )


def run(url: str, count: int, concurrency: int, body=None, token=None) -> list[tuple[int, float]]:
    with ThreadPoolExecutor(concurrency) as pool:
        return list(pool.map(lambda _: call(url, body, token), range(count)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", nargs="?", default="http://localhost:8080")
    parser.add_argument("--requests", type=int, default=100, help="Peticiones de salud")
    parser.add_argument("--queries", type=int, default=10, help="Consultas autenticadas")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--question", default="¿Qué conserva la biblioteca ficticia?")
    args = parser.parse_args(argv)
    api = args.base_url.rstrip("/") + "/api/v1"

    health = run(f"{api}/health", args.requests, args.concurrency)
    print(summary("GET /health", health, {200}))
    failed = any(code != 200 for code, _ in health)

    email, password = os.environ.get("ATENEO_LOAD_EMAIL"), os.environ.get("ATENEO_LOAD_PASSWORD")
    if not (email and password):
        print("Sin ATENEO_LOAD_EMAIL/ATENEO_LOAD_PASSWORD: se omiten login y consultas.")
        return int(failed)
    login = Request(
        f"{api}/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(login, timeout=30) as response:
            token = json.load(response)["access_token"]
    except (HTTPError, URLError, OSError) as error:
        print(f"Login fallido: {error}", file=sys.stderr)
        return 1
    queries = run(
        f"{api}/queries", args.queries, args.concurrency, {"question": args.question}, token
    )
    print(summary("POST /queries", queries, {201}))
    return int(failed or any(code != 201 for code, _ in queries))


if __name__ == "__main__":
    raise SystemExit(main())
