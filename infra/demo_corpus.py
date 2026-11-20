"""Sube el corpus de muestra por la API: uv run --project backend python infra/demo_corpus.py URL.

Usa la cuenta de profesor de ATENEO_SMOKE_EMAIL y ATENEO_SMOKE_PASSWORD. Idempotente: si el
documento ya existe lo sustituye con PUT (misma versión, se reindexa igual). --con-inyeccion
añade muestra-c, el documento con una instrucción incrustada para las pruebas de QA.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

from smoke import call, expect, login, logout, step

# El backend no se instala como paquete: se importa desde su carpeta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def load(base_url, email, password, folder, include_injection=False):
    from app.rag.sample import create_sample

    names = ["muestra-a", "muestra-b"] + (["muestra-c"] if include_injection else [])
    files = {Path(item["pdf"]).stem: item for item in create_sample(folder)}
    token = step("login de profesor", lambda: login(base_url, email, password))
    for name in names:
        metadata = json.loads(Path(files[name]["metadata"]).read_text(encoding="utf-8"))
        document_id = metadata.pop("document_id")
        form = metadata | {"file": (f"{name}.pdf", Path(files[name]["pdf"]).read_bytes())}

        def upload(document_id=document_id, form=form):
            body = {"document_id": document_id} | form
            code, payload = call(base_url, "POST", "/documents", token=token, form=body)
            if code == 409:
                path = f"/documents/{document_id}"
                payload = expect(call(base_url, "PUT", path, token=token, form=form), 200, "PUT")
                return f"sustituido ({payload['status']}, {payload['chunks']} fragmentos)"
            payload = expect((code, payload), 201, "la subida")
            return f"subido ({payload['status']}, {payload['chunks']} fragmentos)"

        print(f"     {document_id}: {step(f'cargar {document_id}', upload)}")
    step("logout", lambda: logout(base_url, token))


def main():
    args = [arg for arg in sys.argv[1:] if arg != "--con-inyeccion"]
    email, password = os.environ.get("ATENEO_SMOKE_EMAIL"), os.environ.get("ATENEO_SMOKE_PASSWORD")
    if len(args) != 1 or not (email and password):
        raise SystemExit(
            "Uso: ATENEO_SMOKE_EMAIL=... ATENEO_SMOKE_PASSWORD=... "
            "uv run --project backend python infra/demo_corpus.py URL [--con-inyeccion]"
        )
    with tempfile.TemporaryDirectory() as folder:
        load(args[0].rstrip("/"), email, password, Path(folder), "--con-inyeccion" in sys.argv)
    print("Corpus de muestra cargado.")


if __name__ == "__main__":
    main()
