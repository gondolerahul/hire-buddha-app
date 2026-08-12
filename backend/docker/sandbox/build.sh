#!/usr/bin/env bash
# Build the hb-sandbox image and pin it by digest.
#
# The image bakes in the Document Factory scripts, which live in the backend
# tree (not next to this Dockerfile), so we assemble a small staging context
# rather than building from this directory or shipping the whole backend as
# context. After a successful build we record the local image ID digest in
# image.pin; the ContainerRuntime reads SANDBOX_IMAGE (default from image.pin)
# so production pins by digest, never by a floating tag.
#
# Usage:
#   ./build.sh                 # build hb-sandbox:local and write image.pin
#   SANDBOX_IMAGE_TAG=hb-sandbox:2026-06-07 ./build.sh
#
# Publishing (push to a registry and re-pin by the registry digest) is a
# deliberate ops step, documented in README.md — not done here.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd "${HERE}/../.." && pwd)"
DOCFACTORY_SRC="${BACKEND_ROOT}/scripts/seeds/default_entities/SeedDocumentFactory/scripts"
TAG="${SANDBOX_IMAGE_TAG:-hb-sandbox:local}"

if [[ ! -d "${DOCFACTORY_SRC}" ]]; then
    echo "error: Document Factory scripts not found at ${DOCFACTORY_SRC}" >&2
    exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

cp "${HERE}/Dockerfile" "${HERE}/requirements.txt" "${STAGE}/"
mkdir -p "${STAGE}/docfactory"
cp -R "${DOCFACTORY_SRC}" "${STAGE}/docfactory/scripts"

echo "Building ${TAG} ..."
docker build -t "${TAG}" "${STAGE}"

DIGEST="$(docker image inspect --format '{{.Id}}' "${TAG}")"
printf '%s\n' "${DIGEST}" > "${HERE}/image.pin"
echo "Built ${TAG}"
echo "Pinned ${DIGEST} -> ${HERE}/image.pin"
echo
echo "To use it locally, set in the worker/API env:"
echo "  SANDBOX_CONTAINER_RUNTIME_ENABLED=true"
echo "  SANDBOX_IMAGE=${TAG}    # or the pinned digest in image.pin"
