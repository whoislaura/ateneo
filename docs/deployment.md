# Entornos y despliegue

## Desarrollo

Usar los pasos del README. `.env.example` documenta todas las variables (base de datos, puerto web, sesión e IA). Copiarlo a `.env` exclusivamente para desarrollo; sin claves, la IA usa `fake`. La web escucha en `127.0.0.1:8080`; PostgreSQL y la API solo son accesibles dentro de la red de Compose.

Los volúmenes conservan datos al detener contenedores. `docker compose down --volumes` elimina la base local: no usar en un servidor con datos que deban conservarse. CI sí elimina su volumen efímero al terminar.

## Ramas y pipeline

El trabajo se hace en ramas cortas que se integran directamente en `main` mediante PR con squash ([flujo](../CONTRIBUTING.md)). No existe rama `staging` permanente.

| Evento | Workflow | Resultado |
|---|---|---|
| PR hacia `main` | `CI` (`ci.yml`) | Checks `Backend`, `Frontend` y `Containers and smoke` |
| Push a `main` (PR integrado) | `Deploy` (`deploy.yml`) | CI → imágenes en GHCR → despliegue al entorno `production` |
| Push a `staging` (solo si se activa la preproducción) | `Deploy` (`deploy.yml`) | CI → imágenes en GHCR → despliegue al entorno `staging` |

