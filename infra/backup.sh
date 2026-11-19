#!/usr/bin/env bash
# Copia de PostgreSQL: infra/backup.sh [DIRECTORIO] (por defecto backups/ en la raíz del despliegue).
# Conserva BACKUP_RETENTION_DAYS días (7 por defecto). Restauración: docs/deployment.md.
set -euo pipefail
cd "$(dirname "$0")/.."
dir=${1:-backups}
days=${BACKUP_RETENTION_DAYS:-7}
umask 077 # la copia contiene hashes de contraseñas y el historial de preguntas
mkdir -p "$dir"
file="$dir/ateneo-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
trap 'rm -f "$file.tmp"' EXIT
docker compose exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' |
  gzip >"$file.tmp"
mv "$file.tmp" "$file"
find "$dir" -name 'ateneo-*.sql.gz' -mtime +"$days" -delete
echo "$file"
