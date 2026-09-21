#!/usr/bin/env bash
set -Eeuo pipefail

: "${MODELARTS_ENDPOINT:?Set the regional ModelArts API endpoint}"
: "${HUAWEICLOUD_PROJECT_ID:?Set the Huawei Cloud project ID}"
: "${X_AUTH_TOKEN:?Export a short-lived IAM token; never save it in a file}"

payload="${1:-rendered/modelarts-service.json}"
[[ -r "$payload" ]] || { echo "payload is not readable: $payload" >&2; exit 2; }

endpoint="${MODELARTS_ENDPOINT%/}/v2/${HUAWEICLOUD_PROJECT_ID}/services"
response="$(mktemp)"
trap 'rm -f "$response"' EXIT

code="$(curl -sS -o "$response" -w '%{http_code}' \
  -X POST "$endpoint" \
  -H "X-Auth-Token: ${X_AUTH_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data-binary "@${payload}")"

python3 - "$response" "$code" <<'PY'
import json, pathlib, sys
path, code = pathlib.Path(sys.argv[1]), int(sys.argv[2])
try:
    body = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    raise SystemExit(f"ModelArts returned HTTP {code} with a non-JSON body: {exc}")
print(json.dumps(body, indent=2))
if code not in (200, 201, 202):
    raise SystemExit(f"ModelArts service creation failed with HTTP {code}")
PY