`Deploy` publica `ghcr.io/<propietario>/<repositorio>/api:<sha>` y `.../web:<sha>` (hoy `ghcr.io/whoislaura/ateneo`), derivados de `github.repository` en minúsculas, con el `GITHUB_TOKEN`; tras transferir el repositorio no hay que tocar el workflow. El paso SSH se omite con un aviso (sin fallar) mientras el entorno no tenga todas las variables y secretos de la tabla de [entornos](#entornos-de-github).

En el servidor, el despliegue copia `compose.yaml`, `compose.prod.yaml`, `infra/db/init.sql` e `infra/backup.sh` a `DEPLOY_PATH`, ejecuta `docker compose pull` y `up -d --wait` con `IMAGE_TAG=<sha>` (la API migra la base al arrancar) y comprueba `/api/v1/health` a través de la web. `compose.prod.yaml` sustituye la construcción local por las imágenes publicadas. Para operar a mano en el servidor: `IMAGE_TAG=<sha> docker compose -f compose.yaml -f compose.prod.yaml <comando>`; el sha desplegado aparece en `docker compose images`. Si el repositorio ya no es `whoislaura/ateneo`, añadir al `.env` del servidor `IMAGE_REPO=ghcr.io/<propietario>/<repositorio>` en minúsculas (el despliegue automático ya lo exporta).

### Entorno de preproducción (opcional)

Los workflows siguen aceptando `staging` por si el cliente quiere probar cada versión en un servidor previo antes de producción. Para activarlo:

1. Crear la rama `staging` desde `main` y protegerla como `main` (ver [protección de ramas](#protección-de-ramas)).
2. Crear el entorno de GitHub `staging` con sus propias variables y secreto, y preparar su servidor o directorio (ver [servidor](#servidor-por-entorno)).
3. Cambiar el flujo: las ramas de trabajo se integran en `staging` con squash, y `staging` se promueve a `main` con un PR integrado con *merge commit* (no squash) para que ambas ramas no diverjan.

Sin la rama, nada cambia: ningún push dispara el entorno `staging`.

## Operación

### Variables del servicio `api`

Compose construye `DATABASE_URL` con `POSTGRES_*` (por eso `POSTGRES_PASSWORD` solo debe tener caracteres seguros en URL, p. ej. `openssl rand -hex 24`) y pasa desde `.env` las variables `ATENEO_*` de `.env.example`, con valores por defecto que funcionan sin claves (`fake`).

| Variable | Uso |
|---|---|
| `ATENEO_TOKEN_TTL_SECONDS` | Vida del token de sesión (28800) |
| `ATENEO_LOGIN_MAX_ATTEMPTS`, `ATENEO_LOGIN_IP_MAX_ATTEMPTS`, `ATENEO_LOGIN_WINDOW_SECONDS` | Logins fallidos por cuenta (5) y por IP (50) en una ventana de 900 s; ver [límite de intentos](#límite-de-intentos-de-login) |
| `ATENEO_TRUSTED_PROXY_HOPS` | Proxies propios delante de la API (1 en Compose: Nginx; 0 en el código) |
| `ATENEO_MAX_UPLOAD_MB` | Límite de subida de PDFs en MB (20; Nginx corta en 25) |
| `ATENEO_LLM_PROVIDER`, `ATENEO_EMBEDDER` | `fake` (defecto) u `openai` (API compatible) |
| `ATENEO_LLM_API_KEYS`, `ATENEO_EMBED_API_KEYS` | Claves separadas por comas (cuentas rotativas); alternativa: `*_API_KEY` con una sola |
| `ATENEO_LLM_MODEL`, `ATENEO_EMBED_MODEL` | Modelos; obligatorios con `openai` |
| `ATENEO_LLM_BASE_URL`, `ATENEO_EMBED_BASE_URL` | Por defecto `https://api.openai.com/v1` |
| `ATENEO_LLM_REASONING` | `low`, `medium`, `high` o vacío (defecto: no se envía). Se envía como `"reasoning": {"effort": ...}`; en modelos con razonamiento evita que los tokens de pensamiento agoten `max_tokens` y corten la respuesta (en `render.yaml`, `low`). La reformulación del chat usa siempre `low` si está definida |
| `ATENEO_EMBED_DIM`, `ATENEO_MAX_DISTANCE` | 256 y 0.5; ver [prototipo RAG](rag-prototype.md) |
| `ATENEO_RETRIEVAL` | Recuperación en PostgreSQL: `hybrid` (defecto; texto completo y vector fusionados por RRF), `text` o `vector`. Ver [QA del RAG](qa-rag.md#recuperación-híbrida) |

Tras cambiar `.env`: `docker compose up -d` (recrea la API).

**Cuentas IA rotativas.** Con varias claves, cada llamada empieza por la última que funcionó; ante 401/402/403 (clave revocada o sin saldo), 429, 5xx o error de red pasa a la siguiente; tras un timeout no reintenta (otro intento superaría los 120 s de Nginx; `ATENEO_LLM_TIMEOUT` debe quedar por debajo). Hace como máximo un intento por clave (dos si hay una sola) y después la API responde 503 `service_unavailable` sin guardar nada. Otros 4xx (p. ej. 400) no se reintentan. Una respuesta 200 sin contenido válido también acaba en 503; la causa queda en el log `ai_error`. Retirar de la lista las claves revocadas o sin saldo. Las claves nunca se registran; los reintentos aparecen como `ai_retry` con la posición de la clave (`key_index`).

### Límites de subida

Nginx acepta cuerpos de hasta 25 MB (`frontend/nginx.conf`); el backend corta en `ATENEO_MAX_UPLOAD_MB` (20 por defecto) y devuelve el 413 JSON del contrato. Ese margen de 5 MB deja responder al backend antes de que Nginx corte. Si se sube `ATENEO_MAX_UPLOAD_MB` por encima de 25, actualizar también `client_max_body_size`.

### Límite de intentos de login

El contador de cuenta se indexa por (correo, IP): quien falla 5 veces desde su IP bloquea solo ese par, no la cuenta para el resto (antes cualquiera podía bloquear 15 min la cuenta del admin). Esto exige que `ATENEO_TRUSTED_PROXY_HOPS` esté bien configurado: si la API ve una misma IP para todos (el proxy), vuelve el bloqueo compartido de la cuenta, y además el límite por IP pasa a ser global.

Pasados los fallos permitidos, `POST /auth/login` responde 429 `too_many_requests` con `Retry-After` (ver [contrato](api-contract.md#autenticación-cu-00-at-08)). El límite por IP es más alto que el de cuenta porque un aula o una red institucional puede salir a internet con una sola IP. Los contadores viven en la memoria del proceso: se pierden al reiniciar la API y no se comparten entre réplicas (suficiente con un único proceso; con varios, mover a la base o a Redis).

La IP del cliente sale de `X-Forwarded-For` solo si `ATENEO_TRUSTED_PROXY_HOPS` es mayor que 0. Cada proxy añade al final la dirección que le conectó; lo anterior lo escribe el cliente y puede ser falso. Con `N` proxies de confianza se toma la entrada `N` contando desde el final. Con 0 se usa la IP de la conexión TCP (uvicorn no reescribe la IP con cabeceras salvo que venga de `127.0.0.1`).

- **Compose con Nginx** (`frontend/nginx.conf`, `X-Forwarded-For $proxy_add_x_forwarded_for`): 1, valor por defecto en `compose.yaml`. La API no publica puertos, así que solo Nginx le llega.
- **Detrás del proxy HTTPS institucional**: con 1, todos los usuarios comparten la IP del proxy institucional y el límite por IP pasa a ser global. Si ese proxy añade `X-Forwarded-For` (confirmarlo con su administrador), usar 2. No subirlo si no lo añade: se confiaría en una entrada que escribe el cliente.
- **Demo en Render**: `render.yaml` no fija la variable (0), así que el límite por IP es común a todos los usuarios de la demo; basta para enseñarla. No se ha comprobado cuántas entradas añade Render a `X-Forwarded-For` en el camino sitio estático → API, y la API también es accesible directamente en `onrender.com` con un salto menos: con un valor mayor que el del camino más corto, un cliente podría elegir su IP. Fijarlo solo tras comprobar ambos caminos.
- **API sin proxy** (uvicorn en local): 0.

### Migraciones y primer administrador

La imagen de la API ejecuta `alembic upgrade head` antes de arrancar uvicorn; si la migración falla, el contenedor no llega a *healthy* y `up --wait` (y el despliegue) falla. No hay registro público; crear el primer administrador (pide la contraseña dos veces):

```sh
docker compose exec api python -m app.auth create-user admin@upr.edu.cu --name "Nombre Apellido" --role admin
```

Para cambiar contraseña, rol o dar de baja una cuenta, y para listarlas:

```sh
docker compose exec api python -m app.auth set-password usuario@upr.edu.cu
docker compose exec api python -m app.auth set-role usuario@upr.edu.cu --role teacher
docker compose exec api python -m app.auth deactivate usuario@upr.edu.cu
docker compose exec api python -m app.auth list-users
```

En servidores, añadir `-f compose.yaml -f compose.prod.yaml` con `IMAGE_TAG` (ver arriba). `python infra/smoke.py` comprueba web, salud, un login fallido que devuelve 401 JSON (base accesible y migrada) y pgvector.

### Logs

La API escribe una línea JSON por evento en stdout (`docker compose logs api`): `ts`, `level`, `logger`, `message` y, por petición, `request_id`, `method`, `path` (sin query string), `status` y `duration_ms`. La respuesta lleva la cabecera `X-Request-ID`. Nunca se registran cuerpos, cabeceras (`Authorization`), tokens, contraseñas ni preguntas; los errores de SQL ocultan sus parámetros. Un error no controlado se registra como `unhandled_error` con su traza y devuelve 500 con el formato del contrato: `{"error": {"code": "internal_error", "message": ..., "details": {"request_id": ...}}}`, de modo que el usuario puede citar el id para localizarlo.

Docker guarda los logs sin límite por defecto; en el servidor, fijar rotación en `/etc/docker/daemon.json` (`"log-driver": "local"` o `json-file` con `max-size`).

### Copias de seguridad

`infra/backup.sh [DIRECTORIO]` ejecuta `pg_dump` dentro del contenedor `db`, guarda `ateneo-<fecha UTC>.sql.gz` (permisos 600) en `backups/` por defecto y borra las de más de `BACKUP_RETENTION_DAYS` días (7). Se ejecuta desde cualquier ruta; opera sobre el proyecto Compose de su directorio (respeta `COMPOSE_PROJECT_NAME` del `.env`). Cron diario del usuario de despliegue:

```cron
15 3 * * * /srv/ateneo/infra/backup.sh >> /srv/ateneo/backups/backup.log 2>&1
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

- `production`: Deployment branches → *Selected branches* → `main`; *Required reviewers* con al menos un integrante.
- `staging` (solo con [preproducción](#entorno-de-preproducción-opcional)): Deployment branches → `staging`.

En cada entorno, con valores distintos por entorno:

| Nombre | Tipo | Contenido |
|---|---|---|
| `DEPLOY_HOST` | Variable | Nombre o IP del servidor |
| `DEPLOY_PORT` | Variable | Puerto SSH (opcional, 22 por defecto) |
| `DEPLOY_USER` | Variable | Usuario de despliegue con acceso a Docker |
| `DEPLOY_PATH` | Variable | Directorio absoluto del despliegue, p. ej. `/srv/ateneo` |
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

Settings → Rules (o Branches), para `main` (y `staging` si se activa la preproducción):

- Exigir pull request con una aprobación y descartar aprobaciones obsoletas.
- Exigir los checks `Backend`, `Frontend` y `Containers and smoke`.
- Permitir solo *squash merge* en Settings → General → Pull Requests (con preproducción, permitir también *merge commit* para la promoción `staging` → `main`).
- Bloquear push forzado y borrado; sin excepciones para administradores.

## Demo en Render

Entorno gratuito para enseñar la aplicación al cliente; no sustituye a producción. `render.yaml` define la API (Docker) y la web (sitio estático que reenvía `/api/*` a la API, así no hace falta CORS). La base es PostgreSQL de [Neon](https://neon.tech), que incluye pgvector; la gratuita de Render caduca a los 30 días.

1. En Neon, crear un proyecto y copiar su cadena de conexión cambiando el esquema a `postgresql+psycopg://` (conservar `?sslmode=require`).
2. En Render: *New* → *Blueprint*, elegir el repositorio y rellenar `DATABASE_URL` con esa cadena. La API migra la base al arrancar.
3. Si Render no asigna `https://ateneo-api.onrender.com` a la API (nombre ocupado), corregir el destino de `/api/*` en `render.yaml`.
4. El plan gratuito no da consola: crear las cuentas desde un equipo local contra la base de Neon:

   ```sh
   cd backend
   DATABASE_URL='postgresql+psycopg://...' uv run python -m app.auth create-user admin@upr.edu.cu --name "Admin Demo" --role admin
   ```

5. Crear también una cuenta `teacher` para el smoke, cargar el corpus de muestra y comprobar el flujo completo (abajo); después, seguir [la guía de demostración](demo.md).

IA: el modelo de lenguaje es real, vía [OpenRouter](https://openrouter.ai) (`ATENEO_LLM_MODEL` en `render.yaml`, un modelo `:free`; si un modelo falla, la causa queda en el log `ai_error`, visible en la pestaña Logs del panel). La clave (`ATENEO_LLM_API_KEYS`) se pone en Render → `ateneo-api` → *Environment*; nunca en el repositorio. Los modelos gratuitos admiten 20 peticiones por minuto y 50 al día por cuenta (1000 tras una compra única de 10 USD); las peticiones fallidas también cuentan, y varias claves de la misma cuenta no suman cuota. Al agotarse, consulta y generación responden 503. Los embeddings siguen en `fake`: pasar a unos reales obliga a resubir el corpus. Para volver al modo sin red, `ATENEO_LLM_PROVIDER=fake`.

Límites: la API se duerme tras 15 minutos sin uso y tarda alrededor de un minuto en despertar, así que conviene abrirla antes de la reunión.

### Smoke integral

Dos scripts que solo usan HTTPS contra la URL pública (sirven también donde la red bloquea PostgreSQL) y valen para Docker local, Render o el servidor institucional. Ambos leen la cuenta de profesor de `ATENEO_SMOKE_EMAIL` y `ATENEO_SMOKE_PASSWORD`; nunca imprimen la contraseña ni el token. Desde la raíz del repositorio:

```sh
export ATENEO_SMOKE_EMAIL=profesor@upr.edu.cu
read -rs ATENEO_SMOKE_PASSWORD && export ATENEO_SMOKE_PASSWORD
uv run --project backend python infra/demo_corpus.py https://ateneo-web.onrender.com
python infra/smoke.py https://ateneo-web.onrender.com
```

- `infra/demo_corpus.py` genera los PDF con `app.rag.sample` (ReportLab, dependencia de desarrollo) y sube `muestra-a` y `muestra-b` con los metadatos de su JSON. Es idempotente: si el documento ya existe (409) lo sustituye con `PUT`, que reindexa y lo reactiva si estaba retirado. `--con-inyeccion` añade `muestra-c`, el documento con una instrucción incrustada para QA; no conviene en una demo.
- Tras el cambio de normalización de ligaduras (ﬁ, ﬂ…) hay que reindexar la demo: volver a ejecutar `infra/demo_corpus.py` (el `PUT` reindexa) y, para cualquier otro PDF, reemplazarlo desde Corpus. Ver [ingestión](ingestion.md).
- `infra/smoke.py` hace las comprobaciones técnicas de siempre (reintenta la salud durante unos minutos por el arranque en frío de Render) y, si las dos variables están definidas, inicia sesión, lee `/auth/me`, lista documentos, consulta «¿Dónde aparece azafrán?» exigiendo `answered` con una cita no vacía, genera un resumen, crea un examen y lee sus soluciones, busca la consulta en el historial, envía feedback y cierra la sesión. Imprime `OK`/`FAIL` por paso y sale con código distinto de cero al primer fallo. La comprobación de pgvector con `docker compose` solo se hace contra `localhost`/`127.0.0.1`; en remoto la cubre la consulta.
- Cada ejecución deja en la cuenta una consulta, una generación, un examen y un feedback; usar una cuenta dedicada al smoke. Cinco logins fallidos seguidos bloquean la cuenta 15 minutos (429).

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
