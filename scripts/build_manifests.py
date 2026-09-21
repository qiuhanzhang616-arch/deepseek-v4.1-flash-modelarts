#!/usr/bin/env python3
"""Hash the pinned checkpoint once and build startup verification manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_OBJECTS = 278
EXPECTED_BYTES = 797_570_012_196
PINNED_MODEL_ID = "Eco-Tech/DeepSeek-V4.1-Flash-w8a8"
PINNED_REVISION = "44201f6d0e14cbc5e73067029762676557a3e7e9"
EXTRA_LFS_FILES = {
    "tokenizer.json",
    "quant_model_description.json",
    "quant_model_weights.safetensors.index.json",
    "optional/quarot.safetensors",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def weight_objects(weights: Path) -> list[Path]:
    files = [path for path in weights.glob("*.safetensors") if path.is_file()]
    files.extend(weights / name for name in EXTRA_LFS_FILES if (weights / name).is_file())
    return sorted(set(files))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--model-id", default=PINNED_MODEL_ID)
    parser.add_argument("--revision", default=PINNED_REVISION)
    args = parser.parse_args()

    root = args.root.resolve()
    weights = root / "weights"
    manifests = root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    incomplete = sorted(str(path.relative_to(root)) for path in weights.rglob("*.incomplete"))
    objects = weight_objects(weights)
    actual_bytes = sum(path.stat().st_size for path in objects)
    failed: list[str] = []
    entries = []
    for index, path in enumerate(objects, 1):
        print(f"[{index}/{len(objects)}] {path.name}", flush=True)
        try:
            entries.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
        except OSError:
            failed.append(str(path.relative_to(root)))

    report = {
        "ok": len(objects) == EXPECTED_OBJECTS
        and actual_bytes == EXPECTED_BYTES
        and not failed
        and not incomplete,
        "hash_checked": not failed,
        "model_id": args.model_id,
        "revision": args.revision,
        "expected_lfs_objects": EXPECTED_OBJECTS,
        "actual_lfs_objects": len(objects),
        "expected_bytes": EXPECTED_BYTES,
        "actual_bytes": actual_bytes,
        "failed": failed,
        "incomplete_files": incomplete,
        "files": entries,
    }
    report_path = manifests / "weights-sha256-verification.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    package_files = []
    for folder in (root / "scripts", root / "config"):
        if folder.exists():
            package_files.extend(
                path
                for path in folder.rglob("*")
                if path.is_file()
                and path.name != "deployment.env"
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            )
    package_lines = [f"{sha256(path)}  {path.relative_to(root).as_posix()}" for path in sorted(package_files)]
    (manifests / "package.sha256").write_text("\n".join(package_lines) + "\n", encoding="utf-8")

    print(report_path)
    if not report["ok"]:
        raise SystemExit("checkpoint verification failed; inspect the generated report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
