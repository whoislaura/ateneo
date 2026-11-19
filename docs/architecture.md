# Acuerdos técnicos iniciales

- Monorepositorio: backend Python 3.12/FastAPI y frontend React/TypeScript/Vite con Node.js 24.
- Dependencias reproducibles mediante `backend/uv.lock` y `frontend/package-lock.json`; cambios de dependencias se revisan en PR.
- PostgreSQL 17 con pgvector. La inicialización crea exclusivamente la extensión; las tablas se crean con las migraciones Alembic de Pedro.
- RAG e ingestión viven dentro de `backend/app/rag/`, a cargo de Laura. No se crea un microservicio adicional.
- Nginx sirve el frontend compilado y reenvía `/api/` a FastAPI. En desarrollo, Vite cumple esa función.

## Interfaz inicial

`GET /api/v1/health` devuelve HTTP 200 y `{"status":"ok"}`. Es una comprobación de vida de la API, independiente de PostgreSQL, corpus y proveedores IA. La página muestra comprobando, conexión disponible o error; cancela la consulta tras 10 segundos.

FastAPI genera OpenAPI en `/openapi.json` y documentación en `/docs` cuando se accede directamente a la API local. El proxy publicado inicialmente expone solo `/api/`; no publica la documentación interactiva.

## Contrato API y modelo de datos

El contrato `/api/v1` y el modelo PostgreSQL de usuarios/roles, documentos, páginas, chunks, citas, historial, exámenes y feedback están descritos en [contrato API](api-contract.md). Laura y Ray lo revisan antes de implementar integraciones. Las rutas responden 501 hasta su tarea de Sprint 1 o 2. El esquema se crea con migraciones Alembic en `backend/migrations/`. No se fija aún proveedor IA, modelo de embeddings ni dimensión vectorial; la columna de embeddings queda sin dimensión hasta AT-14. La estrategia inicial de chunking y su índice textual de muestra están descritos en [ingestión](ingestion.md).

## Contenedores

Compose arranca `db`, `api` y `web`. La API inicial no requiere conexión a la base. `web` espera la salud de `api`; `docker compose up --wait` espera también la salud de `db`. El smoke test comprueba la web, el JSON de salud a través del proxy y la extensión vector en la base.

El script SQL se ejecuta al crear un volumen vacío. Las modificaciones futuras de esquema necesitan migraciones; reiniciar un volumen existente no vuelve a ejecutar el script.

## Dependencias de desarrollo

Se fija temporalmente `minimatch` a 11.0.1 mediante `overrides` para resolver [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249) en las dependencias de ESLint. Retirar el override cuando ESLint y typescript-eslint incorporen la corrección en sus rangos. La compatibilidad se comprueba con lint, TypeScript y compilación.
