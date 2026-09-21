#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RANKTABLE_PATH="${RANKTABLE_PATH:-/user/global/config/global_rank_table.json}"
MODEL_ROOT="${MODEL_ROOT:-/model/deepseek-v41-flash}"
MODEL_PATH="${MODEL_PATH:-${MODEL_ROOT}/weights}"
LOG_ROOT="${LOG_ROOT:-${MODEL_ROOT}/runtime-logs}"
STATE_DIR="${STATE_DIR:-/tmp/deepseek-v41-modelarts}"
EXPECTED_NODES="${EXPECTED_NODES:-4}"
DEVICES_PER_NODE="${DEVICES_PER_NODE:-8}"
SERVICE_PORT="${SERVICE_PORT:-8000}"
DP_RPC_PORT="${DP_RPC_PORT:-13399}"
DP_MASTER_WAIT_SECONDS="${DP_MASTER_WAIT_SECONDS:-3600}"
MODEL_NAME="${MODEL_NAME:-deepseek-v4.1-flash}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-1048576}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-32}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-4096}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.94}"
CANDIDATE_ID="${CANDIDATE_ID:-validated-a2-1m-m094}"
RANKTABLE_WAIT_SECONDS="${RANKTABLE_WAIT_SECONDS:-600}"
ENABLE_RUNTIME_TELEMETRY="${ENABLE_RUNTIME_TELEMETRY:-1}"
TELEMETRY_INTERVAL_SECONDS="${TELEMETRY_INTERVAL_SECONDS:-1}"
CELL_STATE_FILE="${CELL_STATE_FILE:-${MODEL_ROOT}/benchmark-results/.active-cell.json}"
MODEL_LOADER_THREADS="${MODEL_LOADER_THREADS:-128}"

