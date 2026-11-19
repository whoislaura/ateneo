# Frontend (AT-05, AT-20, AT-21, AT-23)

React Router sin framework de UI ni librería de estado. Login, sesión y roles (CU-00), la consulta con visor de citas (CU-01, CU-05), la generación de material (CU-02) y la gestión del corpus (CU-03) usan la API real según `docs/api-contract.md`. Historial, examen y feedback siguen con datos ficticios de `frontend/src/mock.ts` hasta sus tareas de integración. El estado de conexión (`/api/v1/health`, `role="status"`) aparece en el pie de cada pantalla y en el login.

## Cliente de la API

`frontend/src/api.ts` reúne los tipos de las respuestas usadas (`User`, `TokenResponse`, `QueryRequest`, `GenerationRequest`, `Answer`, `Citation`, `Page` y, en un bloque aparte, `CorpusDocument` e `IngestionReport`), alineados con `backend/app/schemas.py`, y un único envoltorio `api()` sobre `fetch` que:

- añade `Authorization: Bearer <token>` si hay sesión y `Content-Type: application/json` si hay cuerpo, salvo con `FormData` (el navegador pone el `multipart/form-data` con su boundary);
- convierte cualquier error en `ApiError` con `status`, `code` y `message` del formato `{"error": {...}}` (o un mensaje genérico si la respuesta no lo sigue);
- `errorMessage()` traduce esos errores a mensajes para el usuario (compartido por las pantallas);
- ante un 401 de una petición con token, descarta el token y avisa a `App`, que vuelve al login conservando la ruta pedida y muestra «Tu sesión ha caducado».

En desarrollo Vite redirige `/api` a `http://127.0.0.1:8000`; en producción lo hace Nginx.

## Sesión (CU-00, AT-20)

- Login con correo y contraseña (`POST /auth/login`). Ante cualquier 401/422 se muestra el mismo mensaje genérico, «Correo o contraseña incorrectos.», sin distinguir el motivo; otros fallos muestran «No se pudo iniciar sesión».
- **Token:** en memoria (variable del módulo `api.ts`) con copia en `sessionStorage` (`ateneo.token`). Así sobrevive a recargar la pestaña, desaparece al cerrarla y no se comparte entre pestañas; no se usa `localStorage` para no dejar tokens persistentes en el equipo, frecuente en ordenadores compartidos de la facultad. Cualquier script inyectado (XSS) podría leerlo igual que si estuviera solo en memoria; la mitigación es no insertar HTML sin escapar (React escapa por defecto) y la caducidad de 8 h del backend. Nunca se registra en consola.
- Al arrancar con un token guardado se llama a `GET /auth/me`; mientras tanto se muestra «Comprobando la sesión…». Si falla, se vuelve al login.
- «Cerrar sesión» llama a `POST /auth/logout` y descarta el token aunque la llamada falle.
- La cabecera muestra el nombre y el rol: `student` → Estudiante, `teacher` → Profesor, `admin` → Administrador.
- 403: la navegación y las rutas se filtran por rol; si la API responde 403 igualmente, la pantalla muestra «Tu rol no tiene permiso para esta acción».

## Rutas

| Ruta | Pantalla | Caso de uso |
|---|---|---|
| `/login` | Correo y contraseña | CU-00 |
| `/` | Redirige a la primera pantalla permitida del rol | — |
| `/consulta` | Pregunta por año/asignatura/tema; respuesta con citas | CU-01, CU-05 |
| `/generacion` | Resumen, esquema, cuadro o diagrama de texto | CU-02, CU-05 |
| `/corpus` | Subir, actualizar y retirar material | CU-03 |
| `/historial` | Actividad propia | CU-04 |
| `/examen` | Configurar, responder y corregir examen | CU-06 |
| `/feedback` | Valorar, reportar error o sugerir mejora | CU-10 |

Sin sesión (o con la sesión caducada), cualquier ruta redirige a `/login` y, al entrar, vuelve a la ruta pedida (incluida la query string). Con un rol sin permiso se muestra «Acceso no permitido». Nginx ya devuelve `index.html` para rutas del cliente (`try_files … /index.html`).

## Roles y pantallas

| Pantalla | Estudiante | Profesor | Administrador |
|---|:-:|:-:|:-:|
| Consulta | ✓ | ✓ | |
| Generación | ✓ | ✓ | |
| Corpus | | ✓ | ✓ |
| Historial | ✓ | ✓ | |
| Examen | ✓ | ✓ | |
| Feedback | ✓ | ✓ | ✓ |

