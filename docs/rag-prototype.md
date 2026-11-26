# RAG restringido al corpus

AT-04 (issue #4) creó el prototipo de línea de comandos en `app.rag.answer` sobre el índice textual de [ingestión](ingestion.md). AT-14 añadió la recuperación por embeddings en PostgreSQL/pgvector (ver [indexación en PostgreSQL](ingestion.md#indexación-en-postgresql-con-embeddings-at-14)). AT-15 y AT-16 lo convierten en la función que usa la API, con citas exactas verificadas. No añade endpoints.

## Flujo

Desde AT-15/AT-16 (issues #15 y #16) el flujo de CU-01 devuelve citas con la forma del contrato ([CU-05](api-contract.md#contrato-de-citas-cu-05)).

1. **Recuperación.** Se eliminan palabras vacías de la pregunta. Con la ruta de un índice SQLite se buscan los términos restantes en FTS5; con una sesión de base de datos se busca la pregunta completa por similitud coseno en pgvector. Máximo cinco fragmentos (modo breve; el [modo desarrollada](#modo-desarrollada) usa más), con los filtros opcionales de año, asignatura y tema.
2. **Fuera del corpus.** pgvector siempre devuelve vecinos, así que se descarta todo vecino que no comparta un término con la pregunta y además esté a más de `ATENEO_MAX_DISTANCE` (distancia coseno, 0.5 por defecto). FTS5 ya exige un término común. Si no quedan términos o fragmentos, la respuesta es `no_evidence` y no se llama al modelo.
3. **Generación.** El prompt de sistema (`SYSTEM_PROMPT`) exige responder en español solo con los fragmentos, terminar cada afirmación con la marca del fragmento (`[F1]`, `[F2]`…) y responder `No encontrado en el corpus.` si no hay base. Cada fragmento se entrega con su marca, título y página.
4. **Cita exacta.** Cada marca se resuelve al fragmento recuperado y, dentro de él, a la oración con más términos de la afirmación que la precede (el fragmento entero si ninguna coincide). Como el texto del fragmento es `página.text[start:end]`, los offsets de la oración se trasladan a la página y `quote` es exactamente ese texto.
5. **Verificación (`app.rag.citations`, CU-05).** Cada cita se comprueba contra la fuente vigente: el `chunk_id` debe existir en la versión actual de un documento no retirado, corresponder al mismo documento, versión y página, quedar dentro del fragmento y cumplir `quote == página.text[start:end]`. Cualquier cita inválida o marca de un fragmento no entregado se informa en `invalid_citations` y la respuesta completa pasa a `no_evidence` (en modo desarrollada solo se eliminan sus oraciones). Si todas son válidas, se renumeran `[1]`, `[2]`… por orden de aparición. Una cita repetida conserva su número y `[n]` es `citations[n - 1]`.

## Modo desarrollada

`answer_question(..., mode="desarrollada")` (en la API, `QueryRequest.mode`) da una respuesta más completa con **la misma única llamada al modelo**: solo cambian la recuperación, el prompt y la política de citas. `mode="breve"` (por defecto) no cambia nada de lo anterior.

**Recuperación (`retrieve_developed`).** Variables de entorno, con valor por defecto y rango (fuera de rango → `ValueError`, la API responde 503):

| Variable | Defecto | Rango | Efecto |
|---|---|---|---|
| `ATENEO_DEVELOPED_FRAGMENTS` | 16 | 1–30 | Fragmentos recuperados como máximo. Se piden 3× candidatos (tope 60) y se aplica el mismo filtro de fuera del corpus que en breve. |
| `ATENEO_DEVELOPED_PER_DOCUMENT` | 6 | 1–30 | Tope de fragmentos por documento, para que entren varios documentos. Es estricto: si solo un documento es pertinente, se usan como mucho 6 de sus fragmentos. |
| `ATENEO_DEVELOPED_CONTEXT_CHARS` | 30000 | 1000–400000 | Presupuesto total de caracteres de fragmentos en el prompt (~8 000 tokens). |

Primero entran los fragmentos recuperados, por relevancia, mientras quepan en el presupuesto. Después, también por relevancia, cada uno se amplía con el fragmento anterior y el siguiente **de la misma página** (los fragmentos se solapan, así que el texto ampliado es contiguo) si caben y no están ya en otro bloque. El texto ampliado es `página.text[start:end]`, así que los offsets siguen siendo de página; el bloque guarda en `chunks` los fragmentos que lo forman y la cita de una afirmación se toma solo de oraciones contenidas enteras en uno de ellos, con el `chunk_id` de ese fragmento. Así la verificación de CU-05 (cita dentro de su fragmento, `quote == página.text[start:end]`) no cambia. Cada bloque sigue teniendo una sola marca `[Fn]`.

**Prompt (`DEVELOPED_PROMPT`).** Mismas reglas comunes (`RULES`: solo corpus, una marca por afirmación, fragmentos y pregunta como datos, sin aceptar premisas falsas) y la negativa exacta `No encontrado en el corpus.`. Pide en español los títulos `## Planteamiento`, `## Desarrollo`, `## Fundamentación` (un argumento por línea `- argumento [Fn]`), `## Conclusión` y `## Límites del corpus` (lo que los fragmentos no cubren, sin inventarlo), entre 300 y 900 palabras, sin negritas ni tablas. Permite oraciones de enlace sin marca solo si no añaden hechos, normas, cifras ni fechas. La llamada fija `max_tokens` con `ATENEO_LLM_MAX_TOKENS` (3000 por defecto, 100–32000; sin tope algunos proveedores gratuitos cortaban la respuesta); el tiempo de espera se configura con `ATENEO_LLM_TIMEOUT` (segundos, 100 por defecto, 1–600). Nginx corta a los 120 s (`proxy_read_timeout`) y la rotación de claves reintenta con otra clave ante un timeout, así que `ATENEO_LLM_TIMEOUT` debe quedar por debajo de 120 (en el chat, con la reformulación de hasta `ATENEO_REWRITE_TIMEOUT`=15 s, la suma queda en 115 s).

**Política de citas.**

- *Breve* y *chat* descartan solo la oración con una marca inválida (fragmento no entregado, cifras que no están en el fragmento o cita que no pasa la verificación) o con cifras sin marca, como *desarrollada*, y la anotan en `invalid_citations`. Antes una sola oración mala invalidaba la respuesta entera y producía `no_evidence` y respuestas pobres. Si no queda ninguna oración verificable, la respuesta es `no_evidence`. La generación (CU-02) sigue siendo estricta.
- *Desarrollada* elimina solo las oraciones afectadas (`cite_reply(..., partial=True)`). La respuesta se parte en oraciones con sus marcas finales y saltos de línea (`SEGMENT`; un punto sin espacio detrás, como en «1.850», no corta). Se elimina toda oración con alguna marca inválida y toda oración **sin marca que contenga cifras** (una cifra no puede publicarse sin cita). Cada oración eliminada se anota en `invalid_citations` como `{"claim", "reason"}`, además del motivo de cada marca (`marker`/campos de la cita y `reason`). Si no queda ninguna marca verificada, la respuesta es `no_evidence`. La afirmación de cada marca es la de su línea (`claim_in_line`), para que la regla de cifras no mezcle elementos de lista distintos. Una sección cuyo contenido se elimina entero conserva su título.
- La negativa `No encontrado en el corpus.` dentro de «Límites del corpus» no anula una respuesta desarrollada con citas válidas; una respuesta que solo es la negativa no tiene marcas y queda `no_evidence`.
- En ambos modos la API vuelve a verificar todas las citas con `app.citations.validate` antes de guardar: nada sin cita verificada se publica, salvo las oraciones de enlace sin marca y sin cifras (límite ya conocido en breve).

El CLI acepta `ask --mode desarrollada`, y cada pregunta del set dorado puede llevar `"mode": "desarrollada"` (`g10`, `g11`).

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
    mode=request.mode,           # "breve" (por defecto) o "desarrollada"
)
```

Resultado (`dict`), con la forma que consume `app.query.ask`:

| Clave | Valor |
|---|---|
| `question` | Pregunta recibida. |
| `status` | `"answered"` o `"no_evidence"` (valores de `AnswerStatus`). |
| `answer` | Texto con marcas `[n]`, donde `n` remite a `citations[n - 1]`; con `no_evidence`, `No encontrado en el corpus.` |
| `citations` | Lista de `chunk_id`, `document_id`, `title`, `version`, `page`, `page_label`, `start`, `end`, `quote`. Corresponden a `CitationOut` con `title` → `document_title`, `version` → `document_version`, `page` → `page_number` y `position` = índice + 1. `answered` ⇒ al menos una; `no_evidence` ⇒ vacía. |
| `invalid_citations` | Diagnóstico, no se muestra al usuario: citas rechazadas (campos de la cita y `reason`), marcas desconocidas (`marker` y `reason`) y, en modo desarrollada, oraciones eliminadas (`claim` y `reason`). |

`answer_question` solo lee; guardar `Answer` y `Citation` corresponde a la API. Para revalidar citas guardadas antes de devolverlas (p. ej. en el historial) se usa la función pura `verify_citations(citations, sources) -> (válidas, inválidas)`, con citas de las mismas claves que `citations`, con `db_sources(session, chunk_ids)` o `sqlite_sources(ruta, chunk_ids)`. Errores de entrada (año, límite, consulta de más de 1.000 caracteres) se lanzan como `ValueError` (`IngestionError`); errores del proveedor o de la base se propagan.

La salida JSON del CLI `ask` es este mismo `dict`.

## Generación (CU-02, AT-17)

`app.rag.generate.generate_material(source, format, prompt, provider, embedder=..., year=..., subject=..., topic=...)` reutiliza el mismo recorrido: `retrieve`, prompt de sistema con las reglas de CU-01 más las instrucciones del formato (`INSTRUCTIONS`), marcas `[Fn]`, cita exacta y verificación con `cite_reply` (extraído de `answer_question`, sin cambiar CU-01). Solo cambia la afirmación que se cita: la línea o celda de tabla donde está la marca, no las anteriores. Devuelve el mismo `dict` que `answer_question` más `format` y, si la salida no sigue la estructura, `error` con `status` `no_evidence`. La estructura de cada formato y su comprobación (`well_formed`) están en el [contrato](api-contract.md#generación-cu-02-at-17). La API llama a `app.generation.generate`, que elige proveedor y embeddings con las mismas variables que `app.query`.

El proveedor `fake` de generación (`app.rag.generate.fake_provider`) toma hasta tres oraciones recuperadas con más términos del tema y las devuelve en la estructura pedida: un párrafo, un esquema con el tema como raíz, un cuadro `Fuente | Contenido` o un diagrama `tema -> fuente: oración`. Los casos dorados de los cuatro formatos están en `backend/tests/test_generations.py`.

## Proveedores

| Nombre | Uso |
|---|---|
| `fake` | Determinista, sin red ni claves. Devuelve la oración recuperada con más términos de la pregunta y su cita; con el prompt desarrollado, los cinco títulos con la mejor oración de cada uno de los tres mejores fragmentos. Es el que usan pruebas y CI. |
| `openai` | Cualquier API de chat compatible con OpenAI (`/chat/completions`), con `temperature` 0. |

Variables del proveedor `openai`, solo en el entorno local (nunca en Git):

- `ATENEO_LLM_API_KEY` (obligatoria)
- `ATENEO_LLM_MODEL` (obligatoria)
- `ATENEO_LLM_BASE_URL` (opcional, por defecto `https://api.openai.com/v1`)
- `ATENEO_LLM_TIMEOUT` (opcional, segundos por llamada, 100 por defecto)

No se ha fijado proveedor IA para producción.

## Ejecutar en PowerShell

Primero crear el índice de muestra según la [guía de ingestión](ingestion.md). Después, desde `backend`:

```powershell
uv run --frozen python -m app.rag ask --index ../data/sample.sqlite --question "¿Qué conserva la biblioteca ficticia?"
uv run --frozen python -m app.rag ask --index ../data/sample.sqlite --question "¿Cuál es el término exclusivo?" --year 4
uv run --frozen python -m app.rag ask --index ../data/sample.sqlite --question "Explica la biblioteca ficticia y la evaluación" --mode desarrollada
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