# A mounted, non-secret override makes a measured tuning candidate take effect
# on a container restart without editing the ModelArts deployment definition.
# Keep the deployment environment as the immutable baseline; the startup log
# records the effective values after this file is applied.
RUNTIME_OVERRIDE_FILE="${RUNTIME_OVERRIDE_FILE:-${SCRIPT_DIR}/runtime-overrides.env}"
if [[ -r "$RUNTIME_OVERRIDE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$RUNTIME_OVERRIDE_FILE"
fi

: "${POD_IP:?ModelArts must inject POD_IP}"
mkdir -p "$LOG_ROOT" "$STATE_DIR"
startup_stamp="$(date +%Y%m%dT%H%M%S)"
log_file="$LOG_ROOT/startup-${POD_IP}-${startup_stamp}.log"
exit_marker="$LOG_ROOT/exit-${POD_IP}-${startup_stamp}.status"
exec > >(tee -a "$log_file") 2>&1

record_exit() {
  status=$?
  printf '[startup] wrapper_exit status=%s\n' "$status"
  printf '%s\n' "$status" > "$exit_marker"
}
trap record_exit EXIT

printf '[startup] waiting for ModelArts ranktable: %s\n' "$RANKTABLE_PATH"
deadline=$((SECONDS + RANKTABLE_WAIT_SECONDS))
while true; do
  if [[ -r "$RANKTABLE_PATH" ]] && \
     python3 - "$RANKTABLE_PATH" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
raise SystemExit(0 if data.get("status") in (None, "completed") else 1)
PY
  then
    break
  fi
  (( SECONDS < deadline )) || { echo '[startup][ERROR] ranktable timeout'; exit 2; }
  sleep 2
done

eval "$(python3 "$SCRIPT_DIR/ma_rank.py" \
  --ranktable "$RANKTABLE_PATH" \
  --pod-ip "$POD_IP" \
  --expected-nodes "$EXPECTED_NODES" \
  --devices-per-node "$DEVICES_PER_NODE" \
  --format shell)"

if [[ "$WORLD_NODES" -ne 4 || "$DEVICES_PER_NODE" -ne 8 ]]; then
  echo '[startup][ERROR] only the validated 4-node x 8-A2 topology is allowed'
  exit 2
fi

NIC_NAME="$(python3 - "$POD_IP" <<'PY'
import fcntl
import os
import socket
import struct
import sys

target = sys.argv[1]
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    for name in sorted(os.listdir('/sys/class/net')):
        try:
            request = struct.pack('256s', name[:15].encode('utf-8'))
            result = fcntl.ioctl(sock.fileno(), 0x8915, request)  # SIOCGIFADDR
        except OSError:
            continue
        if socket.inet_ntoa(result[20:24]) == target:
            print(name)
            break
    else:
        raise SystemExit(2)
PY
)"
[[ -n "$NIC_NAME" ]] || { echo '[startup][ERROR] cannot resolve communication NIC'; exit 2; }

export HCCL_IF_IP="$LOCAL_IP"
export GLOO_SOCKET_IFNAME="$NIC_NAME"
export TP_SOCKET_IFNAME="$NIC_NAME"
export HCCL_SOCKET_IFNAME="$NIC_NAME"
export VLLM_HOST_IP="$LOCAL_IP"
export ASCEND_RT_VISIBLE_DEVICES="$LOCAL_DEVICE_IDS"

if [[ -f /usr/lib/aarch64-linux-gnu/libjemalloc.so.2 ]]; then
  export LD_PRELOAD="/usr/lib/aarch64-linux-gnu/libjemalloc.so.2${LD_PRELOAD:+:$LD_PRELOAD}"
fi

export MODEL_ROOT MODEL_PATH RANKTABLE_PATH POD_IP NODE_RANK NODE0_IP LOCAL_IP NIC_NAME
export MAX_MODEL_LEN MAX_NUM_SEQS MAX_NUM_BATCHED_TOKENS GPU_MEMORY_UTILIZATION
export CANDIDATE_ID CELL_STATE_FILE MODEL_LOADER_THREADS
"$SCRIPT_DIR/preflight.sh"
env | grep -E '^(POD_IP|NODE_RANK|NODE0_IP|LOCAL_IP|NIC_NAME|WORLD_NODES|ASCEND_RT_VISIBLE_DEVICES)=' \
  > "$STATE_DIR/runtime.env"

headless_args=()
if [[ "$NODE_RANK" -ne 0 ]]; then
  headless_args+=(--headless)
fi

printf '[startup] node_rank=%s node0=%s local=%s nic=%s model=%s\n' \
  "$NODE_RANK" "$NODE0_IP" "$LOCAL_IP" "$NIC_NAME" "$MODEL_PATH"
printf '[startup] config candidate_id=%s max_model_len=%s max_num_seqs=%s max_num_batched_tokens=%s gpu_memory_utilization=%s model_loader_threads=%s telemetry_interval=%s cell_state_file=%s\n' \
  "$CANDIDATE_ID" "$MAX_MODEL_LEN" "$MAX_NUM_SEQS" "$MAX_NUM_BATCHED_TOKENS" "$GPU_MEMORY_UTILIZATION" "$MODEL_LOADER_THREADS" "$TELEMETRY_INTERVAL_SECONDS" "$CELL_STATE_FILE"

if [[ "$NODE_RANK" -ne 0 ]]; then
  printf '[startup] waiting for node0 DP RPC endpoint %s:%s (timeout=%ss)\n' \
    "$NODE0_IP" "$DP_RPC_PORT" "$DP_MASTER_WAIT_SECONDS"
  deadline=$((SECONDS + DP_MASTER_WAIT_SECONDS))
  while ! python3 - "$NODE0_IP" "$DP_RPC_PORT" <<'PY'
import socket, sys
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(2.0)
    raise SystemExit(0 if sock.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0 else 1)
PY
  do
    (( SECONDS < deadline )) || {
      echo '[startup][ERROR] node0 DP RPC endpoint did not become ready'
      exit 2
    }
    sleep 2
  done
  printf '[startup] node0 DP RPC endpoint is accepting connections\n'
fi

if [[ "$ENABLE_RUNTIME_TELEMETRY" == "1" ]]; then
  telemetry_log="$LOG_ROOT/telemetry-${POD_IP}-$(date +%Y%m%dT%H%M%S).log"
  TELEMETRY_PARENT_PID="$$" POD_IP="$POD_IP" CANDIDATE_ID="$CANDIDATE_ID" \
    CELL_STATE_FILE="$CELL_STATE_FILE" NIC_NAME="$NIC_NAME" STARTUP_LOG_FILE="$log_file" \
    bash "$SCRIPT_DIR/runtime_telemetry.sh" "$SERVICE_PORT" "$TELEMETRY_INTERVAL_SECONDS" \
    >>"$telemetry_log" 2>&1 &
  printf '[startup] telemetry_pid=%s interval=%ss log=%s\n' "$!" "$TELEMETRY_INTERVAL_SECONDS" "$telemetry_log"
fi

vllm serve "$MODEL_PATH" \
  --host 0.0.0.0 \
  --port "$SERVICE_PORT" \
  "${headless_args[@]}" \
  --data-parallel-address "$NODE0_IP" \
  --data-parallel-rpc-port "$DP_RPC_PORT" \
  --data-parallel-size 4 \
  --data-parallel-size-local 1 \
  --data-parallel-start-rank "$NODE_RANK" \
  --tensor-parallel-size 8 \
  --enable-expert-parallel \
  --served-model-name "$MODEL_NAME" \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --block-size 128 \
  --tokenizer-mode deepseek_v41 \
  --reasoning-parser deepseek_v41 \
  --tool-call-parser deepseek_v41 \
  --enable-auto-tool-choice \
  --trust-remote-code \
  --model-loader-extra-config "{\"enable_multithread_load\":true,\"num_threads\":${MODEL_LOADER_THREADS}}" \
  --safetensors-load-strategy lazy \
  --quantization ascend \
  --additional-config '{"enable_engram":true,"engram_storage":"int8","enable_cpu_binding":true,"ascend_compilation_config":{"enable_npugraph_ex":false,"enable_static_kernel":false}}' \
  --speculative-config '{"method":"dspark","num_speculative_tokens":5,"enforce_eager":true}' \
  --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}' &

vllm_pid=$!
printf '[startup] vllm_pid=%s\n' "$vllm_pid"
trap 'kill -TERM "$vllm_pid" 2>/dev/null || true' TERM INT
set +e
wait "$vllm_pid"
vllm_status=$?
set -e
exit "$vllm_status"
