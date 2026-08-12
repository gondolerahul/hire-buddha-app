#!/bin/sh
# Build the tinyproxy host allow-list from $ALLOWLIST (comma-separated host
# suffixes) at container start, then run the proxy. Keeping the list in an env
# var means the allow-list is per-deployment config, not baked into the image.
set -eu

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
    escaped=$(printf '%s' "$host" | sed 's/\./\\./g')
    printf '(^|\\.)%s$\n' "$escaped" >> "$FILTER"
done
IFS=$OLDIFS

echo "hb-egress-proxy allow-list:" && cat "$FILTER"

exec tinyproxy -d -c /etc/tinyproxy/tinyproxy.conf
