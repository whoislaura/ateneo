# Prototipo RAG restringido al corpus — Sprint 0

Esta entrega implementa AT-04 (issue #4) sobre el índice textual de [ingestión](ingestion.md). Es un prototipo de línea de comandos en `app.rag.answer`; no añade endpoints. Desde AT-14 también puede recuperar por embeddings en PostgreSQL/pgvector (ver [indexación en PostgreSQL](ingestion.md#indexación-en-postgresql-con-embeddings-at-14)).

## Flujo

1. **Recuperación.** Se eliminan palabras vacías de la pregunta y se buscan los términos restantes en el índice SQLite FTS5 (máximo cinco fragmentos), con los filtros opcionales de año, asignatura y tema. Sin `--index` y con `DATABASE_URL`, se busca la pregunta completa por similitud coseno en pgvector (`--embedder fake|openai`); `answer_question` acepta para ello una función de recuperación en lugar de la ruta del índice.
2. **Rechazo sin soporte.** Si no quedan términos o no hay fragmentos, la respuesta es `No encontrado en el corpus.` y no se llama al modelo.
3. **Generación.** El prompt de sistema (`SYSTEM_PROMPT`) exige responder en español solo con los fragmentos, citar cada afirmación como `[documento, p. N]` y responder `No encontrado en el corpus.` si no hay base. Cada fragmento se entrega con ese encabezado de cita.
4. **Verificación de citas.** Cada cita de la respuesta se compara con los pares documento/página recuperados. Las citas que no corresponden se eliminan del texto y se listan en `invalid_citations`. Una respuesta sin ninguna cita válida se sustituye por `No encontrado en el corpus.`

La salida JSON contiene `answer`, `citations` (documento, título, página física y fragmentos de origen), `invalid_citations` y `supported`.

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

`backend/app/rag/golden_questions.json` contiene el set inicial, sintético y basado solo en la muestra ficticia: seis preguntas con documento y página esperados y cuatro que deben rechazarse (fuera del corpus, filtro sin documentos y pregunta sin términos). Una pregunta con fuentes esperadas pasa si cita al menos una de ellas y ninguna cita inválida; una sin fuentes pasa si se rechaza. `backend/tests/test_rag_answer.py` las ejecuta con el proveedor `fake`.

Con el corpus oficial, el set debe sustituirse por preguntas revisadas por docentes para cada asignatura.

## Límites

- La recuperación vectorial siempre devuelve vecinos, aunque la pregunta esté fuera del corpus; igual que en el caso léxico, el rechazo depende del modelo y de la verificación de citas.
- La recuperación SQLite es léxica (BM25, términos unidos por OR): basta un término coincidente para pasar fragmentos al modelo. El rechazo posterior depende del modelo y de la verificación de citas.
- La verificación comprueba que la cita exista entre los fragmentos recuperados, no que el fragmento respalde la afirmación.
- Las citas solo se reconocen con el formato `[documento, p. N]`; otros formatos cuentan como respuesta sin cita.
- El proveedor `fake` no mide calidad de respuesta; solo verifica el recorrido completo.
- La lista de palabras vacías es mínima y se ajustará con preguntas reales.
