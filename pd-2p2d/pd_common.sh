#!/usr/bin/env bash
# W4A8 ModelArts Standard 2P2D engine launcher. Called only after ranktable discovery.
set -Eeuo pipefail

pd_die() { printf '[pd][ERROR] %s\n' "$*" >&2; return 1; }

pd_serve() {
  local role="$1" rank="$2" local_ip="$3" master_ip="$4"
  local model_path="${PD_MODEL_PATH:-/model/w4a8/model-view}"
  local max_len="${PD_MAX_MODEL_LEN:-1048576}"
  local batch seq kv_role kv_port additional kv_config
  [[ "$role" == prefill || "$role" == decode ]] || { pd_die "invalid role $role"; return 1; }
  [[ "$rank" == 0 || "$rank" == 1 ]] || { pd_die "invalid DP rank $rank"; return 1; }
  [[ -f "$model_path/config.json" ]] || { pd_die "missing $model_path/config.json"; return 1; }
  [[ -f "$model_path/tokenizer.json" ]] || { pd_die "missing W4A8 tokenizer"; return 1; }
  [[ -f "$model_path/quant_model_description.json" ]] || { pd_die "missing W4A8 quant metadata"; return 1; }
  python3 - "$model_path/config.json" "$max_len" <<'PY' || return 1
import json, sys
c=json.load(open(sys.argv[1], encoding='utf-8'))
q=c.get('quantization_config',{}).get('model_quant_type')
limit=c.get('text_config',{}).get('max_position_embeddings')
n=int(sys.argv[2])
if q != 'W4A8_DYNAMIC': raise SystemExit(f'[pd] expected W4A8_DYNAMIC, got {q!r}')
if n < 263296: raise SystemExit('[pd] context too short for 256K input + 1K output')
if limit is not None and n > int(limit): raise SystemExit('[pd] context exceeds checkpoint limit')
PY

  export no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost,::1,$local_ip"
  export NO_PROXY="$no_proxy"
  export HCCL_IF_IP="$local_ip" GLOO_SOCKET_IFNAME="${PD_NIC_NAME:-eth0}"
  export TP_SOCKET_IFNAME="${PD_NIC_NAME:-eth0}" HCCL_SOCKET_IFNAME="${PD_NIC_NAME:-eth0}"
  export HCCL_BUFFSIZE="${PD_HCCL_BUFFSIZE:-1024}"
  export HCCL_CONNECT_TIMEOUT="${PD_HCCL_CONNECT_TIMEOUT:-1200}" HCCL_EXEC_TIMEOUT=600
  export HCCL_OP_EXPANSION_MODE=AIV
  export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
  export OMP_PROC_BIND=false OMP_NUM_THREADS="${PD_OMP_NUM_THREADS:-10}"
  export TASK_QUEUE_ENABLE=1 USE_MULTI_GROUPS_KV_CACHE=1
  export VLLM_RPC_TIMEOUT=3600000 VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=3000
  export V41_ENGRAM_HOST_RESIDENT=1 V41_ENGRAM_DEVICE_INDEX=0
  export V41_ENGRAM_LOCAL_OWNER_FILE="${V41_ENGRAM_LOCAL_OWNER_FILE:-/tmp/v41_engram_localowner}"
  export VLLM_SERVER_DEV_MODE=0
  if [[ -f /usr/lib/aarch64-linux-gnu/libjemalloc.so.2 ]]; then
    export LD_PRELOAD="/usr/lib/aarch64-linux-gnu/libjemalloc.so.2${LD_PRELOAD:+:$LD_PRELOAD}"
  fi

  if [[ "$role" == prefill ]]; then
    batch="${PD_P_BATCH_TOKENS:-8192}" seq="${PD_P_MAX_SEQS:-16}"
    kv_role=kv_producer kv_port=30000
    export VLLM_PREFIX_CACHE_RETENTION_INTERVAL="${PD_PREFIX_CACHE_RETENTION_INTERVAL:-16384}"
  else
    batch="${PD_D_BATCH_TOKENS:-512}" seq="${PD_D_MAX_SEQS:-32}"
    kv_role=kv_consumer kv_port=30100
  fi
  additional='{"enable_engram":true,"engram_storage":"int8","enable_cpu_binding":true,"ascend_compilation_config":{"enable_npugraph_ex":true,"enable_static_kernel":true}}'
  kv_config="$(python3 - "$role" "$rank" "$kv_role" "$kv_port" <<'PY'
import json,sys
role,rank,kv_role,port=sys.argv[1:]
print(json.dumps({'kv_connector':'MooncakeHybridConnector','kv_role':kv_role,
 'kv_port':int(port),'engine_id':f'{role}-{rank}',
 'kv_connector_extra_config':{'prefill':{'dp_size':2,'tp_size':8},
                              'decode':{'dp_size':2,'tp_size':8}}},separators=(',',':')))
PY
)" || return 1

  local -a cmd=(vllm serve "$model_path"
    --host 0.0.0.0 --port "${PD_API_PORT:-8000}"
    --served-model-name "${PD_MODEL_NAME:-deepseek-v4.1-flash-w4a8-pd}"
    --trust-remote-code --quantization ascend --dtype bfloat16 --kv-cache-dtype bfloat16
    --tokenizer-mode deepseek_v41 --reasoning-parser deepseek_v41
    --tool-call-parser deepseek_v41 --enable-auto-tool-choice
    --default-chat-template-kwargs '{"reasoning_effort":"low"}'
    --max-model-len "$max_len" --max-num-batched-tokens "$batch" --max-num-seqs "$seq"
    --tensor-parallel-size 8 --enable-expert-parallel --block-size 128
    --data-parallel-size 2 --data-parallel-size-local 1
    --data-parallel-rank "$rank" --data-parallel-address "$master_ip"
    --data-parallel-rpc-port "${PD_DP_RPC_PORT:-13399}"
    --gpu-memory-utilization "${PD_GPU_MEMORY_UTILIZATION:-0.90}"
    --no-disable-hybrid-kv-cache-manager
    --safetensors-load-strategy lazy
    --model-loader-extra-config '{"enable_multithread_load":true,"num_threads":128}'
    --additional-config "$additional" --kv-transfer-config "$kv_config")
  if [[ "$role" == prefill ]]; then
    cmd+=(--enable-prefix-caching --enforce-eager)
  else
    cmd+=(--no-enable-prefix-caching --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}')
  fi

  printf '[pd] role=%s rank=%s local=%s master=%s model=%s max_len=%s batch=%s seq=%s\n' \
    "$role" "$rank" "$local_ip" "$master_ip" "$model_path" "$max_len" "$batch" "$seq"
  if [[ "${PD_VALIDATE_ONLY:-0}" == 1 ]]; then
    printf '[pd] command:'; printf ' %q' "${cmd[@]}"; printf '\n'
    return 0
  fi
  command -v vllm >/dev/null || { pd_die 'vllm CLI missing in image'; return 1; }
  exec "${cmd[@]}"
}
