# Entornos y despliegue

## Desarrollo

Usar los pasos del README. `.env.example` documenta todas las variables (base de datos, puerto web, sesión e IA). Copiarlo a `.env` exclusivamente para desarrollo; sin claves, la IA usa `fake`. La web escucha en `127.0.0.1:8080`; PostgreSQL y la API solo son accesibles dentro de la red de Compose.

Los volúmenes conservan datos al detener contenedores. `docker compose down --volumes` elimina la base local: no usar en un servidor con datos que deban conservarse. CI sí elimina su volumen efímero al terminar.

## Ramas y pipeline

El trabajo se hace en ramas cortas que se integran en `staging`; `staging` se promueve a `main` mediante PR.

| Evento | Workflow | Resultado |
|---|---|---|
| PR hacia `staging` o `main` | `CI` (`ci.yml`) | Checks `Backend`, `Frontend` y `Containers and smoke` |
| Push a `staging` | `Deploy` (`deploy.yml`) | CI → imágenes en GHCR → despliegue al entorno `staging` |
| Push a `main` | `Deploy` (`deploy.yml`) | CI → imágenes en GHCR → despliegue al entorno `production` |

`Deploy` publica `ghcr.io/whoislaura/ateneo/api:<sha>` y `ghcr.io/whoislaura/ateneo/web:<sha>` con el `GITHUB_TOKEN`. El paso SSH se omite con un aviso (sin fallar) mientras el entorno no tenga todas las variables y secretos de la tabla siguiente.

En el servidor, el despliegue copia `compose.yaml`, `compose.prod.yaml`, `infra/db/init.sql` e `infra/backup.sh` a `DEPLOY_PATH`, ejecuta `docker compose pull` y `up -d --wait` con `IMAGE_TAG=<sha>` (la API migra la base al arrancar) y comprueba `/api/v1/health` a través de la web. `compose.prod.yaml` sustituye la construcción local por las imágenes publicadas. Para operar a mano en el servidor: `IMAGE_TAG=<sha> docker compose -f compose.yaml -f compose.prod.yaml <comando>`; el sha desplegado aparece en `docker compose images`.

## Operación

### Variables del servicio `api`

Compose construye `DATABASE_URL` con `POSTGRES_*` (por eso `POSTGRES_PASSWORD` solo debe tener caracteres seguros en URL, p. ej. `openssl rand -hex 24`) y pasa desde `.env` las variables `ATENEO_*` de `.env.example`, con valores por defecto que funcionan sin claves (`fake`).

| Variable | Uso |
|---|---|
| `ATENEO_TOKEN_TTL_SECONDS` | Vida del token de sesión (28800) |
| `ATENEO_LLM_PROVIDER`, `ATENEO_EMBEDDER` | `fake` (defecto) u `openai` (API compatible) |
| `ATENEO_LLM_API_KEYS`, `ATENEO_EMBED_API_KEYS` | Claves separadas por comas (cuentas rotativas); alternativa: `*_API_KEY` con una sola |
| `ATENEO_LLM_MODEL`, `ATENEO_EMBED_MODEL` | Modelos; obligatorios con `openai` |
| `ATENEO_LLM_BASE_URL`, `ATENEO_EMBED_BASE_URL` | Por defecto `https://api.openai.com/v1` |
| `ATENEO_EMBED_DIM`, `ATENEO_MAX_DISTANCE` | 256 y 0.5; ver [prototipo RAG](rag-prototype.md) |

Tras cambiar `.env`: `docker compose up -d` (recrea la API).

**Cuentas IA rotativas.** Con varias claves, cada llamada empieza por la última que funcionó; ante 429, 5xx, timeout o error de red pasa a la siguiente. Hace como máximo un intento por clave (dos si hay una sola) y después la API responde 503 `service_unavailable` sin guardar nada. Otros 4xx (p. ej. 401 por clave revocada) no se reintentan: retirar esa clave de la lista. Las claves nunca se registran; los reintentos aparecen como `ai_retry` con la posición de la clave (`key_index`).

### Límites de subida

Nginx acepta cuerpos de hasta 25 MB (`frontend/nginx.conf`); el backend corta en `ATENEO_MAX_UPLOAD_MB` (20 por defecto) y devuelve el 413 JSON del contrato. Ese margen de 5 MB deja responder al backend antes de que Nginx corte. Si se sube `ATENEO_MAX_UPLOAD_MB` por encima de 25, actualizar también `client_max_body_size`.

