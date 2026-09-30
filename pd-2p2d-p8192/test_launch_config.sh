#!/usr/bin/env bash
set -Eeuo pipefail
base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PD_MODEL_PATH="$base/fixtures" PD_VALIDATE_ONLY=1
unset PD_P_GPU_MEMORY_UTILIZATION PD_D_GPU_MEMORY_UTILIZATION PD_GPU_MEMORY_UTILIZATION
source "$base/pd_common.sh"
p="$(pd_serve prefill 0 172.16.0.11 172.16.0.11)"
d="$(pd_serve decode 0 172.16.0.21 172.16.0.21)"
[[ "$p" == *'--gpu-memory-utilization 0.90'* ]]
[[ "$d" == *'--gpu-memory-utilization 0.90'* ]]
[[ "$p" == *'--max-num-batched-tokens 8192'* ]]
[[ "$d" == *'--max-num-batched-tokens 512'* ]]
p_spec="${p##*--speculative-config }"
d_spec="${d##*--speculative-config }"
[[ "$p_spec" == "$d_spec" && "$p_spec" == *dspark* && "$p_spec" == *5* ]]
printf 'PASS: P batch8192 D512, memory0.90 unchanged on both roles, paired DSpark5 identical\n'
