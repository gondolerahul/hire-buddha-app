#!/bin/sh
# Build the hb-egress-proxy image (Phase 12 `02`/`06` sandbox network gate).
set -eu
DIR=$(cd "$(dirname "$0")" && pwd)
TAG="${1:-hb-egress-proxy:local}"
echo "Building $TAG from $DIR"
docker build -t "$TAG" "$DIR"
echo "Done: $TAG"
