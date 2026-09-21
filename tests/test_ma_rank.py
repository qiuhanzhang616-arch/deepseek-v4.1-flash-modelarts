#!/usr/bin/env python3
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ma_rank import resolve  # noqa: E402


class RankTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads((ROOT / "tests" / "ranktable-4x8.json").read_text())

    def test_resolves_each_a2_node(self) -> None:
        servers = []
        for group in self.data["server_group_list"]:
            servers.extend(group["server_list"])
        for expected_rank, server in enumerate(servers):
            result = resolve(self.data, server["server_ip"], 4, 8)
            self.assertEqual(result["NODE_RANK"], str(expected_rank))
            self.assertEqual(result["NODE0_IP"], servers[0]["server_ip"])
            self.assertEqual(result["LOCAL_DEVICE_IDS"], "0,1,2,3,4,5,6,7")

    def test_rejects_wrong_topology(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected 3 NPU nodes"):
            resolve(self.data, "10.0.0.1", 3, 8)


if __name__ == "__main__":
    unittest.main()

