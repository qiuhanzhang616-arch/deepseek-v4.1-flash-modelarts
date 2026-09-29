#!/usr/bin/env bash
# Draft ModelArts Standard wrapper for one standalone A2 8-NPU W4A8 replica.
# ModelArts already supplies the container/devices; never start nested Docker.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_OVERRIDE_FILE="${RUNTIME_OVERRIDE_FILE:-$SCRIPT_DIR/runtime-overrides.env}"
if [[ -r "$RUNTIME_OVERRIDE_FILE" ]]; then
  # Versioned non-secret candidate values only.
  # shellcheck disable=SC1090
  source "$RUNTIME_OVERRIDE_FILE"
fi

MODEL_PATH="${MODEL_PATH:-/model/w4a8}"
MODEL_NAME="${MODEL_NAME:-deepseek-v4.1-flash}"
PORT="${SERVICE_PORT:-8000}"
LOG_ROOT="${LOG_ROOT:-/model/w4a8-results/runtime-logs}"
STATE_ROOT="${STATE_ROOT:-/tmp/w4a8-state}"
CANDIDATE_ID="${CANDIDATE_ID:-w4a8-a2-single-node-4replicas-c1-draftgraph1}"
MAX_LEN="${MAX_LEN:-262144}"
MAX_SEQS="${MAX_SEQS:-32}"
BAT_TOKENS="${BAT_TOKENS:-8192}"
GPU_UTIL="${GPU_UTIL:-0.92}"
PREFIX="${PREFIX:-1}"
SPEC="${SPEC:-1}"
SP_TOKENS="${SP_TOKENS:-5}"
DRAFT_GRAPH="${DRAFT_GRAPH:-1}"
ENGRAM="${ENGRAM:-1}"
ENGRAM_STORAGE="${ENGRAM_STORAGE:-int8}"
TOOL_CALLING="${TOOL_CALLING:-1}"
DEFAULT_REASONING_EFFORT="${DEFAULT_REASONING_EFFORT:-low}"
TELEMETRY_INTERVAL_SECONDS="${TELEMETRY_INTERVAL_SECONDS:-30}"

mkdir -p "$LOG_ROOT" "$STATE_ROOT"
POD_IP="${POD_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
POD_IP="${POD_IP:-$(hostname)}"
RUN_ID="${CANDIDATE_ID}-$(date +%Y%m%dT%H%M%S)-${POD_IP//./_}"
STARTUP_LOG="$LOG_ROOT/startup-$RUN_ID.log"
exec > >(tee -a "$STARTUP_LOG") 2>&1

fail() { echo "[w4a8-start][ERROR] $*"; exit 2; }

# Community feedback: local health probes can be intercepted by HTTP proxies.
no_proxy="${no_proxy:-}"
no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost,::1,$POD_IP"
export no_proxy NO_PROXY="$no_proxy"

export PYTORCH_NPU_ALLOC_CONF="${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}"
export HCCL_BUFFSIZE="${HCCL_BUFFSIZE:-1024}"
export TASK_QUEUE_ENABLE="${TASK_QUEUE_ENABLE:-1}"
export HCCL_OP_EXPANSION_MODE="${HCCL_OP_EXPANSION_MODE:-AIV}"
export ASCEND_MAX_OP_CACHE_SIZE="${ASCEND_MAX_OP_CACHE_SIZE:--1}"
export V41_KV_TIER="${V41_KV_TIER:-off}"
export V41_ENGRAM_LOCAL_OWNER_FILE="${V41_ENGRAM_LOCAL_OWNER_FILE:-/tmp/v41_engram_localowner}"
export V41_ENGRAM_DEVICE_INDEX="${V41_ENGRAM_DEVICE_INDEX:-0}"
export VLLM_SERVER_DEV_MODE=0
export LOG_REQUESTS=0
# The ModelArts Standard container reports `can't start new thread` while the
# vLLM CLI imports OpenTelemetry on this 192-vCPU flavor. Bound common CPU
# thread pools before any Python/torch/vLLM imports; this changes no model or
# NPU-parallelism settings.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OMP_THREAD_LIMIT="${OMP_THREAD_LIMIT:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"
export NUMEXPR_MAX_THREADS="${NUMEXPR_MAX_THREADS:-1}"
export BLIS_NUM_THREADS="${BLIS_NUM_THREADS:-1}"

