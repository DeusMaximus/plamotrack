#!/bin/bash
# SessionStart hook for Claude Code on the web: gets a fresh cloud container to
# the point where the backend's ruff + pytest and the frontend's lint, vitest and
# build run the way CI's Backend and Frontend jobs do (.github/workflows/ci.yml).
#
# What CI gets from a `postgres:16` service container comes from the image's own
# Postgres 16 here. Docker is installed in the image but its daemon is not
# running, and this hook does not start it, so the Integration job (packaged
# stack, ingress matrix) and Playwright e2e are out of scope. Local machines never
# run it: it exits unless CLAUDE_CODE_REMOTE is set.
#
# Idempotent: every step checks before it acts, so a resume, clear or compact
# re-running it costs seconds. Only the dependency installs are fatal; anything
# about the database is reported in the summary and the rest carries on. Install
# chatter goes to stderr; stdout is a short summary, which the session receives
# as context.
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
LOCAL_DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"
TEST_DATABASE_URL="${LOCAL_DATABASE_URL}_test"
PG_LOG="/var/log/postgresql/postgresql-${PG_VERSION}-${PG_CLUSTER}.log"

log() { echo "[session-start] $*" >&2; }

# --- Postgres ----------------------------------------------------------------
# Running processes are not part of the cached container snapshot, so the
# cluster is started on every session; the role and database persist with it.
psql_admin() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -qtAX "$@"; }

# Called as an `if` condition, where bash suspends `set -e` — so every step
# returns on failure explicitly.
setup_postgres() {
  local ready=false exists
  if ! pg_isready -q -h 127.0.0.1 -p 5432; then
    log "starting Postgres ${PG_VERSION}/${PG_CLUSTER}"
    pg_ctlcluster "$PG_VERSION" "$PG_CLUSTER" start >&2 || return 1
  fi
  for _ in $(seq 1 30); do
    if pg_isready -q -h 127.0.0.1 -p 5432; then ready=true; break; fi
    sleep 1
  done
  [ "$ready" = true ] || { log "Postgres did not become ready"; return 1; }

  exists="$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}'")" || return 1
  if [ "$exists" != "1" ]; then
    log "creating role ${DB_USER}"
    # CREATEDB: tests/conftest.py creates <db>_test itself when it is missing.
    psql_admin -c "CREATE ROLE ${DB_USER} LOGIN CREATEDB PASSWORD '${DB_PASSWORD}'" || return 1
  fi
  exists="$(psql_admin -c "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'")" || return 1
  if [ "$exists" != "1" ]; then
    log "creating database ${DB_NAME}"
    psql_admin -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}" || return 1
  fi
}

# Neither an image without the cluster nor one whose cluster will not start
# fails the hook: the dependency installs below do not need a database.
HAVE_PG=false
if ! command -v pg_ctlcluster >/dev/null || [ ! -d "/etc/postgresql/${PG_VERSION}/${PG_CLUSTER}" ]; then
  log "no Postgres ${PG_VERSION}/${PG_CLUSTER} cluster in this image; skipping database setup"
  PG_SUMMARY="NO Postgres: this image has no ${PG_VERSION}/${PG_CLUSTER} cluster, so the backend tests and the dev server have no database."
elif setup_postgres; then
  HAVE_PG=true
else
  log "Postgres setup failed; continuing without a database"
  PG_SUMMARY="NO Postgres: the ${PG_VERSION}/${PG_CLUSTER} cluster FAILED to start or provision (see ${PG_LOG}), so the backend tests and the dev server have no database."
fi

# --- Backend (uv) --------------------------------------------------------------
# --frozen, as CI: the lockfile is the contract, never rewritten here. Python
# 3.12, as CI; the image's default python3 is 3.11, below requires-python.
log "syncing backend dependencies"
(cd "$REPO/backend" && uv sync --frozen --python 3.12 >&2)

# The dev database at head, so `uv run uvicorn app.main:app` works straight away.
# The test suite migrates its own database (down + up) on every run.
#
# Only the local database is ever migrated, and only when Settings() — what the
# dev server reads — resolves to it. A .env, POSTGRES_* or DATABASE_URL override
# is reported and left alone: this hook runs at every session start, and must
# not run migrations against a database it did not provision.
#
# A failed migration is reported, not fatal: a branch with a broken migration is
# exactly when the session needs the rest of the environment.
if [ "$HAVE_PG" = true ]; then
  configured_url="$(cd "$REPO/backend" \
    && uv run --frozen python -c 'from app.config import Settings; print(Settings().database_url)' \
       2>/dev/null)" || configured_url=""
  if [ -z "$configured_url" ]; then
    log "backend Settings() failed to load; not migrating"
    dev_db_state="not migrated: backend Settings() failed to load (check .env)"
  elif [ "$configured_url" != "$LOCAL_DATABASE_URL" ]; then
    log "Settings() resolves to another database; not migrating"
    dev_db_state="not migrated, and not what the dev server uses: Settings() resolves to another database (a .env, POSTGRES_* or DATABASE_URL override), which this hook leaves alone"
  else
    log "migrating the dev database"
    dev_db_state="at alembic head"
    if ! (cd "$REPO/backend" \
      && DATABASE_URL="$LOCAL_DATABASE_URL" uv run --frozen alembic upgrade head >&2); then
      log "alembic upgrade head failed on the dev database; continuing"
      dev_db_state="NOT at head: 'alembic upgrade head' FAILED at session start"
    fi
  fi
  PG_SUMMARY="Postgres ${PG_VERSION} on 127.0.0.1:5432 (${DB_USER}/${DB_PASSWORD}); dev DB '${DB_NAME}' ${dev_db_state}; tests use '${DB_NAME}_test' via TEST_DATABASE_URL."
fi

# --- Frontend (npm) ------------------------------------------------------------
# npm ci, as CI — never npm install: the lockfile carries `libc` fields a newer
# npm wrote, and the npm bundled with Node 22 strips them on install, leaving the
# tracked lockfile dirty every session. npm ci deletes node_modules first, so it
# runs only when needed: package.json or package-lock.json differs from what was
# last installed, or `npm ls` finds the installed top level incomplete. Otherwise
# the cached snapshot's node_modules is reused as is.
FRONTEND="$REPO/frontend"
INSTALL_STAMP="$FRONTEND/node_modules/.session-start-install.sha256"
install_hash="$(sha256sum "$FRONTEND/package.json" "$FRONTEND/package-lock.json" | sha256sum | cut -d' ' -f1)"
if [ -f "$INSTALL_STAMP" ] && [ "$(cat "$INSTALL_STAMP")" = "$install_hash" ] \
  && (cd "$FRONTEND" && npm ls --depth=0 --offline --no-update-notifier >/dev/null 2>&1); then
  log "frontend dependencies match package.json and package-lock.json; skipping npm ci"
else
  log "installing frontend dependencies (npm ci)"
  (cd "$FRONTEND" && npm ci --no-audit --no-fund --no-update-notifier >&2)
  echo "$install_hash" > "$INSTALL_STAMP"
fi

# --- Session environment ------------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export TEST_DATABASE_URL='${TEST_DATABASE_URL}'" >> "$CLAUDE_ENV_FILE"
fi

cat <<EOF
Cloud dev environment ready (.claude/hooks/session-start.sh):
- ${PG_SUMMARY}
- backend/.venv synced (uv, Python 3.12); frontend/node_modules installed (Node $(node --version)).
- Docker is installed but not started, and this hook does not start it: the packaged Compose stack, backend/ingress_matrix.py and Playwright e2e are not set up.
EOF
