#!/usr/bin/env python3
"""Discover a 2P2D ModelArts Standard deployment from its global ranktable.

Never fall back to hard-coded Pod IPs. The launcher must wait for exactly four
distinct Pods across role-0 (prefill) and role-1 (decode), then fail closed.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


def servers(value):
    if isinstance(value, dict):
        if isinstance(value.get("server_list"), list):
            for item in value["server_list"]:
                if isinstance(item, dict):
                    yield item
        for child in value.values():
            yield from servers(child)
    elif isinstance(value, list):
        for child in value:
            yield from servers(child)


def discover(document, local_ip, expected_role):
    groups = {"prefill": [], "decode": []}
    seen = {}
    for server in servers(document):
        name = server.get("pod_name", "")
        ip = server.get("server_ip", "")
        if not name or not ip:
            continue
        if "-role-0-" in name:
            role = "prefill"
        elif "-role-1-" in name:
            role = "decode"
        else:
            continue
        if name in seen:
            if seen[name] != (role, ip):
                raise ValueError(f"conflicting role/IP for Pod {name}")
            continue
        seen[name] = (role, ip)
        groups[role].append((name, ip))

    if any(len(groups[role]) != 2 for role in groups):
        raise ValueError(
            "expected exactly 2 prefill and 2 decode Pods in the global ranktable; "
            f"found {len(groups['prefill'])}+{len(groups['decode'])}"
        )
    # ModelArts' ranktable server_list order is the platform-assigned instance
    # order. A random Pod-name suffix must not decide DP rank after a restart.
    ordered = groups
    local = [(role, index) for role, entries in ordered.items()
             for index, (_, ip) in enumerate(entries) if ip == local_ip]
    if len(local) != 1 or local[0][0] != expected_role:
        raise ValueError(f"local IP {local_ip} does not map to one {expected_role} Pod")
    rank = local[0][1]
    return [
        local_ip,
        ordered[expected_role][0][1],
        str(rank),
        ordered["prefill"][0][1],
        ordered["prefill"][1][1],
        ordered["decode"][0][1],
        ordered["decode"][1][1],
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("prefill", "decode"), required=True)
    parser.add_argument("--ranktable", type=Path, default=Path(os.environ.get(
        "GLOBAL_RANK_TABLE_FILE_PATH", "/user/global/config/global_rank_table.json")))
    parser.add_argument("--local-ip", default=os.environ.get("POD_IP", ""))
    parser.add_argument("--wait-seconds", type=int, default=300)
    args = parser.parse_args()
    if not args.local_ip:
        parser.error("POD_IP/--local-ip is required; refusing to guess from a node IP")
    deadline = time.monotonic() + args.wait_seconds
    last_error = "ranktable not ready"
    while True:
        try:
            output = discover(json.loads(args.ranktable.read_text()), args.local_ip, args.role)
            print("\n".join(output))
            return
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise SystemExit(f"[pd] peer discovery failed: {last_error}")
        time.sleep(2)


if __name__ == "__main__":
    main()
