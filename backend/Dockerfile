# syntax=docker/dockerfile:1@sha256:572cebbc2b15e6f84c077742952674889cb63cd5e9b80abdffcbe587b6f19183

# Both stages share one base image so the virtualenv's interpreter path is valid
# in the runtime stage — a venv built against a different python layout copies
# across looking fine and fails on the first import.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS build

COPY --from=ghcr.io/astral-sh/uv:0.5@sha256:7bff3c3776ec467fc1437960f2c469d8beb30f536a6465a3350c647ccd260ec2 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve in their own layer, keyed on the lockfile alone, so
# editing a service module doesn't reinstall SQLAlchemy.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS runtime

ARG SOURCE_REVISION=working-tree
ARG RELEASE_VERSION=unreleased
LABEL org.opencontainers.image.source="https://github.com/DeusMaximus/plamotrack" \
      org.opencontainers.image.revision=$SOURCE_REVISION \
      org.opencontainers.image.version=$RELEASE_VERSION

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
#
# --no-proxy-headers is load-bearing (design notes §5.6, proxy trust): uvicorn's
# default middleware rewrites request.client from X-Forwarded-For for any peer
# on its trust list, and request.client is the raw socket peer that /readyz's
# `internal` check reads. The app resolves the forwarded address itself, from
# TRUSTED_PROXIES, into a separate key (app/ingress.py).
# Pin one worker explicitly: WEB_CONCURRENCY and UVICORN_WORKERS can override
# uvicorn's default. The in-process global login failure budget requires this
# pin; adding workers requires a shared store first (design notes §5.6, T8).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--workers", "1"]
