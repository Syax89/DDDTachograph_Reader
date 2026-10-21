"""A padding run must not consume the first byte of the record that follows it.

``_skip_padding`` / ``_skip_padding_inner`` used to advance one byte past the
pairwise fill check unconditionally, to "include the last byte of the run". When
the fill byte is also the first byte of the next record — a 0x00-filled gap in
front of a card EF whose tag is a two-byte 00xxh (EF_ICC 0002h, EF_IC 0005h) —
that byte is the record's tag high byte, so the record vanished and the walk
desynced for the rest of the file.
"""
import os
import struct
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.parser.deterministic import CoverageTracker, DeterministicParser
from core.registry.models import TachoResult


def stap(tag, dtype, payload):
    return struct.pack(">HBH", tag, dtype, len(payload)) + payload


def padding_bytes(result):
    return sum(p["length"] for p in result["raw_tags"].get("Padding", []))


class TestZeroFilledGapBeforeLowTagRecord(unittest.TestCase):

    def _parse(self, data):
        return DeterministicParser().parse(data, is_vu=False)

    def test_skip_padding_returns_the_true_run_length(self):
        data = b"\x00\x00" + stap(0x0002, 0x00, b"\xAA" * 8) + stap(0x0501, 0x00, b"\xBB" * 8)
        parser = DeterministicParser()
        parser.generation = "G1"
        parser.is_vu = False
        parser.coverage = CoverageTracker(len(data))
        self.assertEqual(parser._skip_padding(data, 0, len(data)), 2)

    def test_zero_filled_gap_keeps_the_following_record(self):
        data = b"\x00\x00" + stap(0x0002, 0x00, b"\xAA" * 8) + stap(0x0501, 0x00, b"\xBB" * 8)
        result = self._parse(data)
        self.assertIn("0002_EF_ICC", result["raw_tags"])
        self.assertIn("0501_G1_DriverCardApplicationIdentification", result["raw_tags"])
        self.assertEqual(padding_bytes(result), 2)
        self.assertEqual(result["coverage"]["unknown_bytes"], 0)
        self.assertEqual(result["coverage"]["covered_pct"], 100.0)

    def test_three_zero_bytes_of_gap_keep_the_following_record(self):
        data = b"\x00" * 3 + stap(0x0002, 0x00, b"\xAA" * 8) + stap(0x0501, 0x00, b"\xBB" * 8)
        result = self._parse(data)
        self.assertIn("0002_EF_ICC", result["raw_tags"])
        self.assertEqual(padding_bytes(result), 3)
        self.assertEqual(result["coverage"]["unknown_bytes"], 0)

    def test_zero_filled_gap_before_ef_ic(self):
        # EF_IC (0005h) is the other mandatory card EF whose tag starts with 0x00.
        data = b"\x00\x00" + stap(0x0005, 0x00, b"\xAA" * 8) + stap(0x0520, 0x00, b"\xBB" * 8)
        result = self._parse(data)
        self.assertIn("0005_EF_IC", result["raw_tags"])
        self.assertEqual(padding_bytes(result), 2)
        self.assertEqual(result["coverage"]["unknown_bytes"], 0)

    def test_zero_filled_gap_before_a_high_tag_record_is_all_padding(self):
        # The record's first byte is not the fill byte: the whole run is padding.
        data = b"\x00\x00" + stap(0x0501, 0x00, b"\xAA" * 8)
        result = self._parse(data)
        self.assertIn("0501_G1_DriverCardApplicationIdentification", result["raw_tags"])
        self.assertEqual(padding_bytes(result), 2)
        self.assertEqual(result["coverage"]["unknown_bytes"], 0)

    def test_zero_filled_gap_inside_a_container(self):
        # Same walk inside a container payload (relative offsets, base offset).
        payload = b"\x00\x00" + stap(0x0002, 0x00, b"\xAA" * 8)
        parser = DeterministicParser()
        parser.generation = "G1"
        parser.is_vu = False
        parser.coverage = CoverageTracker(100 + len(payload))
        parser.results = TachoResult().to_dict()
        self.assertEqual(
            parser._skip_padding_inner(payload, 0, len(payload), 100, 1, "Container", "stap"),
            2)
        pads = parser.results["raw_tags"]["Container > Padding"]
        self.assertEqual(sum(p["length"] for p in pads), 2)
        # Recorded at absolute (container-relative) offsets.
        self.assertEqual(pads[0]["offset"], "0x00000064")

    def test_padding_run_still_reaches_a_record_that_starts_at_its_end(self):
        # Control: the run must still be skipped whole when nothing starts inside it.
        data = b"\xFF" * 4 + stap(0x0002, 0x00, b"\xAA" * 8)
        result = self._parse(data)
        self.assertIn("0002_EF_ICC", result["raw_tags"])
        self.assertEqual(padding_bytes(result), 4)


if __name__ == "__main__":
    unittest.main()
