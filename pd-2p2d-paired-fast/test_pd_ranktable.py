import unittest
import tempfile
import time
from pathlib import Path

from pd_ranktable import collect, discover, local_unit, rendezvous


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.table = {"server_group_list": [
            {"server_list": [
                {"pod_name": "svc-role-0-z", "server_ip": "172.16.0.12"},
                {"pod_name": "svc-role-0-a", "server_ip": "172.16.0.11"},
            ]},
            {"server_list": [
                {"pod_name": "svc-role-1-z", "server_ip": "172.16.0.22"},
                {"pod_name": "svc-role-1-a", "server_ip": "172.16.0.21"},
            ]},
        ]}

    def test_uses_platform_order_not_pod_name_sort(self):
        self.assertEqual(discover(self.table, "172.16.0.11", "prefill"), [
            "172.16.0.11", "172.16.0.12", "1",
            "172.16.0.12", "172.16.0.11", "172.16.0.22", "172.16.0.21",
        ])

    def test_rejects_wrong_role(self):
        with self.assertRaises(ValueError):
            discover(self.table, "172.16.0.21", "prefill")

    def test_rejects_incomplete_topology(self):
        self.table["server_group_list"][1]["server_list"].pop()
        with self.assertRaises(ValueError):
            discover(self.table, "172.16.0.11", "prefill")

    def test_rejects_conflicting_duplicate(self):
        self.table["server_group_list"][0]["server_list"].append(
            {"pod_name": "svc-role-0-z", "server_ip": "172.16.0.99"})
        with self.assertRaises(ValueError):
            discover(self.table, "172.16.0.11", "prefill")

    def test_two_unit_ranktables_meet_on_shared_sfs(self):
        p_doc = {"server_group_list": [self.table["server_group_list"][0]]}
        d_doc = {"server_group_list": [self.table["server_group_list"][1]]}
        now = time.time()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for role, rank, ip, doc in (
                ("prefill", 0, "172.16.0.12", p_doc),
                ("prefill", 1, "172.16.0.11", p_doc),
                ("decode", 0, "172.16.0.22", d_doc),
            ):
                self.assertEqual(local_unit(doc, ip, role)[0], rank)
                with self.assertRaises(ValueError):
                    rendezvous(collect(doc), role, rank, ip, directory, "test-v2", now)
            output = rendezvous(collect(d_doc), "decode", 1, "172.16.0.21",
                                directory, "test-v2", now)
            self.assertEqual(output, ["172.16.0.21", "172.16.0.22", "1",
                                      "172.16.0.12", "172.16.0.11",
                                      "172.16.0.22", "172.16.0.21"])
            self.assertEqual(rendezvous(collect(p_doc), "prefill", 0,
                                        "172.16.0.12", directory, "test-v2", now)[2], "0")


if __name__ == "__main__":
    unittest.main()
