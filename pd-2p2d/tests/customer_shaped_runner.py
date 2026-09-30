#!/usr/bin/env python3
"""PD-only synthetic customer-shape screen. Never a captured arrival replay."""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import traceback
import urllib.request

MODEL = "deepseek-v4.1-flash-w4a8-pd"
LOCK = threading.Lock()


def save(path, value):
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    os.replace(pending, path)


def post(url, payload, timeout):
    return urllib.request.urlopen(urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}), timeout=timeout)


def prepare(item, namespace, tokenize_url):
    group = item["prefix_group"] if item["cache_class"] == "hot" else item["request_id"]
    marker = "PD_REPLAY_" + hashlib.sha256(group.encode()).hexdigest()[:12]
    prefix = namespace + "/" + group + ". Marker " + marker + ". Filler:"
    tail = "\nReturn " + marker + " first, then numbered coding review checklist items until output limit."
    target = item["input_tokens"]
    unit = item["prompt_unit"]
    repeats = target
    for _ in range(10):
        messages = [{"role": "user", "content": prefix + unit * repeats + tail}]
        payload = {"model": MODEL, "messages": messages,
                   "add_generation_prompt": True, "return_token_strs": False,
                   "chat_template_kwargs": {"reasoning_effort": "low"}}
        with post(tokenize_url, payload, 120) as response:
            count = json.load(response)["count"]
        if count == target:
            return messages, marker
        repeats += target - count
        if repeats < 0:
            break
    raise ValueError(f"exact token construction failed {item['request_id']}: {count}/{target}")


def request(item, messages, marker, root, endpoint, deadline, stop):
    directory = root / item["request_id"]
    directory.mkdir()
    payload = {"model": MODEL, "messages": messages, "stream": True,
               "stream_options": {"include_usage": True}, "temperature": 0,
               "reasoning_effort": "low", "thinking_token_budget": 128,
               "max_tokens": item["output_tokens"], "ignore_eos": True}
    save(directory / "request.json", payload)
    result = dict(item, success=False, retry=0, fallback=0)
    started = time.monotonic()
    first = first_content = last = None
    body = ""
    usage = None
    done = False
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("phase deadline before submission")
        with post(endpoint, payload, min(1200, remaining)) as response:
            result["http"] = response.status
            with (directory / "response.sse").open("wb") as raw:
                for line in response:
                    raw.write(line)
                    raw.flush()
                    if time.monotonic() > deadline:
                        raise TimeoutError("phase deadline during stream")
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        done = True
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        raise ValueError(str(event["error"]))
                    if event.get("usage"):
                        usage = event["usage"]
                    for choice in event.get("choices", []):
                        delta = choice.get("delta", {})
                        if delta.get("reasoning") or delta.get("content"):
                            now = time.monotonic()
                            first = first if first is not None else now
                            last = now
                        if delta.get("content"):
                            first_content = first_content if first_content is not None else now
                            body += delta["content"]
        result.update(done=done, marker_ok=marker in body, usage=usage,
                      body_chars=len(body), e2e_s=time.monotonic() - started,
                      ttft_s=None if first is None else first - started,
                      first_content_s=None if first_content is None else first_content - started)
        generated = (usage or {}).get("completion_tokens", 0)
        result["stream_tpot_estimate_s"] = (
            (last - first) / (generated - 1) if first is not None and generated > 1 else None)
        result["request_tps"] = generated / result["e2e_s"] if result["e2e_s"] > 0 else None
        result["success"] = bool(result["http"] == 200 and done and marker in body and
                                 usage and usage.get("prompt_tokens") == item["input_tokens"] and
                                 generated == item["output_tokens"])
        if not result["success"]:
            stop.set()
    except Exception as exc:
        result.update(error=str(exc), traceback=traceback.format_exc(),
                      e2e_s=time.monotonic() - started)
        stop.set()
    save(directory / "result.json", result)
    with LOCK:
        with (root / "requests.jsonl").open("a") as output:
            output.write(json.dumps(result) + "\n")
    return result


