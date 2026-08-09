# syntax=docker/dockerfile:1

# Both stages share one base image so the virtualenv's interpreter path is valid
# in the runtime stage — a venv built against a different python layout copies
# across looking fine and fails on the first import.
FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve in their own layer, keyed on the lockfile alone, so
# editing a service module doesn't reinstall SQLAlchemy.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Unprivileged: nothing here writes to disk. Photo storage (M7) will need a
# volume owned by this uid.
RUN useradd --create-home --uid 10001 plamotrack

WORKDIR /app

COPY --from=build --chown=plamotrack:plamotrack /app/.venv /app/.venv
# Source is copied rather than pip-installed: alembic wants alembic.ini and the
# versions directory on disk next to the app, not inside site-packages.
COPY --chown=plamotrack:plamotrack app ./app
COPY --chown=plamotrack:plamotrack alembic ./alembic
COPY --chown=plamotrack:plamotrack alembic.ini ./alembic.ini

USER plamotrack

EXPOSE 8000

# Config arrives as real environment variables; app/config.py finds no .env file
# in here and falls through to them (.dockerignore keeps one from sneaking in).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
