#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_manifests import weight_objects  # noqa: E402


class WeightObjectTests(unittest.TestCase):
    def test_selects_pinned_lfs_object_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            weights = Path(temp)
            for name in (
                "quant_model_weights-00001-of-00272.safetensors",
                "engram_embed_weight_l1.safetensors",
                "tokenizer.json",
                "quant_model_description.json",
                "quant_model_weights.safetensors.index.json",
                "optional/quarot.safetensors",
                "aurora_export_manifest.json",
            ):
                path = weights / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            selected = {path.relative_to(weights).as_posix() for path in weight_objects(weights)}
            self.assertIn("optional/quarot.safetensors", selected)
            self.assertNotIn("aurora_export_manifest.json", selected)
            self.assertEqual(len(selected), 6)


if __name__ == "__main__":
    unittest.main()

