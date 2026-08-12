# hb-egress-proxy — default-deny forward proxy for the per-tenant sandbox.
# Phase 12 `02`/`06`: the network gate for synthesized / network-using tools.
FROM alpine:3.20

RUN apk add --no-cache tinyproxy

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# The allow-list is supplied at run time; default is the Google API surface.
ENV ALLOWLIST="googleapis.com,google.com"

EXPOSE 8888
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
