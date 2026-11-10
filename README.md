# Ateneo

Asistente académico para la carrera de Licenciatura en Derecho de la Universidad de Pinar del Río. El MVP cubrirá **consultar → sintetizar → practicar** usando bibliografía oficial y citas verificables.

Esta base de Sprint 0 incluye una página inicial, API de salud, PostgreSQL/pgvector, contenedores y CI. Las funciones académicas aún están pendientes.

## Inicio con Docker (recomendado)

Instalar Git y Docker Engine con Compose v2 (Docker Desktop con contenedores Linux en Windows). Desde PowerShell:

```powershell
git clone https://github.com/whoislaura/ateneo.git
Set-Location ateneo
Copy-Item .env.example .env
docker compose up --build --wait
```

Abrir http://localhost:8080. La página debe indicar «Conexión disponible». La API responde en http://localhost:8080/api/v1/health. Detener con `docker compose down`; el volumen de PostgreSQL se conserva.

El archivo `.env` inicial usa una contraseña exclusivamente local. PostgreSQL y la API no publican puertos al host; el sitio escucha únicamente en loopback. El acceso remoto y HTTPS se definirán con el servidor institucional.

## Desarrollo sin Docker

Requisitos: Node.js 24, Python 3.12 y uv. uv puede instalar Python 3.12 automáticamente si falta. PostgreSQL no es necesario para la página inicial ni para el endpoint de salud.

Terminal 1, desde la raíz:

```powershell
uv sync --frozen --project backend
uv run --project backend uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1
```

Terminal 2:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Abrir la URL que imprima Vite (normalmente http://localhost:5173). Vite reenvía `/api` al backend local; no se necesitan claves IA.

## Comprobaciones

Desde la raíz:

```powershell
uv run --project backend ruff check backend infra/smoke.py
uv run --project backend pytest backend/tests
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Con el stack Docker arrancado y Python disponible:

```powershell
python infra/smoke.py
```

CI ejecuta estas comprobaciones y construye los contenedores. Los checks requeridos se llaman `Backend`, `Frontend` y `Containers and smoke`.

## Ingestión de muestra (Sprint 0)

Disponible el recorrido PDF → páginas → fragmentos → búsqueda textual local. La [guía de ingestión](docs/ingestion.md) incluye comandos PowerShell, metadatos, ejemplo reproducible y límites. Los archivos de muestra son ficticios y no requieren claves IA ni Docker.

## Organización

- `backend/`: FastAPI; Pedro dirige API/modelo y Laura `app/rag/`.
- `frontend/`: React/TypeScript/Vite, a cargo de Ray.
- `infra/`: inicialización pgvector y smoke test; Laura en Sprint 0, Pedro desde Sprint 1.
- `docs/`: alcance, tareas, arquitectura y despliegue.

Consultar [colaboración](CONTRIBUTING.md), [backlog](docs/backlog.md), [issues en GitHub](docs/github-issues.md), [arquitectura](docs/architecture.md), [alcance](docs/scope.md) y [despliegue](docs/deployment.md).

## Contenido y propiedad

No subir PDFs del corpus, índices, datos de usuarios ni secretos. No se ha otorgado una licencia de uso del código; su licencia se acordará con el titular del proyecto.
