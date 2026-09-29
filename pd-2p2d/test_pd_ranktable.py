import unittest

from pd_ranktable import discover


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


if __name__ == "__main__":
    unittest.main()
