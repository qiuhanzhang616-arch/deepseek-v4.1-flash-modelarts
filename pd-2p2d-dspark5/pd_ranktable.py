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


def collect(document):
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

    return groups


def local_unit(document, local_ip, expected_role):
    groups = collect(document)
    own = groups[expected_role]
    if len(own) != 2:
        raise ValueError(f"expected 2 {expected_role} Pods in local ranktable; found {len(own)}")
    matches = [i for i, (_, ip) in enumerate(own) if ip == local_ip]
    if len(matches) != 1:
        raise ValueError(f"local IP {local_ip} does not map to one {expected_role} Pod")
    return matches[0], own


def discover(document, local_ip, expected_role):
    groups = collect(document)
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


def rendezvous(groups, role, rank, local_ip, directory, epoch, now):
    """Exchange role-local ranktables through a new, versioned writable SFS dir."""
    directory.mkdir(parents=True, exist_ok=True)
    record = {"epoch": epoch, "role": role, "rank": rank, "ip": local_ip,
              "updated": now}
    target = directory / f"{role}-{rank}.json"
    pending = directory / f".{role}-{rank}-{os.getpid()}.tmp"
    pending.write_text(json.dumps(record, separators=(",", ":")))
    os.replace(pending, target)
    peers = {}
    for peer_role in ("prefill", "decode"):
        for peer_rank in (0, 1):
            path = directory / f"{peer_role}-{peer_rank}.json"
            try:
                item = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if (item.get("epoch") != epoch or item.get("role") != peer_role
                    or item.get("rank") != peer_rank
                    or now - float(item.get("updated", 0)) > 600):
                continue
            ip = item.get("ip", "")
            if not isinstance(ip, str) or not ip or any(c not in "0123456789." for c in ip):
                continue
            peers[(peer_role, peer_rank)] = ip
    if len(peers) != 4:
        raise ValueError(f"SFS rendezvous has {len(peers)}/4 fresh role records")
    own = groups[role]
    if [peers[(role, i)] for i in (0, 1)] != [ip for _, ip in own]:
        raise ValueError("role-local ranktable disagrees with SFS rendezvous")
    return [local_ip, peers[(role, 0)], str(rank),
            peers[("prefill", 0)], peers[("prefill", 1)],
            peers[("decode", 0)], peers[("decode", 1)]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("prefill", "decode"), required=True)
    parser.add_argument("--ranktable", type=Path, default=Path(os.environ.get(
        "GLOBAL_RANK_TABLE_FILE_PATH", "/user/global/config/global_rank_table.json")))
    parser.add_argument("--local-ip", default=os.environ.get("POD_IP", ""))
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--rendezvous-dir", type=Path, default=Path(os.environ.get(
        "PD_RENDEZVOUS_DIR", "/model/w4a8-results/pd-2p2d-state")))
    parser.add_argument("--epoch", default=os.environ.get("PD_RENDEZVOUS_ID", ""))
    args = parser.parse_args()
    if not args.local_ip:
        parser.error("POD_IP/--local-ip is required; refusing to guess from a node IP")
    if not args.epoch or not all(c.isalnum() or c in "-_" for c in args.epoch):
        parser.error("a safe, deployment-specific PD_RENDEZVOUS_ID is required")
    deadline = time.monotonic() + args.wait_seconds
    last_error = "ranktable not ready"
    last_report = ""
    while True:
        try:
            document = json.loads(args.ranktable.read_text())
            try:
                output = discover(document, args.local_ip, args.role)
            except ValueError:
                rank, own = local_unit(document, args.local_ip, args.role)
                output = rendezvous(collect(document), args.role, rank, args.local_ip,
                                    args.rendezvous_dir / args.epoch, args.epoch, time.time())
            print("\n".join(output))
            return
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if last_error != last_report:
                print(f"[pd] peer discovery waiting: {last_error}", file=sys.stderr,
                      flush=True)
                last_report = last_error
        if time.monotonic() >= deadline:
            raise SystemExit(f"[pd] peer discovery failed: {last_error}")
        time.sleep(2)


if __name__ == "__main__":
    main()
