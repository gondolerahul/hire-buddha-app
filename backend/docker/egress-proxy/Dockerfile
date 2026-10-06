# hb-egress-proxy — the sandbox's ways out (Phase 12 `02`/`06`, TL-15, TL-18).
#   MODE=allowlist: tinyproxy, default-deny over $ALLOWLIST (synthesized tools).
#   MODE=web:       web_proxy.py, any public address and never an internal one
#                   (the browser). See entrypoint.sh.
FROM alpine:3.20

RUN apk add --no-cache tinyproxy python3

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY web_proxy.py /usr/local/bin/web_proxy.py
RUN chmod +x /usr/local/bin/entrypoint.sh

# The allow-list is supplied at run time; default is the Google API surface.
ENV ALLOWLIST="googleapis.com,google.com" \
    MODE="allowlist"

EXPOSE 8888
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
