#!/bin/sh
# The app's runtime settings, from the environment the App Controller sets, as
# /config.js (window.HB_CONFIG). Values are JSON-escaped; nothing secret is
# ever here (a form's public key may only create one kind of record).
set -eu
json() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
cat > /tmp/config.js <<EOF
window.HB_CONFIG = {
  "dataApiUrl": "$(json "${HB_DATA_API_URL:-}")",
  "tenant": "$(json "${HB_TENANT_KEY:-}")",
  "app": "$(json "${HB_APP:-}")",
  "publicKey": "$(json "${HB_PUBLIC_KEY:-}")"
};
EOF
