#!/usr/bin/env bash
# Despliega en la demo de Render el commit actual (HEAD).
# Render vigila la rama `main` del repositorio enlazado y despliega cada push; este script
# comprueba el código, enseña qué se va a subir, pide confirmación y hace el push (nunca forzado).
# Las migraciones (alembic upgrade head) las ejecuta la propia API al arrancar en Render.
#
# Uso: infra/deploy-render.sh [--sin-pruebas]
# Variables opcionales:
#   ATENEO_DEPLOY_REPO    repositorio que vigila Render (git@github.com:xcaim04/ateneo.git)
#   ATENEO_DEPLOY_BRANCH  rama que vigila Render (main)
#   ATENEO_DEPLOY_URL     URL pública de la web (https://ateneo-web.onrender.com)
set -euo pipefail

REPO=${ATENEO_DEPLOY_REPO:-git@github.com:xcaim04/ateneo.git}
BRANCH=${ATENEO_DEPLOY_BRANCH:-main}
URL=${ATENEO_DEPLOY_URL:-https://ateneo-web.onrender.com}
cd "$(git rev-parse --show-toplevel)"

if [[ -n $(git status --porcelain) ]]; then
  echo "Hay cambios sin commit. Haz commit o stash antes de desplegar." >&2
  exit 1
fi

echo "== Comprobando que Render puede avanzar sin forzar"
git fetch --quiet "$REPO" "$BRANCH"
if ! git merge-base --is-ancestor FETCH_HEAD HEAD; then
  echo "$REPO $BRANCH tiene commits que no están en tu HEAD. Fusiónalos primero:" >&2
  echo "  git pull $REPO $BRANCH" >&2
  exit 1
fi
if git diff --quiet FETCH_HEAD HEAD; then
  echo "Render ya tiene este código. Nada que desplegar."
  exit 0
fi

if [[ ${1:-} != --sin-pruebas ]]; then
  echo "== Backend: ruff y pytest (como la CI)"
  uv run --project backend ruff check backend infra/smoke.py
  uv run --project backend pytest -q backend/tests
  echo "== Frontend: lint, tipos y build"
  (cd frontend && npm ci --silent && npm run lint && npm run typecheck && npm run build)
fi

echo "== Commits que se van a desplegar"
git log --oneline FETCH_HEAD..HEAD
if git diff --name-only FETCH_HEAD HEAD | grep -q '^backend/migrations/'; then
  echo "AVISO: incluye migraciones; la API las aplicará en la base de la demo (Neon) al arrancar."
fi
read -rp "¿Desplegar $(git rev-parse --short HEAD) en $REPO ($BRANCH)? [s/N] " answer
[[ $answer == [sS] ]] || { echo "Cancelado."; exit 1; }

git push "$REPO" "HEAD:refs/heads/$BRANCH"
echo "Push hecho. Render construye y despliega en unos 5-10 minutos (pestaña Events del servicio)."
echo "Cuando termine, comprueba la demo con el smoke (pide la cuenta de profesor):"
echo "  export ATENEO_SMOKE_EMAIL=profesor@... ; read -rs ATENEO_SMOKE_PASSWORD && export ATENEO_SMOKE_PASSWORD"
echo "  python infra/smoke.py $URL"
