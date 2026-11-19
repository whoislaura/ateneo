# Contrato API y modelo de datos — Sprint 0

Esta entrega implementa AT-02 (issue #2). Define el contrato que guía Sprint 1 y 2; los endpoints responden HTTP 501 hasta que cada tarea los implemente. La fuente de verdad es el código: esquemas en `backend/app/schemas.py`, rutas en `backend/app/api.py`, tablas en `backend/app/models.py` y migraciones en `backend/migrations/`. FastAPI publica el contrato completo en `/openapi.json` y `/docs` al acceder directamente a la API local.

Laura y Ray revisan el contrato antes de integrar RAG y frontend. Un cambio incompatible requiere actualizar este documento, los esquemas y las pruebas en el mismo PR.

## Convenciones

- Prefijo `/api/v1`, JSON UTF-8 salvo la subida de PDFs (`multipart/form-data`). Identificadores y valores enumerados en inglés; textos para el usuario en español.
- Autenticación: token `Authorization: Bearer <token>` obtenido en `POST /auth/login`. Todas las rutas salvo login y salud lo exigen. Ver [Autenticación](#autenticación-cu-00-at-08).
- Fechas ISO 8601 con zona horaria. Las listas devuelven un array JSON; el historial pagina con `limit` (1–100, 20 por defecto) y `offset`.
- Año: entero de 1 a 4. Asignatura y tema: texto de 1 a 200 caracteres. Preguntas: hasta 1.000 caracteres, igual que el índice de muestra.

### Errores

Todo error de `/api/v1` usa la misma forma:

```json
{"error": {"code": "validation_error", "message": "Solicitud inválida.", "details": [...]}}
```

`code` es estable y legible por máquina; `message` se puede mostrar; `details` es opcional (en 422 contiene la lista de campos inválidos de FastAPI con `loc`, `msg` y `type`). Códigos usados: 401 `unauthorized`, 403 `forbidden`, 404 `not_found`, 409 `conflict`, 422 `validation_error`, 501 `not_implemented`, 503 `service_unavailable` (el proveedor de IA o de embeddings falló o está mal configurado; no se guarda nada). Cambiar esta forma exige una nueva versión de la API (`/api/v2`).

## Roles

| Rol | Valor | Permisos |
|---|---|---|
| Estudiante | `student` | Consulta, generación, historial propio, exámenes, feedback, lectura del corpus vigente. |
| Profesor | `teacher` | Lo anterior y gestión del corpus (subir, actualizar, retirar, ver retirados). |
| Administrador | `admin` | Gestión del corpus (incluidos retirados) y envío de feedback. |

Cada usuario tiene un único rol. Sin sesión válida: 401. Sin permiso: 403. Recurso de otro usuario (respuesta, examen): 404, para no revelar su existencia. Los permisos de la tabla de endpoints ya se aplican (dependencia `require_roles` en `backend/app/auth.py`): los stubs responden 401/403 antes del 501. Las rutas «Autor» solo exigen sesión; la comprobación de autoría corresponde a la tarea que las implemente (`GET /answers/{answer_id}` ya la aplica: 404 si no existe o es de otro usuario, también para Administrador).

## Autenticación (CU-00, AT-08)

- `POST /auth/login` con `email` y `password`. El correo se compara sin distinguir mayúsculas. Correo inexistente, contraseña errónea y usuario inactivo devuelven el mismo 401 `Correo o contraseña incorrectos.`, con el mismo coste de cálculo.
- El token es opaco (256 bits aleatorios), no un JWT. La base guarda solo su SHA-256 en `auth_sessions`, con expiración fija de `expires_in` segundos (`ATENEO_TOKEN_TTL_SECONDS`, 8 h por defecto). Se eligió frente a JWT porque `POST /auth/logout` debe invalidar el token y así no hace falta clave de firma.
- `POST /auth/logout` borra la sesión. Un token expirado, revocado o de un usuario inactivo recibe 401 con `WWW-Authenticate: Bearer`.
- Contraseñas con scrypt de la biblioteca estándar (sal aleatoria, parámetros guardados en el hash) y comparación en tiempo constante.
- No hay registro público. Alta de usuarios desde `backend/` con `DATABASE_URL` definida; la contraseña se pide por consola:

  ```powershell
  uv run python -m app.auth create-user admin@upr.edu.cu --name "Nombre Apellido" --role admin
  ```

- El frontend guarda el token donde decida AT-05/AT-20; se recomienda memoria o `sessionStorage`, nunca registrarlo en logs.

## Endpoints

| Método y ruta | CU | Tarea | Roles | Resultado |
|---|---|---|---|---|
| `POST /auth/login` | CU-00 | AT-08 | Público | `TokenResponse` (token y usuario) |
| `POST /auth/logout` | CU-00 | AT-08 | Todos | 204 |
| `GET /auth/me` | CU-00 | AT-08 | Todos | `UserOut` |
| `POST /queries` | CU-01, CU-05 | AT-09, AT-12 | Estudiante, Profesor | 201 `AnswerOut` |
| `POST /generations` | CU-02, CU-05 | AT-12 | Estudiante, Profesor | 201 `AnswerOut` |
| `GET /answers/{answer_id}` | CU-04 | AT-11 | Autor | `AnswerOut` |
| `GET /documents` | CU-03 | AT-10 | Todos | `DocumentOut[]`; filtros `year`, `subject`, `topic`, `include_retired` |
| `POST /documents` | CU-03 | AT-10 | Profesor, Administrador | 201 `IngestionReport`; 409 si el identificador existe |
| `GET /documents/{document_id}` | CU-03 | AT-10 | Todos | `DocumentOut` |
| `PUT /documents/{document_id}` | CU-03 | AT-10 | Profesor, Administrador | `IngestionReport` tras reindexar |
| `DELETE /documents/{document_id}` | CU-03 | AT-10 | Profesor, Administrador | 204; retira, no borra |
| `GET /documents/{document_id}/pages/{page_number}` | CU-05 | AT-12 | Todos | `PageOut` para verificar una cita |
| `GET /history` | CU-04 | AT-11 | Estudiante, Profesor | `HistoryEntryOut[]` propias, más recientes primero |
| `POST /exams` | CU-06 | AT-27 | Estudiante, Profesor | 201 `ExamOut` sin respuestas |
| `GET /exams` | CU-06 | AT-27 | Estudiante, Profesor | `ExamOut[]` propios |
| `GET /exams/{exam_id}` | CU-06 | AT-27 | Autor | `ExamOut` |
| `GET /exams/{exam_id}/answers` | CU-06, CU-05 | AT-27 | Autor | `ExamAnswerOut[]` con citas |
| `POST /feedback` | CU-10 | AT-28 | Todos | 201 `FeedbackOut` |

La subida usa los campos de formulario `document_id`, `title`, `year`, `subject`, `topic` y `file`; la actualización, los mismos sin `document_id`. `IngestionReport` tiene la forma que ya devuelve `app.rag.index.index_document`: `status` es `indexed` o `partial` y `no_text_pages` lista las páginas sin texto extraíble.

`POST /generations` recibe `format` (`summary`, `outline`, `table`, `diagram`) y `prompt`; el contenido se devuelve como texto en `content`. `POST /exams` recibe año, asignatura, tema opcional, `question_count` (1–50) y `difficulty` (`easy`, `medium`, `hard`). `POST /feedback` recibe `kind`: `rating` exige `rating` de 1 a 5; `error` y `suggestion` exigen `comment`. `answer_id` y `exam_id` vinculan opcionalmente el feedback.

## Contrato de citas (CU-05)

Toda respuesta de CU-01 y CU-02 es un `AnswerOut` con `status`:

- `answered`: `content` contiene marcas `[n]` y `citations` tiene al menos una cita; cada marca corresponde a `position`.
- `no_evidence`: el corpus no respalda una respuesta; `content` lo explica y `citations` está vacío.

### Consulta (CU-01, AT-09)

`POST /queries` recibe `question` y los filtros opcionales `year`, `subject` y `topic` (se recortan espacios; asignatura y tema se comparan sin distinguir mayúsculas). Un filtro sin documentos no es un error: devuelve `no_evidence`. Se recupera de los documentos no retirados con pgvector, se genera la respuesta, se validan las citas (abajo) y, en una sola transacción, se guardan la respuesta, sus citas como copia y una entrada de historial `query`. La respuesta se puede reabrir con `GET /answers/{answer_id}`.

El proveedor se elige por entorno: `ATENEO_LLM_PROVIDER` (`fake` por defecto, `openai`) y `ATENEO_EMBEDDER` (`fake` por defecto, `openai`; debe ser el mismo que indexó el corpus). Las variables de cada proveedor están en el [prototipo RAG](rag-prototype.md). Pruebas y CI usan siempre `fake`. Un fallo del proveedor devuelve 503 sin guardar nada.

El RAG se invoca solo a través de `app.query.ask`, que devuelve `status`, `answer` con marcas `[n]` y `citations` con `document_id`, `title`, `version`, `page`, `start`, `end`, `quote` y `chunk_id`, donde `[n]` remite a la cita n.

El esquema rechaza cualquier otra combinación. Cada respuesta de examen exige también al menos una cita.

```json
{
  "position": 1,
  "chunk_id": "3f1c…",
  "document_id": "muestra-a",
  "document_title": "Muestra sintética muestra-a",
  "document_version": "9b2e…",
  "page_number": 1,
  "page_label": null,
  "start": 0,
  "end": 412,
  "quote": "MATERIAL SINTÉTICO…"
}
```

Una cita es válida si `quote == texto_de_página[start:end]`, para la página física `page_number` de la versión `document_version`. `start`/`end` son offsets de caracteres sobre el texto normalizado de la página, con final exclusivo, igual que en la [ingestión](ingestion.md). `page_number` es la página física desde 1; `page_label` es la etiqueta impresa solo si el PDF la incorpora. El backend valida esta igualdad antes de guardar o devolver una cita (AT-12, AT-16); el visor (AT-21) la comprueba con `GET /documents/{id}/pages/{n}` mientras la versión vigente coincida.

La cita se guarda como copia: documento, título, versión, página y texto citado. Así el historial conserva referencias comprobables aunque el documento se reindexe o retire; `chunk_id` pasa a nulo cuando su fragmento deja de existir.

### Validación de citas (AT-12)

`app.citations.validate` se aplica a todo resultado de CU-01 (y servirá para CU-02) antes de guardarlo o devolverlo:

1. Una cita se descarta si su documento no existe, está retirado o su versión no es la vigente; si la página no existe; si `start`/`end` no son enteros con `0 <= start < end`; o si `quote` está vacía o difiere de `pages.text[start:end]`.
2. Título del documento y etiqueta de página se copian de la base, no del modelo. `chunk_id` pasa a nulo si el fragmento no existe en ese documento y página.
3. Las marcas `[n]` de citas descartadas o inexistentes se eliminan del texto; las citas válidas sin marca se descartan. Las restantes se renumeran `1..k` por orden de aparición.
4. Si no queda ninguna cita, la respuesta pasa a `no_evidence` con `content` = `No encontrado en el corpus.`, sin el texto generado.

## Modelo de datos

PostgreSQL 17 con pgvector. Las tablas se crean exclusivamente mediante Alembic.

| Tabla | Contenido |
|---|---|
| `users` | Correo único, nombre, hash de contraseña, `role` (`student`/`teacher`/`admin`), activo, fecha de alta. |
| `documents` | Versión vigente de cada documento. `id` es el `document_id` de la ingestión; `version` el SHA-256 del PDF; año (1–4), asignatura, tema, archivo, `status` (`indexed`/`partial`/`retired`), configuración de chunking y autor de la subida. |
| `pages` | Página física por documento: número, etiqueta, texto normalizado y `status` (`text`/`no_text`). |
| `chunks` | Fragmento de la ingestión: `id` (`chunk_id` determinista), documento, versión, página, `start_offset`/`end_offset`, texto y `embedding` (pgvector, nulo hasta AT-14). |
| `answers` | Resultado de consulta o generación: autor, `kind` (`query`/`summary`/`outline`/`table`/`diagram`), `status`, pregunta, filtros y contenido. |
| `citations` | Copia verificable de cada cita, ligada a una respuesta o a una pregunta de examen (exactamente una). |
| `exams`, `exam_questions` | Configuración del examen y preguntas ordenadas con su respuesta. |
| `history_entries` | CU-04: fecha, autor, `action` y resumen, con enlace opcional a respuesta, examen o documento. |
| `feedback` | Valoración (1–5), error o sugerencia, con autor y vínculo opcional a respuesta o examen. |

Una reingestión sustituye páginas y fragmentos del documento, como el índice de muestra. Retirar marca `status = retired`: el documento deja de recuperarse, pero conserva sus filas para el historial. Los `CHECK` de la base repiten las reglas del contrato (año, offsets, valoración, propietario de la cita).

La columna `embedding` no fija dimensión ni índice ANN: ambos dependen del modelo de embeddings, que aún no está decidido. Se añadirán por migración en AT-14.

### Migraciones

Con PostgreSQL disponible y la extensión `vector` creada (`infra/db/init.sql`), desde `backend/`:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://ateneo:<contraseña>@localhost:5432/ateneo"
uv run --frozen alembic upgrade head
```

`uv run --frozen alembic upgrade head --sql` genera el SQL sin conexión. Compose aún no publica PostgreSQL ni ejecuta migraciones al arrancar; su automatización corresponde a DevOps (AT-13). Para cambios de esquema: modificar `app/models.py`, generar la revisión con `alembic revision --autogenerate -m "..."` contra una base migrada, revisarla y versionarla.

## Comprobación

`backend/tests/test_contract.py` comprueba que OpenAPI describe todas las rutas, el formato de error, las reglas de citas y feedback y la compatibilidad con la salida de la ingestión. `backend/tests/test_models.py` genera el SQL de la migración sin base de datos; si `ATENEO_TEST_DATABASE_URL` apunta a una base PostgreSQL desechable, además aplica la migración, compara el esquema con los modelos y la revierte. CI no dispone de PostgreSQL para el job de backend, por lo que esa parte se omite allí.

`backend/tests/test_auth.py` prueba login, sesión, logout, expiración, credenciales erróneas sin enumeración, la matriz de roles y el comando de alta con usuarios y sesiones en SQLite en memoria (`dependency_overrides`), sin PostgreSQL.

`backend/tests/test_queries.py` prueba CU-01 y la validación de citas en SQLite en memoria, sustituyendo solo la recuperación pgvector por una falsa; con `ATENEO_TEST_DATABASE_URL` además recorre la consulta completa con la muestra indexada en PostgreSQL.

## Pendiente

- Citas a nivel de frase: hasta AT-15 la consulta cita el primer fragmento recuperado de cada página citada, no la frase exacta.

- Gestión de usuarios más allá del alta por consola (baja, cambio de rol o contraseña).
- Consulta del feedback por administradores y profesores (AT-28).
- Límite de tamaño de PDF y procesamiento asíncrono de subidas (AT-10, AT-18).
- Dimensión del embedding e índice vectorial (AT-14).
