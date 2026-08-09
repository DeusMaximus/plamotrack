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

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
