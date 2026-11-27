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

`code` es estable y legible por máquina; `message` se puede mostrar; `details` es opcional (en 422 contiene la lista de campos inválidos de FastAPI con `loc`, `msg` y `type`; nunca el valor enviado). Los ids enteros de ruta, cuerpo y filtros deben estar en 1..2147483647 y los `offset` en 0..1000000; fuera de rango es 422. Códigos usados: 401 `unauthorized`, 403 `forbidden`, 404 `not_found`, 409 `conflict`, 413 `request_entity_too_large`, 422 `validation_error`, 429 `too_many_requests` (con cabecera `Retry-After` en segundos), 501 `not_implemented`, 503 `service_unavailable` (el proveedor de IA o de embeddings falló o está mal configurado; no se guarda nada). Cambiar esta forma exige una nueva versión de la API (`/api/v2`).

## Roles

| Rol | Valor | Permisos |
|---|---|---|
| Estudiante | `student` | Consulta, generación, historial propio, exámenes, feedback, lectura del corpus vigente. |
| Profesor | `teacher` | Lo anterior y gestión del corpus (subir, actualizar, retirar, ver retirados). |
| Administrador | `admin` | Gestión del corpus (incluidos retirados), envío de feedback y panel de [administración](#administración) (`/admin/*`, exclusivo). |

Cada usuario tiene un único rol. Sin sesión válida: 401. Sin permiso: 403. Recurso de otro usuario (respuesta, examen): 404, para no revelar su existencia. Los permisos de la tabla de endpoints ya se aplican (dependencia `require_roles` en `backend/app/auth.py`): los stubs responden 401/403 antes del 501. Las rutas «Autor» solo exigen sesión; la comprobación de autoría corresponde a la tarea que las implemente (`GET /answers/{answer_id}` ya la aplica: 404 si no existe o es de otro usuario, también para Administrador).

## Autenticación (CU-00, AT-08)

- `POST /auth/login` con `email` y `password`. El correo se compara sin distinguir mayúsculas. Correo inexistente, contraseña errónea y usuario inactivo devuelven el mismo 401 `Correo o contraseña incorrectos.`, con el mismo coste de cálculo.
- El token es opaco (256 bits aleatorios), no un JWT. La base guarda solo su SHA-256 en `auth_sessions`, con expiración fija de `expires_in` segundos (`ATENEO_TOKEN_TTL_SECONDS`, 8 h por defecto). Se eligió frente a JWT porque `POST /auth/logout` debe invalidar el token y así no hace falta clave de firma.
- Tras `ATENEO_LOGIN_MAX_ATTEMPTS` fallos (5) para un correo, o `ATENEO_LOGIN_IP_MAX_ATTEMPTS` (50) desde una IP, en una ventana fija de `ATENEO_LOGIN_WINDOW_SECONDS` (900 s), el login responde 429 `too_many_requests` con `Retry-After` hasta que acabe la ventana, aunque la contraseña sea correcta. Cuentan también los correos inexistentes. Un login correcto pone a cero el contador de la cuenta, no el de la IP. La IP del cliente se obtiene como se explica en el [despliegue](deployment.md#límite-de-intentos-de-login).
- `POST /auth/logout` borra la sesión. Un token expirado, revocado o de un usuario inactivo recibe 401 con `WWW-Authenticate: Bearer`.
- Contraseñas con scrypt de la biblioteca estándar (sal aleatoria, parámetros guardados en el hash) y comparación en tiempo constante.
- No hay registro público. Alta de usuarios desde `backend/` con `DATABASE_URL` definida; la contraseña se pide por consola:

  ```powershell
  uv run python -m app.auth create-user admin@upr.edu.cu --name "Nombre Apellido" --role admin
  ```

- El mismo comando mantiene cuentas: `set-password` (revoca las sesiones abiertas), `set-role`, `deactivate`/`activate` (la baja también revoca sesiones) y `list-users`.

- El frontend guarda el token donde decida AT-05/AT-20; se recomienda memoria o `sessionStorage`, nunca registrarlo en logs.

## Endpoints

| Método y ruta | CU | Tarea | Roles | Resultado |
|---|---|---|---|---|
| `POST /auth/login` | CU-00 | AT-08 | Público | `TokenResponse` (token y usuario) |
| `POST /auth/logout` | CU-00 | AT-08 | Todos | 204 |
| `GET /auth/me` | CU-00 | AT-08 | Todos | `UserOut` |
| `POST /queries` | CU-01, CU-05 | AT-09, AT-12 | Estudiante, Profesor | 201 `AnswerOut` |
| `POST /generations` | CU-02, CU-05 | AT-12 | Estudiante, Profesor | 201 `AnswerOut` |
| `POST /conversations` | CU-01, CU-05 | AT-09 | Estudiante, Profesor | 201 `TurnOut`; abre una conversación con su primera pregunta (título derivado de ella) |
| `POST /conversations/{conversation_id}/messages` | CU-01, CU-05 | AT-09 | Propietario | 201 `TurnOut`; pregunta de seguimiento con memoria. 404 si es de otro usuario |
| `GET /conversations` | CU-04 | AT-11 | Estudiante, Profesor | `ConversationOut[]` propias, de actividad más reciente a más antigua. `limit` de 1 a 100 (20 por defecto), `offset` desde 0 |
| `GET /conversations/{conversation_id}` | CU-04 | AT-11 | Propietario | `ConversationDetail`: hilo completo con las citas de cada respuesta. 404 si es de otro |
| `DELETE /conversations/{conversation_id}` | CU-04 | AT-11 | Propietario | 204; borra mensajes, respuestas, citas y su entrada de historial |
| `GET /answers/{answer_id}` | CU-04 | AT-11 | Autor | `AnswerOut` |
| `GET /documents` | CU-03 | AT-10 | Todos | `DocumentOut[]`; filtros `year`, `subject`, `topic`, `include_retired` |
| `POST /documents` | CU-03 | AT-10 | Profesor, Administrador | 201 `IngestionReport`; 409 si el identificador existe |
| `GET /documents/{document_id}` | CU-03 | AT-10 | Todos | `DocumentOut` |
| `PUT /documents/{document_id}` | CU-03 | AT-10 | Profesor, Administrador | `IngestionReport` tras reindexar |
| `DELETE /documents/{document_id}` | CU-03 | AT-10 | Profesor, Administrador | 204; retira, no borra |
| `GET /documents/{document_id}/pages/{page_number}` | CU-05 | AT-12 | Todos | `PageOut` para verificar una cita |
| `GET /history` | CU-04 | AT-11 | Estudiante, Profesor | `HistoryEntryOut[]` de consultas, conversaciones (`action: conversation`, con `conversation_id`) y generaciones propias, más recientes primero. `limit` de 1 a 100 (20 por defecto), `offset` desde 0 |
| `DELETE /history/{entry_id}` | CU-04 | AT-11 | Autor | 204; borra la consulta, generación, conversación (con sus mensajes) o examen (con su clave) y sus datos guardados |
| `DELETE /history` | CU-04 | AT-11 | Autor | 204; borra todas sus consultas, conversaciones, generaciones y exámenes con sus respuestas |
| `POST /exams` | CU-06 | AT-27 | Estudiante, Profesor | 201 `ExamOut` sin respuestas. 422 si el corpus no permite generar la cantidad solicitada con citas verificables. 503 si falla el proveedor de IA |
| `GET /exams` | CU-06 | AT-27 | Estudiante, Profesor | `ExamOut[]` propios, más recientes primero. `limit` de 1 a 100 (20 por defecto), `offset` desde 0 |
| `GET /exams/{exam_id}` | CU-06 | AT-27 | Autor | `ExamOut` |
| `DELETE /exams/{exam_id}` | CU-06 | | Autor | 204; borra el examen, su clave de corrección, citas y entrada de historial. 404 si es de otro usuario |
| `GET /exams/{exam_id}/answers` | CU-06, CU-05 | AT-27 | Autor | `ExamAnswerOut[]` con citas |
| `GET /exams/{exam_id}/pdf` | CU-06 | | Autor | `application/pdf`: examen para el estudiante, sin soluciones |
| `GET /exams/{exam_id}/answers/pdf` | CU-06, CU-05 | | Autor | `application/pdf`: clave de corrección con soluciones, puntuación y citas |
| `POST /feedback` | CU-10 | AT-28 | Todos | 201 `FeedbackOut`. 404 si la referencia a una respuesta o examen no existe o pertenece a otro usuario |
| `GET /admin/stats` | — | #29 | Administrador | `AdminStats` |
| `GET /admin/users` | — | #29 | Administrador | `AdminUserOut[]`; filtros `q`, `role`, `limit`, `offset` |
| `POST /admin/users` | — | #29 | Administrador | 201 `AdminUserOut`; 409 si el correo existe |
| `PATCH /admin/users/{user_id}` | — | #29 | Administrador | `AdminUserOut`; 409 por las reglas de protección |
| `POST /admin/users/{user_id}/password` | — | #29 | Administrador | 204; revoca sesiones |
| `DELETE /admin/users/{user_id}/sessions` | — | #29 | Administrador | 204 |
| `GET /admin/answers` | — | #29 | Administrador | `AdminAnswerOut[]`; filtros `kind`, `status`, `user_id`, `limit`, `offset` |
| `GET /admin/answers/{answer_id}` | — | #29 | Administrador | `AnswerOut` de cualquier autor |
| `GET /admin/feedback` | — | #29 | Administrador | `AdminFeedbackOut[]`; filtros `kind`, `limit`, `offset` |
| `GET /admin/logs` | — | #29 | Administrador | Entradas de log recientes; `level`, `q`, `limit` |

El borrado del historial es físico y solo afecta al autor: elimina la respuesta y sus citas; el feedback vinculado queda sin referencia. No borra documentos, exámenes ni entradas de corpus.

La subida usa los campos de formulario `document_id`, `title`, `year`, `subject`, `topic` y `file`; la actualización, los mismos sin `document_id`. `IngestionReport` tiene la forma que ya devuelve `app.rag.index.index_document`: `status` es `indexed` o `partial` y `no_text_pages` lista las páginas sin texto extraíble.

### Gestión del corpus (CU-03, AT-10, AT-18)

Implementado en `backend/app/corpus.py`; las rutas de `api.py` solo lo invocan.

- **Subir** (`POST /documents`): `document_id` de 1 a 200 caracteres `[A-Za-z0-9._-]`, empezando por letra o número (va en la URL). 409 si ya existe, también si está retirado: para reutilizarlo se sustituye con `PUT`.
- **Archivo**: debe empezar por `%PDF-` (si no, 422). Límite `ATENEO_MAX_UPLOAD_MB` (entero, 20 por defecto): por encima, 413. La extracción es la de la [ingestión](ingestion.md): un PDF cifrado, dañado o sin ningún texto extraíble devuelve 422 con el motivo en `message`. `filename` guarda el nombre enviado, sin ruta.
- **Indexación**: síncrona dentro de la petición, con `vector.store_document` y el embedder de `ATENEO_EMBEDDER` (`fake` por defecto; el mismo que usa la consulta). Si falla el proveedor de embeddings: 503 y no cambia nada.
- **Actualizar** (`PUT /documents/{id}`): 404 si no existe. Sustituye PDF y metadatos y reindexa en una transacción: la versión anterior sigue vigente hasta el `COMMIT` y se conserva entera si algo falla. Tras el cambio solo se recuperan fragmentos de la versión nueva. Las citas ya guardadas no se tocan (son copia; su `chunk_id` pasa a nulo) y siguen legibles en `GET /answers/{id}`; el visor avisa de que la versión cambió. Un documento retirado vuelve a estar vigente al sustituirlo. Si el PDF es idéntico a la versión vigente (mismo SHA-256), la operación es idempotente: 200 con el mismo `version`, solo se actualizan los metadatos y no se recalculan embeddings ni fragmentos (las citas vigentes conservan su `chunk_id`).
- **Retirar** (`DELETE /documents/{id}`): 404 si no existe; idempotente (204 también si ya estaba retirado, sin repetir el historial). Marca `status = retired` sin borrar páginas, fragmentos ni citas. Desde ese momento no se recupera en consultas ni valida citas nuevas (`no_evidence` si era la única fuente).
- **Listar y leer**: `GET /documents` ordena por año, asignatura y título; `subject` y `topic` se comparan sin mayúsculas ni espacios extremos, como en la consulta. `include_retired=true` es 403 para Estudiante. Para Estudiante, un documento retirado es 404 en `GET /documents/{id}` y en `GET /documents/{id}/pages/{n}`; Profesor y Administrador sí lo leen.
- **Historial**: subir, actualizar y retirar añaden una entrada `document_upload`, `document_update` o `document_retire` con el título y `document_id`. `documents.uploaded_by` guarda quién subió la versión vigente. La entrada se escribe justo después de la transacción de reindexación, no dentro de ella.

`shortcut:` el PDF se procesa de forma síncrona y en memoria, y Starlette recibe el cuerpo entero antes de comprobar el límite; Nginx corta en 25 MB con `client_max_body_size` (ver [despliegue](deployment.md#límites-de-subida)). Basta para el tamaño del corpus del MVP; pasar a una cola de trabajos (respuesta 202 y estado `processing`) cuando las subidas tarden más que el timeout del proxy o se usen embeddings remotos con documentos grandes.

`POST /generations` recibe `format` (`summary`, `outline`, `table`, `diagram`) y `prompt`; el contenido se devuelve como texto estructurado en `content` (ver [Generación](#generación-cu-02-at-17)). `POST /exams` recibe año, asignatura, tema opcional, `question_count` (1–20), `difficulty` (`easy`, `medium`, `hard`) y `types` opcional (lista no vacía de `multiple_choice`, `true_false`, `development`, `case`; por defecto, examen mixto). `POST /feedback` recibe `kind`: `rating` exige `rating` de 1 a 5; `error` y `suggestion` exigen `comment`. `answer_id` y `exam_id` vinculan opcionalmente el feedback.

## Administración

Rutas `/admin/*` en `backend/app/admin.py`, solo para `admin` (401 sin sesión, 403 otros roles). Listados como `GET /history`: array JSON con `limit` (1–100, 20 por defecto) y `offset`, más recientes primero (`created_at` y `id` descendentes).

- **Resumen** (`GET /admin/stats`): `users` (`total`, `active`, `by_role` con todos los roles), `documents` (`total`, `active` = no retirados, `retired`, `pages` y `pages_without_text` de todos los documentos), `activity` (`queries`, `generations`, `exams`, `feedback`, `no_evidence` = respuestas con ese estado, y `last_7_days`: siete entradas `{date, queries, generations, exams}` de hace 6 días a hoy en UTC, incluidas las de cero).
- **Cuentas**: `AdminUserOut` = `id`, `email`, `full_name`, `role`, `is_active`, `created_at`, `active_sessions` (sesiones no expiradas). `GET /admin/users` filtra con `q` (contiene en correo o nombre, sin mayúsculas) y `role`. `POST /admin/users` recibe `email`, `full_name`, `role`, `password`: el correo se guarda en minúsculas; 409 `conflict` si ya existe; 422 si la contraseña tiene menos de 8 caracteres o el correo no es válido. `PATCH /admin/users/{id}` recibe parcialmente `full_name`, `role`, `is_active`; desactivar revoca las sesiones; 409 si el admin intenta desactivarse o quitarse el rol a sí mismo, o si el sistema quedaría sin admin activo; 404 si no existe. `POST /admin/users/{id}/password` (`{"password"}`, mínimo 8) y `DELETE /admin/users/{id}/sessions` devuelven 204 y cierran todas las sesiones del usuario.
- **Materiales**: se usan las rutas de corpus existentes (`GET /documents?include_retired=true`, etc.).
- **Consultas y generaciones**: `GET /admin/answers` filtra por `kind` (valores de `AnswerKind`), `status` (`answered`/`no_evidence`) y `user_id`; cada elemento lleva `id`, `kind`, `status`, `question`, `user` (`id`, `email`, `full_name`), `citations` (número) y `created_at`. `GET /admin/answers/{id}` devuelve el `AnswerOut` completo de cualquier autor.
- **Feedback**: `GET /admin/feedback` filtra por `kind`; cada elemento lleva `id`, `kind`, `rating`, `comment`, `answer_id`, `exam_id`, `user` (nulo si la cuenta se borró) y `created_at`.
- **Logs**: `GET /admin/logs` devuelve las entradas tal como las emite `app.logs` (`ts`, `level`, `logger`, `message`, `request_id`, `method`, `path`, `status`, `duration_ms`, `exception`…), más recientes primero. `limit` de 1 a 500 (100 por defecto); `level` `INFO`, `WARNING` o `ERROR` (ese nivel o superior); `q` busca, sin mayúsculas, en `message`, `path` y `request_id`. `shortcut:` la fuente es un búfer en memoria con las últimas 1000 entradas del proceso: se pierde al reiniciar y no se comparte entre workers; los logs completos siguen en stdout (panel de Render). Nunca contiene cuerpos, tokens, contraseñas ni preguntas.
- **Auditoría**: cada acción sobre cuentas emite el log `admin_action` con `action` (`user_create`, `user_update`, `password_reset`, `sessions_revoke`), `target_user_id` y `admin_user_id`, sin correos ni contraseñas.

## Contrato de citas (CU-05)

Toda respuesta de CU-01 y CU-02 es un `AnswerOut` con `status`:

- `answered`: `content` contiene marcas `[n]` y `citations` tiene al menos una cita; cada marca corresponde a `position`.
- `no_evidence`: el corpus no respalda una respuesta; `content` lo explica y `citations` está vacío.

### Consulta (CU-01, AT-09)

`POST /queries` recibe `question` y los filtros opcionales `year`, `subject` y `topic` (se recortan espacios; asignatura y tema se comparan sin distinguir mayúsculas). Un filtro sin documentos no es un error: devuelve `no_evidence`. Se recupera de los documentos no retirados con pgvector, se genera la respuesta, se validan las citas (abajo) y, en una sola transacción, se guardan la respuesta, sus citas como copia y una entrada de historial `query`. La respuesta se puede reabrir con `GET /answers/{answer_id}`.

`mode` (opcional) elige el tipo de respuesta: `"breve"` (por defecto; el comportamiento de siempre) o `"desarrollada"` (más fragmentos y respuesta estructurada con `## Planteamiento`, `## Desarrollo`, `## Fundamentación`, `## Conclusión` y `## Límites del corpus`, ver [prototipo RAG](rag-prototype.md#modo-desarrollada)). Cualquier otro valor da 422. Los clientes que no lo envían siguen igual. El modo no se guarda (no hay columna en `answers` y no se añaden migraciones) y `AnswerOut` no lo devuelve; una respuesta desarrollada se reconoce porque su `content` tiene líneas `## …`. En `content`, una línea que empieza por `## ` es un título y una que empieza por `- ` es un elemento de lista; las demás son párrafos.

```json
{"question": "¿Qué requisitos tiene la usucapión?", "year": 2, "mode": "desarrollada"}
```

### Chat con memoria (CU-01)

La pantalla Consulta es un chat. `POST /conversations` y `POST /conversations/{id}/messages` reciben `question` (1–1000 caracteres) y los filtros opcionales `year`, `subject`, `topic` (los filtros valen por turno) y `mode` (`chat` por defecto, o `desarrollada`: estructura Planteamiento, Desarrollo, Fundamentación, Conclusión y Límites del corpus; no se guarda) y devuelven un `TurnOut`: `conversation` (`ConversationOut`: `id`, `title`, `created_at`, `updated_at`) y `messages` (el mensaje del usuario y el del asistente). Cada `MessageOut` lleva `role` (`user`/`assistant`), `content`, `status` (`answered`/`no_evidence`, solo en el asistente), `answer_id` y `citations` (mismas `CitationOut` y renumeración `[n]` que `AnswerOut`; se abren con el visor de `GET /documents/{id}/pages/{n}`).

- Siempre responde en modo `chat`: recuperación amplia (la de `desarrollada`), prosa conversacional de 150 a 600 palabras restringida al corpus y con citas. No hay campo `mode`.
- Memoria: con los últimos 6 mensajes del hilo (300 caracteres cada uno, sin marcas `[n]`), la pregunta de seguimiento se reformula como pregunta autónoma antes de recuperar fragmentos y esos turnos acompañan al prompt de respuesta como contexto, no como fuente. Con `ATENEO_LLM_PROVIDER=fake` la reformulación es determinista: pregunta anterior del usuario + pregunta nueva. Si falla la llamada de reformulación se usa esa misma concatenación.
- Un turno es atómico: ante un fallo del proveedor (503) no se guarda ni el mensaje del usuario ni la conversación; el cliente puede reintentar.
- Cada mensaje del asistente se guarda como un `Answer` (`kind = query`) con sus `Citation`, así que `POST /feedback` con su `answer_id` y el panel de administración funcionan igual.
- Solo el propietario ve, amplía o borra una conversación: de otro usuario responde 404. Admin recibe 403 como en el resto de rutas de estudio.
- La conversación aparece una vez en `GET /history` y se borra con `DELETE /history/{entry_id}` o `DELETE /history`.
- Si se borra una conversación mientras se espera la respuesta de un turno, ese turno responde 404 al terminar y no guarda nada.
- Límite por usuario en `POST /queries`, `/generations`, `/conversations`, `/conversations/{id}/messages` y `/exams`: `ATENEO_AI_MAX_REQUESTS` (20) peticiones por `ATENEO_AI_WINDOW_SECONDS` (600, ventana deslizante, en memoria del proceso); al superarlo, 429 con `Retry-After`.

`POST /queries` no cambia y sigue sin memoria.

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

### Generación (CU-02, AT-17)

`POST /generations` recibe `format`, `prompt` (tema o pregunta, 1–1000 caracteres) y los mismos filtros opcionales que la consulta. Sigue el flujo de CU-01: recuperación, generación restringida al corpus con marcas por fragmento, cita exacta por oración, validación (abajo) y, en una sola transacción, la respuesta (`answers.kind` = `format`), sus citas y una entrada de historial `generation` con `prompt` como resumen. Se reabre con `GET /answers/{answer_id}`; un fallo del proveedor devuelve 503 sin guardar nada. El RAG se invoca solo a través de `app.generation.generate`, con la misma forma de resultado que `app.query.ask`.

`content` es texto por líneas (se ignoran las vacías) con marcas `[n]`; `kind` indica la estructura:

| `format` | Estructura de `content` | Cada elemento con marca |
|---|---|---|
| `summary` | Uno o varios párrafos, uno por línea. | Cada párrafo. |
| `outline` | Una línea por elemento: `- texto`, con dos espacios de sangría por nivel; el primero en nivel 0 y cada nivel como mucho uno más que el anterior. | Cada hoja; un elemento con hijos puede no llevarla. |
| `table` | Tabla Markdown: encabezados, separadora (`---`, admite `:`) y al menos una fila de datos, todas entre `\|` y con el mismo número de columnas (≥ 2). La primera columna nombra el aspecto comparado; las celdas no contienen `\|`. | Cada fila de datos. |
| `diagram` | Una relación por línea: `Origen -> Destino` o `Origen -> Destino: relación`. | Cada relación. |

```text
- Fuentes del Derecho Romano
  - La costumbre es fuente del derecho. [1]
  - El senadoconsulto lo dicta el Senado. [2]
```

```text
| Fuente | Órgano | Época |
|---|---|---|
| Ley | Comicios [1] | República [1] |
| Senadoconsulto | Senado [2] | República [2] |
```

```text
Costumbre -> Ley escrita: se codifica [1]
Ley escrita -> Edictos [2]
```

La estructura se comprueba con `app.rag.generate.well_formed` en el RAG y tras la validación de citas en la API. Si falla la estructura o alguna cita utilizada, la generación entera pasa a `no_evidence` con `content` = `No encontrado en el corpus.`.

### Validación de citas (AT-12)

`app.citations.validate` se aplica a todo resultado de CU-01 y CU-02 antes de guardarlo o devolverlo:

1. Una cita se descarta si su documento no existe, está retirado o su versión no es la vigente; si la página no existe; si `start`/`end` no son enteros con `0 <= start < end`; o si `quote` está vacía o difiere de `pages.text[start:end]`.
2. Título del documento y etiqueta de página se copian de la base, no del modelo. `chunk_id` pasa a nulo si el fragmento no existe en ese documento y página.
3. Cada marca `[n]` debe referenciar una cita verificable. Se conservan solo las citas utilizadas y se renumeran `1..k` por orden de aparición.
4. Si una marca referencia una cita descartada o inexistente, o si el texto carece de marcas, la respuesta pasa a `no_evidence` con `content` = `No encontrado en el corpus.`, sin el texto generado.

### Exámenes y feedback (CU-06 y CU-10)

El examen es mixto y lo genera la IA con el material vigente de la clasificación pedida (año, asignatura y tema opcional). `question_count` es el número de preguntas; `types` limita los tipos (por defecto los cuatro). El reparto, con al menos un caso práctico si hay dos o más preguntas, se ordena como un examen real: test (`multiple_choice`, cuatro opciones y una correcta), verdadero o falso con justificación (`true_false`), desarrollo (`development`) y caso práctico (`case`: supuesto de hecho con varias preguntas `a)`, `b)`…). Las dificultades baja, media y alta se indican al modelo. Cada pregunta lleva `kind`, `statement`, `options` (solo test, si no `null`), `points` (la suma de todo el examen es 10) y el examen `duration_minutes` y `total_points`. Los exámenes anteriores, de completar fragmento, se leen con `kind` `completion`, 1 punto por pregunta y 30 minutos.

Una sola llamada al proveedor devuelve el JSON de todas las preguntas (varias llamadas por examen superarían los 120 s del proxy). La salida se valida: JSON inválido, preguntas mal formadas (p. ej. un test sin cuatro opciones distintas) o repetidas se descartan. La solución de cada pregunta se verifica como una respuesta de CU-01: cada línea lleva una marca `[Fn]` que se resuelve con `cite_reply` en una cita exacta de la página (versión y offsets) y las marcas se renumeran `[1]..[k]` por pregunta. Una pregunta cuya solución no se pueda citar se descarta; si faltan preguntas hay un único reintento, solo por las que faltan y solo si la primera llamada tardó menos de 45 s. Si aun así no se alcanza `question_count`, la respuesta es 422 («El corpus vigente permite N preguntas…») y no se guarda nada. El `criteria` (criterio de corrección) lo redacta el modelo sin citas y puntúa las ideas del modelo de respuesta, que sí está citado. Con `ATENEO_LLM_PROVIDER=fake` el generador es determinista y produce una pregunta válida de cada tipo con oraciones del corpus. La creación guarda el examen, las preguntas, las citas y la entrada de actividad en la misma transacción.

Las soluciones se consultan en `/exams/{exam_id}/answers` (`answer`, `criteria` y citas) con la cuenta que creó el examen. `GET /exams/{exam_id}/pdf` descarga el examen en A4 para el estudiante: cabecera con universidad, facultad y carrera, asignatura, año, tema, fecha, duración, nombre y grupo a rellenar, instrucciones generales, preguntas numeradas con su puntuación y total, casillas en las de test y verdadero o falso, líneas para responder a las de desarrollo y al caso, y pie con «Página n de N». `GET /exams/{exam_id}/answers/pdf` descarga la clave (`CLAVE DE CORRECCIÓN`) con solución, criterio, puntuación y fuentes (documento y página). Ambos usan el mismo control de acceso que el examen (404 si es de otro usuario) y devuelven `Content-Disposition: attachment`. La práctica es de autocorrección. El feedback admite valoraciones, reportes de error y sugerencias, con referencias opcionales a recursos propios.

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
| `conversations`, `messages` | Chat con memoria (migración 0005): conversación con propietario, título y fechas; mensaje `user`/`assistant` con contenido y, el del asistente, enlace a su `answers` (estado y citas). La entrada de historial `conversation` se enlaza con `history_entries.conversation_id`. |
| `exams`, `exam_questions` | Configuración y duración del examen; preguntas ordenadas con `kind`, `options`, `points`, respuesta y `criteria` (migración 0006). |
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

`backend/tests/test_corpus.py` prueba CU-03 y la reindexación en SQLite en memoria con claves foráneas activas: `store_document` es el real y solo se sustituye la búsqueda pgvector por una por términos con el mismo filtro de retirados. Comprueba subida, filtros, página, 409/404/413/422/503, roles, historial, que tras `PUT` solo se recupera la versión nueva y la cita antigua sigue como copia, y que tras `DELETE` la consulta devuelve `no_evidence`. Con `ATENEO_TEST_DATABASE_URL` repite subir → actualizar → retirar contra PostgreSQL/pgvector.

`backend/tests/test_admin.py` prueba las rutas `/admin/*` en SQLite en memoria: permisos, resumen, alta y edición de cuentas con sus reglas 409, revocación de sesiones, listados con filtros y logs sin secretos.

`backend/tests/test_queries.py` prueba CU-01 y la validación de citas en SQLite en memoria, sustituyendo solo la recuperación pgvector por una falsa; `backend/tests/test_generations.py` hace lo mismo con CU-02 (los cuatro formatos, estructura inválida, roles, 503) y casos dorados de los generadores sobre la muestra; con `ATENEO_TEST_DATABASE_URL` además recorre la consulta completa con la muestra indexada en PostgreSQL.

## Pendiente

- Consulta del feedback por profesores (AT-28); los administradores ya lo ven en `GET /admin/feedback`.
- Procesamiento asíncrono de subidas (ver el `shortcut` de la gestión del corpus).
- Dimensión del embedding e índice vectorial (AT-14).
