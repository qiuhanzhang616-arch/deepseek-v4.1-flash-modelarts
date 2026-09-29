#!/usr/bin/env python3
"""Download the pinned publisher W4A8 snapshot directly to an SFS directory."""

import argparse
import shutil
from pathlib import Path

MODEL_ID = "chiro2001/DeepSeek-V4.1-Flash-w4a8-Ascend"
REVISION = "fa598df636ddc2f9ba4168459effa2875cb0c959"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--min-free-gib",
        type=int,
        default=750,
        help="Free-space gate before download and Engram reassembly; set explicitly for a verified partial resume.",
    )
    args = parser.parse_args()
    if args.workers < 1 or args.min_free_gib < 0:
        parser.error("workers must be positive and min-free-gib nonnegative")
    target = args.local_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    free_gib = shutil.disk_usage(target).free / 2**30
    if free_gib < args.min_free_gib:
        parser.error(
            f"only {free_gib:.1f} GiB free at {target}; need {args.min_free_gib} GiB "
            "or an explicit lower gate for a checked resume"
        )
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError as exc:
        raise SystemExit("Install ModelScope first: python -m pip install modelscope") from exc
    print(f"Downloading {MODEL_ID}@{REVISION} to {target}", flush=True)
    result = snapshot_download(
        model_id=MODEL_ID,
        revision=REVISION,
        local_dir=str(target),
        max_workers=args.workers,
    )
    if Path(result).resolve() != target:
        raise SystemExit(f"unexpected download directory: {result}")
    print(f"Snapshot ready: {target}")


if __name__ == "__main__":
    main()
