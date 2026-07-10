"""Regression tests for malformed-input resource limits."""
from core.parser.deterministic import DeterministicParser
from core.utils.ber_tlv import read_ber_tlv_header


def test_ber_high_tag_with_too_many_octets_is_rejected():
    # A continuation run must not grow an arbitrary-size Python integer.
    data = b"\x1f" + b"\x80" * 16 + b"\x00"

    assert read_ber_tlv_header(data) == (None, None, 0)


def test_ber_high_tag_at_supported_limit_is_accepted():
    data = b"\x1f\x81\x81\x01\x00"

    tag, length, header_size = read_ber_tlv_header(data)

    assert tag == 0x1F818101
    assert length == 0
    assert header_size == 5


def test_adjacent_unknown_bytes_produce_one_bounded_range():
    # Invalid STAP dtype values force the G1 parser to advance byte-by-byte.
    results = DeterministicParser().parse(b"\xfe" * 4096, is_vu=False)

    unparsed = results["raw_tags"]["Unparsed Data"]
    assert len(unparsed) == 1
    assert unparsed[0]["length"] == 4096
    assert len(unparsed[0]["data_hex"]) <= 259  # 128 bytes plus ellipsis
    assert results["metadata"]["coverage_pct"] == results["coverage"]["covered_pct"]
