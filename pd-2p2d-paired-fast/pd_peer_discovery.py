#!/usr/bin/env python3
"""Explicit-role, fresh-epoch SFS discovery for exactly two P and two D Pods.

All four Pods use the same immutable script directory and a new deployment epoch.
Registration precedes model loading and does not require platform ranktable names.
Ranks are the same deterministic Pod-name order seen by every participant.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import socket
import sys
import time
from pathlib import Path


def choose(records, epoch, contract, now, local_name, role, local_ip):
    groups = {'prefill': [], 'decode': []}
    for item in records:
        if item.get('epoch') != epoch or now - item.get('updated', 0) > 90:
            continue
        if item.get('role') not in groups:
            raise ValueError('invalid advertised role')
        if item.get('contract') != contract:
            raise ValueError('peer script/DSpark contract mismatch')
        ipaddress.IPv4Address(item['ip'])
        groups[item['role']].append(item)
    if any(len(g) > 2 for g in groups.values()):
        raise ValueError('more than two fresh Pods in one role; use a new epoch')
    if any(len(g) != 2 for g in groups.values()):
        raise ValueError('registered P=%d/2 D=%d/2' % (len(groups['prefill']), len(groups['decode'])))
    all_items = groups['prefill'] + groups['decode']
    if len({x['name'] for x in all_items}) != 4 or len({x['ip'] for x in all_items}) != 4:
        raise ValueError('duplicate Pod identity or IP')
    for group in groups.values():
        group.sort(key=lambda x: x['name'])
    own = groups[role]
    matches = [i for i, x in enumerate(own) if x['name'] == local_name and x['ip'] == local_ip]
    if len(matches) != 1:
        raise ValueError('local identity missing or conflicting')
    return [local_ip, own[0]['ip'], str(matches[0]),
            *[x['ip'] for x in groups['prefill']], *[x['ip'] for x in groups['decode']]]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--role', choices=['prefill', 'decode'], required=True)
    p.add_argument('--local-ip', required=True)
    p.add_argument('--pod-name', default=socket.gethostname())
    p.add_argument('--script', type=Path, required=True)
    p.add_argument('--wait-seconds', type=int, default=300)
    p.add_argument('--register-only', action='store_true')
    p.add_argument('--parent-pid', type=int)
    a = p.parse_args()
    ipaddress.IPv4Address(a.local_ip)
    epoch = os.environ.get('PD_RENDEZVOUS_ID', '')
    if not epoch or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in epoch):
        p.error('a new safe deployment-specific epoch is required')
    if not a.pod_name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in a.pod_name):
        p.error('invalid Pod identity')
    contract = {'common_sha256': hashlib.sha256(a.script.read_bytes()).hexdigest(),
                'discovery_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'spec': {'method': 'dspark', 'num_speculative_tokens': 5, 'enforce_eager': True},
                'model_path': os.environ.get('PD_MODEL_PATH', '/model/w4a8/model-view'),
                'context': os.environ.get('PD_MAX_MODEL_LEN', '1048576')}
    if os.environ.get('PD_NUM_SPEC_TOKENS', '5') != '5':
        p.error('paired DSpark5 required')
    root = Path(os.environ.get('PD_RENDEZVOUS_DIR', '/model/w4a8-results/pd-2p2d-state')) / epoch
    root.mkdir(parents=True, exist_ok=True)
    target = root / (a.pod_name + '.json')
    pending = root / ('.' + a.pod_name + '-' + str(os.getpid()) + '.tmp')
    deadline = time.monotonic() + a.wait_seconds
    last = ''
    while True:
        now = time.time()
        item = {'epoch': epoch, 'name': a.pod_name, 'role': a.role, 'ip': a.local_ip,
                'updated': now, 'contract': contract}
        pending.write_text(json.dumps(item), encoding='utf-8')
        os.replace(pending, target)
        if a.register_only:
            if a.parent_pid:
                try: os.kill(a.parent_pid, 0)
                except ProcessLookupError: return
            time.sleep(5)
            continue
        records = []
        for path in root.glob('*.json'):
            try:
                record = json.loads(path.read_text())
                if isinstance(record, dict): records.append(record)
            except (OSError, ValueError):
                continue
        try:
            out = choose(records, epoch, contract, now, a.pod_name, a.role, a.local_ip)
            print('\n'.join(out), flush=True)
            return
        except (ValueError, KeyError, TypeError) as exc:
            message = str(exc)
            if message != last:
                print('[pd] explicit-role discovery waiting: ' + message, file=sys.stderr, flush=True)
                last = message
            if time.monotonic() >= deadline:
                raise SystemExit('[pd] explicit-role discovery timed out: ' + message)
            time.sleep(1)


if __name__ == '__main__':
    main()
