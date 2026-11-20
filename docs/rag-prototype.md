# RAG restringido al corpus

AT-04 (issue #4) creó el prototipo de línea de comandos en `app.rag.answer` sobre el índice textual de [ingestión](ingestion.md). AT-14 añadió la recuperación por embeddings en PostgreSQL/pgvector (ver [indexación en PostgreSQL](ingestion.md#indexación-en-postgresql-con-embeddings-at-14)). AT-15 y AT-16 lo convierten en la función que usa la API, con citas exactas verificadas. No añade endpoints.

## Flujo

Desde AT-15/AT-16 (issues #15 y #16) el flujo de CU-01 devuelve citas con la forma del contrato ([CU-05](api-contract.md#contrato-de-citas-cu-05)).

1. **Recuperación.** Se eliminan palabras vacías de la pregunta. Con la ruta de un índice SQLite se buscan los términos restantes en FTS5; con una sesión de base de datos se busca la pregunta completa por similitud coseno en pgvector. Máximo cinco fragmentos, con los filtros opcionales de año, asignatura y tema.
2. **Fuera del corpus.** pgvector siempre devuelve vecinos, así que se descarta todo vecino que no comparta un término con la pregunta y además esté a más de `ATENEO_MAX_DISTANCE` (distancia coseno, 0.5 por defecto). FTS5 ya exige un término común. Si no quedan términos o fragmentos, la respuesta es `no_evidence` y no se llama al modelo.
3. **Generación.** El prompt de sistema (`SYSTEM_PROMPT`) exige responder en español solo con los fragmentos, terminar cada afirmación con la marca del fragmento (`[F1]`, `[F2]`…) y responder `No encontrado en el corpus.` si no hay base. Cada fragmento se entrega con su marca, título y página.
4. **Cita exacta.** Cada marca se resuelve al fragmento recuperado y, dentro de él, a la oración con más términos de la afirmación que la precede (el fragmento entero si ninguna coincide). Como el texto del fragmento es `página.text[start:end]`, los offsets de la oración se trasladan a la página y `quote` es exactamente ese texto.
5. **Verificación (`app.rag.citations`, CU-05).** Cada cita se comprueba contra la fuente vigente: el `chunk_id` debe existir en la versión actual de un documento no retirado, corresponder al mismo documento, versión y página, quedar dentro del fragmento y cumplir `quote == página.text[start:end]`. Cualquier cita inválida o marca de un fragmento no entregado se informa en `invalid_citations` y la respuesta completa pasa a `no_evidence`. Si todas son válidas, se renumeran `[1]`, `[2]`… por orden de aparición. Una cita repetida conserva su número y `[n]` es `citations[n - 1]`.

## Integración con la API (AT-09, AT-12)

```python
from app.rag.answer import PROVIDERS, answer_question
from app.rag.vector import EMBEDDERS

result = answer_question(
    session,                     # Session de SQLAlchemy (pgvector) o Path de un índice SQLite
    request.question,
    PROVIDERS["openai"],         # (system, user) -> str; "fake" en pruebas
    embedder=EMBEDDERS["openai"],  # el mismo modelo que indexó; "fake" por defecto
    year=request.year, subject=request.subject, topic=request.topic,
)
```

Resultado (`dict`), con la forma que consume `app.query.ask`:

| Clave | Valor |
|---|---|
| `question` | Pregunta recibida. |
| `status` | `"answered"` o `"no_evidence"` (valores de `AnswerStatus`). |
| `answer` | Texto con marcas `[n]`, donde `n` remite a `citations[n - 1]`; con `no_evidence`, `No encontrado en el corpus.` |
| `citations` | Lista de `chunk_id`, `document_id`, `title`, `version`, `page`, `page_label`, `start`, `end`, `quote`. Corresponden a `CitationOut` con `title` → `document_title`, `version` → `document_version`, `page` → `page_number` y `position` = índice + 1. `answered` ⇒ al menos una; `no_evidence` ⇒ vacía. |
| `invalid_citations` | Diagnóstico, no se muestra al usuario: citas rechazadas (campos de la cita y `reason`) o marcas desconocidas (`marker` y `reason`). |

`answer_question` solo lee; guardar `Answer` y `Citation` corresponde a la API. Para revalidar citas guardadas antes de devolverlas (p. ej. en el historial) se usa la función pura `verify_citations(citations, sources) -> (válidas, inválidas)`, con citas de las mismas claves que `citations`, con `db_sources(session, chunk_ids)` o `sqlite_sources(ruta, chunk_ids)`. Errores de entrada (año, límite, consulta de más de 1.000 caracteres) se lanzan como `ValueError` (`IngestionError`); errores del proveedor o de la base se propagan.

La salida JSON del CLI `ask` es este mismo `dict`.

## Generación (CU-02, AT-17)

`app.rag.generate.generate_material(source, format, prompt, provider, embedder=..., year=..., subject=..., topic=...)` reutiliza el mismo recorrido: `retrieve`, prompt de sistema con las reglas de CU-01 más las instrucciones del formato (`INSTRUCTIONS`), marcas `[Fn]`, cita exacta y verificación con `cite_reply` (extraído de `answer_question`, sin cambiar CU-01). Solo cambia la afirmación que se cita: la línea o celda de tabla donde está la marca, no las anteriores. Devuelve el mismo `dict` que `answer_question` más `format` y, si la salida no sigue la estructura, `error` con `status` `no_evidence`. La estructura de cada formato y su comprobación (`well_formed`) están en el [contrato](api-contract.md#generación-cu-02-at-17). La API llama a `app.generation.generate`, que elige proveedor y embeddings con las mismas variables que `app.query`.

El proveedor `fake` de generación (`app.rag.generate.fake_provider`) toma hasta tres oraciones recuperadas con más términos del tema y las devuelve en la estructura pedida: un párrafo, un esquema con el tema como raíz, un cuadro `Fuente | Contenido` o un diagrama `tema -> fuente: oración`. Los casos dorados de los cuatro formatos están en `backend/tests/test_generations.py`.

## Proveedores

| Nombre | Uso |
|---|---|
| `fake` | Determinista, sin red ni claves. Devuelve la oración recuperada con más términos de la pregunta y su cita. Es el que usan pruebas y CI. |
| `openai` | Cualquier API de chat compatible con OpenAI (`/chat/completions`), con `temperature` 0. |

Variables del proveedor `openai`, solo en el entorno local (nunca en Git):

- `ATENEO_LLM_API_KEY` (obligatoria)
- `ATENEO_LLM_MODEL` (obligatoria)
- `ATENEO_LLM_BASE_URL` (opcional, por defecto `https://api.openai.com/v1`)

No se ha fijado proveedor IA para producción.

## Ejecutar en PowerShell

Primero crear el índice de muestra según la [guía de ingestión](ingestion.md). Después, desde `backend`:

```powershell
uv run --frozen python -m app.rag ask --index ../data/sample.sqlite --question "¿Qué conserva la biblioteca ficticia?"
uv run --frozen python -m app.rag ask --index ../data/sample.sqlite --question "¿Cuál es el término exclusivo?" --year 4
uv run --frozen python -m app.rag eval --index ../data/sample.sqlite
```

Con un proveedor real:

```powershell
$env:ATENEO_LLM_API_KEY = "<clave>"
$env:ATENEO_LLM_MODEL = "<modelo>"
uv run --frozen python -m app.rag ask --index ../data/sample.sqlite --question "¿Qué conserva la biblioteca ficticia?" --provider openai
```

`eval` devuelve código 1 si alguna pregunta falla.

## Preguntas doradas

`backend/app/rag/golden_questions.json` contiene el set sintético basado solo en la muestra ficticia: preguntas en el corpus con documento, página y texto citado esperados, fuera del corpus, con filtros equivocados, con instrucciones inyectadas y con premisas falsas. Categorías, reglas de aprobado y resultados en [QA del RAG](qa-rag.md). `backend/tests/test_rag_answer.py` las ejecuta con el índice SQLite y el proveedor `fake`, y comprueba que cada `quote` es exactamente `página.text[start:end]`. `backend/tests/test_rag_vector.py` las ejecuta además por pgvector con el embedder `fake` (requiere `ATENEO_TEST_DATABASE_URL`) y comprueba que las preguntas fuera del corpus no llegan al modelo aunque pgvector devuelva vecinos.

Con el corpus oficial, el set debe sustituirse por preguntas revisadas por docentes para cada asignatura.

## Límites

- `ATENEO_MAX_DISTANCE` es una hipótesis: depende del modelo de embeddings y debe calibrarse con preguntas doradas reales al elegirlo. Un término común muy frecuente (p. ej. «derecho») basta para que un fragmento pase; el rechazo final depende entonces del modelo y de la verificación.
- La verificación comprueba que la cita exista tal cual en la página vigente, no que el fragmento respalde la afirmación; solo las cifras de la afirmación deben aparecer en el fragmento citado.
- La oración citada se elige por términos comunes con la afirmación; las abreviaturas con punto («art.») y los saltos de línea la cortan. Si no coincide ninguna, se cita el fragmento entero.
- Solo se reconocen marcas `[Fn]`; otros formatos cuentan como respuesta sin cita. Las marcas `[n]` que escriba el modelo se eliminan.
- El proveedor `fake` y el embedder `fake` no miden calidad; solo verifican el recorrido completo.
- Generación: la estructura se valida por líneas; un origen de diagrama con ` -> ` o una celda con `|` invalidan la salida entera (pasa a `no_evidence`), igual que un elemento sin cita. No hay casos dorados con un proveedor real.
- La lista de palabras vacías es mínima y se ajustará con preguntas reales.
