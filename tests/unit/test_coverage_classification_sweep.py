"""The coverage tracker must not rescan every covered interval per boundary.

``CoverageTracker.get_non_overlapping_classifications`` answers "is this byte
covered but unclassified?" for each boundary point. It used to test that with
``any(start <= point < end for each covered range)``, i.e. a full sweep of the
range list per point: O(points x ranges) — 3 s for 8 000 ranges of a public
``mark_covered`` caller. The merged ranges answer the same question with a
single forward cursor.
"""
import os
import random
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.parser.deterministic import CoverageTracker


class CountingRanges(list):
    """A range list that counts how often it is iterated."""

    scans = 0

    def __iter__(self):
        CountingRanges.scans += 1
        return super().__iter__()


def reference_totals(tracker):
    """Brute-force reference: per-byte majority, most recent classification wins."""
    totals = {}
    for byte in range(tracker.total_size):
        owner = None
        for start, end, classification in tracker.classification_ranges:
            if start <= byte < end:
                owner = classification
        if owner is None and any(s <= byte < e for s, e in tracker.covered_ranges):
            owner = "Unclassified"
        if owner is not None:
            totals[owner] = totals.get(owner, 0) + 1
    return totals


class TestNonOverlappingClassifications(unittest.TestCase):

    def test_covered_but_unclassified_ranges_are_not_rescanned_per_point(self):
        tracker = CoverageTracker(2000)
        for index in range(1000):
            tracker.mark_covered(index * 2, index * 2 + 1)
        tracker.covered_ranges = CountingRanges(tracker.covered_ranges)

        CountingRanges.scans = 0
        totals = tracker.get_non_overlapping_classifications()

        self.assertEqual(totals, {"Unclassified": 1000})
        # One pass over the ranges (to merge them), not one pass per point.
        self.assertLessEqual(CountingRanges.scans, 2)

    def test_large_range_set_is_fast(self):
        tracker = CoverageTracker(40_000)
        for index in range(8000):
            tracker.mark_covered(index * 4, index * 4 + 2)
        totals = tracker.get_non_overlapping_classifications()
        self.assertEqual(totals, {"Unclassified": 16_000})

    def test_totals_match_a_brute_force_reference(self):
        rng = random.Random(20261020)
        tracker = CoverageTracker(400)
        for order in range(120):
            start = rng.randrange(0, 400)
            end = min(400, start + rng.randrange(1, 40))
            if rng.random() < 0.4:
                tracker.mark_covered(start, end)
            else:
                tracker.mark_classified(start, end, f"Tag_{order:04X}")
        self.assertEqual(tracker.get_non_overlapping_classifications(),
                         reference_totals(tracker))

    def test_fully_classified_file_has_no_unclassified_bytes(self):
        tracker = CoverageTracker(64)
        tracker.mark_classified(0, 32, "Tag_0002")
        tracker.mark_classified(32, 64, "Tag_0501")
        self.assertEqual(tracker.get_non_overlapping_classifications(),
                         {"Tag_0002": 32, "Tag_0501": 32})


if __name__ == "__main__":
    unittest.main()
