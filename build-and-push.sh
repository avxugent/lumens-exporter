#!/usr/bin/env bash
#
# Build and push the lumens-exporter Docker image (linux/amd64 + linux/arm64)
# to Docker Hub as kristofkeppens/lumens-exporter.
#
# Requires: docker buildx, and `docker login` already done for an account
# with push access to kristofkeppens/lumens-exporter.
#
# Usage:
#   ./build-and-push.sh            # tags :latest and :<git-short-sha>
#   ./build-and-push.sh v1.2.0     # also tags :v1.2.0

set -euo pipefail

IMAGE="kristofkeppens/lumens-exporter"
PLATFORMS="linux/amd64,linux/arm64"
BUILDER="lumens-exporter-builder"

cd "$(dirname "${BASH_SOURCE[0]}")"

sha="$(git rev-parse --short HEAD)"
tags=(-t "${IMAGE}:latest" -t "${IMAGE}:${sha}")
if [[ $# -ge 1 ]]; then
  tags+=(-t "${IMAGE}:${1}")
fi

if ! docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
  echo "Creating buildx builder '${BUILDER}' (docker-container driver, required for multi-platform push)..."
  docker buildx create --name "$BUILDER" --driver docker-container --bootstrap
fi

echo "Building and pushing ${IMAGE} for ${PLATFORMS}..."
docker buildx build \
  --builder "$BUILDER" \
  --platform "$PLATFORMS" \
  "${tags[@]}" \
  --push \
  .

echo "Done: ${tags[*]}"
