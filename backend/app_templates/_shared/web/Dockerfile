# A HireBuddha web app (D48): React + TypeScript built by Vite, served by nginx.
# Runs as nginx's unprivileged user on port 8080 with a read-only root file
# system; /tmp is the only writable path (the App Controller mounts it).
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
USER root
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY 40-hb-config.sh /docker-entrypoint.d/40-hb-config.sh
RUN chmod 0755 /docker-entrypoint.d/40-hb-config.sh
COPY --from=build /src/dist /usr/share/nginx/html
USER 101
EXPOSE 8080
