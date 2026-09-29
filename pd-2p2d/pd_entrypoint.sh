#!/usr/bin/env bash
# Same command for both instances in one ModelArts unit; pass prefill or decode.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
role="${1:-}"
[[ "$role" == prefill || "$role" == decode ]] || { echo 'usage: pd_entrypoint.sh prefill|decode' >&2; exit 2; }
export POD_IP="${POD_IP:-$(hostname -I | awk '{print $1}')}"
[[ -n "$POD_IP" ]] || { echo '[pd] POD_IP unavailable' >&2; exit 2; }
rank_output="$(python3 "$SCRIPT_DIR/pd_ranktable.py" --role "$role" --local-ip "$POD_IP")" || exit 2
mapfile -t peer <<<"$rank_output"
[[ "${#peer[@]}" -eq 7 ]] || { echo '[pd] incomplete ranktable discovery' >&2; exit 2; }
local_ip="${peer[0]}" master_ip="${peer[1]}" rank="${peer[2]}"
if [[ -n "${PD_EXPECTED_RANK:-}" && "$rank" != "$PD_EXPECTED_RANK" ]]; then
  echo "[pd] wrapper expects rank $PD_EXPECTED_RANK but ranktable assigns $rank" >&2
  exit 2
fi
p0="${peer[3]}" p1="${peer[4]}" d0="${peer[5]}" d1="${peer[6]}"
source "$SCRIPT_DIR/pd_common.sh"

if [[ "${PD_VALIDATE_ONLY:-0}" == 1 ]]; then
  pd_serve "$role" "$rank" "$local_ip" "$master_ip"
  printf '[pd] proxy peers P=%s,%s D=%s,%s\n' "$p0" "$p1" "$d0" "$d1"
  exit 0
fi
log_dir="${PD_LOG_DIR:-/model/w4a8-results/pd-2p2d-logs}"
mkdir -p "$log_dir"
log_file="$log_dir/${role}-${rank}-${POD_IP//./_}-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$log_file") 2>&1
printf '[pd] pod=%s role=%s rank=%s log=%s\n' "$POD_IP" "$role" "$rank" "$log_file"

pd_serve "$role" "$rank" "$local_ip" "$master_ip" &
engine_pid=$!
cleanup() {
  trap - EXIT INT TERM
  [[ -z "${proxy_pid:-}" ]] || kill "$proxy_pid" 2>/dev/null || true
  kill "$engine_pid" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Never advertise readiness while this local engine has not completed loading.
ready=0
for ((i=0; i<1800; i++)); do
  kill -0 "$engine_pid" 2>/dev/null || { echo '[pd] engine exited before /health'; exit 2; }
  if python3 - "${PD_API_PORT:-8000}" <<'PY' 2>/dev/null
import sys,urllib.request
with urllib.request.urlopen('http://127.0.0.1:'+sys.argv[1]+'/health',timeout=2) as r:
    assert r.status==200
PY
  then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 ]] || { echo '[pd] local engine readiness timed out'; exit 2; }

proxy="$SCRIPT_DIR/load_balance_proxy_server_example.py"
[[ -f "$proxy" ]] || { echo "[pd] proxy missing: $proxy" >&2; exit 2; }
python3 "$proxy" --host 0.0.0.0 --port "${PD_PROXY_PORT:-9000}" \
  --prefiller-hosts "$p0" "$p1" --prefiller-ports "${PD_API_PORT:-8000}" "${PD_API_PORT:-8000}" \
  --decoder-hosts "$d0" "$d1" --decoder-ports "${PD_API_PORT:-8000}" "${PD_API_PORT:-8000}" \
  --max-waiting-retries 360 --waiting-retry-interval 10 &
proxy_pid=$!
printf '[pd] proxy started port=%s pid=%s\n' "${PD_PROXY_PORT:-9000}" "$proxy_pid"
wait -n "$engine_pid" "$proxy_pid"
echo '[pd] engine or proxy exited; terminating peer process'
exit 2
