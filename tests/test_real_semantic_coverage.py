import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from specs.semantic_coverage_audit import audit_directory, compare_to_baseline


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")
BASELINE_PATH = os.path.join(ROOT_DIR, "specs", "semantic_coverage_report.json")


class TestRealSemanticCoverage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(DDD_DIR):
            raise unittest.SkipTest("DDD directory not found")
        if not os.path.exists(BASELINE_PATH):
            raise unittest.SkipTest("Semantic coverage baseline not found")

    def test_real_ddd_unparsed_bytes_do_not_regress(self):
        with open(BASELINE_PATH, "r", encoding="utf-8") as handle:
            baseline = json.load(handle)

        metrics = audit_directory(DDD_DIR)
        comparison = compare_to_baseline(metrics, baseline)

        self.assertTrue(comparison["passed"], comparison)


if __name__ == "__main__":
    unittest.main()
