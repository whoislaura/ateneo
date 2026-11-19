# Frontend: wireframes y esqueleto (AT-05)

Esqueleto navegable con React Router y datos ficticios. No hay autenticación real ni llamadas a la API salvo el estado de conexión (`/api/v1/health`), visible en el pie de cada pantalla. Login y roles reales llegan con AT-08/AT-20; las integraciones, con las tareas de UI de cada caso de uso.

Los tipos y datos simulados están en `frontend/src/mock.ts`. Cuando se integre `docs/api-contract.md` (AT-02), alinear esos tipos con el contrato antes de conectar cada pantalla.

## Rutas

| Ruta | Pantalla | Caso de uso |
|---|---|---|
| `/login` | Acceso simulado: elegir rol | CU-00 |
| `/` | Redirige a `/consulta` | — |
| `/consulta` | Pregunta por año/asignatura/tema; respuesta con citas | CU-01, CU-05 |
| `/generacion` | Resumen, esquema, cuadro o diagrama de texto | CU-02, CU-05 |
| `/corpus` | Subir, actualizar y retirar material | CU-03 |
| `/historial` | Actividad propia | CU-04 |
| `/examen` | Configurar, responder y corregir examen | CU-06 |
| `/feedback` | Valorar, reportar error o sugerir mejora | CU-10 |

Sin sesión, cualquier ruta redirige a `/login` y, al entrar, vuelve a la ruta pedida. Con un rol sin permiso se muestra «Acceso no permitido». Nginx ya devuelve `index.html` para rutas del cliente (`try_files … /index.html`).

## Roles y pantallas

| Pantalla | Estudiante | Profesor | Administrador |
|---|:-:|:-:|:-:|
| Consulta | ✓ | ✓ | ✓ |
| Generación | ✓ | ✓ | ✓ |
| Corpus | | ✓ | ✓ |
| Historial | ✓ | ✓ | |
| Examen | ✓ | ✓ | |
| Feedback | ✓ | ✓ | ✓ |

Corpus e historial siguen el alcance (gestión para Profesor/Administrador; historial para Estudiante/Profesor). Examen para Administrador queda pendiente de confirmar con el cliente. La matriz vive en `frontend/src/App.tsx`; el control definitivo corresponde al backend.

## Layout común

```
+--------------------------------------------------------------+
| [Saltar al contenido]                                        |
| Ateneo   Consulta Generación Corpus ...    Profesor [Salir]  |
+--------------------------------------------------------------+
| <main> contenido de la pantalla                              |
+--------------------------------------------------------------+
| [Estado de conexión]  Pantallas de demostración              |
+--------------------------------------------------------------+
```

La navegación muestra solo las pantallas del rol. Al cambiar de ruta, el foco pasa al contenido principal.

## Wireframes

### Login (CU-00)

```
DERECHO · UNIVERSIDAD DE PINAR DEL RÍO
Ateneo
Un espacio para consultar, comprender y practicar.
+ Entrar como (simulado) -------+
| (•) Estudiante                |
| ( ) Profesor                  |
| ( ) Administrador             |
+-------------------------------+
[Entrar]
[Estado de conexión]
```

### Consulta (CU-01, CU-05)

```
Consulta
Año [1.º ▾]  Asignatura [Derecho Romano ▾]  Tema [Fuentes ▾]
Pregunta [______________________________]
[Consultar]
-- Respuesta -------------------------------------------------
Texto con citas en línea [Documento, p. 12] ...
Fuentes
  [Documento, p. 12]  ← al pulsar muestra el fragmento citado
  [Documento, p. 15]
  > «fragmento…» — Documento, p. 12
```

### Generación (CU-02)

```
Generación de material
Año [▾]  Asignatura [▾]  Tema [▾]
Tipo [Resumen | Esquema | Cuadro | Diagrama de texto ▾]
[Generar]
-- Resultado -------------------------------------------------
| texto preformateado (esquema, cuadro o diagrama)           |
Fuentes  [Documento, p. N] ...
```

### Corpus (CU-03, Profesor/Administrador)

```
Gestión de corpus
Año [▾]  Asignatura [▾]  Tema [▾]
Documento PDF [Elegir archivo]
[Subir material]
Material registrado
| Título | Año | Asignatura | Tema | Páginas | Estado | [Actualizar] [Retirar] |
```

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

Landmarks `header`/`nav`/`main`/`footer`, enlace para saltar al contenido, campos con etiqueta, grupos con `fieldset`/`legend`, tablas con `caption` y encabezados, foco visible y mensajes de envío con `role="status"`. Sin framework de UI.

## Pendiente

- Alinear tipos de `mock.ts` con `docs/api-contract.md` (AT-02) y sustituir los datos simulados por llamadas reales.
- Sustituir el rol simulado (guardado en `sessionStorage`) por la sesión real (AT-08/AT-20).
- Validar wireframes con el cliente en la revisión de Sprint 0 (AT-07).
