# Entrega al cliente

Guía para el equipo informático que recibe Ateneo: qué servidor hace falta, cómo hacer el primer despliegue, cómo activar los despliegues automáticos, cómo traspasar el repositorio y cómo comprobar que todo funciona. El detalle de operación diaria (variables, usuarios, logs, copias) está en [despliegue](deployment.md); aquí se enlaza en lugar de repetirlo.

## 1. Requisitos del servidor

Ateneo son tres contenedores: PostgreSQL 17 con pgvector (`db`), la API FastAPI (`api`) y Nginx con la web (`web`). Todo el estado vive en la base: los PDF subidos no se guardan, solo su texto por página, los fragmentos y sus embeddings. Conservar los PDF originales fuera del servidor (hacen falta para reindexar).

| Recurso | Mínimo | Recomendado | Notas |
|---|---|---|---|
| Sistema | Linux x86_64 con Docker Engine y Compose v2 | Ubuntu Server 24.04 LTS o Debian 12 | Las imágenes de GHCR se construyen solo para `amd64`; en ARM, construir en el servidor (opción B) |
| CPU | 2 vCPU | 4 vCPU | La extracción de PDF y el troceado ocurren en la API al subir |
| RAM | 4 GB | 8 GB | PostgreSQL y la API; construir en el servidor (opción B) necesita ~2 GB más durante el build |
| Disco | 30 GB | 80 GB SSD | Imágenes (unos pocos GB), base, copias locales de 7 días y logs. La base crece con el corpus: con embeddings de 1536 dimensiones, cada fragmento ocupa unos 8 KB con su texto |
| Red | Salida HTTPS a GHCR (opción A) o a Docker Hub, PyPI y npm (opción B); al proveedor IA si se usa uno real | | Entrada solo al proxy HTTPS; la web escucha en `127.0.0.1` |

