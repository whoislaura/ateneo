# Frontend

React Router sin framework de UI ni librería de estado. Login, sesión y roles (CU-00), la consulta con visor de citas (CU-01, CU-05), la generación de material (CU-02), la gestión del corpus (CU-03), el historial con borrado por entrada o completo (CU-04), los exámenes (CU-06), el feedback (CU-10) y el panel de administración (`/dashboard`) usan la API real según `docs/api-contract.md`. El estado de conexión (`/api/v1/health`, `role="status"`) aparece en el pie de cada pantalla y en el login.

## Cliente de la API

`frontend/src/api.ts` reúne los tipos de las respuestas usadas (`User`, `TokenResponse`, `QueryRequest`, `GenerationRequest`, `Answer`, `Citation`, `Page` y, en un bloque aparte, `CorpusDocument` e `IngestionReport`), alineados con `backend/app/schemas.py`, y un único envoltorio `api()` sobre `fetch` que:

- añade `Authorization: Bearer <token>` si hay sesión y `Content-Type: application/json` si hay cuerpo, salvo con `FormData` (el navegador pone el `multipart/form-data` con su boundary);
- convierte cualquier error en `ApiError` con `status`, `code` y `message` del formato `{"error": {...}}` (o un mensaje genérico si la respuesta no lo sigue);
- `errorMessage()` traduce esos errores a mensajes para el usuario (compartido por las pantallas);
- ante un 401 de una petición con token, descarta el token y avisa a `App`, que vuelve al login conservando la ruta pedida y muestra «Tu sesión ha caducado».

En desarrollo Vite redirige `/api` a `http://127.0.0.1:8000`; en producción lo hace Nginx.

## Sesión (CU-00, AT-20)

- Login con correo y contraseña (`POST /auth/login`). Ante cualquier 401/422 se muestra el mismo mensaje genérico, «Correo o contraseña incorrectos.», sin distinguir el motivo; un 429 muestra el mensaje del backend (cuántos minutos esperar) y otros fallos «No se pudo iniciar sesión».
- **Token:** en memoria (variable del módulo `api.ts`) con copia en `sessionStorage` (`ateneo.token`). Así sobrevive a recargar la pestaña, desaparece al cerrarla y no se comparte entre pestañas; no se usa `localStorage` para no dejar tokens persistentes en el equipo, frecuente en ordenadores compartidos de la facultad. Cualquier script inyectado (XSS) podría leerlo igual que si estuviera solo en memoria; la mitigación es no insertar HTML sin escapar (React escapa por defecto) y la caducidad de 8 h del backend. Nunca se registra en consola.
- Al arrancar con un token guardado se llama a `GET /auth/me`; mientras tanto se muestra «Comprobando la sesión…». Si falla, se vuelve al login.
- «Cerrar sesión» llama a `POST /auth/logout` y descarta el token aunque la llamada falle.
- La cabecera muestra el nombre y el rol: `student` → Estudiante, `teacher` → Profesor, `admin` → Administrador.
- 403: la navegación y las rutas se filtran por rol; si la API responde 403 igualmente, la pantalla muestra «Tu rol no tiene permiso para esta acción».

## Rutas

| Ruta | Pantalla | Caso de uso |
|---|---|---|
| `/login` | Correo y contraseña | CU-00 |
| `/` | Redirige a la primera pantalla permitida del rol (el Panel para el administrador) | — |
| `/dashboard` | Panel de administración con pestañas (`?tab=`) | Admin |
| `/consulta` | Chat con memoria: conversaciones, hilo de burbujas y citas (`?c=ID` abre una conversación) | CU-01, CU-05 |
| `/generacion` | Resumen, esquema, cuadro o diagrama de texto | CU-02, CU-05 |
| `/corpus` | Subir, actualizar y retirar material | CU-03 |
| `/historial` | Actividad propia | CU-04 |
| `/examen` | Configurar, responder y corregir examen | CU-06 |
| `/feedback` | Valorar, reportar error o sugerir mejora | CU-10 |

Sin sesión (o con la sesión caducada), cualquier ruta redirige a `/login` y, al entrar, vuelve a la ruta pedida (incluida la query string). Con un rol sin permiso se muestra «Acceso no permitido». Nginx ya devuelve `index.html` para rutas del cliente (`try_files … /index.html`).

