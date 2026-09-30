#!/usr/bin/env bash
# Same command for both instances in one ModelArts unit; pass prefill or decode.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
role="${1:-}"
[[ "$role" == prefill || "$role" == decode ]] || { echo 'usage: pd_entrypoint.sh prefill|decode' >&2; exit 2; }
export POD_IP="${POD_IP:-$(hostname -I | awk '{print $1}')}"
[[ -n "$POD_IP" ]] || { echo '[pd] POD_IP unavailable' >&2; exit 2; }
export PD_RENDEZVOUS_ID="${PD_RENDEZVOUS_ID:-w4a8-pd-paired-fast-p8192-20260930-r3}"
log_dir="${PD_LOG_DIR:-/model/w4a8-results/pd-2p2d-logs}"
mkdir -p "$log_dir"
export PD_LOG_FILE="${PD_LOG_FILE:-$log_dir/${role}-${POD_IP//./_}-$(date -u +%Y%m%dT%H%M%SZ).log}"
log_file="$PD_LOG_FILE"
if [[ "${PD_LOG_CAPTURE_READY:-0}" != 1 ]]; then
  export PD_LOG_CAPTURE_READY=1
  exec > >(tee -a "$log_file") 2>&1
fi
# Install compatibility before discovery, engine and proxy children are created.
# The marker is set only by the launcher after syscall and thread probes pass.
if [[ "${PD_CLONE3_COMPAT_READY:-0}" != 1 ]]; then
  exec python3 -u "$SCRIPT_DIR/pd_clone3_compat.py" bash "$SCRIPT_DIR/pd_entrypoint.sh" "$role"
fi
printf '[pd] discovery start pod=%s role=%s epoch=%s ranktable=%s log=%s\n' \
  "$POD_IP" "$role" "$PD_RENDEZVOUS_ID" \
  "${GLOBAL_RANK_TABLE_FILE_PATH:-/user/global/config/global_rank_table.json}" "$log_file"
discovery_started=$SECONDS
python3 "$SCRIPT_DIR/pd_peer_discovery.py" --role "$role" --local-ip "$POD_IP" \
  --pod-name "${HOSTNAME:-$(hostname)}" --script "$SCRIPT_DIR/pd_common.sh" \
  --register-only --parent-pid "$$" &
registration_pid=$!
trap 'kill "$registration_pid" 2>/dev/null || true' EXIT
rank_output="$(python3 "$SCRIPT_DIR/pd_peer_discovery.py" --role "$role" --local-ip "$POD_IP" --pod-name "${HOSTNAME:-$(hostname)}" --script "$SCRIPT_DIR/pd_common.sh")" || exit 2
printf '[pd] discovery completed elapsed=%ss source=explicit-role-sfs\n' "$((SECONDS-discovery_started))"
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
printf '[pd] pod=%s role=%s rank=%s log=%s\n' "$POD_IP" "$role" "$rank" "$log_file"

pd_serve "$role" "$rank" "$local_ip" "$master_ip" &
engine_pid=$!
cleanup() {
  trap - EXIT INT TERM
  [[ -z "${proxy_pid:-}" ]] || kill "$proxy_pid" 2>/dev/null || true
  kill "$registration_pid" 2>/dev/null || true
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