# Install the ModelArts-only OTel startup shim before any Python process starts.
# The failure traceback is in Resource.create -> ThreadPoolExecutor.submit;
# the shim runs only the two cheap built-in resource detectors synchronously.
export PYTHONPATH="$SCRIPT_DIR/c4${PYTHONPATH:+:$PYTHONPATH}"
export OTEL_EXPERIMENTAL_RESOURCE_DETECTORS="service_instance,otel"
SITE_CUSTOMIZE="$SCRIPT_DIR/c4/sitecustomize.py"
SITE_CUSTOMIZE_SHA256="0efb7f448ecddae5644a766c4266b114e9ff7151bcff419f40a5ffa268bff0ef"
[[ -s "$SITE_CUSTOMIZE" ]] || fail "OpenTelemetry thread shim missing: $SITE_CUSTOMIZE"
actual_site_sha="$(sha256sum "$SITE_CUSTOMIZE" | awk '{print $1}')"
[[ "$actual_site_sha" == "$SITE_CUSTOMIZE_SHA256" ]] || \
  fail "OpenTelemetry thread shim hash mismatch: $actual_site_sha"
printf '[w4a8-start][THREAD-DIAG] sitecustomize_sha256=%s\n' "$actual_site_sha"

# Capture the actual container PID/thread ceiling and prove one thread can start
# before loading model weights or initializing the NPU runtime.
for limit_file in /sys/fs/cgroup/pids.current /sys/fs/cgroup/pids.max \
                  /sys/fs/cgroup/pids/pids.current /sys/fs/cgroup/pids/pids.max; do
  if [[ -r "$limit_file" ]]; then
    printf '[w4a8-start][THREAD-DIAG] %s=%s\n' "$limit_file" "$(<"$limit_file")"
  fi
done
grep -E 'Max processes|Max stack size' /proc/self/limits || true
grep '^Threads:' /proc/self/status || true
if ! python3 - <<'PY'
import threading
import opentelemetry.sdk.resources as resources

if not getattr(resources, "_w4a8_serial_resource_detection", False):
    raise RuntimeError("ModelArts OTel serial-resource shim was not loaded")

thread = threading.Thread(target=lambda: None)
thread.start()
thread.join(timeout=5)
if thread.is_alive():
    raise RuntimeError("one-thread startup probe timed out")
print("[w4a8-start][THREAD-DIAG] OTel shim and single-thread probe passed")
PY
then
  fail "Python/OTel thread preflight failed; refusing to load 490-GiB W4A8 checkpoint"
fi

[[ -d "$MODEL_PATH" ]] || fail "model directory missing: $MODEL_PATH"
[[ -f "$MODEL_PATH/config.json" ]] || fail "config.json missing"
[[ -f "$MODEL_PATH/tokenizer.json" ]] || fail "tokenizer.json missing"
[[ -f "$MODEL_PATH/quant_model_description.json" ]] || fail "quant_model_description.json missing"
shopt -s nullglob
main_shards=("$MODEL_PATH"/quant_model_weights-*-of-00072.safetensors)
mtp_shards=("$MODEL_PATH"/mtpq-*-of-00004.safetensors)
[[ "${#main_shards[@]}" -eq 72 ]] || fail "expected 72 main W4A8 shards; found ${#main_shards[@]}"
[[ "${#mtp_shards[@]}" -eq 4 ]] || fail "expected 4 MTPQ shards; found ${#mtp_shards[@]}"
[[ -f "$MODEL_PATH/quant_model_weights.safetensors.index.json" ]] || fail "W4A8 shard index missing"
[[ -f "$MODEL_PATH/mtpq_manifest.json" ]] || fail "MTPQ manifest missing"
[[ -f "$MODEL_PATH/engram_int8/PARTS.sha256" ]] || fail "Engram part checksum manifest missing"
[[ -f "$MODEL_PATH/engram_int8/reassemble_engram_weights.sh" ]] || fail "Engram reassembly and verification script missing"
# ENGRAM_VERIFY=size (default): check exact byte sizes only; the tensors were
# SHA256-verified at reassembly and in preflight and are mounted read-only.
# ENGRAM_VERIFY=sha256: full checksum pass (~420 GB read from SFS per replica).
if [[ "${ENGRAM_VERIFY:-size}" == "sha256" ]]; then
  (cd "$MODEL_PATH/engram_int8" && bash ./reassemble_engram_weights.sh --check-only) \
    || fail "Engram parts or reassembled tensors do not match pinned checksums"

  for tensor in layers_1_engram_embed.weight layers_14_engram_embed.weight; do
    [[ -f "$MODEL_PATH/engram_int8/${tensor}.safetensors" ]] || \
      fail "Engram tensor must be reassembled before launch: $tensor"
  done
  (cd "$MODEL_PATH/engram_int8" && awk '$2 == "layers_1_engram_embed.weight.safetensors" || $2 == "layers_14_engram_embed.weight.safetensors" || $2 == "layers_1_engram_embed.scale.safetensors" || $2 == "layers_14_engram_embed.scale.safetensors" {print}' PARTS.sha256 | sha256sum -c -) \
    || fail "reassembled Engram tensor/scale checksum verification failed"
