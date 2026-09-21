#!/usr/bin/env python3
"""Validate the immutable weight-verification report used by every ModelArts pod."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def readiness_failures(
    report: dict[str, object], expected_objects: int, expected_bytes: int
) -> list[str]:
    checks = {
        "ok": report.get("ok") is True,
        "hash_checked": report.get("hash_checked") is True,
        "expected_lfs_objects": report.get("expected_lfs_objects") == expected_objects,
        "expected_bytes": report.get("expected_bytes") == expected_bytes,
        "failed": report.get("failed") == [],
        "incomplete_files": report.get("incomplete_files") == [],
    }
    return [name for name, passed in checks.items() if not passed]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-objects", type=int, required=True)
    parser.add_argument("--expected-bytes", type=int, required=True)
    args = parser.parse_args()

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"weight verification report is unreadable: {exc}")

    failed = readiness_failures(report, args.expected_objects, args.expected_bytes)
    if failed:
        raise SystemExit(
            "weight verification report failed readiness checks: " + ", ".join(failed)
        )

    print(
        "[preflight] immutable weight report passed: "
        f"objects={args.expected_objects} bytes={args.expected_bytes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
