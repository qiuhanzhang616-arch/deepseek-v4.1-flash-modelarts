#!/usr/bin/env bash
set -Eeuo pipefail

STATE_DIR="${STATE_DIR:-/tmp/deepseek-v41-modelarts}"
SERVICE_PORT="${SERVICE_PORT:-8000}"

[[ -r "$STATE_DIR/runtime.env" ]] || exit 1
set -a
# shellcheck disable=SC1090
source "$STATE_DIR/runtime.env"
set +a

if [[ "${NODE_RANK:-}" == "0" ]]; then
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
    "http://127.0.0.1:${SERVICE_PORT}/health" || true)"
  [[ "$code" == "200" ]]
else
  pgrep -af 'vllm serve' | grep -F -- '--headless' >/dev/null
fi
