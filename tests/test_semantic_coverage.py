import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from specs.semantic_coverage_audit import compare_to_baseline, semantic_metrics


class TestSemanticCoverageMetrics(unittest.TestCase):

    def test_semantic_metrics_excludes_unparsed_and_padding_bytes(self):
        result = {
            "metadata": {
                "file_size_bytes": 100,
                "coverage_pct": 100.0,
                "generation": "G2.2 (Smart V2)",
            },
            "raw_tags": {
                "Unparsed Data": [
                    {"offset": 10, "length": 12},
                    {"offset": 50, "length": 8},
                    {"offset": 70, "length": 1},
                    {"offset": 71, "length": 1},
                ],
                "Padding": [
                    {"offset": 90, "length": 5},
                ],
                "KnownTag": [
                    {"offset": 0, "length": 10, "raw_hex": "FF" * 99},
                ],
            },
            "calibrations": [
                {"raw_tail_hex": "001122"},
            ],
            "gnss_auth": [
                {
                    "raw_hex": "AABBCCDD",
                    "header_hex": "AABB",
                    "payload_hex": "CCDD",
                },
            ],
        }

        metrics = semantic_metrics(result)

        self.assertEqual(metrics["tracked_byte_coverage"], 100.0)
        self.assertEqual(metrics["unparsed_bytes"], 22)
        self.assertEqual(metrics["padding_bytes"], 5)
        self.assertEqual(metrics["decoded_bytes"], 73)
        self.assertEqual(metrics["decoded_byte_coverage"], 73.0)
        self.assertEqual(metrics["unparsed_blocks"], 4)
        self.assertEqual(metrics["stranded_blocks"], 2)
        self.assertEqual(metrics["stranded_bytes"], 2)
        self.assertEqual(metrics["meaningful_unparsed_blocks"], 2)
        self.assertEqual(metrics["meaningful_unparsed_bytes"], 20)
        self.assertEqual(metrics["meaningful_byte_coverage"], 80.0)
        self.assertEqual(metrics["raw_tail_bytes"], 3)
        self.assertEqual(metrics["raw_blob_bytes"], 4)
        self.assertEqual(metrics["semantic_debt_bytes"], 29)
        self.assertEqual(metrics["strict_decoded_bytes"], 66)
        self.assertEqual(metrics["strict_decoded_byte_coverage"], 66.0)

    def test_baseline_comparison_fails_only_on_unparsed_increase(self):
        metrics = {
            "same.ddd": {"unparsed_bytes": 10},
            "better.ddd": {"unparsed_bytes": 4},
            "worse.ddd": {"unparsed_bytes": 12},
        }
        baseline = {
            "same.ddd": {"unparsed_bytes": 10},
            "better.ddd": {"unparsed_bytes": 8},
            "worse.ddd": {"unparsed_bytes": 7},
        }

        comparison = compare_to_baseline(metrics, baseline)

        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["regressions"], [{
            "filename": "worse.ddd",
            "metric": "unparsed_bytes",
            "baseline_unparsed_bytes": 7,
            "current_unparsed_bytes": 12,
            "increase": 5,
        }])

    def test_baseline_comparison_fails_on_missing_files(self):
        comparison = compare_to_baseline(
            {"new.ddd": {"unparsed_bytes": 0, "semantic_debt_bytes": 0}},
            {},
        )

        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["missing_baseline"], ["new.ddd"])

    def test_baseline_comparison_fails_on_semantic_debt_increase(self):
        comparison = compare_to_baseline(
            {"file.ddd": {"unparsed_bytes": 0, "semantic_debt_bytes": 12}},
            {"file.ddd": {"unparsed_bytes": 0, "semantic_debt_bytes": 4}},
        )

        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["regressions"], [{
            "filename": "file.ddd",
            "metric": "semantic_debt_bytes",
            "baseline_semantic_debt_bytes": 4,
            "current_semantic_debt_bytes": 12,
            "increase": 8,
        }])


if __name__ == "__main__":
    unittest.main()
