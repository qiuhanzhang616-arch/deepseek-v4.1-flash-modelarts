#!/usr/bin/env bash
set -uo pipefail

metrics_port="${1:-8000}"
interval_seconds="${2:-1}"
parent_pid="${TELEMETRY_PARENT_PID:-1}"
candidate_id="${CANDIDATE_ID:-unknown}"
cell_state_file="${CELL_STATE_FILE:-/model/deepseek-v41-flash/benchmark-results/.active-cell.json}"
nic_name="${NIC_NAME:-unknown}"
startup_log_file="${STARTUP_LOG_FILE:-}"
metric_pattern='vllm:(num_requests_running|num_requests_waiting|num_requests_waiting_by_reason|kv_cache_usage_perc|gpu_cache_usage_perc|prefix_cache_hits|prefix_cache_queries|prompt_tokens|generation_tokens|time_to_first_token_seconds|inter_token_latency_seconds|request_queue_time_seconds|request_prefill_time_seconds|request_decode_time_seconds|num_preemptions_total|spec_decode_num_drafts_total|spec_decode_num_accepted_tokens_total|spec_decode_num_accepted_tokens_per_pos_total)'

read_cell_state() {
  python3 - "$cell_state_file" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    state = json.loads(p.read_text(encoding="utf-8"))
except (OSError, ValueError, TypeError):
    state = {}
def clean(value):
    return str(value if value is not None else "idle").replace(" ", "_")
print("cell=%s phase=%s round=%s" % (
    clean(state.get("cell_id")), clean(state.get("phase")), clean(state.get("round"))))
PY
}

emit_system_json() {
  python3 - "$nic_name" "$startup_log_file" <<'PY'
import json, os, pathlib, resource, sys, time

nic, startup_log = sys.argv[1:3]
def read_int(path):
    try:
        return int(pathlib.Path(path).read_text().strip())
    except (OSError, ValueError):
        return None

mem = {}
try:
    for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        mem[key] = int(value.strip().split()[0]) * 1024
except (OSError, ValueError, IndexError):
    pass

cpu_total_ticks = cpu_idle_ticks = None
try:
    parts = pathlib.Path('/proc/stat').read_text().splitlines()[0].split()[1:]
    ticks = [int(value) for value in parts]
    cpu_total_ticks = sum(ticks)
    cpu_idle_ticks = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
except (OSError, ValueError, IndexError):
    pass

try:
    shm = os.statvfs('/dev/shm')
    shm_total = shm.f_blocks * shm.f_frsize
    shm_free = shm.f_bavail * shm.f_frsize
except OSError:
    shm_total = shm_free = None

rss_bytes = 0
vllm_pids = []
for proc in pathlib.Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        cmd = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
        if not any(token in cmd for token in ('vllm', 'EngineCore', 'APIServer')):
            continue
        status = (proc / 'status').read_text()
        rss_kb = next(int(line.split()[1]) for line in status.splitlines() if line.startswith('VmRSS:'))
        rss_bytes += rss_kb * 1024
        vllm_pids.append(int(proc.name))
    except (OSError, ValueError, StopIteration):
        continue

net = {}
if nic and nic != 'unknown':
    base = pathlib.Path('/sys/class/net') / nic / 'statistics'
    for name in ('rx_bytes','tx_bytes','rx_errors','tx_errors','rx_dropped','tx_dropped'):
        net[name] = read_int(base / name)

graph_fallback = graph_replay = 0
if startup_log:
    try:
        text = pathlib.Path(startup_log).read_text(encoding='utf-8', errors='replace')
        graph_fallback = sum(text.lower().count(x) for x in ('graph fallback', 'cudagraph fallback', 'npugraph fallback'))
        graph_replay = sum(text.lower().count(x) for x in ('graph replay', 'cudagraph replay', 'npugraph replay'))
    except OSError:
        pass

payload = {
    'kind': 'system', 'epoch_ns': time.time_ns(),
    'loadavg': list(os.getloadavg()), 'cpu_count': os.cpu_count(),
    'cpu_total_ticks': cpu_total_ticks, 'cpu_idle_ticks': cpu_idle_ticks,
    'mem_available_bytes': mem.get('MemAvailable'), 'mem_total_bytes': mem.get('MemTotal'),
    'vllm_rss_bytes': rss_bytes, 'vllm_processes': len(vllm_pids),
    'shm_total_bytes': shm_total, 'shm_free_bytes': shm_free,
    'nic': nic, 'network': net,
    'graph_fallback_events': graph_fallback, 'graph_replay_events': graph_replay,
}
print('SYSTEM_JSON ' + json.dumps(payload, separators=(',', ':'), sort_keys=True))
PY
}

emit_engine_log_json() {
  python3 - "$startup_log_file" <<'PY'
import json, os, pathlib, re, sys

path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
if not path:
    raise SystemExit(0)
try:
    size = path.stat().st_size
    with path.open('rb') as handle:
        handle.seek(max(0, size - 524288))
        text = handle.read().decode('utf-8', errors='replace').replace('\r', '\n')
except OSError:
    raise SystemExit(0)

pattern = re.compile(
    r'(?:Engine\s+(?P<engine>\d+):\s*)?Avg prompt throughput:\s*'
    r'(?P<prompt>[0-9.]+)\s*tokens/s,\s*Avg generation throughput:\s*'
    r'(?P<generation>[0-9.]+)\s*tokens/s,\s*Running:\s*'
    r'(?P<running>\d+)\s*reqs,\s*(?:Waiting|Pending):\s*'
    r'(?P<waiting>\d+)\s*reqs(?P<tail>[^\n]*)'
)
matches = list(pattern.finditer(text))
if not matches:
    raise SystemExit(0)
match = matches[-1]
tail = match.group('tail')
def optional(pattern, default=0.0):
    found = re.search(pattern, tail)
    return float(found.group(1)) if found else default
payload = {
    'kind': 'engine_log',
    'engine': match.group('engine') or 'unknown',
    'prompt_tokens_per_s': float(match.group('prompt')),
    'generation_tokens_per_s': float(match.group('generation')),
    'running_requests': int(match.group('running')),
    'waiting_requests': int(match.group('waiting')),
    'deferred_requests': int(optional(r'Deferred:\s*(\d+)\s*reqs')),
    'preemptions': int(optional(r'Preemptions:\s*(\d+)')),
    'kv_cache_usage_percent': optional(r'GPU KV cache usage:\s*([0-9.]+)%'),
    'prefix_cache_hit_percent': optional(r'Prefix cache hit rate:\s*([0-9.]+)%'),
}
print('ENGINE_LOG_JSON ' + json.dumps(payload, separators=(',', ':'), sort_keys=True))
PY
}

while kill -0 "$parent_pid" 2>/dev/null; do
  cell_state="$(read_cell_state 2>/dev/null || printf 'cell=idle phase=idle round=idle')"
  printf '\n===== %s host=%s pod=%s candidate=%s %s =====\n' \
    "$(date --iso-8601=milliseconds)" "$(hostname)" "${POD_IP:-unknown}" "$candidate_id" "$cell_state"
  if command -v curl >/dev/null 2>&1; then
    curl -sS --max-time 5 "http://127.0.0.1:${metrics_port}/metrics" 2>/dev/null \
      | grep -E "$metric_pattern" || true
  fi
  if command -v npu-smi >/dev/null 2>&1; then
    timeout 12 npu-smi info 2>&1 || true
  fi
  emit_engine_log_json || true
  emit_system_json || true
  sleep "$interval_seconds"
done
