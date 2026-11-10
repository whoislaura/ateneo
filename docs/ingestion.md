# Ingestión de PDFs e índice de muestra — Sprint 0

Esta entrega implementa AT-03 (issue #3). Funciona localmente con PDFs que contienen texto seleccionable, sin servidor ni claves IA. El corpus oficial aún no está disponible. La muestra es ficticia y no permite evaluar exactitud académica.

## Ejecutar la muestra en PowerShell

Desde la raíz del repositorio, con uv y Python 3.12 disponibles:

```powershell
Set-Location backend
uv sync --frozen
uv run --frozen python -m app.rag sample --output ../data/sample
uv run --frozen python -m app.rag ingest --pdf ../data/sample/muestra-a.pdf --metadata ../data/sample/muestra-a.json --index ../data/sample.sqlite
uv run --frozen python -m app.rag ingest --pdf ../data/sample/muestra-b.pdf --metadata ../data/sample/muestra-b.json --index ../data/sample.sqlite
uv run --frozen python -m app.rag search --index ../data/sample.sqlite --query azafran
uv run --frozen python -m app.rag search --index ../data/sample.sqlite --query biblioteca --year 4 --subject "Asignatura ficticia B" --topic "Evaluación"
```

La primera búsqueda devuelve la página física 1 de `muestra-a`. La segunda limita los resultados a `muestra-b`. La página 2 de `muestra-a` está vacía a propósito: su ingestión devuelve `status: partial` y `no_text_pages: [2]`. Ese estado no implica un fallo de escritura; informa de cobertura de extracción incompleta.

`sample` genera dos PDFs reproducibles (3 y 2 páginas) y sus metadatos. Para repetirlo, usar otra carpeta; el comando rechaza sobrescribir los archivos existentes. `ingest` sí admite repetirse: sustituye el documento identificado sin duplicarlo. Los comandos escriben JSON por stdout; errores operativos van a stderr y devuelven código 1. Argumentos inválidos devuelven código 2.

## Metadatos de entrada

Archivo JSON UTF-8, con todos los campos obligatorios y sin campos adicionales:

```json
{
  "document_id": "muestra-a",
  "title": "Muestra sintética muestra-a",
  "year": 1,
  "subject": "Asignatura ficticia A",
  "topic": "Biblioteca"
}
```

`year` es un entero de 1 a 4; las cadenas no pueden quedar vacías. El identificador es estable y lo proporciona el operador. Una ingestión corresponde a una clasificación de año/asignatura/tema; la clasificación múltiple se coordinará con Pedro para el contrato de producción. No se infiere ningún dato académico del nombre del PDF.

## Contrato interno para integrar con Pedro

Las estructuras están en `app.rag.ingestion`; no constituyen tablas definitivas ni endpoints del backend.

| Estructura | Contenido |
|---|---|
| `DocumentMetadata` | Identificador, título, año, asignatura y tema validados. |
| `Document` | Metadatos, nombre del archivo (sin ruta), SHA-256 de los bytes como versión, configuración de chunking, páginas y fragmentos. |
| `Page` | Número físico desde 1, etiqueta si el PDF la incorpora, texto normalizado y estado `text`/`no_text`. Documento y versión se obtienen de su `Document`. |
| `Chunk` | Identificador determinista, página, posiciones `start`/`end` y texto; documento y versión se obtienen de su `Document` y se guardan explícitamente al indexar. |

La página física y la etiqueta del PDF se conservan separadas. No se interpreta como número impreso un pie de página ni se inventan etiquetas ausentes. Los offsets son índices de caracteres Python sobre el texto normalizado, con final exclusivo: `page.text[start:end] == chunk.text`. No son posiciones de bytes ni coordenadas visuales.

La normalización usa Unicode NFC, unifica saltos de línea, elimina NUL y espacios redundantes y conserva separaciones de párrafos. No elimina encabezados/pies ni intenta reconstruir tablas o separar columnas.

## Chunking

Valores iniciales: máximo 1.200 caracteres y solapamiento objetivo 200. Se pueden cambiar con `--chunk-size` y `--overlap`; el solapamiento debe ser menor que el tamaño. Las unidades son caracteres, no tokens del modelo.

Los cortes se ajustan a palabras cuando es posible. El solapamiento efectivo puede ser menor para respetar palabras o evitar repetir un fragmento corto. Una palabra mayor que el límite se divide. Ningún fragmento cruza páginas; no se omite contenido no blanco. Los identificadores dependen del documento, versión, página, offsets, texto y versión del algoritmo (`ateneo-chunk-v1`).

Estos valores son una hipótesis de trabajo: se ajustarán con bibliografía real y evaluación RAG.

## Índice textual local

SQLite FTS5, incluido en el Python utilizado en desarrollo y comprobado en CI. Un único archivo guarda `documents`, `pages`, `chunks` y un marcador de versión de esquema. Es un artefacto de muestra, no una migración del modelo PostgreSQL/pgvector de producción.

- Tokenización Unicode, búsqueda textual sin distinguir mayúsculas ni acentos.
- Los términos de la consulta se buscan como literales unidos por OR. La consulta no ejecuta operadores FTS introducidos por el usuario.
- Orden BM25 ascendente y desempate por identificador de fragmento; máximo cinco resultados. El score no expresa una probabilidad de corrección.
- Filtros exactos por año/asignatura/tema; las cadenas se normalizan a NFC, se recortan y se comparan sin distinguir mayúsculas. En los filtros los acentos sí son significativos.
- Cada resultado contiene documento, título, archivo, versión, clasificación, página física, etiqueta, offsets, texto y score.
- Sin coincidencias devuelve `[]`. Una ruta de índice inexistente da error sin crear un archivo vacío.
- Límite de consulta: 1.000 caracteres. El límite de resultados admite de 1 a 5.

La extracción completa ocurre antes de abrir la transacción de escritura. Se reemplazan juntos los metadatos, páginas y fragmentos del identificador recibido. Un error conserva la versión anterior y los demás documentos. El índice mantiene solo la versión actual; no reemplaza el historial académico CU-04 que corresponde al backend. No se reutilizan archivos SQLite ajenos ni esquemas de muestra incompatibles.

## Límites y revisión del material

- No hay OCR. `no_text` puede significar página vacía, imagen o contenido que el extractor no interpreta. Un PDF parcialmente legible se indexa con advertencias; uno enteramente sin texto se rechaza.
- Los PDFs cifrados o dañados se rechazan con un error. No se solicitan ni almacenan contraseñas.
- No hay embeddings, generación IA ni citas generadas por un modelo; la salida son fragmentos y sus referencias verificables.
- Los documentos se procesan en memoria. Esta herramienta CLI es para muestras controladas. Límites de tamaño, aislamiento del parser y procesamiento de archivos subidos se definirán al integrarla con CU-03.
- PDFs, metadatos de muestra e índices generados se guardan bajo `data/`, fuera de Git. El generador y sus pruebas sí se versionan. ReportLab es dependencia de desarrollo; la extracción solo necesita pypdf.

## Comprobación

Desde la raíz:

```powershell
uv run --frozen --project backend ruff check backend infra/smoke.py
uv run --frozen --project backend pytest backend/tests
```

Las pruebas cubren extracción, etiquetas, caracteres españoles, cobertura y solapamiento, filtros, reingestión, rollback, errores y recorrido CLI completo. CI las ejecuta con las comprobaciones existentes de frontend y contenedores.

La aceptación académica requerirá documentos oficiales y preguntas revisadas por docentes. La entrega final debe cubrir todas las asignaturas de 1.º a 4.º año; esta muestra no acredita esa cobertura.
