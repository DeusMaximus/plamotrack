# syntax=docker/dockerfile:1

FROM node:22-slim AS build

WORKDIR /app

# npm ci keys off the lockfile, so dependencies stay cached across source edits.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .

# VITE_API_BASE is baked at build time; the default (/api) is what nginx serves,
# so there is nothing to configure for the bundled stack.
RUN npm run build


FROM nginx:1.27-alpine AS runtime

ARG SOURCE_REVISION=working-tree
ARG RELEASE_VERSION=unreleased
LABEL org.opencontainers.image.source="https://github.com/DeusMaximus/plamotrack" \
      org.opencontainers.image.revision=$SOURCE_REVISION \
      org.opencontainers.image.version=$RELEASE_VERSION

# The ingress config is a template the image renders at start (nginx/), with
# the Host allowlist assembled from the same .env keys the API reads. Only
# PLAMOTRACK_* names are substituted, so nginx's own $variables survive.
ENV NGINX_ENVSUBST_FILTER=^PLAMOTRACK_

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
# The entrypoint sources the .envsh, so it must reach the image with LF endings:
# a CRLF copy — what a default Git for Windows checkout produces — fails to
# parse and the container exits. The repository's .gitattributes forces LF on
# checkout (#255); backend/tests/test_line_endings.py holds it there.
COPY --chmod=755 nginx/15-plamotrack-server-names.envsh /docker-entrypoint.d/15-plamotrack-server-names.envsh

EXPOSE 80
