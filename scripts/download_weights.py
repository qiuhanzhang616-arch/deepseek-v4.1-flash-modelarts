#!/usr/bin/env python3
"""Resume a pinned ModelScope snapshot directly into the SFS weights directory."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_MODEL_ID = "Eco-Tech/DeepSeek-V4.1-Flash-w8a8"
DEFAULT_REVISION = "44201f6d0e14cbc5e73067029762676557a3e7e9"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError as exc:
        raise SystemExit("install modelscope first: python -m pip install -U modelscope") from exc

    args.output.mkdir(parents=True, exist_ok=True)
    result = snapshot_download(
        args.model_id,
        revision=args.revision,
        local_dir=str(args.output),
        max_workers=args.workers,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

