#!/usr/bin/env python3
"""Check /models, non-streaming text, and terminal SSE on a deployed service."""

import argparse
import json
import os

import requests


def run(base_url: str, model: str, api_key: str) -> None:
    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    listing = requests.get(f"{base}/models", headers=headers, timeout=20)
    listing.raise_for_status()
    ids = {entry.get("id") for entry in listing.json().get("data", [])}
    if model not in ids:
        raise ValueError(f"{model} absent from /models")

    request = {
        "model": model,
        "messages": [{"role": "user", "content": "What is 6 times 7? Reply with only the number."}],
        "temperature": 0,
        "max_tokens": 64,
        "reasoning_effort": "low",
    }
    ordinary = requests.post(f"{base}/chat/completions", headers=headers, json=request, timeout=90)
    ordinary.raise_for_status()
    answer = ordinary.json()["choices"][0]["message"].get("content") or ""
    if "42" not in answer:
        raise ValueError(f"non-streaming content invalid: {answer[:80]!r}")

    parts = []
    done = False
    with requests.post(
        f"{base}/chat/completions",
        headers=headers,
        json=dict(request, stream=True),
        stream=True,
        timeout=(20, 90),
    ) as stream:
        stream.raise_for_status()
        for line in stream.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                done = True
                break
            event = json.loads(payload)
            for choice in event.get("choices", []):
                parts.append(choice.get("delta", {}).get("content") or "")
    if not done or "42" not in "".join(parts):
        raise ValueError("streaming content or [DONE] invalid")
    print(json.dumps({"models": "PASS", "nonstream": "PASS", "sse_done": "PASS"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Exact ModelArts or gateway URL ending in /v1")
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    args = parser.parse_args()
    key = os.environ.get("MODELARTS_API_KEY")
    if not key:
        parser.error("read API key from MODELARTS_API_KEY, not a CLI argument")
    run(args.base_url, args.model, key)


if __name__ == "__main__":
    main()
