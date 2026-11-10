# Backlog acordado

Cada fila corresponde a una tarea proporcionada por Laura. El sprint y el responsable se conservan.

## Sprint 0

| ID | Responsable | Tarea |
|---|---|---|
| AT-01 | Laura | Crear repositorio, pipeline CI/CD, entornos y secretos; esqueleto de despliegue web |
| AT-02 | Pedro | Definir contrato API y modelo de datos: usuarios/roles, documentos, chunks, citas, historial, exámenes, feedback |
| AT-03 | Laura | Diseñar esquema de ingestión: PDF a texto por página, metadatos año/asignatura/tema, chunking e índice de muestra |
| AT-04 | Laura | Prototipo RAG restringido al corpus con prompt y citado obligatorio; set inicial de preguntas doradas |
| AT-05 | Ray | Wireframes mínimos y esqueleto frontend: login, layout por rol, rutas y pantallas mock de consulta, corpus, historial, examen y feedback |
| AT-06 | Todos | Cargar corpus de muestra y hacer smoke test integral en staging |
| AT-07 | Todos | Revisión funcional de Sprint 0 con el cliente |

## Sprint 1

| ID | Responsable | Tarea |
|---|---|---|
| AT-08 | Pedro | Autenticación y roles CU-00: login, sesión y permisos Estudiante/Profesor/Administrador |
| AT-09 | Pedro | API de consulta CU-01: pregunta por año, asignatura y tema; orquesta RAG y devuelve respuesta + citas |
| AT-10 | Pedro | API de gestión de corpus CU-03: subir, actualizar y retirar material por año/asignatura |
| AT-11 | Pedro | API de historial CU-04: registrar fecha, autor, acción y resumen; exponerlo a estudiantes/profesores |
| AT-12 | Pedro | Contrato y validación de fuentes/citas CU-05 en todas las respuestas de CU-01 y CU-02 |
| AT-13 | Pedro | DevOps Sprint 1: despliegue, logs, manejo de errores, configuración de cuentas IA rotativas y respaldo básico |
| AT-14 | Laura | Ingestión completa del corpus de muestra: PDF por página, metadatos, chunking, embeddings e indexación |
| AT-15 | Laura | Recuperación y generación CU-01: búsqueda de fragmentos, respuesta en español restringida al corpus y citado |
| AT-16 | Laura | Verificador de citas CU-05: mapear chunk a documento/página y validar que la cita exista |
| AT-17 | Laura | Generadores CU-02: resumen textual, esquema jerárquico, cuadro comparativo y diagrama simple en texto, siempre con fuentes |
| AT-18 | Laura | Reindexación al subir, actualizar o retirar material |
| AT-19 | Laura | QA RAG Sprint 1: pruebas de alucinación, preguntas fuera del corpus y ajuste de prompts |
| AT-20 | Ray | UI login/roles CU-00 |
| AT-21 | Ray | UI consulta CU-01 + visor de fuentes/citas CU-05 |
| AT-22 | Ray | UI generación CU-02: selector de formato y render de resumen/esquema/cuadro/diagrama texto |
| AT-23 | Ray | UI gestión de corpus CU-03 para Profesor/Administrador |
| AT-24 | Ray | UI historial CU-04 visible para estudiantes y profesores |
| AT-25 | Ray | Integración Sprint 1: estados de carga/error/vacío y pruebas de flujo completo |
| AT-26 | Todos | Revisión funcional de Sprint 1 con el cliente |

## Sprint 2

| ID | Responsable | Tarea |
|---|---|---|
| AT-27 | Pedro | API de exámenes CU-06: configuración asignatura/tema/cantidad/dificultad, generación y consulta de respuestas |
| AT-28 | Pedro | API de feedback CU-10: registrar valoración, error reportado y sugerencia |
| AT-29 | Pedro | Ajustes de backend derivados de Sprint 1 y feedback; seguridad, validaciones y rendimiento básico |
| AT-30 | Pedro | Despliegue final, repositorio del cliente y configuración de entrega |
| AT-31 | Laura | Lógica de generación de exámenes CU-06: preguntas por dificultad desde corpus, respuestas y fuentes |
| AT-32 | Laura | Ajustes RAG por feedback: recuperación, citas y prompts; pruebas de regresión |
| AT-33 | Laura | QA final RAG: calidad de exámenes, citas completas, alucinaciones y carga básica |
| AT-34 | Laura | Apoyo backend a exámenes, feedback y correcciones finales |
| AT-35 | Ray | UI exámenes CU-06: selección de asignatura/tema/cantidad/dificultad, examen y consulta de respuestas |
| AT-36 | Ray | UI feedback CU-10: reportar error, valorar respuesta y sugerir mejora |
| AT-37 | Ray | Ajustes finales de UI, compatibilidad de navegador y accesibilidad básica |
| AT-38 | Todos | Integración final y preparación de demo de cierre |

## Dependencias iniciales

El contrato de Pedro guía la integración del frontend de Ray y del RAG de Laura. El smoke integral de Sprint 0 requiere corpus, prototipo, contratos y staging; el smoke técnico de este repositorio solo verifica web/API/base. La tarea inicial de infraestructura continúa abierta hasta disponer del servidor, despliegue y secretos reales.