La matriz sigue la tabla de endpoints del contrato (consulta, generación, historial y exámenes exigen Estudiante o Profesor; corpus, Profesor o Administrador). Vive en `frontend/src/App.tsx`; el control definitivo es del backend (403).

## Layout común

```
+--------------------------------------------------------------+
| [Saltar al contenido]                                        |
| Ateneo   Consulta Generación ...  Nombre · Profesor [Cerrar] |
+--------------------------------------------------------------+
| <main> contenido de la pantalla                              |
+--------------------------------------------------------------+
| [Estado de conexión]  Aviso de pantallas aún simuladas       |
+--------------------------------------------------------------+
```

La navegación muestra solo las pantallas del rol. Al cambiar de ruta, el foco pasa al contenido principal.

## Wireframes

### Login (CU-00)

```
DERECHO · UNIVERSIDAD DE PINAR DEL RÍO
Ateneo
Un espacio para consultar, comprender y practicar.
[Tu sesión ha caducado…]          ← solo tras un 401
Correo electrónico [____________]
Contraseña         [____________]
[Correo o contraseña incorrectos.] ← role="alert", recibe el foco
[Entrar]
[Estado de conexión]
```

### Consulta (CU-01, CU-05)

```
Consulta
Año [Todos ▾]  Asignatura [____]  Tema [____]   (opcionales)
Pregunta [______________________________]
[Consultar]
«Consultando el corpus…»            ← role="status" mientras carga
-- Respuesta -------------------------------------------------
Texto con marcas en línea [1] … [2]  ← cada marca abre su cita
Fuentes
  [1] Documento, p. 12
  [2] Documento, p. 15
  + Cita [1] ---------------------------------------------+
  | Documento  Título                                     |
  | Versión    9b2e…  (SHA-256 abreviado)                 |
  | Página     12 (impresa: xii)                          |
  | > texto citado exacto                                 |
  | [Ver en la página]                                    |
  | …texto de la página con el fragmento ==resaltado==…   |
  +-------------------------------------------------------+
```

`POST /queries` recibe `question` y, si se rellenan, `year`, `subject` y `topic`. Estados: vacío inicial, cargando, error (`role="alert"`, enlazado a la pregunta con `aria-describedby`), `answered` y `no_evidence` («Sin evidencia en el corpus», sin citas). Al llegar la respuesta o el error, el foco pasa al encabezado o al mensaje. Las sugerencias de asignatura y tema salen aún de `mock.ts`.

El visor muestra la copia guardada de la cita y, a petición, carga `GET /documents/{id}/pages/{n}`. Si la versión vigente coincide con `document_version` y `text[start:end] == quote`, resalta el fragmento con `<mark>` y lo desplaza a la vista; si la versión cambió o el texto no coincide, lo avisa y muestra la página sin resaltar.

### Generación (CU-02, AT-22)

```
Generación de material
Formato ( ) Resumen ( ) Esquema ( ) Cuadro comparativo ( ) Diagrama de texto
Año [Todos ▾]  Asignatura [____]  Tema [____]   (opcionales)
Contenido a sintetizar [______________________]
[Generar]
«Generando a partir del corpus…»     ← role="status" mientras carga
-- Esquema (título del formato) ------------------------------
  resumen:  párrafos con marcas [1]
  esquema:  lista anidada <ul> con marcas
  cuadro:   <table> con caption (el tema), <th scope="col"> y
            <th scope="row"> en la primera columna
  diagrama: Origen ──(relación)──▶ Destino   ← <pre aria-hidden>
            Relaciones: 1. Origen → Destino: relación [1]  ← alternativa textual
Fuentes  [1] Documento, p. N  → mismo visor de citas que Consulta
```

