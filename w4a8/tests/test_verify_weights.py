import json
import tempfile
import unittest
from pathlib import Path

from w4a8.tools.verify_weights import inspect


class VerifyWeightsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("config.json", "tokenizer.json", "quant_model_description.json", "mtpq_manifest.json"):
            (self.root / name).write_text("{}")
        (self.root / "quant_model_weights.safetensors.index.json").write_text(
            json.dumps({"weight_map": {"x": "quant_model_weights-00001-of-00072.safetensors"}})
        )
        for index in range(1, 73):
            (self.root / f"quant_model_weights-{index:05d}-of-00072.safetensors").touch()
        for index in range(1, 5):
            (self.root / f"mtpq-{index:05d}-of-00004.safetensors").touch()
        (self.root / "engram_int8").mkdir()
        (self.root / "engram_int8" / "PARTS.sha256").write_text("")

    def test_structural_layout(self):
        result = inspect(self.root, structural_only=True)
        self.assertEqual(result["main_shards"], 72)
        self.assertEqual(result["mtp_shards"], 4)

    def test_missing_shard_rejected(self):
        (self.root / "quant_model_weights-00072-of-00072.safetensors").unlink()
        with self.assertRaisesRegex(ValueError, "shard count"):
            inspect(self.root, structural_only=True)

    def test_incomplete_download_rejected(self):
        (self.root / "leftover.incomplete").touch()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            inspect(self.root, structural_only=True)

    def test_index_may_reference_engram_files(self):
        (self.root / "engram_int8" / "scale.safetensors").touch()
        (self.root / "quant_model_weights.safetensors.index.json").write_text(
            json.dumps({"weight_map": {"x": "engram_int8/scale.safetensors"}})
        )
        self.assertEqual(inspect(self.root, structural_only=True)["indexed_tensors"], 1)

    def test_missing_index_reference_rejected(self):
        (self.root / "quant_model_weights.safetensors.index.json").write_text(
            json.dumps({"weight_map": {"x": "missing.safetensors"}})
        )
        with self.assertRaisesRegex(ValueError, "missing files"):
            inspect(self.root, structural_only=True)

    def test_index_traversal_rejected(self):
        (self.root / "quant_model_weights.safetensors.index.json").write_text(
            json.dumps({"weight_map": {"x": "../outside.safetensors"}})
        )
        with self.assertRaisesRegex(ValueError, "unsafe indexed path"):
            inspect(self.root, structural_only=True)


if __name__ == "__main__":
    unittest.main()
