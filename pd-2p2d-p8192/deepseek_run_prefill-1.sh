#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PD_EXPECTED_RANK=1
exec bash "$SCRIPT_DIR/pd_entrypoint.sh" prefill
