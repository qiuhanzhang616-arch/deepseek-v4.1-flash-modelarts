#!/usr/bin/env python3
"""Fail-closed structural and optional full Engram SHA256 check before deployment."""

import argparse
import hashlib
import json
from pathlib import Path

MAIN = 72
MTP = 4
ENGRAM_SIZES = {
    "layers_1_engram_embed.weight.safetensors": 98305579120,
    "layers_14_engram_embed.weight.safetensors": 98308270704,
    "layers_1_engram_embed.scale.safetensors": 12288197488,
    "layers_14_engram_embed.scale.safetensors": 12288533936,
}


def inspect(root: Path, *, structural_only: bool = False, full_hash: bool = False) -> dict:
    missing = [
        name
        for name in (
            "config.json",
            "tokenizer.json",
            "quant_model_description.json",
            "quant_model_weights.safetensors.index.json",
            "mtpq_manifest.json",
        )
        if not (root / name).is_file()
    ]
    if missing:
        raise ValueError(f"missing required model files: {missing}")
    main = sorted(root.glob("quant_model_weights-*-of-00072.safetensors"))
    mtp = sorted(root.glob("mtpq-*-of-00004.safetensors"))
    if len(main) != MAIN or len(mtp) != MTP:
        raise ValueError(f"shard count mismatch: main={len(main)}/{MAIN}, mtp={len(mtp)}/{MTP}")
    incomplete = [p for p in root.rglob("*") if p.is_file() and p.name.endswith(".incomplete")]
    if incomplete:
        raise ValueError(f"incomplete downloads: {len(incomplete)}")
    index = json.loads((root / "quant_model_weights.safetensors.index.json").read_text())
    weight_map = index.get("weight_map", {})
    if not weight_map:
        raise ValueError("empty quantized weight index")
    referenced = set(weight_map.values())
    unsafe = [name for name in referenced if Path(name).is_absolute() or ".." in Path(name).parts]
    if unsafe:
        raise ValueError(f"unsafe indexed path: {unsafe[:5]}")
    missing_references = [name for name in referenced if not (root / name).is_file()]
    if missing_references:
        raise ValueError(f"index references missing files: {sorted(missing_references)[:5]}")
    engram = root / "engram_int8"
    if not (engram / "PARTS.sha256").is_file():
        raise ValueError("Engram PARTS.sha256 is missing")
    if not structural_only:
        for name, expected in ENGRAM_SIZES.items():
            path = engram / name
            if not path.is_file() or path.stat().st_size != expected:
                raise ValueError(f"Engram file missing or wrong size: {name}")
    if full_hash:
        if structural_only:
            raise ValueError("--full-hash cannot be combined with --structural-only")
        expected_hashes = {}
        for line in (engram / "PARTS.sha256").read_text().splitlines():
            fields = line.split()
            if len(fields) == 2:
                expected_hashes[fields[1].removeprefix("*")] = fields[0]
        for name in ENGRAM_SIZES:
            expected = expected_hashes.get(name)
            if not expected:
                raise ValueError(f"no checksum entry for {name}")
            digest = hashlib.sha256()
            with (engram / name).open("rb") as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest().lower() != expected.lower():
                raise ValueError(f"Engram SHA256 mismatch: {name}")
    return {
        "main_shards": len(main),
        "mtp_shards": len(mtp),
        "indexed_tensors": len(weight_map),
        "engram_check": "sha256" if full_hash else "structure" if structural_only else "size",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--structural-only", action="store_true")
    parser.add_argument("--full-hash", action="store_true")
    args = parser.parse_args()
    print(json.dumps(inspect(args.model_dir, structural_only=args.structural_only, full_hash=args.full_hash), indent=2))


if __name__ == "__main__":
    main()