### Migraciones y primer administrador

La imagen de la API ejecuta `alembic upgrade head` antes de arrancar uvicorn; si la migración falla, el contenedor no llega a *healthy* y `up --wait` (y el despliegue) falla. No hay registro público; crear el primer administrador (pide la contraseña dos veces):

```sh
docker compose exec api python -m app.auth create-user admin@upr.edu.cu --name "Nombre Apellido" --role admin
```

En servidores, añadir `-f compose.yaml -f compose.prod.yaml` con `IMAGE_TAG` (ver arriba). `python infra/smoke.py` comprueba web, salud, un login fallido que devuelve 401 JSON (base accesible y migrada) y pgvector.

### Logs

La API escribe una línea JSON por evento en stdout (`docker compose logs api`): `ts`, `level`, `logger`, `message` y, por petición, `request_id`, `method`, `path` (sin query string), `status` y `duration_ms`. La respuesta lleva la cabecera `X-Request-ID`. Nunca se registran cuerpos, cabeceras (`Authorization`), tokens, contraseñas ni preguntas; los errores de SQL ocultan sus parámetros. Un error no controlado se registra como `unhandled_error` con su traza y devuelve 500 con el formato del contrato: `{"error": {"code": "internal_error", "message": ..., "details": {"request_id": ...}}}`, de modo que el usuario puede citar el id para localizarlo.

Docker guarda los logs sin límite por defecto; en el servidor, fijar rotación en `/etc/docker/daemon.json` (`"log-driver": "local"` o `json-file` con `max-size`).

### Copias de seguridad

`infra/backup.sh [DIRECTORIO]` ejecuta `pg_dump` dentro del contenedor `db`, guarda `ateneo-<fecha UTC>.sql.gz` (permisos 600) en `backups/` por defecto y borra las de más de `BACKUP_RETENTION_DAYS` días (7). Se ejecuta desde cualquier ruta; opera sobre el proyecto Compose de su directorio (respeta `COMPOSE_PROJECT_NAME` del `.env`). Cron diario del usuario de despliegue:

```cron
15 3 * * * /srv/ateneo-staging/infra/backup.sh >> /srv/ateneo-staging/backups/backup.log 2>&1
```

Copiar `backups/` fuera del servidor (otro disco o máquina): una copia en el mismo disco no protege de su pérdida. Restaurar (sustituye el contenido actual de la base):

```sh
docker compose stop web api
gunzip -c backups/ateneo-<fecha>.sql.gz | docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
docker compose start api web
```

`stop`, `exec` y `start` no construyen ni descargan imágenes, así que valen igual en servidores sin `-f compose.prod.yaml`. Probar la restauración periódicamente en una máquina o proyecto aparte (`COMPOSE_PROJECT_NAME` distinto).

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
2. Crear `DEPLOY_PATH` y dentro un `.env` con permisos 600 a partir de `.env.example`, con `POSTGRES_PASSWORD` aleatoria, segura en URL y propia del entorno, y las claves IA del entorno si se usa `openai`. Si staging y producción comparten servidor, usar directorios y `WEB_PORT` distintos y añadir `COMPOSE_PROJECT_NAME=ateneo-staging` o `ateneo-production`.
3. Permitir la descarga de imágenes: hacer públicos los paquetes `ateneo/api` y `ateneo/web` en GHCR o ejecutar una vez `docker login ghcr.io` en el servidor con un token de solo `read:packages`.
4. Programar `infra/backup.sh` en cron (ver Copias de seguridad).
5. Publicar la web: sigue escuchando en `127.0.0.1:WEB_PORT`; el proxy HTTPS institucional (o uno propio) debe reenviar a ese puerto.

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
- Ruta de datos persistentes y destino externo de las copias de seguridad.

## Producción

Separar servidor o directorio, base, almacenamiento y secretos de staging. Acordar dominio, HTTPS, copias, recuperación y entrega al cliente. Nunca reutilizar la contraseña de ejemplo.

Las variables con prefijo `VITE_` se incluyen en archivos públicos del navegador: no colocar allí secretos. Las claves IA se usan exclusivamente en backend y viven en el `.env` del servidor. No crear claves de proveedores hasta elegirlos.

## Traspaso

Laura prepara infraestructura en Sprint 0. Pedro asume despliegue, logs y configuración operativa desde Sprint 1; en ese momento actualizará `CODEOWNERS` y esta guía con el servidor acordado.
