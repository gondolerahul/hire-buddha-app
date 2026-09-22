#!/usr/bin/env bash
#
# Publish a signed dialer APK to https://app.hirebuddha.com/download/app/
#
#   deploy/dialer-downloads/publish.sh [path-to-app-release.apk]
#
# The version, size and checksum all come from the APK itself, so the page can never
# disagree with the file it links to — which is exactly how the site sat on 1.0.4 after
# 1.1.0 had been built.
#
# Refuses to publish if the signing certificate differs from what is already live,
# because Android will not install such an update over an existing one: every rep
# would have to uninstall first, losing their session and device verification.
#
# Afterwards it prints the backend/.env lines to change. The in-app update prompt is
# driven by MOBILE_APP_LATEST_VERSION_CODE, not by this directory.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APK="${1:-$REPO/mobile/android/app/build/outputs/apk/release/app-release.apk}"
DST="${DIALER_DOWNLOAD_DIR:-/var/www/hirebuddha-downloads/app}"
TEMPLATE="$REPO/deploy/dialer-downloads/index.template.html"

die() { echo "error: $*" >&2; exit 1; }

[ -f "$APK" ] || die "no APK at $APK (run: cd mobile/android && ./gradlew :app:assembleRelease)"
[ -d "$DST" ] || die "download directory $DST does not exist"
[ -f "$TEMPLATE" ] || die "missing $TEMPLATE"

BT="$(ls -d "${ANDROID_HOME:-$HOME/Android/Sdk}"/build-tools/* 2>/dev/null | sort -V | tail -1)"
[ -n "$BT" ] || die "Android build-tools not found; set ANDROID_HOME"
AAPT2="$BT/aapt2"; APKSIGNER="$BT/apksigner"

badging="$("$AAPT2" dump badging "$APK")"
VERSION="$(sed -n "s/.*versionName='\([^']*\)'.*/\1/p" <<<"$badging" | head -1)"
CODE="$(sed -n "s/.*versionCode='\([^']*\)'.*/\1/p" <<<"$badging" | head -1)"
[ -n "$VERSION" ] && [ -n "$CODE" ] || die "could not read version from the APK"

"$APKSIGNER" verify "$APK" >/dev/null 2>&1 || die "APK is not signed — is keystore.properties in place?"
NEW_CERT="$("$APKSIGNER" verify --print-certs "$APK" | sed -n 's/.*certificate SHA-256 digest: //p' | head -1)"

# An upgrade signed by a different key cannot install over the old one.
if [ -f "$DST/hirebuddha-dialer.apk" ]; then
  OLD_CERT="$("$APKSIGNER" verify --print-certs "$DST/hirebuddha-dialer.apk" | sed -n 's/.*certificate SHA-256 digest: //p' | head -1)"
  if [ "$NEW_CERT" != "$OLD_CERT" ]; then
    die "signing certificate changed ($OLD_CERT -> $NEW_CERT).
     Every rep would have to uninstall before they could update.
     Publish only with the release key at ~/.hirebuddha-secrets/hirebuddha-release.jks."
  fi
fi

if [ -f "$DST/hirebuddha-dialer-$VERSION.apk" ] && \
   ! cmp -s "$APK" "$DST/hirebuddha-dialer-$VERSION.apk"; then
  die "$VERSION is already published with different bytes. Bump versionCode/versionName first."
fi

install -m 0644 "$APK" "$DST/hirebuddha-dialer-$VERSION.apk"
install -m 0644 "$APK" "$DST/hirebuddha-dialer.apk"

( cd "$DST" && sha256sum hirebuddha-dialer-*.apk > SHA256SUMS )
SHA="$(sha256sum "$DST/hirebuddha-dialer-$VERSION.apk" | cut -d' ' -f1)"
SIZE_MB="$(awk "BEGIN{printf \"%.1f\", $(stat -c%s "$APK")/1048576}")"

# Render atomically: a half-written page must never be served.
python3 - "$TEMPLATE" "$DST/index.html" "$VERSION" "$SHA" "$SIZE_MB" <<'PY'
import os, sys, tempfile
template, target, version, sha, size = sys.argv[1:6]
html = open(template).read()
for key, value in (("VERSION", version), ("SHA256", sha), ("SIZE_MB", size)):
    html = html.replace("{{%s}}" % key, value)
assert "{{" not in html, "unsubstituted placeholder left in the page"
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target))
with os.fdopen(fd, "w") as f:
    f.write(html)
os.chmod(tmp, 0o644)
os.replace(tmp, target)
PY

echo "published $VERSION ($CODE) — ${SIZE_MB} MB"
echo "  sha256 $SHA"
echo "  https://app.hirebuddha.com/download/app/"
echo
echo "Now tell the backend, or the in-app update prompt will not fire:"
echo "  backend/.env:  MOBILE_APP_LATEST_VERSION_CODE=$CODE"
echo "                 MOBILE_APP_LATEST_VERSION_NAME=$VERSION"
echo "  then: touch backend/src/main.py   # uvicorn --reload watches .py, not .env"
