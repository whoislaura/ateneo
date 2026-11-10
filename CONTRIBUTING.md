# Trabajo del equipo

| Integrante | GitHub | Responsabilidad |
|---|---|---|
| Laura | @whoislaura | Infraestructura inicial, ingestión, RAG, citas, generación y QA RAG |
| Pedro | @pedrosarmientot | Contrato API, modelo, autenticación, APIs y DevOps desde Sprint 1 |
| Ray | @raysanjudo2006-netizen | Diseño, frontend, accesibilidad e integración UI |

## Flujo

1. Elegir una issue del sprint y revisar sus dependencias.
2. Actualizar `main` y crear una rama corta `feat/numero-descripcion`, `fix/numero-descripcion` o `chore/numero-descripcion`.
3. Implementar y ejecutar los checks relevantes del README.
4. Abrir un pull request contra `main`, enlazar la issue y describir la verificación.
5. Obtener una aprobación de otro integrante y los tres checks CI satisfactorios; integrar con squash y eliminar la rama de trabajo.

`main` queda protegida frente a pushes forzados y borrado. No se usa una rama permanente por persona. Los cambios de contratos se coordinan con Pedro; las referencias documento/página con Laura; los estados de interfaz con Ray.

`CODEOWNERS` solicita revisión por área una vez que los colaboradores aceptan la invitación. Al iniciar Sprint 1, actualizar infraestructura, Compose y workflows para que Pedro sea su responsable, según la tarea DevOps ya asignada.

Las tareas de Todos incluyen a los tres. Si GitHub aún no permite asignar una cuenta invitada, el nombre queda registrado en la issue y debe completarse la asignación cuando acepte.

## Datos y secretos

Versionar `.env.example` solo con ejemplos. Configurar secretos reales en el entorno correspondiente y nunca en el frontend ni en archivos de Git. Las pruebas CI iniciales usan datos sintéticos y no llaman servicios IA.

## Criterio de terminado

Cumplir la aceptación de la issue, aportar evidencia de pruebas, actualizar documentación afectada y pasar revisión. El backlog completo permanece abierto hasta comprobar cada entrega, aunque este arranque cubra parte de una tarea.