Son estimaciones para un corpus de cientos de PDF y uso de una facultad; no se han medido en el servidor definitivo. Para comprobarlo antes de abrirlo a usuarios, usar `infra/load.py` contra el servidor nuevo ([carga básica](qa-rag.md#carga-básica)).

Además: un nombre DNS, un certificado HTTPS (o un proxy institucional que lo termine), un usuario de sistema dedicado y un destino externo para las copias.

## 2. Primer despliegue

Hay dos formas de obtener las imágenes:

- **Opción A (recomendada): imágenes publicadas.** GitHub Actions las construye en cada push a `main` y las publica en `ghcr.io/<propietario>/<repositorio>`. El servidor solo descarga.
- **Opción B: construir en el servidor.** Para servidores sin acceso a GHCR o sin GitHub Actions (por ejemplo, tras un espejo en GitLab). Requiere clonar el repositorio en el servidor.

### 2.1 Preparar el servidor

```sh
# Como administrador. Docker Engine desde el repositorio oficial: https://docs.docker.com/engine/install/
sudo adduser --disabled-password ateneo
sudo usermod -aG docker ateneo        # equivale a root: usuario y máquina dedicados
sudo install -d -o ateneo -g ateneo -m 750 /srv/ateneo
```

### 2.2 Archivo `.env` y secretos

Como usuario `ateneo`, en `/srv/ateneo`:

```sh
cd /srv/ateneo
# Opción A: copiar .env.example desde el repositorio. Opción B: git clone <url> . y usar el del clon.
cp .env.example .env && chmod 600 .env
openssl rand -hex 24                  # pegar como POSTGRES_PASSWORD
```

Editar `.env`:

- `POSTGRES_PASSWORD`: el valor generado (hexadecimal: debe ser seguro en URL). Nunca reutilizar el de ejemplo ni compartirlo entre entornos.
- Borrar la línea `DATABASE_URL` (solo sirve fuera de Docker).
- `WEB_PORT`: puerto local al que apuntará el proxy HTTPS (8080 por defecto).
- `ATENEO_TRUSTED_PROXY_HOPS=2` si el proxy HTTPS añade `X-Forwarded-For` (los ejemplos de abajo lo hacen); ver [límite de intentos](deployment.md#límite-de-intentos-de-login).
- `IMAGE_REPO=ghcr.io/<propietario>/<repositorio>` en minúsculas (opción A, si el repositorio ya no es `whoislaura/ateneo`).
- Proveedor IA: ver [apartado 5](#5-cambiar-el-proveedor-de-ia). Sin claves funciona con `fake`, que no sirve para uso real.

No hay más secretos de aplicación: los tokens de sesión son aleatorios y se guardan en la base.

### 2.3 Arrancar

**Opción A.** Copiar `compose.yaml`, `compose.prod.yaml`, `infra/db/init.sql` e `infra/backup.sh` a `/srv/ateneo` (misma estructura de carpetas). Si los paquetes de GHCR son privados, `docker login ghcr.io` con un token de solo `read:packages`. Después:

```sh
export COMPOSE_FILE=compose.yaml:compose.prod.yaml IMAGE_TAG=<sha de main>
docker compose pull
docker compose up -d --wait --wait-timeout 180
```

Una vez activado el despliegue automático ([apartado 3](#3-despliegue-automático)) este paso lo hace GitHub Actions en cada push a `main`.

**Opción B.** Desde el clon:

```sh
docker compose up -d --build --wait --wait-timeout 300
```

Para actualizar: `git pull` y repetir el comando.

La API aplica las migraciones al arrancar; si fallan, `--wait` falla y `docker compose logs api` muestra el motivo.

### 2.4 Primer administrador

No hay registro público. Con las mismas variables `COMPOSE_FILE`/`IMAGE_TAG` de la opción A (o desde el clon en la opción B):

```sh
docker compose exec api python -m app.auth create-user admin@upr.edu.cu --name "Nombre Apellido" --role admin
```

Pide la contraseña dos veces. El resto de comandos de cuentas está en [migraciones y primer administrador](deployment.md#migraciones-y-primer-administrador).

### 2.5 Proxy HTTPS

La web solo escucha en `127.0.0.1:WEB_PORT`. Un proxy en la misma máquina termina HTTPS y reenvía. Debe permitir cuerpos de 25 MB (subida de PDF) y esperar al menos 120 s (generación con IA).

**Caddy** (certificado automático de Let's Encrypt si el dominio es público; añade `X-Forwarded-For` por defecto):

```caddyfile
ateneo.upr.edu.cu {
    request_body {
        max_size 25MB
    }
    reverse_proxy 127.0.0.1:8080 {
        transport http {
            read_timeout 130s
        }
    }
}
```

**Nginx** (certificado institucional o de `certbot --nginx`):

```nginx
server {
    listen 80;
    server_name ateneo.upr.edu.cu;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    http2 on;
    server_name ateneo.upr.edu.cu;
    ssl_certificate     /etc/ssl/ateneo/fullchain.pem;
    ssl_certificate_key /etc/ssl/ateneo/privkey.pem;
    client_max_body_size 25m;
    add_header Strict-Transport-Security "max-age=31536000" always;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 130s;
    }
}
```

Con cualquiera de los dos, `ATENEO_TRUSTED_PROXY_HOPS=2`. Si delante hay además un proxy institucional, sumar uno solo si ese proxy también añade `X-Forwarded-For` (confirmarlo con su administrador).

### 2.6 Rotación de logs

Docker no limita los logs por defecto. En `/etc/docker/daemon.json`:

```json
{ "log-driver": "local", "log-opts": { "max-size": "20m", "max-file": "5" } }
```

`sudo systemctl restart docker` y recrear los contenedores (`docker compose up -d --force-recreate`): la configuración solo se aplica a contenedores nuevos.

### 2.7 Copias de seguridad con copia externa

`infra/backup.sh` vuelca la base comprimida en `backups/` y conserva 7 días ([detalle](deployment.md#copias-de-seguridad)). Cron del usuario `ateneo` (`crontab -e`), con una copia diaria a otra máquina:

```cron
15 3 * * * /srv/ateneo/infra/backup.sh >> /srv/ateneo/backups/backup.log 2>&1
45 3 * * * rsync -a /srv/ateneo/backups/ copias@backup.upr.edu.cu:/copias/ateneo/ >> /srv/ateneo/backups/rsync.log 2>&1
```

El destino (`copias@backup...`) es un ejemplo: usar el servidor de copias institucional, con clave SSH propia y retención mayor que la local. Las copias contienen hashes de contraseñas y el historial de preguntas: tratarlas como datos personales.

## 3. Despliegue automático

`Deploy` (`.github/workflows/deploy.yml`) se ejecuta en cada push a `main`: pasa CI, publica las imágenes y entra por SSH al servidor para descargar, arrancar y comprobar `/api/v1/health`. Mientras falte configuración, publica las imágenes y omite el paso SSH con un aviso.

Requisitos: que el servidor acepte SSH desde los runners de GitHub (IP variables de GitHub) o, si la red institucional no lo permite, un [runner propio](https://docs.github.com/actions/hosting-your-own-runners) dentro de la red (cambiar `runs-on` del job `Deploy`).

En GitHub, Settings → Environments → `production` (Deployment branches: `main`; *Required reviewers* opcional):

| Nombre | Tipo | Valor | Cómo obtenerlo |
|---|---|---|---|
| `DEPLOY_HOST` | Variable | Nombre o IP del servidor | Administrador del servidor |
| `DEPLOY_PORT` | Variable | Puerto SSH (opcional, 22) | Administrador del servidor |
| `DEPLOY_USER` | Variable | `ateneo` | Apartado 2.1 |
| `DEPLOY_PATH` | Variable | `/srv/ateneo` | Apartado 2.1 |
| `DEPLOY_KNOWN_HOSTS` | Variable | Huella del servidor | `ssh-keyscan -p <puerto> <host>`, comparada con `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` en el servidor |
| `DEPLOY_SSH_KEY` | Secreto | Clave privada dedicada | `ssh-keygen -t ed25519 -N '' -f ateneo-deploy`; la `.pub` va a `~ateneo/.ssh/authorized_keys` y el archivo privado se borra tras pegarlo |

Las claves IA y la contraseña de la base no van a GitHub: viven en el `.env` del servidor. Para un servidor de preproducción, ver [entorno de preproducción](deployment.md#entorno-de-preproducción-opcional).

Tras el primer push a `main` en el repositorio nuevo, en el perfil u organización → Packages → `ateneo/api` y `ateneo/web`: hacerlos públicos o mantenerlos privados con el `docker login` del apartado 2.3.

## 4. Traspaso del repositorio

### 4.1 Transferir en GitHub (recomendado)

Settings → General → *Transfer ownership* hacia la organización del cliente (requiere permiso para crear repositorios en ella). Se conservan issues, PR, historial y Actions; GitHub redirige las URL antiguas.

Después de transferir:

- **Imágenes**: `deploy.yml` deriva el nombre de `github.repository`, así que publica en `ghcr.io/<organización>/<repositorio>` sin cambios. Las imágenes antiguas quedan en el espacio del propietario anterior y no se mueven. En el servidor, fijar `IMAGE_REPO` en `.env` (apartado 2.2) para operar a mano; el despliegue automático ya lo exporta. Opcionalmente, cambiar el valor por defecto en `compose.prod.yaml`.
- **Packages**: en la organización, permitir que Actions publique paquetes y fijar su visibilidad.
- **Entornos y secretos**: comprobar que `production` y sus variables siguen presentes; si no, recrearlos (apartado 3).
- **Reglas**: protección de `main` según [protección de ramas](deployment.md#protección-de-ramas).
- **`.github/CODEOWNERS`**: sustituir las cuentas del equipo por las del cliente (o un equipo de la organización).
- **Enlaces**: URL de `git clone` y sección Equipo del `README.md`, enlaces de `docs/github-issues.md` y `CONTRIBUTING.md`. No hay badges; si se añaden, usar el propietario nuevo.
- **Demo en Render**: el Blueprint está enlazado al repositorio anterior; reconectarlo o eliminarlo.

### 4.2 Espejo en otra organización o en GitLab

Si el cliente prefiere su propia copia y el original se conserva:

```sh
git clone --mirror https://github.com/whoislaura/ateneo.git
cd ateneo.git
git push --mirror https://<servidor>/<organización>/ateneo.git
```

Solo se copia Git (ramas, etiquetas, historial); no issues, PR, entornos, secretos ni paquetes.

- **En GitHub**: aplicar la lista del apartado 4.1 y crear entornos, secretos y reglas desde cero.
- **En GitLab**: los workflows de GitHub Actions no se ejecutan. Usar la opción B del apartado 2 o escribir un `.gitlab-ci.yml` equivalente (no incluido). Si se publican imágenes en su registro, fijar `IMAGE_REPO` al nombre del registro (`registry.<servidor>/<grupo>/ateneo`).

## 5. Cambiar el proveedor de IA

Ateneo acepta cualquier API compatible con OpenAI (OpenAI, Gemini, Groq, un servidor propio…). En el `.env` del servidor:

```sh
ATENEO_LLM_PROVIDER=openai
ATENEO_LLM_API_KEYS=clave1,clave2        # una o varias; rotan ante cuotas o caídas
ATENEO_LLM_MODEL=<modelo>
ATENEO_LLM_BASE_URL=https://api.openai.com/v1
ATENEO_EMBEDDER=openai
ATENEO_EMBED_API_KEYS=...
ATENEO_EMBED_MODEL=<modelo de embeddings>
ATENEO_EMBED_BASE_URL=https://api.openai.com/v1
ATENEO_EMBED_DIM=<dimensión del modelo>
```

Aplicar con `docker compose up -d` (con las variables de la opción A). Comprobar con una consulta real.

- Cambiar solo el modelo de respuesta (`ATENEO_LLM_*`) no requiere más pasos.
- Cambiar el embedder o su dimensión invalida el índice: hay que reemplazar cada PDF desde la pantalla Corpus para reindexarlo. Hasta entonces, los fragmentos con otra dimensión se ignoran y, con la misma dimensión, la búsqueda devuelve resultados sin sentido. Ver [ingestión](ingestion.md) y la [calibración de `ATENEO_MAX_DISTANCE`](rag-prototype.md).
- Medir la calidad con el proveedor elegido: [QA del RAG](qa-rag.md).

## 6. Verificación tras la entrega

En el servidor, desde `/srv/ateneo` con las variables de la opción A exportadas (o desde el clon):

| # | Comprobación | Cómo | Resultado esperado |
|---|---|---|---|
| 1 | Contenedores sanos | `docker compose ps` | `db`, `api` y `web` en `healthy`/`running` |
| 2 | Smoke técnico | `python3 infra/smoke.py http://127.0.0.1:8080` (copiar `infra/smoke.py` si se usó la opción A) | `Smoke OK: ...` |
| 3 | HTTPS | Abrir `https://<dominio>` | Candado válido; el pie indica «Conexión disponible» |
| 4 | Login | Entrar con el administrador | Acceso al inicio; un login erróneo muestra el error, no un 500 |
| 5 | Subida | Corpus → subir un PDF de ~20 MB con metadatos | Documento en estado indexado |
| 6 | Consulta | Preguntar algo que esté en ese PDF | Respuesta con cita que abre la página correcta |
| 7 | Logs | `docker compose logs api --tail 20` | Líneas JSON sin contraseñas ni preguntas |
| 8 | Copia | `infra/backup.sh` | Archivo `backups/ateneo-<fecha>.sql.gz` y copia en el destino externo al día siguiente |
| 9 | Restauración | Ver abajo | La copia restaurada permite login y consulta |
| 10 | Despliegue automático | Integrar un PR trivial en `main` | Job `Deploy` en verde y el sha nuevo en `docker compose images` |

**Prueba de restauración** (en una máquina aparte o en otro directorio del mismo servidor, sin tocar producción):

```sh
mkdir /srv/ateneo-restore && cd /srv/ateneo-restore
cp -r /srv/ateneo/compose*.yaml /srv/ateneo/infra /srv/ateneo/.env .
# En este .env: COMPOSE_PROJECT_NAME=ateneo-restore y WEB_PORT=8090
docker compose up -d --wait            # con las variables de la opción A
docker compose stop web api
gunzip -c /srv/ateneo/backups/ateneo-<fecha>.sql.gz | docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
docker compose start api web
python3 /srv/ateneo-restore/infra/smoke.py http://127.0.0.1:8090
```

Entrar en `http://127.0.0.1:8090` (túnel SSH) con una cuenta real y repetir una consulta. Después, `docker compose down --volumes` **solo dentro de `/srv/ateneo-restore`**.

## 7. Lista de entrega

| Elemento | Responsable | Estado |
|---|---|---|
| Código, Dockerfiles, Compose dev/prod, migraciones al arrancar | Equipo | Hecho |
| CI (`Backend`, `Frontend`, `Containers and smoke`) y Deploy a GHCR por SSH | Equipo | Hecho |
| Logs JSON, `infra/backup.sh`, `infra/smoke.py` | Equipo | Hecho |
| Documentación de despliegue, operación y esta guía | Equipo | Hecho |
| Demo en Render | Equipo | Hecho |
| Servidor con los requisitos del apartado 1 | Cliente | Pendiente |
| Usuario de despliegue y acceso SSH (o runner propio) | Cliente | Pendiente |
| DNS, certificado y proxy HTTPS | Cliente | Pendiente |
| `.env` del servidor con contraseña propia | Cliente (con el equipo) | Pendiente |
| Elección y claves del proveedor IA | Cliente | Pendiente |
| Transferencia o espejo del repositorio | Equipo y cliente | Pendiente |
| Entorno `production`, variables, secreto y reglas de `main` | Cliente (con el equipo) | Pendiente |
| Visibilidad o acceso a los paquetes GHCR | Cliente | Pendiente |
| Cron de copias y copia externa | Cliente | Pendiente |
| Rotación de logs de Docker | Cliente | Pendiente |
| Primer administrador y cuentas iniciales | Cliente | Pendiente |
| Carga del corpus oficial | Cliente | Pendiente |
| Verificación del apartado 6, incluida la restauración | Equipo y cliente | Pendiente |
| `CODEOWNERS`, enlaces y README con el propietario nuevo | Cliente | Pendiente |
| Licencia de uso del código | Titular del proyecto | Pendiente |
