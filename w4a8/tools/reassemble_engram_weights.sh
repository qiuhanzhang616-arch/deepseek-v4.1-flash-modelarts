#!/usr/bin/env bash
# Safely reconstruct the two publisher-split Engram INT8 weight tensors.
# Run this copy from the snapshot's engram_int8/ directory. Parts are retained.
set -Eeuo pipefail
cd "$(dirname "$0")"
[[ -f PARTS.sha256 ]] || { echo "PARTS.sha256 missing" >&2; exit 2; }
command -v sha256sum >/dev/null

case "${1:-}" in
  "") CHECK_ONLY=0 ;;
  --check-only) CHECK_ONLY=1 ;;
  --help|-h)
    echo "usage: bash reassemble_engram_weights.sh [--check-only]"
    echo "Never deletes split parts. Full outputs are SHA256-verified before publication."
    exit 0 ;;
  *) echo "unsupported argument: $1" >&2; exit 2 ;;
esac

declare -A expected=(
  [layers_1_engram_embed.weight.safetensors]=51d28f161232e3bf600b92ef4e3c38ceb9164b801bd456503bb1a29da496ea9f
  [layers_14_engram_embed.weight.safetensors]=bee6e08838c75d40c4b1f5f8d7e4716aba34f90c03c17e77ad406e36188cccaa
)

tmp=""
cleanup() { [[ -z "$tmp" ]] || rm -f -- "$tmp"; }
trap cleanup EXIT

for layer in 1 14; do
  target="layers_${layer}_engram_embed.weight.safetensors"
  if [[ -e "$target" ]]; then
    printf '%s  %s\n' "${expected[$target]}" "$target" | sha256sum -c -
    echo "verified existing $target"
    continue
  fi
  parts=()
  for n in 0 1 2 3 4 5; do
    printf -v number '%02d' "$n"
    part="${target}.part-${number}-of-06"
    [[ -f "$part" ]] || { echo "missing $part" >&2; exit 2; }
    want="$(awk -v file="$part" '$2 == file {print $1; exit}' PARTS.sha256)"
    [[ -n "$want" ]] || { echo "checksum entry missing for $part" >&2; exit 2; }
    printf '%s  %s\n' "$want" "$part" | sha256sum -c -
    parts+=("$part")
  done
  if (( CHECK_ONLY )); then
    echo "parts verified; $target not created (--check-only)"
    continue
  fi
  tmp="${target}.tmp-$$"
  [[ ! -e "$tmp" ]] || { echo "temporary target already exists: $tmp" >&2; exit 2; }
  cat -- "${parts[@]}" > "$tmp"
  printf '%s  %s\n' "${expected[$target]}" "$tmp" | sha256sum -c -
  mv -n -- "$tmp" "$target"
  [[ ! -e "$tmp" ]] || { echo "target appeared concurrently; refusing to overwrite" >&2; exit 2; }
  printf '%s  %s\n' "${expected[$target]}" "$target" | sha256sum -c -
  tmp=""
  echo "published verified $target (split parts retained)"
done
