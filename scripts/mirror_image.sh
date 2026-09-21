#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_IMAGE="${SOURCE_IMAGE:-quay.io/ascend/vllm-ascend:deepseek-v4.1-flash@sha256:521f866a8d45b5af40cde09c46664838dae41031f4a0ed0183091bdd8ebed2d8}"
: "${DEST_IMAGE:?Set DEST_IMAGE to your private SWR image URI}"

docker pull --platform linux/arm64 "$SOURCE_IMAGE"
architecture="$(docker image inspect "$SOURCE_IMAGE" --format '{{.Architecture}}')"
[[ "$architecture" == "arm64" ]] || {
  echo "expected an arm64 image, got $architecture" >&2
  exit 2
}

docker tag "$SOURCE_IMAGE" "$DEST_IMAGE"
docker push "$DEST_IMAGE"
docker image inspect "$DEST_IMAGE" --format 'mirrored image={{index .RepoDigests 0}} architecture={{.Architecture}}'

