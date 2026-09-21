#!/usr/bin/env bash
set -Eeuo pipefail

: "${MODEL_PATH:?MODEL_PATH is required}"
: "${RANKTABLE_PATH:?RANKTABLE_PATH is required}"
: "${POD_IP:?POD_IP is required}"
: "${MAX_MODEL_LEN:=1048576}"
: "${MAX_NUM_SEQS:=32}"

workspace_root="$(dirname "$MODEL_PATH")"
: "${WEIGHT_HASH_REPORT:=$workspace_root/manifests/weights-sha256-verification.json}"
: "${PACKAGE_HASH_MANIFEST:=$workspace_root/manifests/package.sha256}"
: "${EXPECTED_WEIGHT_OBJECTS:=278}"
: "${EXPECTED_WEIGHT_BYTES:=797570012196}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  printf '[preflight][ERROR] %s\n' "$*" >&2
  exit 2
}

[[ "$(uname -m)" == "aarch64" ]] || fail "image architecture must be aarch64"
command -v python3 >/dev/null || fail "python3 is missing"
command -v vllm >/dev/null || fail "vllm executable is missing"
[[ -r "$RANKTABLE_PATH" ]] || fail "ranktable is not readable: $RANKTABLE_PATH"
[[ -r "$MODEL_PATH/config.json" ]] || fail "model config is missing: $MODEL_PATH/config.json"
[[ -r "$MODEL_PATH/quant_model_description.json" ]] || fail "Ascend quantization description is missing"
[[ -r "$WEIGHT_HASH_REPORT" ]] \
  || fail "final weight SHA256 report is missing: $WEIGHT_HASH_REPORT"
[[ -r "$PACKAGE_HASH_MANIFEST" ]] \
  || fail "deployment package hash manifest is missing: $PACKAGE_HASH_MANIFEST"

python3 "$script_dir/verify_readiness.py" \
  "$WEIGHT_HASH_REPORT" \
  --expected-objects "$EXPECTED_WEIGHT_OBJECTS" \
  --expected-bytes "$EXPECTED_WEIGHT_BYTES" \
  || fail "immutable weight verification did not pass"

(cd "$workspace_root" && sha256sum -c "$PACKAGE_HASH_MANIFEST" >/dev/null) \
  || fail "deployment package SHA256 verification failed"

partial_file="$(find "$MODEL_PATH" -type f -name '*.incomplete' -print -quit)"
[[ -z "$partial_file" ]] || fail "weights are still downloading: $partial_file"

weight_count="$(find "$MODEL_PATH" -maxdepth 1 -type f -name 'quant_model_weights-*.safetensors' | wc -l)"
[[ "$weight_count" -eq 270 ]] || fail "expected 270 quant_model_weights shards, found $weight_count"
engram_count="$(find "$MODEL_PATH" -maxdepth 1 -type f \
  \( -name 'engram_embed_weight_l*.safetensors' -o -name 'engram_embed_scale_l*.safetensors' \) | wc -l)"
[[ "$engram_count" -eq 4 ]] || fail "expected 4 engram weight/scale tensors, found $engram_count"

[[ "$MAX_MODEL_LEN" -eq 1048576 ]] \
  || fail "1M candidate requires MAX_MODEL_LEN=1048576, found $MAX_MODEL_LEN"
[[ "$MAX_NUM_SEQS" -ge 12 ]] \
  || fail "bundle requires at least 12 sequences per DP rank, found $MAX_NUM_SEQS"

device_count=0
for index in 0 1 2 3 4 5 6 7; do
  [[ -e "/dev/davinci${index}" ]] && device_count=$((device_count + 1))
done
[[ "$device_count" -eq 8 ]] || fail "expected 8 visible Ascend devices, found $device_count"

python3 -c 'import vllm, vllm_ascend' >/dev/null \
  || fail "vllm or vllm_ascend cannot be imported"

printf '[preflight] immutable artifacts, model, 1M context contract, runtime, ranktable and 8 NPUs passed\n'
