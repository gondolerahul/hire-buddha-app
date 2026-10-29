# HireBuddha frontend image (Phase 14 WS1 1.1): the production build behind nginx.
# The Vite dev server is for development only (tech spec §12.6).
#
#   docker build -t hb-frontend .
#
# The SPA talks to its own origin (VITE_API_BASE_URL=/api/v1); nginx forwards
# /api/ and the /stream/ sockets to the API (API_UPSTREAM, default the in-cluster
# service), so the browser needs no CORS and every environment uses one image.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_GOOGLE_CLIENT_ID=
ARG VITE_MICROSOFT_CLIENT_ID=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID \
    VITE_MICROSOFT_CLIENT_ID=$VITE_MICROSOFT_CLIENT_ID
RUN npx vite build

# Runs as a non-root user and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
ENV API_UPSTREAM=http://hb-api:8000 \
    NGINX_ENVSUBST_FILTER=^API_UPSTREAM$
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
# The security headers every page and asset carries (SH-E5): a snippet each location includes.
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
