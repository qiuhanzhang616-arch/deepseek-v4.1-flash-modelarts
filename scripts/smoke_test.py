#!/usr/bin/env python3
"""Run non-streaming and streaming OpenAI-compatible smoke tests."""

from __future__ import annotations

import argparse
import json
import urllib.request


def post(url: str, api_key: str, body: dict) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="ModelArts call URL ending before /v1")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    args = parser.parse_args()
    endpoint = args.base_url.rstrip("/") + "/v1/chat/completions"

    common = {
        "model": args.model,
        "messages": [{"role": "user", "content": "Reply only: DEPLOYMENT_OK"}],
        "max_tokens": 32,
        "reasoning_effort": "none",
    }
    status, text = post(endpoint, args.api_key, {**common, "stream": False})
    payload = json.loads(text)
    if status != 200 or not (payload.get("choices") or [{}])[0].get("message", {}).get("content"):
        raise SystemExit("non-streaming smoke test failed")

    status, text = post(endpoint, args.api_key, {**common, "stream": True})
    if status != 200 or "[DONE]" not in text:
        raise SystemExit("streaming smoke test failed")
    print("non-streaming=PASS streaming=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
