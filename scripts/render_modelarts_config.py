#!/usr/bin/env python3
"""Render the ModelArts payload from environment variables without secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from string import Template


PLACEHOLDER = re.compile(r"CHANGE_ME|\$\{[A-Z0-9_]+\}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.template.read_text(encoding="utf-8")
    rendered = Template(source).substitute(os.environ)
    unresolved = sorted(set(PLACEHOLDER.findall(rendered)))
    if unresolved:
        raise SystemExit("unresolved placeholders: " + ", ".join(unresolved))

    payload = json.loads(rendered)
    if payload.get("deploy_type") != "MULTI":
        raise SystemExit("deploy_type must remain MULTI")
    units = payload["group_configs"][0]["unit_configs"]
    topology = {unit["name"]: unit["count"] for unit in units}
    if topology != {"role-0": 1, "role-1": 3}:
        raise SystemExit(f"unexpected topology: {topology}")
    if any(unit["envs"].get("GPU_MEMORY_UTILIZATION") != "0.94" for unit in units):
        raise SystemExit("both units must use the validated 0.94 HBM fraction")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