def phase(items, prepared, root, endpoint, concurrency, deadline, stop):
    pending = iter(items)
    results = []
    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = set()
        def submit():
            if stop.is_set() or time.monotonic() >= deadline:
                return False
            item = next(pending, None)
            if item is None:
                return False
            messages, marker = prepared[item["request_id"]]
            futures.add(pool.submit(request, item, messages, marker, root, endpoint, deadline, stop))
            return True
        for _ in range(concurrency):
            submit()
        while futures:
            complete, _ = cf.wait(futures, return_when=cf.FIRST_COMPLETED)
            for future in complete:
                futures.remove(future)
                results.append(future.result())
                submit()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:9000/v1/chat/completions")
    parser.add_argument("--tokenize", default="http://127.0.0.1:8000/tokenize")
    args = parser.parse_args()
    args.root.mkdir(exist_ok=False)
    manifest = json.loads(args.manifest.read_text())
    assert len(manifest["requests"]) == 75
    save(args.root / "manifest.json", manifest)
    save(args.root / "binding.json", {
        "evidence_class": "customer-shaped synthetic; closed-loop; not natural arrival trace",
        "endpoint": args.endpoint, "tokenize": args.tokenize, "namespace": args.namespace,
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "topology": "2P2D, four A2 nodes,32NPUs",
        "timing_note": "stream TPOT estimate uses usage token count; chunks may coalesce tokens"})
    state = args.root / "status.json"
    save(state, {"status": "preparing"})
    stop = threading.Event()
    all_results = []
    try:
        prepared = {item["request_id"]: prepare(item, args.namespace, args.tokenize)
                    for item in manifest["requests"]}
        save(args.root / "prepared.json", {key: {"marker": value[1]} for key, value in prepared.items()})
        epoch = time.monotonic()
        warm = []
        for group in ("hot-0", "hot-1", "hot-2", "hot-3"):
            candidate = max((i for i in manifest["requests"] if i["cache_class"] == "hot" and
                             i["prefix_group"] == group), key=lambda i: i["input_tokens"])
            warm.append(dict(candidate, request_id="prime-" + group, output_tokens=256, scored=False))
            prepared["prime-" + group] = prepared[candidate["request_id"]]
        save(state, {"status": "active", "phase": "warmup", "started": time.time()})
        primes = phase(warm, prepared, args.root, args.endpoint, 4, epoch + 300, stop)
        if len(primes) != 4 or stop.is_set():
            raise RuntimeError("warmup gate failed")
        for name in ("C1", "C4", "C8"):
            spec = manifest["schedule"][name]
            while time.monotonic() < epoch + spec["start"]:
                time.sleep(min(1, epoch + spec["start"] - time.monotonic()))
            if stop.is_set():
                break
            save(state, {"status": "active", "phase": name, "completed": len(all_results)})
            planned = [item for item in manifest["requests"] if item["phase"] == name]
            measured = phase(planned, prepared, args.root, args.endpoint, spec["concurrency"],
                             epoch + spec["end"], stop)
            all_results.extend(measured)
            save(args.root / (name + "-results.json"), measured)
            if len(measured) != len(planned):
                stop.set()
            if stop.is_set():
                break
        submitted = {item["request_id"] for item in all_results}
        summary = {"status": "complete" if len(all_results) == 75 and not stop.is_set() else "failed",
                   "submitted": len(all_results), "successful": sum(i["success"] for i in all_results),
                   "not_submitted": [i["request_id"] for i in manifest["requests"] if i["request_id"] not in submitted],
                   "elapsed_s": time.monotonic() - epoch}
        save(args.root / "summary.json", summary)
        save(state, summary)
        print(json.dumps(summary), flush=True)
    except Exception as exc:
        save(state, {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    main()