else
  declare -A engram_size=(
    [layers_1_engram_embed.weight.safetensors]=98305579120
    [layers_14_engram_embed.weight.safetensors]=98308270704
    [layers_1_engram_embed.scale.safetensors]=12288197488
    [layers_14_engram_embed.scale.safetensors]=12288533936
  )
  for f in "${!engram_size[@]}"; do
    got="$(stat -c %s "$MODEL_PATH/engram_int8/$f" 2>/dev/null)" || fail "Engram file missing: $f"
    [[ "$got" == "${engram_size[$f]}" ]] || fail "Engram size mismatch: $f is $got bytes, expected ${engram_size[$f]}"
  done
  printf "[startup] Engram size check passed (ENGRAM_VERIFY=size; sha256 skipped)\n"
fi

device_count="$(python3 - <<'PY'
import torch
print(torch.npu.device_count())
PY
)" || fail "unable to enumerate Ascend NPUs"
[[ "$device_count" -eq 8 ]] || fail "each standalone replica must see 8 NPUs; found $device_count"
# ModelArts Standard blocks npu-smi inside inference containers (ret -8005),
# and the management call can terminate the launcher before a shell fallback.
# Device enumeration above remains the hard gate; keep npu-smi telemetry-only.
printf '[w4a8-start][WARN] skipped npu-smi info; torch.npu.device_count=%s\n' "$device_count"

SERVE_V2="${SERVE_V2:-/opt/dsv41/scripts/serve_v2.sh}"
[[ -f "$SERVE_V2" ]] || fail "ModelScope A2 serve_v2.sh missing in image"
[[ -f /opt/dsv41/BUILD_INFO.txt ]] || fail "custom image BUILD_INFO.txt missing"
[[ -f /opt/dsv41/scripts/serve_v2.sh ]] || fail "custom image serve_v2.sh missing"

# Follow the ModelArts Standard startup package: use a lightweight runtime
# import preflight, then let the actual server command parse its full arguments.
# Running `vllm serve --help` here eagerly imports API/OTel/SciPy before server
# startup and has repeatedly stalled or exhausted container thread creation.
if ! python3 -c 'import vllm, vllm_ascend; print("[startup] vllm and vllm_ascend imports passed")'; then
  fail "vllm or vllm_ascend cannot be imported"
fi
printf '[startup] lightweight runtime preflight passed; proceeding to serve_v2\n'

if [[ "$DRAFT_GRAPH" == "1" ]]; then
  ASCEND_PKG="$(awk -F= '$1=="ascend_pkg"{print $2; exit}' /opt/dsv41/BUILD_INFO.txt)"
  ASCEND_PKG="${ASCEND_PKG:-/vllm-workspace/vllm-ascend/vllm_ascend}"
  DRAFT_DIR=/opt/dsv41/patches/draft
  for pair in \
      "dsa_v1.py:$ASCEND_PKG/attention/dsa_v1.py" \
      "dspark_proposer.py:$ASCEND_PKG/spec_decode/dspark_proposer.py" \
      "llm_base_proposer.py:$ASCEND_PKG/spec_decode/llm_base_proposer.py"; do
    src="${pair%%:*}"
    dst="${pair#*:}"
    [[ -f "$DRAFT_DIR/$src" ]] || fail "draft-graph source missing: $DRAFT_DIR/$src"
    install -m 0644 "$DRAFT_DIR/$src" "$dst"
    [[ "$(sha256sum "$DRAFT_DIR/$src" | awk '{print $1}')" == \
       "$(sha256sum "$dst" | awk '{print $1}')" ]] || fail "draft-graph copy hash mismatch: $src"
  done
  grep -q DSPARK_GRAPH_CAPTURE_METADATA "$ASCEND_PKG/spec_decode/dspark_proposer.py" || \
    fail "draft patch absent from live tree; refusing silent graph fallback"
  export DSPARK_GRAPH_CAPTURE_METADATA=1
