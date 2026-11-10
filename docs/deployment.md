# Entornos y despliegue

## Desarrollo

Usar los pasos del README. `.env.example` documenta `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` y `WEB_PORT`. Copiarlo a `.env` exclusivamente para desarrollo. La web escucha en `127.0.0.1:8080`; PostgreSQL y la API solo son accesibles dentro de la red de Compose.

Los volúmenes conservan datos al detener contenedores. `docker compose down --volumes` elimina la base local: no usar en un servidor con datos que deban conservarse. CI sí elimina su volumen efímero al terminar.

## Staging — pendiente

Aún se desconocen el servidor y el acceso. Recoger:

- Sistema operativo, arquitectura, CPU/RAM y almacenamiento disponible.
- Docker Engine/Compose y permisos del usuario de despliegue.
- Conectividad desde GitHub Actions o necesidad de un runner institucional.
- Acceso administrativo, dominio, DNS, HTTPS y reglas de red.
- Ruta de datos persistentes, copias de seguridad y procedimiento de recuperación.

Al confirmar esos datos, definir la configuración de servidor y el transporte del despliegue. Mantener la web detrás del proxy HTTPS institucional o configurar uno específico. Crear el entorno GitHub `staging` con secretos mínimos y un smoke test posterior al despliegue. No hay actualmente job de CD, credenciales reales ni servidor configurado.

## Producción — pendiente

Separar base, almacenamiento y secretos de staging. Acordar dominio, HTTPS, copias, recuperación, aprobación de despliegue y entrega al cliente. Nunca reutilizar la contraseña de ejemplo.

Las variables con prefijo `VITE_` se incluyen en archivos públicos del navegador: no colocar allí secretos. Las futuras claves IA se utilizarán exclusivamente en backend. No crear claves de proveedores hasta elegirlos.

## Traspaso

Laura prepara infraestructura en Sprint 0. Pedro asume despliegue, logs y configuración operativa desde Sprint 1; en ese momento actualizará `CODEOWNERS` y esta guía con el servidor acordado.
