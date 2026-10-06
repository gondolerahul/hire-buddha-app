#!/bin/sh
# Two modes, one image (TL-15, TL-18):
#   MODE=allowlist (default) - tinyproxy, default-deny over $ALLOWLIST host
#                              suffixes; the network gate for a synthesized tool
#                              that declares ALLOWLIST.
#   MODE=web                 - web_proxy.py: any public host, but every address
#                              a host resolves to must be public, and the proxy
#                              connects to the address it checked. The browser's
#                              way out.
set -eu

if [ "${MODE:-allowlist}" = "web" ]; then
    exec python3 /usr/local/bin/web_proxy.py
fi

# Build the tinyproxy host allow-list from $ALLOWLIST (comma-separated host
# suffixes) at container start, then run the proxy. Keeping the list in an env
# var means the allow-list is per-deployment config, not baked into the image.
FILTER=/etc/tinyproxy/filter
: > "$FILTER"

# Default to the Google API surface the platform's own tools depend on.
ALLOWLIST="${ALLOWLIST:-googleapis.com,google.com}"

# Each entry becomes an anchored regex matching the host and any subdomain:
#   googleapis.com  ->  (^|\.)googleapis\.com$
OLDIFS=$IFS
IFS=','
for host in $ALLOWLIST; do
    # trim whitespace
    host=$(printf '%s' "$host" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$host" ] && continue
    escaped=$(printf '%s' "$host" | sed 's/\./\./g')
    printf '(^|\.)%s$\n' "$escaped" >> "$FILTER"
done
IFS=$OLDIFS

echo "hb-egress-proxy allow-list:" && cat "$FILTER"

exec tinyproxy -d -c /etc/tinyproxy/tinyproxy.conf
