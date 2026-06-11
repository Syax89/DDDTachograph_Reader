"""Regression tests for padding handling in the deterministic parser.

A card file starts with the EF_ICC STAP header (tag 0x0002): its first byte is
0x00, which must never be treated as a lone padding byte — doing so desyncs the
whole parse (the parser would eat the record header and lose every EF).
"""
import os
import struct
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.deterministic_parser import DeterministicParser


def stap(tag, dtype, payload):
    return struct.pack(">HBH", tag, dtype, len(payload)) + payload


class TestPaddingSkip(unittest.TestCase):

    def _parse(self, data):
        return DeterministicParser().parse(data, is_vu=False)

    def test_leading_zero_of_record_header_is_not_padding(self):
        # File starts directly with EF_ICC (tag 0x0002) — first byte is 0x00.
        data = stap(0x0002, 0x00, b"\xAA" * 8)
        results = self._parse(data)
        self.assertIn("0002_EF_ICC", results["raw_tags"])
        self.assertEqual(results["coverage"]["covered_pct"], 100.0)

    def test_lone_padding_byte_before_record_does_not_eat_header(self):
        # A lone 0x00 gap byte right before a record: the record must survive.
        data = b"\x00" + stap(0x0520, 0x00, b"\xAA" * 8)
        results = self._parse(data)
        self.assertIn("0520_G1_Identification", results["raw_tags"])

    def test_padding_run_then_record(self):
        data = b"\xFF" * 4 + stap(0x0002, 0x00, b"\xAA" * 8)
        results = self._parse(data)
        self.assertIn("0002_EF_ICC", results["raw_tags"])
        pads = results["raw_tags"].get("Padding", [])
        self.assertEqual(sum(p["length"] for p in pads), 4)
        self.assertEqual(results["coverage"]["covered_pct"], 100.0)

    def test_lone_trailing_padding_byte(self):
        # A single padding byte at EOF is classified without overshooting.
        data = stap(0x0002, 0x00, b"\xAA" * 8) + b"\xFF"
        results = self._parse(data)
        self.assertIn("0002_EF_ICC", results["raw_tags"])
        pads = results["raw_tags"].get("Padding", [])
        self.assertEqual(sum(p["length"] for p in pads), 1)
        self.assertEqual(results["coverage"]["covered_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
