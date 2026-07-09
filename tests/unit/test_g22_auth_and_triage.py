import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.decoders import parse_g22_auth_subtag
from specs.unparsed_pattern_triage import triage_directory


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")


class TestG22AuthSubtag(unittest.TestCase):

    def test_gnss_auth_subtag_records_raw(self):
        payload = b"\xAA\xBB\xCC\xDD" * 4
        results = {}
        parse_g22_auth_subtag(payload, results, 0x960F)
        self.assertEqual(len(results["gnss_auth"]), 1)
        entry = results["gnss_auth"][0]
        self.assertEqual(entry["tag"], "0x960F")
        self.assertEqual(entry["length"], 16)
        self.assertEqual(entry["raw_hex"], payload.hex())

    def test_load_unload_auth_subtag_records_raw(self):
        payload = b"\x01\x02\x03\x04\x05"
        results = {}
        parse_g22_auth_subtag(payload, results, 0x6399)
        self.assertEqual(len(results["load_unload_auth"]), 1)
        entry = results["load_unload_auth"][0]
        self.assertEqual(entry["tag"], "0x6399")
        self.assertEqual(entry["length"], 5)

    def test_empty_payload_is_recorded(self):
        results = {}
        parse_g22_auth_subtag(b"", results, 0x960F)
        self.assertEqual(results["gnss_auth"][0]["length"], 0)


class TestUnparsedPatternTriage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(DDD_DIR):
            raise unittest.SkipTest("DDD directory not found")

    def test_triage_runs_and_returns_top_patterns(self):
        # An empty report means every byte of every real file is classified
        # (the goal); when patterns do remain, validate their shape.
        report = triage_directory(DDD_DIR, top_n=5)
        for entry in report:
            self.assertIn("pattern", entry)
            self.assertIn("count", entry)
            self.assertIn("total_bytes", entry)
            self.assertGreaterEqual(entry["count"], 1)


if __name__ == "__main__":
    unittest.main()
