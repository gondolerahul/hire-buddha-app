# hb-caddy-redis — the tenant app edge (Phase 14 WS6 6.9, spike SP-3): Caddy with
# on-demand TLS and the caddy-storage-redis module, so every edge replica shares
# the certificates it issues (storage redis { address … key_prefix caddy } in the
# Caddyfile the App Controller writes). Runs as uid 10001 on 8080/8443.
#   docker build -t hb-caddy-redis:local backend/docker/caddy-redis
ARG CADDY_VERSION=2.11.6
FROM caddy:${CADDY_VERSION}-builder AS build
ARG STORAGE_REDIS_VERSION=v1.8.2
RUN xcaddy build --with github.com/pberkel/caddy-storage-redis@${STORAGE_REDIS_VERSION}

FROM caddy:${CADDY_VERSION}-alpine
COPY --from=build /usr/bin/caddy /usr/bin/caddy
# Writable places for a non-root Caddy (its data and config are also overridden by
# XDG paths; certificates themselves live in Redis).
RUN mkdir -p /data/caddy /config/caddy && chown -R 10001:10001 /data /config
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
USER 10001
EXPOSE 8080 8443
