#!/usr/bin/env bash
# Build the publisher's pinned A2 runtime on an ARM64 build host and push it to private SWR.
set -Eeuo pipefail

: "${SOURCE_DIR:?Set SOURCE_DIR to the pinned upstream checkout}"
: "${DEST_IMAGE:?Set DEST_IMAGE to your private SWR URI and immutable tag}"
[[ "$DEST_IMAGE" != *CHANGE_ME* ]] || { echo "Replace CHANGE_ME in DEST_IMAGE" >&2; exit 2; }

PINNED_COMMIT=7e902a1ab49ee299d37bd38c8cde3f680ce4dc7f
BASE_IMAGE="${BASE_IMAGE:-quay.nju.edu.cn/ascend/vllm-ascend:deepseek-v4.1-flash-openeuler@sha256:0713ca300d55cd907a8beb9fca2444d8f2cf18036e9652f73a636d3dc54fc2a4}"
BUILDER="${BUILDER:-default}"

[[ -f "$SOURCE_DIR/Dockerfile" && -f "$SOURCE_DIR/tools/check_checksums.sh" ]] || {
  echo "Incomplete publisher source checkout" >&2; exit 2;
}
[[ "$(git -C "$SOURCE_DIR" rev-parse HEAD)" == "$PINNED_COMMIT" ]] || {
  echo "Publisher source commit differs from the tested package" >&2; exit 2;
}
[[ "$(uname -m)" == aarch64 ]] || {
  echo "Use an ARM64/aarch64 builder for this tested build path" >&2; exit 2;
}
docker info >/dev/null
docker buildx inspect "$BUILDER" >/dev/null

bash "$SOURCE_DIR/tools/check_checksums.sh"
bash "$SOURCE_DIR/tools/selfcheck_pkg.sh"
docker pull --platform linux/arm64 "$BASE_IMAGE"

docker buildx build \
  --builder "$BUILDER" \
  --platform linux/arm64 \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --build-arg ASCEND_PKG=/vllm-workspace/vllm-ascend/vllm_ascend \
  --build-arg VLLM_ROOT=/vllm-workspace/vllm \
  --build-arg SKIP_PGO=1 \
  --provenance=false \
  --sbom=false \
  --tag "$DEST_IMAGE" \
  --push \
  "$SOURCE_DIR"

docker buildx imagetools inspect "$DEST_IMAGE"
printf 'source_commit=%s\nbase_image=%s\npushed_image=%s\n' \
  "$PINNED_COMMIT" "$BASE_IMAGE" "$DEST_IMAGE"
