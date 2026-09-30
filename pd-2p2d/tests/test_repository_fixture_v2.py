import ast
import unittest
from repository_fixture_v2 import repository, review_quality


class FixtureTests(unittest.TestCase):
    def test_known_defect_is_reproducible(self):
        text = repository("hot-0")
        code = text.split("## src/inventory_0000.py\n", 1)[1].split("## tests/", 1)[0]
        scope = {}
        exec(compile(ast.parse(code), "fixture", "exec"), scope)
        stock = {"SKU": 7}
        scope["reserve_stock_0000"](stock, "SKU", -3)
        self.assertEqual(stock["SKU"], 10)

    def test_reference_adapter_rejects_negative_without_mutation(self):
        text = repository("hot-0")
        code = text.split("## src/tenant_0001/inventory.py\n", 1)[1].split("## tests/", 1)[0]
        scope = {}
        exec(compile(ast.parse(code), "fixture", "exec"), scope)
        stock = {"SKU": 7}
        with self.assertRaises(ValueError):
            scope["reserve_stock_0001"](stock, "SKU", -3)
        self.assertEqual(stock, {"SKU": 7})

    def test_quality_rejects_generic_refusal(self):
        self.assertFalse(review_quality("I cannot help with repeated padding."))
        self.assertTrue(review_quality("reserve_stock_0000 allows negative quantity; validate quantity <= 0."))

    def test_corpus_has_deterministic_distinct_tenants(self):
        self.assertEqual(repository("hot-0"), repository("hot-0"))
        self.assertNotEqual(repository("hot-0"), repository("hot-1"))
        self.assertIn("## src/tenant_1800/inventory.py", repository("hot-0"))


if __name__ == "__main__":
    unittest.main()
