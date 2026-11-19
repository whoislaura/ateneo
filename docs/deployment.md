# Entornos y despliegue

## Desarrollo

Usar los pasos del README. `.env.example` documenta `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` y `WEB_PORT`. Copiarlo a `.env` exclusivamente para desarrollo. La web escucha en `127.0.0.1:8080`; PostgreSQL y la API solo son accesibles dentro de la red de Compose.

Los volúmenes conservan datos al detener contenedores. `docker compose down --volumes` elimina la base local: no usar en un servidor con datos que deban conservarse. CI sí elimina su volumen efímero al terminar.

## Ramas y pipeline

El trabajo se hace en ramas cortas que se integran en `staging`; `staging` se promueve a `main` mediante PR.

| Evento | Workflow | Resultado |
|---|---|---|
| PR hacia `staging` o `main` | `CI` (`ci.yml`) | Checks `Backend`, `Frontend` y `Containers and smoke` |
| Push a `staging` | `Deploy` (`deploy.yml`) | CI → imágenes en GHCR → despliegue al entorno `staging` |
| Push a `main` | `Deploy` (`deploy.yml`) | CI → imágenes en GHCR → despliegue al entorno `production` |

`Deploy` publica `ghcr.io/whoislaura/ateneo/api:<sha>` y `ghcr.io/whoislaura/ateneo/web:<sha>` con el `GITHUB_TOKEN`. El paso SSH se omite con un aviso (sin fallar) mientras el entorno no tenga todas las variables y secretos de la tabla siguiente.

En el servidor, el despliegue copia `compose.yaml`, `compose.prod.yaml` e `infra/db/init.sql` a `DEPLOY_PATH`, ejecuta `docker compose pull` y `up -d --wait` con `IMAGE_TAG=<sha>` y comprueba `/api/v1/health` a través de la web. `compose.prod.yaml` sustituye la construcción local por las imágenes publicadas. Para operar a mano en el servidor: `IMAGE_TAG=<sha> docker compose -f compose.yaml -f compose.prod.yaml <comando>`; el sha desplegado aparece en `docker compose images`.

## Configuración pendiente para un administrador

### Entornos de GitHub

Settings → Environments, crear:

- `staging`: Deployment branches → *Selected branches* → `staging`.
- `production`: Deployment branches → `main`; *Required reviewers* con al menos un integrante.

En cada entorno, con valores distintos por entorno:

| Nombre | Tipo | Contenido |
|---|---|---|
| `DEPLOY_HOST` | Variable | Nombre o IP del servidor |
| `DEPLOY_PORT` | Variable | Puerto SSH (opcional, 22 por defecto) |
| `DEPLOY_USER` | Variable | Usuario de despliegue con acceso a Docker |
| `DEPLOY_PATH` | Variable | Directorio absoluto del despliegue, p. ej. `/srv/ateneo-staging` |
| `DEPLOY_KNOWN_HOSTS` | Variable | Salida de `ssh-keyscan -p <puerto> <host>`, verificada con el administrador del servidor |
| `DEPLOY_SSH_KEY` | Secreto | Clave privada ed25519 dedicada, sin frase de paso, solo para este entorno |

Los secretos de la aplicación no pasan por GitHub: viven en el `.env` del servidor (siguiente apartado). Así la contraseña de la base no se expone a los runners.

### Servidor (por entorno)

1. Instalar Docker Engine con Compose v2; crear el usuario de despliegue y añadir su clave pública (`DEPLOY_SSH_KEY`) a `authorized_keys`. Pertenecer al grupo `docker` equivale a acceso root: usar una máquina o usuario dedicados.
2. Crear `DEPLOY_PATH` y dentro un `.env` con permisos 600 a partir de `.env.example`, con `POSTGRES_PASSWORD` aleatoria y propia del entorno. Si staging y producción comparten servidor, usar directorios y `WEB_PORT` distintos y añadir `COMPOSE_PROJECT_NAME=ateneo-staging` o `ateneo-production`.
3. Permitir la descarga de imágenes: hacer públicos los paquetes `ateneo/api` y `ateneo/web` en GHCR o ejecutar una vez `docker login ghcr.io` en el servidor con un token de solo `read:packages`.
4. Publicar la web: sigue escuchando en `127.0.0.1:WEB_PORT`; el proxy HTTPS institucional (o uno propio) debe reenviar a ese puerto.

### Protección de ramas

Settings → Rules (o Branches), para `staging` y `main`:

- Exigir pull request con una aprobación y descartar aprobaciones obsoletas.
- Exigir los checks `Backend`, `Frontend` y `Containers and smoke`; en `staging`, además, la rama actualizada (en `main` no, porque cada merge commit de promoción obligaría a reintegrar `main` en `staging`).
- Bloquear push forzado y borrado; sin excepciones para administradores.

Convenciones: las ramas de trabajo se integran en `staging` con squash; la promoción `staging` → `main` se integra con *merge commit* (no squash) para que ambas ramas no diverjan. GitHub no impide por regla PRs a `main` desde otras ramas: revisar que el origen sea `staging`.

## Datos aún desconocidos del servidor

- Sistema operativo, arquitectura, CPU/RAM y almacenamiento disponible.
- Conectividad SSH desde GitHub Actions o necesidad de un runner institucional (en ese caso, cambiar `runs-on` del job `Deploy`).
- Dominio, DNS, HTTPS y reglas de red.
- Ruta de datos persistentes, copias de seguridad y procedimiento de recuperación.

## Producción

Separar servidor o directorio, base, almacenamiento y secretos de staging. Acordar dominio, HTTPS, copias, recuperación y entrega al cliente. Nunca reutilizar la contraseña de ejemplo.

Las variables con prefijo `VITE_` se incluyen en archivos públicos del navegador: no colocar allí secretos. Las futuras claves IA se utilizarán exclusivamente en backend y se añadirán al `.env` del servidor. No crear claves de proveedores hasta elegirlos.

## Traspaso

Laura prepara infraestructura en Sprint 0. Pedro asume despliegue, logs y configuración operativa desde Sprint 1; en ese momento actualizará `CODEOWNERS` y esta guía con el servidor acordado.
