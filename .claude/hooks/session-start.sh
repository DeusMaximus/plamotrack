#!/bin/bash
# SessionStart hook for Claude Code on the web: gets a fresh cloud container to
# the point where the backend's ruff + pytest and the frontend's lint, vitest and
# build run the way CI's Backend and Frontend jobs do (.github/workflows/ci.yml).
#
# What CI gets from a `postgres:16` service container comes from the image's own
# Postgres 16 here — the web container has no Docker daemon running, so the
# Integration job (packaged stack, ingress matrix) and Playwright e2e are out of
# scope for this hook. Local machines never run it: it exits unless
# CLAUDE_CODE_REMOTE is set.
#
# Idempotent: every step checks before it acts, so a resume, clear or compact
# re-running it costs seconds. Install chatter goes to stderr; stdout is a short
# summary, which the session receives as context.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"

# The credentials Settings() falls back to with no .env (backend/app/config.py),
# and the test URL CI's Backend job sets — so tests pass whether or not a .env
# exists, and never touch the dev database.
PG_VERSION=16
PG_CLUSTER=main
DB_USER=plamotrack
DB_PASSWORD=plamotrack
DB_NAME=plamotrack
TEST_DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}_test"

log() { echo "[session-start] $*" >&2; }

# --- Postgres ----------------------------------------------------------------
# Running processes are not part of the cached container snapshot, so the
# cluster is started on every session; the role and database persist with it.
# An image without the cluster skips this section rather than failing the hook,
# so the dependency installs below still happen.
if command -v pg_ctlcluster >/dev/null && [ -d "/etc/postgresql/${PG_VERSION}/${PG_CLUSTER}" ]; then
  if ! pg_isready -q -h 127.0.0.1 -p 5432; then
    log "starting Postgres ${PG_VERSION}/${PG_CLUSTER}"
    pg_ctlcluster "$PG_VERSION" "$PG_CLUSTER" start >&2
  fi
  for _ in $(seq 1 30); do
    pg_isready -q -h 127.0.0.1 -p 5432 && break
    sleep 1
  done
  pg_isready -q -h 127.0.0.1 -p 5432 || { log "Postgres did not become ready"; exit 1; }

  psql_admin() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -qtAX "$@"; }

  if [ "$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}'")" != "1" ]; then
    log "creating role ${DB_USER}"
    # CREATEDB: tests/conftest.py creates <db>_test itself when it is missing.
    psql_admin -c "CREATE ROLE ${DB_USER} LOGIN CREATEDB PASSWORD '${DB_PASSWORD}'"
  fi
  if [ "$(psql_admin -c "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'")" != "1" ]; then
    log "creating database ${DB_NAME}"
    psql_admin -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}"
  fi
  PG_SUMMARY="Postgres ${PG_VERSION} on 127.0.0.1:5432 (${DB_USER}/${DB_PASSWORD}); dev DB '${DB_NAME}' at alembic head; tests use '${DB_NAME}_test' via TEST_DATABASE_URL."
  HAVE_PG=true
else
  log "no Postgres ${PG_VERSION}/${PG_CLUSTER} cluster in this image; skipping database setup"
  PG_SUMMARY="NO Postgres: this image has no ${PG_VERSION}/${PG_CLUSTER} cluster, so the backend tests and the dev server have no database."
  HAVE_PG=false
fi

# --- Backend (uv) --------------------------------------------------------------
# --frozen, as CI: the lockfile is the contract, never rewritten here. Python
# 3.12, as CI; the image's default python3 is 3.11, below requires-python.
log "syncing backend dependencies"
(cd "$REPO/backend" && uv sync --frozen --python 3.12 >&2)

# The dev database at head, so `uv run uvicorn app.main:app` works straight away.
# The test suite migrates its own database (down + up) on every run.
if [ "$HAVE_PG" = true ]; then
  log "migrating the dev database"
  (cd "$REPO/backend" \
    && DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}" \
       uv run --frozen alembic upgrade head >&2)
fi

# --- Frontend (npm) ------------------------------------------------------------
# npm ci, as CI — never npm install: the lockfile carries `libc` fields a newer
# npm wrote, and the npm bundled with Node 22 strips them on install, leaving the
# tracked lockfile dirty every session. npm ci deletes node_modules first, so it
# runs only when the lockfile's content differs from what was last installed;
# otherwise the cached snapshot's node_modules is reused as is.
FRONTEND="$REPO/frontend"
LOCK_STAMP="$FRONTEND/node_modules/.session-start-lock.sha256"
lock_hash="$(sha256sum "$FRONTEND/package-lock.json" | cut -d' ' -f1)"
if [ -f "$LOCK_STAMP" ] && [ "$(cat "$LOCK_STAMP")" = "$lock_hash" ]; then
  log "frontend dependencies match package-lock.json; skipping npm ci"
else
  log "installing frontend dependencies (npm ci)"
  (cd "$FRONTEND" && npm ci --no-audit --no-fund --no-update-notifier >&2)
  echo "$lock_hash" > "$LOCK_STAMP"
fi

# --- Session environment ------------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export TEST_DATABASE_URL='${TEST_DATABASE_URL}'" >> "$CLAUDE_ENV_FILE"
fi

cat <<EOF
Cloud dev environment ready (.claude/hooks/session-start.sh):
- ${PG_SUMMARY}
- backend/.venv synced (uv, Python 3.12); frontend/node_modules installed (Node $(node --version)).
- No Docker daemon: the packaged Compose stack, backend/ingress_matrix.py and Playwright e2e are not set up.
EOF
