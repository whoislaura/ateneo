# Revisión funcional con el cliente

Kit para las revisiones de Sprint 0 (#7) y Sprint 1 (#26) y para la demo de cierre (#38). La reunión la conduce el equipo; este documento fija qué preparar, qué enseñar, qué decir y cómo registrar la aceptación. Los comandos de puesta en marcha están en la [guía de demo](demo.md).

Casos de uso del MVP ([alcance](scope.md)): CU-00 acceso, CU-01 consulta, CU-02 generación de material, CU-03 gestión de corpus, CU-04 historial, CU-05 fuentes y citas, CU-06 exámenes y CU-10 feedback. CU-07 a CU-09 no forman parte del MVP.

## Preparación (día anterior y 30 min antes)

- [ ] **Entorno principal:** demo en Render, https://ateneo-web.onrender.com. La API se duerme tras 15 min sin uso y tarda alrededor de 1 min en despertar: abrir la web 10–15 min antes, esperar a que el pie muestre «Conexión disponible.» y hacer una consulta de prueba. Volver a usarla cada pocos minutos si la reunión se retrasa.
- [ ] **Cuentas:** `admin@upr.edu.cu`, `profe@upr.edu.cu` y `estudiante@upr.edu.cu`. Las contraseñas las tiene el equipo fuera del repositorio; no proyectarlas ni dictarlas. Probar cada una antes: 5 intentos fallidos bloquean esa cuenta 15 min, y en Render el límite por IP es común a todos los usuarios de la demo.
- [ ] **Corpus:** entrar como profesor, abrir **Corpus** y comprobar que `muestra-a` y `muestra-b` aparecen en «Material registrado» con los metadatos de [Corpus de muestra](demo.md#corpus-de-muestra). Tener también los PDF de muestra generados en el equipo del presentador para la subida en vivo.
- [ ] **Datos limpios:** como estudiante, vaciar el historial de ensayos previos con «Borrar todo el historial» si conviene empezar de cero.
- [ ] **Navegador:** Chrome, Firefox o Edge recientes, ventana privada por rol (la sesión vive en `sessionStorage` y no se comparte entre pestañas), zoom al 125 % para proyectar. Desactivar notificaciones.
- [ ] **Plan B:** stack local con Docker siguiendo la [guía de demo](demo.md#demo-local-con-docker), ya arrancado y con el corpus cargado en el portátil del presentador. Si Render no responde en 2 min, cambiar a `http://localhost:8080` sin depurar en directo.
- [ ] **Roles en la reunión:** un presentador, una persona que anota en la [plantilla de feedback](#registro-de-feedback) y una que lleva el tiempo.
- [ ] Imprimir o compartir la [lista de aceptación](#lista-de-aceptación).

## Agenda (45 min)

| Min | Bloque | Contenido |
|---|---|---|
| 0–5 | Apertura | Objetivo de la revisión, alcance del sprint y [límites conocidos](#límites-conocidos) |
| 5–8 | Acceso y roles | CU-00: login, barra superior con usuario y rol, menú lateral por rol |
| 8–22 | Estudiante | CU-01, CU-05, CU-02, CU-06, CU-04, CU-10 |
| 22–30 | Profesor | CU-03: subir, actualizar y retirar material; lo que añade al rol de estudiante |
| 30–34 | Administrador | CU-03 con retirados, CU-10, pantallas no permitidas |
| 34–42 | Aceptación y feedback | Recorrer la lista de aceptación, recoger observaciones y cambios pedidos |
| 42–45 | Cierre | Decisiones, responsables y siguiente revisión |

En las revisiones de sprint, enseñar solo los casos entregados en ese sprint y marcar el resto como «no aplica»; en la demo de cierre (#38), todos.

## Límites conocidos

Decirlos en la apertura, antes de enseñar nada:

- **IA de demostración:** el proveedor `fake` es determinista. Enseña el flujo completo y que cada afirmación lleva cita verificable, pero no la calidad del texto. La calidad se evalúa con el proveedor real ([QA del RAG](qa-rag.md)).
- **Corpus sintético:** `muestra-a` y `muestra-b` son PDF ficticios sin validez académica. El alcance sigue siendo todas las asignaturas de 1.º a 4.º, pendiente de que el cliente entregue la bibliografía oficial.
- **Sin OCR:** solo PDF con texto seleccionable; las páginas escaneadas quedan sin texto y el sistema lo indica.
- **Usuarios por consola:** no hay registro ni pantalla de administración de usuarios; altas, roles, contraseñas y bajas las hace el equipo técnico.
- **Feedback sin pantalla de lectura:** se guarda en la base y lo revisa el equipo.
- **Demo gratuita:** Render se duerme y tarda en despertar; no representa el rendimiento de producción.

## Guion por rol

Formato: **Mostrar** lo que se hace en pantalla, **Decir** el mensaje para el cliente, **Esperado** lo que debe verse.

### Acceso (CU-00)

1. **Mostrar:** pantalla de login («Iniciar sesión», «Correo electrónico», «Contraseña», «Entrar»). Introducir una contraseña errónea una vez.
   **Decir:** no hay registro público; el mensaje no revela si el correo existe.
   **Esperado:** «Correo o contraseña incorrectos.»
2. **Mostrar:** entrar como `estudiante@upr.edu.cu`.
   **Esperado:** barra superior con inicial, nombre, distintivo «Estudiante» y «Cerrar sesión»; menú lateral con Consulta, Generación, Historial, Examen y Feedback; pie con «Conexión disponible.».

### Estudiante

3. **Consulta con cita (CU-01, CU-05).** **Mostrar:** **Consulta**, pregunta `¿Dónde aparece azafrán?`, «Consultar». Pulsar la marca [1] o la fuente en «Fuentes»; en el visor «Cita [1]», pulsar «Ver en la página».
   **Decir:** cada afirmación remite a documento, versión y página; el estudiante puede comprobar el texto original.
   **Esperado:** bloque «Respuesta» con [1]; visor con Documento, Versión y Página 1 de `muestra-a`; la página con el fragmento resaltado.
4. **Sin evidencia (CU-01).** **Mostrar:** misma pregunta con Año «2.º año» (no hay material de ese año).
   **Decir:** si el corpus no respalda una respuesta, el sistema lo dice en lugar de inventar.
   **Esperado:** «Sin evidencia en el corpus», sin fuentes.
5. **Generación (CU-02).** **Mostrar:** **Generación**, formato «Resumen», contenido `azafrán`, «Generar». Repetir con «Esquema», «Cuadro comparativo» y «Diagrama de texto».
   **Decir:** el material se sintetiza solo desde el corpus y lleva las mismas citas verificables.
   **Esperado:** contenido del formato elegido con marcas [n] que abren el visor de citas.
6. **Examen (CU-06, CU-05).** **Mostrar:** **Examen** → «Configurar examen»: 1.º año, Asignatura `Asignatura ficticia A`, Cantidad de preguntas 2, Dificultad «Media», «Generar examen». Escribir una respuesta y pulsar «Ver respuestas».
   **Decir:** las preguntas salen del material de la asignatura; cada respuesta esperada muestra su fuente.
   **Esperado:** examen en «Exámenes guardados»; tras «Ver respuestas», «Respuesta esperada» y la cita con documento y página de cada pregunta.
7. **Historial (CU-04).** **Mostrar:** **Historial** → tabla «Actividad reciente» con Fecha, Acción y Resumen. Eliminar una entrada con «Eliminar» y confirmar.
   **Decir:** cada usuario ve solo su actividad y puede borrarla, una a una o entera («Borrar todo el historial»). Los exámenes se guardan aparte, en la pantalla Examen.
   **Esperado:** entradas «Consulta» y «Generación» de los pasos 3–5; tras borrar, «Entrada eliminada.».
8. **Feedback (CU-10).** **Mostrar:** desde una respuesta o examen, «Enviar feedback de esta respuesta» / «de este examen». Tipo «Valoración», puntuación 1–5, «Enviar feedback». Enseñar también «Reportar error» y «Sugerir mejora» (comentario obligatorio).
   **Esperado:** nota «Sobre la respuesta …» o «Sobre el examen …» y «Tu feedback se guardó.».

### Profesor

9. **Mostrar:** «Cerrar sesión» y entrar como `profe@upr.edu.cu`.
   **Decir:** el profesor tiene todo lo del estudiante y además gestiona el corpus.
   **Esperado:** distintivo «Profesor» y la entrada **Corpus** en el menú.
10. **Subir material (CU-03).** **Mostrar:** **Corpus** («Gestión de corpus») → «Subir material»: Identificador `muestra-demo`, Título, Año, Asignatura, Tema, Documento PDF (`muestra-a.pdf` del equipo), «Subir material».
    **Decir:** al subir, el PDF se extrae e indexa en el momento; el informe dice qué páginas no tienen texto (no hay OCR).
    **Esperado:** ««Título» indexado: N páginas, M fragmentos. Páginas sin texto extraíble: 2; …»; en «Material registrado», estado «Indexado con páginas sin texto».
11. **Actualizar (CU-03).** **Mostrar:** «Actualizar» en `muestra-demo`, cambiar el título, elegir el PDF, «Actualizar material» y confirmar «Sustituir».
    **Decir:** las citas ya guardadas conservan su copia; el visor avisa si el documento cambió.
12. **Retirar (CU-03).** **Mostrar:** «Retirar» en `muestra-demo` y confirmar en «Retirar material».
    **Decir:** retirar no borra: deja de usarse en consultas nuevas y se puede reactivar subiendo una nueva versión.
    **Esperado:** ««Título» retirado: ya no se usa en respuestas nuevas.»; desaparece de la lista y con «Incluir retirados» + «Filtrar» aparece como «Retirado».

No retirar `muestra-a` ni `muestra-b`: el resto del guion depende de ellos.

### Administrador

13. **Mostrar:** entrar como `admin@upr.edu.cu`.
    **Esperado:** distintivo «Administrador»; menú solo con Corpus y Feedback.
14. **Mostrar:** **Corpus** con «Incluir retirados» → `muestra-demo` «Retirado». Escribir `/consulta` en la barra de direcciones.
    **Decir:** el administrador gestiona material y envía feedback, pero no consulta ni hace exámenes, por contrato.
    **Esperado:** «Acceso no permitido».
15. **Mostrar:** **Feedback** → «Sugerir mejora» con un comentario.
    **Esperado:** «Tu feedback se guardó.».

## Lista de aceptación

Revisión: ☐ Sprint 0 (#7) ☐ Sprint 1 (#26) ☐ Cierre (#38) · Fecha: ____ · Entorno: ☐ Render ☐ Local

| CU | Criterio de aceptación | Paso | Resultado (OK / Obs. / N. A.) | Observación |
|---|---|---|---|---|
| CU-00 | Solo usuarios dados de alta entran; credenciales erróneas dan un mensaje genérico; cada rol ve solo sus pantallas | 1, 2, 9, 13, 14 | | |
| CU-01 | Una pregunta obtiene respuesta basada en el corpus, filtrable por año, asignatura y tema; sin respaldo responde «Sin evidencia en el corpus» | 3, 4 | | |
| CU-02 | Se generan resumen, esquema, cuadro comparativo y diagrama de texto a partir del corpus | 5 | | |
| CU-03 | Profesor y administrador suben, actualizan y retiran PDF; el estudiante no gestiona el corpus | 10–12, 14 | | |
| CU-04 | El usuario ve sus consultas y generaciones, más recientes primero, y puede borrarlas | 7 | | |
| CU-05 | Toda respuesta, material y respuesta de examen lleva citas con documento y página; la cita se comprueba en la página original | 3, 5, 6 | | |
| CU-06 | Se configura un examen por año, asignatura, tema, cantidad y dificultad; las respuestas esperadas se muestran con fuente | 6 | | |
| CU-10 | Se puede valorar (1–5), reportar un error o sugerir una mejora, vinculado o no a una respuesta o examen | 8, 15 | | |

Aceptación global: ☐ Aceptado ☐ Aceptado con observaciones ☐ No aceptado

| | Nombre | Cargo | Firma |
|---|---|---|---|
| Cliente | | | |
| Equipo | | | |

## Registro de feedback

Una fila por observación, anotada en el momento y leída en voz alta en el bloque de aceptación.

| # | CU / pantalla | Observación (literal del cliente) | Tipo (error / cambio / nueva función / duda) | Severidad | Cambio solicitado | Decisión | Responsable |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |

Severidad: **Bloqueante** (impide aceptar el CU), **Alta** (debe resolverse antes de la entrega), **Media** (se planifica), **Baja** (mejora opcional).
Decisión: **Aceptado para el MVP**, **Fuera de alcance** (ver límites del [alcance](scope.md); requiere acuerdo de cambio) o **Pendiente** (falta información del cliente).

Decisiones de la reunión: ______ · Próxima revisión: ______

## De la reunión a GitHub

En las 24 h siguientes:

1. Comentar en la issue de la revisión (#7, #26 o #38) el resultado de la lista de aceptación, el enlace al acta y las decisiones.
2. Por cada fila **Aceptado para el MVP**, abrir una issue con la plantilla «Error» (comportamiento incorrecto) o «Tarea» (cambio pedido), con:
   - título `[Revisión Sprint N] CU-XX: resumen breve`;
   - el texto literal del cliente, el paso del guion y el entorno en que se vio;
   - criterio de aceptación observable;
   - `Refs #7`, `#26` o `#38` según la reunión.
3. Agruparlas como en #32 (ajustes del RAG por feedback: recuperación, citas, prompts) y #34 (correcciones finales de backend): si una observación encaja en una issue abierta, comentar allí en lugar de abrir otra.
4. **Fuera de alcance:** una sola issue de propuesta de cambio con todas las peticiones, para negociar con el cliente; no se planifica sin acuerdo.
5. **Pendiente:** issue asignada a quien debe pedir la información, con fecha de la siguiente revisión.
6. No incluir contraseñas, datos personales ni contenido privado del corpus en las issues.
