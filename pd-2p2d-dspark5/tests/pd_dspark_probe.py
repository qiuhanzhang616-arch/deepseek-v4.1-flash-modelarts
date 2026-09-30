"""Small serial DSpark diagnostic. No deployment changes or request retries.

Run inside an authorized isolated candidate with its metrics port reachable.
Credentials are read only from PROBE_API_KEY; never saved in artifacts.
"""
import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


def fetch(url, data=None, timeout=30):
    headers = {}
    key = os.environ.get('PROBE_API_KEY', '')
    if key and data is not None:
        headers['Authorization'] = 'Bearer ' + key
    if data is not None:
        headers['Content-Type'] = 'application/json'
    return urllib.request.urlopen(urllib.request.Request(
        url, data=json.dumps(data).encode() if data is not None else None,
        headers=headers), timeout=timeout)


def engine_metrics(url):
    with fetch(url) as response:
        body = response.read().decode()
    result = {}
    for line in body.splitlines():
        if line.startswith('#') or 'spec_decode' not in line:
            continue
        match = re.fullmatch(r'([^\s]+)\s+([-+0-9.eE]+)(?:\s+\d+)?', line)
        if match:
            result[match[1]] = float(match[2])
    if not result:
        raise RuntimeError('No speculative counters at metrics endpoint; cannot measure acceptance')
    return result


def metrics(url):
    """Capture both decode APIs, preserving identity and rejecting double-counts."""
    result = {}
    engines = set()
    for index, endpoint in enumerate(url.split(',')):
        values = engine_metrics(endpoint)
        local = {m.group(1) for key in values for m in [re.search(r'engine="([^"]+)"', key)] if m}
        if not local or local & engines:
            raise RuntimeError('Decode metrics missing unique engine labels; cannot aggregate safely')
        engines.update(local)
        result.update({f'endpoint{index}::{key}': value for key, value in values.items()})
    if len(engines) != 2:
        raise RuntimeError('Expected exactly two independent decode engines')
    return result


def counter_delta(before, after):
    if before.keys() != after.keys():
        raise RuntimeError('Speculative metric series changed; isolate service and verify restart/ranks')
    delta = {key: after[key] - value for key, value in before.items()}
    if any(value < 0 for value in delta.values()):
        raise RuntimeError('Counter reset during probe')
    return delta


def totals(delta, suffix):
    return sum(v for k, v in delta.items() if k.split('{', 1)[0].endswith(suffix))


def summarize(delta, draft_length):
    accepted = totals(delta, 'spec_decode_num_accepted_tokens_total')
    drafts = totals(delta, 'spec_decode_num_drafts_total')
    proposed = totals(delta, 'spec_decode_num_draft_tokens_total')
    inferred = proposed == 0
    if inferred:
        # Valid only for fixed-length drafts, verified in the effective runtime.
        proposed = drafts * draft_length
    positions = {}
    for key, value in delta.items():
        if 'spec_decode_num_accepted_tokens_per_pos_total' in key:
            match = re.search(r'(?:position|pos)="(\d+)"', key)
            if match:
                pos = match[1]
                positions[pos] = positions.get(pos, 0) + value
    return {
        'accepted_draft_tokens': accepted,
        'draft_rounds': drafts,
        'proposed_draft_tokens': proposed,
        'denominator_inferred_from_fixed_draft_length': inferred,
        'block_average_acceptance': accepted / proposed if proposed else None,
        'per_position_acceptance': {k: v / drafts for k, v in positions.items()} if drafts else {},
        'mean_emitted_length_per_round_estimate': 1 + accepted / drafts if drafts else None,
        'raw_counter_deltas': delta,
    }