fi

if [[ -f /opt/dsv41/admission_gate.patch.NOT_APPLIED ]]; then
  export VLLM_ADMISSION_GATE=0
else
  export VLLM_ADMISSION_GATE=1
fi

# Match the A2 recipe's sparse graph capture buckets and include max-seq * (1+S).
step_tokens=$((SP_TOKENS + 1))
capture_max=$((MAX_SEQS * step_tokens))
(( capture_max < 32 )) && capture_max=32
CAPTURE_SIZES=1,2,3,4
for size in 6 8 12 16 20 24 32 40 48; do
  if (( size >= step_tokens && size <= capture_max )); then CAPTURE_SIZES="$CAPTURE_SIZES,$size"; fi
done
size=96
while (( size <= capture_max )); do CAPTURE_SIZES="$CAPTURE_SIZES,$size"; size=$((size * 2)); done
case ",$CAPTURE_SIZES," in *,"$step_tokens",*) ;; *) CAPTURE_SIZES="$CAPTURE_SIZES,$step_tokens" ;; esac
case ",$CAPTURE_SIZES," in *,"$capture_max",*) ;; *) CAPTURE_SIZES="$CAPTURE_SIZES,$capture_max" ;; esac

export MODEL="$MODEL_PATH" TP=8 DP=1 PORT="$PORT" SERVED_NAME="$MODEL_NAME"
export MAX_LEN MAX_SEQS BAT_TOKENS GPU_UTIL BLOCK=128 KV_DTYPE=bfloat16
export GRAPH=1 EAGER=0 PREFIX SPEC SPEC_EAGER=0 SP_TOKENS ENGRAM ENGRAM_STORAGE VISION=1
export NPUGRAPH_EX=1 STATIC_KERNEL=1 CPU_BIND=1 MULTISTREAM=1 DSA_OVERLAP=1
export FUSED_MC2=0 MC2=0 MC2_HIER=0 REDUCE_SAMPLE=0 LOADER_MT=1 LAZY=1 VISION=1
export CAPTURE_SIZES PROFILE=0
export V41_ENGRAM_HOST_RESIDENT=1
export DRAFT_WINDOW="${DRAFT_WINDOW:-5}"
export LOG_REQUESTS=1 MAX_LOG_LEN=2048
if [[ "$TOOL_CALLING" == "1" ]]; then
  export EXTRA='--tokenizer-mode=deepseek_v41 --reasoning-parser=deepseek_v41 --tool-call-parser=deepseek_v41 --enable-auto-tool-choice --default-chat-template-kwargs={"reasoning_effort":"low"}'
else
  fail "tool calling is required by this candidate contract"
fi

printf '[w4a8-start] candidate=%s pod=%s model=%s port=%s\n' "$CANDIDATE_ID" "$POD_IP" "$MODEL_PATH" "$PORT"
printf '[w4a8-start] ctx=%s seqs=%s bat=%s gpu_util=%s prefix=%s dspark=%s draft_graph=%s capture=%s engram_index=%s admission_gate=%s reasoning=%s\n' \
  "$MAX_LEN" "$MAX_SEQS" "$BAT_TOKENS" "$GPU_UTIL" "$PREFIX" "$SP_TOKENS" "$DRAFT_GRAPH" "$CAPTURE_SIZES" "$V41_ENGRAM_DEVICE_INDEX" "$VLLM_ADMISSION_GATE" "$DEFAULT_REASONING_EFFORT"
cat /opt/dsv41/BUILD_INFO.txt

CELL_STATE_FILE="${CELL_STATE_FILE:-/model/w4a8-results/.active-cell.json}"
if [[ -f "$SCRIPT_DIR/runtime_telemetry.sh" ]]; then
  telemetry_log="$LOG_ROOT/telemetry-$RUN_ID.log"
  TELEMETRY_PARENT_PID="$$" POD_IP="$POD_IP" CANDIDATE_ID="$CANDIDATE_ID" \
    CELL_STATE_FILE="$CELL_STATE_FILE" STARTUP_LOG_FILE="$STARTUP_LOG" \
    bash "$SCRIPT_DIR/runtime_telemetry.sh" "$PORT" "$TELEMETRY_INTERVAL_SECONDS" \
    >>"$telemetry_log" 2>&1 &
  printf '[w4a8-start] telemetry_pid=%s log=%s\n' "$!" "$telemetry_log"
fi

cd /opt/dsv41
exec bash "$SERVE_V2"

