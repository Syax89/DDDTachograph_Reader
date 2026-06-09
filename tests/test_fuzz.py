"""Fuzz/robustness tests: verify parser handles corrupted inputs without crashes.

Covers: truncated files, invalid BER lengths, malformed nested tags,
anomalous padding, out-of-range offsets, empty files, and edge cases.
"""

import struct
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddd_parser import TachoParser


def _make_temp_file(data):
    f = tempfile.NamedTemporaryFile(suffix='.ddd', delete=False)
    f.write(data)
    f.close()
    return f.name


def _parse_and_collect(path):
    """Parse a file and collect errors instead of crashing."""
    try:
        parser = TachoParser(path)
        result = parser.parse()
        return result, None
    except Exception as e:
        return None, str(e)


class TestFuzzTruncatedFiles(unittest.TestCase):
    """Truncated or empty files must not crash."""

    def test_empty_file(self):
        path = _make_temp_file(b'')
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
            self.assertEqual(result["metadata"]["file_size_bytes"], 0)
        finally:
            os.unlink(path)

    def test_one_byte_file(self):
        path = _make_temp_file(b'\x00')
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_two_byte_file(self):
        path = _make_temp_file(b'\x76\x31')
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_truncated_g1_header(self):
        data = b'\x00\x01' + struct.pack(">H", 100) + b'\x00' * 10
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_truncated_g2_header(self):
        data = b'\x76\x21' + struct.pack(">H", 200) + b'\x00' * 5
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_truncated_g22_header(self):
        data = b'\x76\x31' + struct.pack(">H", 200) + b'\x00' * 5
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_header_length_exceeds_file(self):
        data = b'\x76\x21' + struct.pack(">H", 65535) + b'\x00' * 10
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_random_binary_no_crash(self):
        import random
        random.seed(42)
        data = bytes(random.getrandbits(8) for _ in range(1024))
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)


class TestFuzzInvalidBERLengths(unittest.TestCase):
    """Invalid BER-TLV length fields must not crash."""

    def test_zero_length_tag(self):
        tag = b'\x01\x00'
        path = _make_temp_file(tag)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_negative_length_indefinite(self):
        tag = b'\x01\x80'
        path = _make_temp_file(tag)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_length_bytes_exceed_remaining(self):
        tag = b'\x01\x82\xFF\xFF'
        path = _make_temp_file(tag)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_four_byte_length(self):
        tag = b'\x01\x84\x00\x00\x00\x64'
        path = _make_temp_file(tag)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_length_too_large(self):
        tag = b'\x01\x83\x10\x00\x00'
        path = _make_temp_file(tag + b'\x00' * 10)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)


class TestFuzzNestedMalformed(unittest.TestCase):
    """Malformed nested tag structures must not crash."""

    def test_nested_with_invalid_inner_tag(self):
        outer = b'\x76\x21' + struct.pack(">H", 10) + b'\x00\x02'
        inner = b'\xFF\x01\x00'
        data = outer + inner
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_nested_with_missing_length(self):
        data = b'\x76\x21' + struct.pack(">H", 5) + b'\x01'
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_nested_container_traversal(self):
        outer = b'\x76\x21' + struct.pack(">H", 8) + b'\x00\x02'
        inner = b'\x00\x01\x00\x04' + b'\x00' * 4
        data = outer + inner
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_g2_container_with_garbage_inner(self):
        outer = b'\x76\x21' + struct.pack(">H", 20) + b'\x00\x02'
        garbage = b'\xDE\xAD\xBE\xEF' * 3 + b'\x00' * 4
        data = outer + garbage
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)


class TestFuzzPaddingAnomalies(unittest.TestCase):
    """Various padding and fill byte patterns must not crash."""

    def test_all_zeros_file(self):
        data = b'\x00' * 1000
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_all_ff_file(self):
        data = b'\xFF' * 1000
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_all_55_file(self):
        data = b'\x55' * 1000
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_mixed_padding_and_tags(self):
        data = b'\x00' * 10 + b'\x76\x21' + struct.pack(">H", 8) + b'\x00\x02' + b'\x00' * 4 + b'\xFF' * 20
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)


class TestFuzzLargeFiles(unittest.TestCase):
    """Large file handling without crashes."""

    def test_large_padding_file(self):
        data = b'\x00' * 10000
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_large_repeating_pattern(self):
        pattern = b'\x00\x01\x00\x02' + b'\x00' * 4
        data = pattern * 1000
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)


class TestFuzzRecordArrayEdgeCases(unittest.TestCase):
    """RecordArray edge cases must not crash."""

    def test_record_array_zero_records(self):
        record_array = struct.pack(">BHH", 1, 64, 0)
        data = b'\x76\x31' + struct.pack(">H", len(record_array)) + record_array
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_record_array_huge_count(self):
        record_array = struct.pack(">BHH", 1, 10, 65535)
        data = b'\x76\x31' + struct.pack(">H", len(record_array)) + record_array
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_record_array_negative_size(self):
        record_array = struct.pack(">BHH", 1, 0xFFFE, 1)
        data = b'\x76\x31' + struct.pack(">H", len(record_array)) + record_array + b'\x00' * 10
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)


class TestFuzzStapEdgeCases(unittest.TestCase):
    """STAP (G1) edge cases must not crash."""

    def test_stap_missing_length(self):
        data = b'\x00\x01' + b'\x00' * 100
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_stap_zero_length_tlv(self):
        data = b'\x00\x01\x00\x00' + b'\x00' * 10
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)

    def test_stap_length_mismatch(self):
        data = b'\x00\x01\x00\x64' + b'\x00' * 20
        path = _make_temp_file(data)
        try:
            result, err = _parse_and_collect(path)
            self.assertIsNotNone(result)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
