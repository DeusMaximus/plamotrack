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

# The ingress config is a template the image renders at start (nginx/), with
# the Host allowlist assembled from the same .env keys the API reads. Only
# PLAMOTRACK_* names are substituted, so nginx's own $variables survive.
ENV NGINX_ENVSUBST_FILTER=^PLAMOTRACK_

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=755 nginx/15-plamotrack-server-names.envsh /docker-entrypoint.d/15-plamotrack-server-names.envsh

EXPOSE 80