## Roles y pantallas

| Pantalla | Estudiante | Profesor | Administrador |
|---|:-:|:-:|:-:|
| Panel | | | ✓ |
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
| [icono] Ateneo                 (N) Nombre [Profesor] [Salir] |  ← barra superior fija
+------------+-------------------------------------------------+
| Consulta   | <main> contenido (máx. 1040 px, centrado)        |
| Generación |   tarjetas (.card) con formularios y resultados  |
| ...        |                                                 |
| (lateral)  | [● Conexión disponible]          Proyecto Ateneo |
+------------+-------------------------------------------------+
```

La navegación (`<nav class="sidebar">`) muestra solo las pantallas del rol: barra lateral en escritorio y franja horizontal desplazable bajo la cabecera por debajo de 900 px (sin JavaScript extra). Por debajo de 600 px el nombre del usuario y el texto de «Cerrar sesión» se ocultan solo a la vista (los lectores de pantalla los siguen leyendo). Al cambiar de ruta, el foco pasa al contenido principal.

## Sistema visual

Todo el estilo vive en `frontend/src/style.css` (CSS plano, sin dependencias). Los valores se definen como propiedades personalizadas en `:root` y el tema oscuro (`prefers-color-scheme: dark`) solo redefine los colores:

- **Color:** `--primary` (azul académico) con `--primary-hover`, `--primary-soft` y `--on-primary`; neutros `--bg`, `--surface`, `--surface-2`, `--border`, `--border-strong`, `--text`, `--text-muted`; estados `--success`, `--warning`, `--danger` con su fondo `*-bg`; `--accent` (bronce) para citas y `--mark` para el resaltado; `--focus` para el anillo de foco. Todos los pares de texto cumplen WCAG AA (≥ 4,5:1; bordes de campos y foco ≥ 3:1) en ambos temas.
- **Espaciado:** `--space-1` … `--space-7` (4, 8, 12, 16, 24, 32, 48 px). **Radios:** `--radius-sm`, `--radius`, `--radius-lg`, `--radius-pill`. **Sombras:** `--shadow-sm`, `--shadow`, `--shadow-lg`.
- **Tipografía:** pilas del sistema, sin descargar fuentes (la app funciona sin acceso a Internet): `--font-sans` para la interfaz, `--font-serif` para títulos, la respuesta y el texto de las fuentes (lectura de documento), `--font-mono` para identificadores y el diagrama. Escala `--text-xs` … `--text-2xl`.

Convenciones de clases:

| Clase | Uso |
|---|---|
| `.card` | Panel blanco con borde y sombra para formularios y listas; si contiene un único `fieldset`, su `legend` hace de título |
| `.result` | Tarjeta de resultado (respuesta, material generado, examen activo) |
| `button` / `.secondary` / `.danger` / `.secondary.danger` / `.small` / `.link` | Acción principal, secundaria, destructiva (confirmar retirada), destructiva atenuada (en tablas), tamaño compacto y botón con aspecto de enlace |
| `.fields` | Rejilla adaptable de campos (año, asignatura, tema…) |
| `fieldset.options` | Grupo de radios como fichas (formato, valoración) |
| `.status` + `.ok` / `.warning` / `.error` | Avisos; en el pie se muestran como píldora con punto de color |
| `.loading` | Región `role="status"` con indicador giratorio cuando tiene texto (vacía no ocupa espacio) |
| `.empty` | Estado vacío (sin consultas, sin material, historial vacío) |
| `.badge` + `.role` / `.indexed` / `.partial` / `.retired` / `.query` / `.generation` / `.success` / `.warning` / `.danger` | Distintivos de rol, estado del documento, tipo de actividad y estados genéricos (cuenta activa, nivel de log) |
| `.tabs`, `.stats` / `.stat`, `.bars`, `.legend`, `.meta` | Pestañas del panel, tarjetas de cifras, gráfico de barras en CSS con su leyenda y lista de metadatos |
| `.table-wrap` | Contenedor con desplazamiento horizontal propio para tablas anchas (`role="region"`, enfocable) |
| `.citations`, `.cite-num`, `.viewer`, `.source`, `.page` | Lista de fuentes, visor de la cita, cita textual y texto de la página con `<mark>` |
| `.questions`, `.solution`, `.exam-list` | Preguntas numeradas del examen, respuesta esperada y exámenes guardados |

Los iconos son SVG en línea con `aria-hidden="true"` (`Icon` en `App.tsx`); el texto contiguo da el nombre accesible. Con `prefers-reduced-motion: reduce` se desactivan transiciones y animaciones. Diseño comprobado hasta 360 px de ancho sin desplazamiento horizontal de la página.

## Wireframes

### Login (CU-00)

```
+ panel de marca (azul) ---------------+ + tarjeta ---------------------+
| [icono]                               | | Iniciar sesión               |
| DERECHO · UNIVERSIDAD DE PINAR DEL RÍO| | …formulario (abajo)…         |
| Ateneo                                | |                              |
| Un espacio para consultar, …          | |                              |
+---------------------------------------+ +------------------------------+
   (en pantallas estrechas el panel de marca queda encima)