`frontend/src/generacion.tsx` envía `POST /generations` con `format`, `prompt` y los filtros rellenados, y renderiza `content` según `kind` con la estructura del [contrato](api-contract.md#generación-cu-02-at-17). Estados y foco iguales que Consulta: vacío, cargando, error (`role="alert"`, 503 incluido) y `no_evidence` («Sin evidencia en el corpus», sin citas). Las marcas `[n]` de cualquier formato son botones que abren el visor de citas (`MarkedText` y `Citations` de `consulta.tsx`). En el diagrama, el dibujo es solo visual y la lista de relaciones (en el `figcaption`) es la alternativa para lectores de pantalla y contiene las marcas.

### Corpus (CU-03, Profesor/Administrador)

```
Gestión de corpus
-- Subir material | Actualizar «Título» -----------------------
Identificador [________]   ← solo al subir; no se puede cambiar
Título [________]
Año [1.º ▾]  Asignatura [____]  Tema [____]
Documento PDF [Elegir archivo]
[Subir material] [Cancelar]   ← Cancelar solo al actualizar
[=====>      ] «Subiendo, extrayendo e indexando…»  ← mientras procesa
[Error de la API]               ← role="alert", recibe el foco
«Título» indexado: N páginas, M fragmentos. Páginas sin texto: …
-- Material registrado ---------------------------------------
Año [Todos ▾]  Asignatura [____]  Tema [____]  [ ] Incluir retirados  [Filtrar]
| Título | Identificador | Año | Asignatura | Tema | Archivo | Estado | Actualizado | [Actualizar] [Retirar] |
+ Retirar material / Sustituir material ---------+   ← <dialog> modal
| Qué ocurrirá con el documento y sus citas      |
| [Cancelar] [Retirar | Sustituir]               |
+------------------------------------------------+
```

`frontend/src/corpus.tsx`. La lista llama a `GET /documents` con los filtros rellenados (`include_retired=true` si se marca) y muestra el estado: Indexado, Indexado con páginas sin texto o Retirado. Subir envía `POST /documents` como `FormData`; «Actualizar» carga los datos del documento en el mismo formulario (sin identificador) y, tras confirmar en el diálogo, envía `PUT /documents/{id}`. «Retirar» pide confirmación y envía `DELETE`; un retirado no tiene ese botón y se reactiva actualizándolo.

Estados: cargando la lista; lista vacía; procesando (campos y botones deshabilitados, `<progress>` indeterminado y aviso `role="status"`, ya que `fetch` no informa del progreso de subida y casi todo el tiempo es extracción e indexación); éxito con el informe de ingestión; error. Los mensajes de error son los de la API (409 identificador repetido, 413 tamaño, 422 PDF no válido o sin texto, 503 embeddings), salvo 403/404 y fallos de red, que tienen texto propio. El diálogo es un `<dialog>` nativo con `showModal()`: atrapa el foco, empieza en «Cancelar», se cierra con Escape y devuelve el foco al botón que lo abrió. Al pulsar «Actualizar» el foco va al encabezado del formulario; tras retirar, al aviso de resultado.

### Historial (CU-04)

```
Historial
Actividad reciente
| Fecha | Acción (consulta/generación/examen) | Resumen |
```

### Examen (CU-06)

```
Examen
Año [▾]  Asignatura [▾]  Tema [▾]
Cantidad [2]  Dificultad [Media ▾]
[Generar examen]
+ 1. Enunciado ---------------+
| ( ) opción A  ( ) opción B  |
| Correcta/Incorrecta. Fuente: [Documento, p. N]   ← tras corregir
+-----------------------------+
[Ver respuestas]
```

### Feedback (CU-10)

```
Feedback
+ Valoración de la última respuesta +
| ( )1 ( )2 ( )3 ( )4 ( )5          |
+-----------------------------------+
Tipo [Reportar error | Sugerir mejora ▾]
Comentario [______________________]
[Enviar]   → «Envío simulado»
```

## Accesibilidad

Landmarks `header`/`nav`/`main`/`footer`, enlace para saltar al contenido, campos con etiqueta, grupos con `fieldset`/`legend`, tablas con `caption` y encabezados, foco visible y mensajes de envío con `role="status"`. Errores con `role="alert"` enlazados a sus campos con `aria-describedby` y con foco al aparecer; regiones `role="status"` para las cargas; el foco pasa al resultado de la consulta, al visor de la cita y al texto de la página cargada. Las marcas `[n]` son botones con nombre accesible («Cita 1: Documento, p. 12»).

## Comprobación manual

`npm run dev` con la API en `127.0.0.1:8000`. Sin base de datos el login devuelve 500 y la UI muestra el error genérico. Para recorrer los flujos sin backend completo basta un servidor de prueba que responda a `/auth/*`, `/queries`, `/generations` y `/documents…` con las formas del contrato. La pantalla de corpus se puede probar con la API real sobre SQLite (`DATABASE_URL=sqlite:///…` y tablas creadas con `Base.metadata.create_all`): subir, listar, actualizar y retirar funcionan; la consulta y la generación no, porque necesitan pgvector.

## Pendiente

- Integrar historial, examen y feedback con la API y retirar sus datos de `mock.ts`.
- Sugerencias de asignatura y tema a partir de `GET /documents` (AT-10) en lugar de `mock.ts`.
- Validar wireframes con el cliente (AT-07).
