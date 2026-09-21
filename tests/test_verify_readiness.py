#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_readiness import readiness_failures


EXPECTED_OBJECTS = 278
EXPECTED_BYTES = 797_570_012_196


def valid_report() -> dict[str, object]:
    return {
        "ok": True,
        "hash_checked": True,
        "expected_lfs_objects": EXPECTED_OBJECTS,
        "expected_bytes": EXPECTED_BYTES,
        "failed": [],
        "incomplete_files": [],
    }


class ReadinessReportTests(unittest.TestCase):
    def test_accepts_only_complete_hash_verified_report(self) -> None:
        self.assertEqual(
            readiness_failures(valid_report(), EXPECTED_OBJECTS, EXPECTED_BYTES), []
        )

    def test_rejects_each_unsafe_field(self) -> None:
        unsafe_values = {
            "ok": False,
            "hash_checked": False,
            "expected_lfs_objects": EXPECTED_OBJECTS - 1,
            "expected_bytes": EXPECTED_BYTES - 1,
            "failed": ["bad-shard"],
            "incomplete_files": ["partial-shard"],
        }
        for field, unsafe_value in unsafe_values.items():
            with self.subTest(field=field):
                report = valid_report()
                report[field] = unsafe_value
                self.assertIn(
                    field,
                    readiness_failures(report, EXPECTED_OBJECTS, EXPECTED_BYTES),
                )


if __name__ == "__main__":
    unittest.main()