[Tu sesión ha caducado…]          ← solo tras un 401
Correo electrónico [____________]
Contraseña         [____________]
[Correo o contraseña incorrectos.] ← role="alert", recibe el foco
[Entrar]
[Estado de conexión]
```

### Consulta (CU-01, CU-05): chat con memoria

```
Consulta
+ Conversaciones ------+ Título de la conversación        [Borrar conversación]
| [Nueva conversación] | +- role="log" aria-live="polite" ---------------------+
| ¿Qué es la usucap…   | |                      [ burbuja del usuario        ] |
| ¿Plazo de la pre…    | | [ burbuja del asistente con marcas [1] [2]       ] |
| [Ver más]            | |   Fuentes  [1] Documento, p. 12  → visor de citas  |
|                      | | «Pensando…»  ← role="status" mientras espera       |
|                      | | [ error ] [Reintentar]                             |
|                      | +-----------------------------------------------------+
|                      | > Filtros del corpus (opcionales): año, asignatura, tema
|                      | Pregunta [______]   [Enviar]  Enter envía; Shift+Enter salta
+----------------------+
```

Usa `POST /conversations` (primer mensaje) y `POST /conversations/{id}/messages`; la lista sale de `GET /conversations` (20 por página, «Ver más»), el hilo de `GET /conversations/{id}` y «Borrar conversación» (con `<dialog>` de confirmación) de `DELETE /conversations/{id}`. No hay selector de modo: el chat responde siempre en el modo `chat` del backend. La pregunta aparece enseguida como burbuja; si la petición falla, el error se muestra como mensaje del asistente (`role="alert"`) con un botón «Reintentar» que reenvía la misma pregunta con los filtros actuales. Mientras espera no se puede enviar, cambiar de conversación ni borrar. El hilo es `role="log"` con `aria-live="polite"`, la caja de entrada tiene `<label>` y la ayuda de teclado va enlazada con `aria-describedby`. Las burbujas del asistente reutilizan `AnswerText` (que renderiza `content` por líneas: `## Título` como `<h3>`, líneas `- …` como lista, el resto como párrafos), `Citations` y el visor de citas, con ids propios por mensaje (`useId`); abrir una cita cierra la de otro mensaje. El enlace «Enviar feedback de esta respuesta» usa el `answer_id` del mensaje. El Historial muestra las conversaciones con un botón «Abrir» (`/consulta?c=ID`).

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

Consulta `GET /api/v1/history` con la sesión activa. Muestra las consultas y generaciones propias en páginas de 20, de la más reciente a la más antigua.

```
Historial
Actividad reciente
| Fecha | Acción (consulta/generación) | Resumen |
```

### Examen (CU-06)

Permite generar y volver a abrir exámenes propios. El examen es mixto (test, verdadero o falso, desarrollo y caso práctico) y se pueden marcar los tipos que se quieren; generarlo tarda unos segundos porque lo redacta la IA. Los enunciados se muestran primero y el botón «Ver respuestas» carga las soluciones y el criterio de corrección con el texto exacto de la cita, el documento y la página. «Descargar examen (PDF)» y «Descargar clave (PDF)» bajan el examen para el estudiante y la clave del profesor.

```
Examen
Año [▾]  Asignatura [▾]  Tema [▾]
Cantidad [2]  Dificultad [Media ▾]
Tipos [ ] Test [ ] V/F [ ] Desarrollo [ ] Caso
[Generar examen]
[Descargar examen (PDF)] [Descargar clave (PDF)]
+ 1. Test · 1 pt -------------+
| Enunciado                   |
| ( ) A) …  ( ) B) …          |
+-----------------------------+
[Ver respuestas]
```

