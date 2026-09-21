#!/usr/bin/env python3
"""Resolve ModelArts Standard multi-unit rank information for DeepSeek V4.1."""

import argparse
import json
import shlex
import sys


def numeric_group_id(group, fallback):
    try:
        return int(group.get("group_id", fallback))
    except (TypeError, ValueError):
        return fallback


def server_ip(server):
    for key in ("server_ip", "container_ip", "pod_ip"):
        if server.get(key):
            return str(server[key])
    return ""


def devices(server):
    value = server.get("device", server.get("device_list", []))
    return value if isinstance(value, list) else []


def resolve(data, pod_ip, expected_nodes, devices_per_node):
    groups = data.get("server_group_list")
    if not isinstance(groups, list):
        raise ValueError("ranktable is missing server_group_list")

    ordered_groups = sorted(
        enumerate(groups), key=lambda item: numeric_group_id(item[1], item[0])
    )
    nodes = []
    seen = set()
    for _, group in ordered_groups:
        for server in group.get("server_list", []):
            devs = devices(server)
            if not devs:
                continue
            ip = server_ip(server)
            key = server.get("server_id") or ip
            if not key or key in seen:
                continue
            seen.add(key)
            nodes.append({"ip": ip, "server": server, "devices": devs})

    if len(nodes) != expected_nodes:
        raise ValueError(
            f"expected {expected_nodes} NPU nodes, found {len(nodes)}; "
            "use role-0=1 and role-1=3 for the validated A2 topology"
        )
    if not nodes[0]["ip"]:
        raise ValueError("node 0 has no routable server_ip/container_ip")

    for index, node in enumerate(nodes):
        if len(node["devices"]) != devices_per_node:
            raise ValueError(
                f"node {index} has {len(node['devices'])} devices, "
                f"expected {devices_per_node}"
            )

    matches = [index for index, node in enumerate(nodes) if node["ip"] == pod_ip]
    if len(matches) != 1:
        raise ValueError(f"POD_IP {pod_ip!r} matched {len(matches)} nodes")

    return {
        "NODE_RANK": str(matches[0]),
        "NODE0_IP": nodes[0]["ip"],
        "LOCAL_IP": pod_ip,
        "WORLD_NODES": str(len(nodes)),
        "LOCAL_DEVICE_IDS": ",".join(str(i) for i in range(devices_per_node)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ranktable", required=True)
    parser.add_argument("--pod-ip", required=True)
    parser.add_argument("--expected-nodes", type=int, default=4)
    parser.add_argument("--devices-per-node", type=int, default=8)
    parser.add_argument("--format", choices=("json", "shell"), default="json")
    args = parser.parse_args()

    with open(args.ranktable, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    result = resolve(data, args.pod_ip, args.expected_nodes, args.devices_per_node)
    if args.format == "shell":
        for key, value in result.items():
            print(f"export {key}={shlex.quote(value)}")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False)
        print()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ma_rank.py: {exc}", file=sys.stderr)
        raise SystemExit(2)
