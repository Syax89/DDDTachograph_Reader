"""TREP 11 body measurement must not rescan the buffer for its trailer.

``_trep11_body_len`` locates the ``76 14`` trailer that closes a TREP 11 body.
It scanned forward from the candidate body start on every call, and the chain
validator calls it once per ``76 11`` candidate, so a buffer made of
``76 06`` + N x ``76 11`` cost O(n^2): 16 002 bytes took 3.5 s and 32 002 bytes
14 s (a damaged or crafted G1 download, or a TREP 06 card region whose payload
is full of ``76 11`` byte pairs). The trailer positions are now indexed once per
walk and looked up by bisect.
"""
import os
import random
import struct
import sys
import time
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.parser.g1_walker import _new_walk_ctx, _trep11_body_len, iter_g1_vu_messages


def scan_reference(data, pos, end):
    """The original forward scan, kept as the behavioural reference."""
    cursor = pos
    while cursor < end - 1:
        if data[cursor] == 0x76 and data[cursor + 1] == 0x14:
            return cursor - pos
        cursor += 1
    return None


class TestTrep11BodyLength(unittest.TestCase):

    def test_body_ends_at_the_trailer(self):
        data = b"\x76\x11" + b"\x00" * 5 + b"\x76\x14" + b"\x00\x00"
        self.assertEqual(_trep11_body_len(data, 2, len(data)), 5)

    def test_no_trailer_means_no_body(self):
        data = b"\x76\x11" + b"\x00" * 40
        self.assertIsNone(_trep11_body_len(data, 2, len(data)))

    def test_result_matches_the_forward_scan(self):
        rng = random.Random(20261020)
        for _ in range(200):
            data = bytes(rng.choice((0x00, 0x11, 0x14, 0x76, 0x06)) for _ in range(60))
            pos = rng.randrange(0, 50)
            self.assertEqual(_trep11_body_len(data, pos, len(data)),
                             scan_reference(data, pos, len(data)))

    def test_shared_index_gives_the_same_answer(self):
        data = b"\x76\x11" + b"\x00" * 5 + b"\x76\x14" + b"\x00\x00"
        ctx = _new_walk_ctx()
        self.assertEqual(_trep11_body_len(data, 2, len(data), ctx),
                         _trep11_body_len(data, 2, len(data), ctx))
        self.assertEqual(_trep11_body_len(data, 2, len(data), ctx), 5)

    def test_trailer_at_the_very_end_is_found(self):
        data = b"\x76\x11" + b"\x00" * 3 + b"\x76\x14"
        self.assertEqual(_trep11_body_len(data, 2, len(data)), 3)


class TestTrep11FloodCost(unittest.TestCase):

    def test_many_trep11_pairs_walk_in_linear_time(self):
        data = b"\x76\x06" + b"\x76\x11" * 16_000
        started = time.perf_counter()
        messages = list(iter_g1_vu_messages(data))
        elapsed = time.perf_counter() - started
        self.assertIsInstance(messages, list)
        # Quadratic scaling took 14 s here; linear is milliseconds.
        self.assertLess(elapsed, 2.0)

    def test_repeated_walk_is_stable(self):
        data = b"\x76\x06" + b"\x76\x11" * 400 + b"\x76\x01" + struct.pack(">H", 0)
        first = list(iter_g1_vu_messages(data))
        second = list(iter_g1_vu_messages(data))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