### Feedback (CU-10)

Guarda valoraciones, reportes y sugerencias. Los enlaces de consulta, generación y examen adjuntan el ID del recurso al feedback.

```
Feedback
+ Valoración +
| ( )1 ( )2 ( )3 ( )4 ( )5          |
+-----------------------------------+
Tipo [Reportar error | Sugerir mejora ▾]
Comentario [______________________]
[Enviar feedback] → «Tu feedback se guardó»
```

### Panel de administración (solo Administrador)

`frontend/src/dashboard/` (una pestaña por archivo; tipos en `frontend/src/admin-api.ts`, rutas `/api/v1/admin/*`). Es la pantalla inicial del administrador; los demás roles ven «Acceso no permitido». Las pestañas siguen el patrón WAI-ARIA (`role="tablist"`, flechas, Inicio y Fin, activación automática) y la activa se guarda en `?tab=` para sobrevivir a una recarga.

| Pestaña (`?tab=`) | Contenido |
|---|---|
| Resumen (`resumen`) | Cifras de `GET /admin/stats`: cuentas por rol y activas, documentos activos/retirados, páginas y páginas sin texto, actividad total y % sin evidencia; gráfico de barras apiladas de 7 días en CSS (`aria-hidden`) con la tabla de datos como alternativa |
| Cuentas (`cuentas`) | Crear cuenta (contraseña ≥ 8); lista paginada con búsqueda y filtro de rol; por fila: cambiar rol, activar/desactivar, restablecer contraseña y cerrar sesiones, siempre en un `<dialog>` modal. Los 409/422 de la API (correo repetido, último admin, desactivarse a sí mismo) se muestran dentro del diálogo |
| Materiales (`materiales`) | `GET /documents?include_retired=true` con recuento por estado; subir, actualizar y retirar se hacen en Corpus (enlace) |
| Consultas (`consultas`) | Consultas y generaciones de todas las cuentas, paginadas y filtrables por tipo y estado. «Ver» abre la respuesta completa (`?answer=ID`, `GET /admin/answers/{id}`) con el mismo renderizado y visor de citas que Consulta y Generación |
| Feedback (`feedback`) | Feedback paginado con filtro de tipo, valoración y enlace a la respuesta relacionada (`?tab=consultas&answer=ID`) |
| Logs (`logs`) | Últimas entradas del búfer en memoria (las 1000 últimas del proceso actual) con nivel mínimo, búsqueda, botón «Actualizar» y actualización automática cada 10 s (desactivada por defecto); la excepción se despliega con `<details>` |

Las listas paginan como Historial (`limit = 21`: la fila extra activa «Siguiente») y comparten los estados de carga, vacío y error (con «Reintentar»).

## Accesibilidad

Landmarks `header`/`nav`/`main`/`footer`, enlace para saltar al contenido, foco visible con contraste ≥ 3:1 en ambos temas, contraste AA, respeto de `prefers-reduced-motion`, campos con etiqueta, grupos con `fieldset`/`legend`, tablas con `caption` y encabezados, foco visible y mensajes de envío con `role="status"`. Errores con `role="alert"` enlazados a sus campos con `aria-describedby` y con foco al aparecer; regiones `role="status"` para las cargas; el foco pasa al resultado de la consulta, al visor de la cita y al texto de la página cargada. Las marcas `[n]` son botones con nombre accesible («Cita 1: Documento, p. 12»).

## Comprobación manual

`npm run dev` con la API en `127.0.0.1:8000`. Sin base de datos el login devuelve 500 y la UI muestra el error genérico. Para recorrer los flujos sin backend completo basta un servidor de prueba que responda a `/auth/*`, `/queries`, `/generations` y `/documents…` con las formas del contrato. La pantalla de corpus se puede probar con la API real sobre SQLite (`DATABASE_URL=sqlite:///…` y tablas creadas con `Base.metadata.create_all`): subir, listar, actualizar y retirar funcionan; la consulta y la generación no, porque necesitan pgvector.

## Pendiente

- Sugerencias de asignatura y tema a partir de `GET /documents` (AT-10) en lugar de `mock.ts`.
- Validar wireframes con el cliente (AT-07).
