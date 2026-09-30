#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROXY_PY="${PD_PROXY_IMPL:-$SCRIPT_DIR/load_balance_proxy_server_example.py}"

[[ -f "$PROXY_PY" ]] || { echo "[pd] proxy implementation missing: $PROXY_PY" >&2; exit 1; }
command -v python3 >/dev/null || { echo '[pd] python3 is required' >&2; exit 1; }

export POD_IP="${POD_IP:-$(hostname -I | awk '{print $1}')}"
rank_output="$(python3 "$SCRIPT_DIR/pd_ranktable.py" --role "${PD_ROLE:-prefill}" --local-ip "$POD_IP")" || exit 2
mapfile -t peer <<<"$rank_output"
[[ "${#peer[@]}" -eq 7 ]] || { echo '[pd] incomplete ranktable discovery' >&2; exit 2; }

cmd=(python3 "$PROXY_PY"
  --host 0.0.0.0 --port "${PD_PROXY_PORT:-9000}"
  --prefiller-hosts "${peer[3]}" "${peer[4]}"
  --prefiller-ports "${PD_API_PORT:-8000}" "${PD_API_PORT:-8000}"
  --decoder-hosts "${peer[5]}" "${peer[6]}"
  --decoder-ports "${PD_API_PORT:-8000}" "${PD_API_PORT:-8000}"
  --max-waiting-retries 360 --waiting-retry-interval 10)

if [[ "${PD_VALIDATE_ONLY:-0}" == 1 ]]; then
  printf '[pd] proxy source: %s\n' "$PROXY_PY"
  printf '[pd] command:'; printf ' %q' "${cmd[@]}"; printf '\n'
  exit 0
fi
exec "${cmd[@]}"