TASKS = [
    'Calculate 17 * 19. Explain briefly.',
    'Write a Python function that returns the second largest distinct integer, or None.',
    'Explain why SQL parameter binding prevents injection; give a short example.',
    'Review this function: def f(xs): return xs[0]. Identify its empty-input bug and fix it.',
    'Return a JSON object with status equal to ok and count equal to 3, after the first line.',
    'Write three tests for a function that deduplicates a list while preserving order.',
    'Explain the difference between a process and a thread in three points.',
    'Write a Java method to check whether a string is a palindrome, and mention null handling.',
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True, help='Isolated model-direct /v1 URL')
    parser.add_argument('--metrics-url', required=True, help='Comma-separated two isolated decode /metrics URLs')
    parser.add_argument('--model', default='deepseek-v4.1-flash-w4a8-pd')
    parser.add_argument('--out', required=True)
    parser.add_argument('--effective-draft-length', required=True, type=int)
    parser.add_argument('--effective-config', required=True, help='Sanitized effective config receipt JSON')
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--temperature', type=float, default=0)
    args = parser.parse_args()
    receipt = json.loads(Path(args.effective_config).read_text(encoding='utf-8'))
    required = ('image_digest', 'target_weight_revision', 'draft_weight_revision',
                'draft_graph_effective', 'speculative_config', 'isolated_engine_confirmed')
    if any(k not in receipt for k in required) or receipt['isolated_engine_confirmed'] is not True:
        parser.error('Effective config receipt incomplete or engine isolation not confirmed')
    if not 1 <= args.effective_draft_length <= 16:
        parser.error('Invalid fixed draft length')
    if not 1 <= args.count <= len(TASKS):
        parser.error('Count must be between one and eight')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'effective-config.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    rows = []
    try:
        for i, task in enumerate(TASKS[:args.count]):
            marker = 'DSPARKCHECK' + str(i)
            prompt = f'Probe {args.namespace}-{i}. Start your final answer with {marker}.\n{task}'
            payload = {'model': args.model, 'messages': [{'role': 'user', 'content': prompt}],
                       'temperature': args.temperature, 'stream': True, 'stream_options': {'include_usage': True},
                       'max_tokens': 512, 'reasoning_effort': 'low', 'thinking_token_budget': 128}
            before = metrics(args.metrics_url)
            start = time.monotonic()
            first = first_content = None
            last = None
            content = ''
            usage = None
            done = False
            with (out / f'{i:02d}.sse').open('wb') as log:
                with fetch(args.base_url.rstrip('/') + '/chat/completions', payload, timeout=120) as response:
                    for line in response:
                        log.write(line)
                        if not line.startswith(b'data:'):
                            continue
                        data = line[5:].strip()
                        if data == b'[DONE]':
                            done = True
                            continue
                        event = json.loads(data)
                        if event.get('error'):
                            raise RuntimeError('Model error; inspect saved SSE')
                        if event.get('usage'):
                            usage = event['usage']
                        for choice in event.get('choices', []):
                            delta = choice.get('delta', {})
                            now = time.monotonic()
                            if delta.get('reasoning_content') or delta.get('reasoning') or delta.get('content'):
                                first = now if first is None else first
                                last = now
                            if delta.get('content'):
                                first_content = now if first_content is None else first_content
                                content += delta['content']
            end = time.monotonic()
            after = metrics(args.metrics_url)
            row = {'request_index': i, 'ttft_s': first - start if first else None,
                   'requested_temperature': args.temperature,
                   'first_content_s': first_content - start if first_content else None,
                   'e2e_s': end - start, 'sse_done': done, 'marker_pass': marker in content,
                   'usage': usage, 'speculative': summarize(counter_delta(before, after), args.effective_draft_length)}
            n = (usage or {}).get('completion_tokens', 0)
            row['tpot_s'] = (last - first) / (n - 1) if first and last and n > 1 else None
            rows.append(row)
            (out / 'requests.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
            if not done or not content or marker not in content:
                raise RuntimeError('Content/SSE/marker gate failed; stop new requests')
            if row['speculative']['draft_rounds'] == 0:
                raise RuntimeError('No draft rounds measured; verify SPEC and metric endpoint')
        (out / 'status.json').write_text(json.dumps({'status': 'complete', 'count': len(rows),
            'scope': 'C1 short-input diagnostic only; not a deployment promotion'}), encoding='utf-8')
    except Exception as exc:
        (out / 'status.json').write_text(json.dumps({'status': 'failed', 'count': len(rows),
            'error_type': type(exc).__name__, 'note': 'Stopped new requests; inspect local evidence'}), encoding='utf-8')
        raise SystemExit('Probe stopped; evidence saved. No retries performed.') from None
    print(f'Completed {len(rows)} requests; evidence saved in {out}')


if __name__ == '__main__':
    main()
