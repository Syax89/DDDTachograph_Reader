"""``_unsigned_gaps`` is exact and cheap.

The gap finder used to paint a one-byte-per-byte coverage map and then scan it
in Python: 2.3 ms on a 108 KB download and 249 ms on a 10 MB one. It now merges
section ranges and takes the complement. These tests pin the output to the old
byte-map semantics (a reference implementation over randomised section layouts)
so the speed-up cannot change which bytes are reported as unsigned.
"""
import random

from core.crypto.vu_signature import _unsigned_gaps


def _reference_gaps(data, sections):
    """The pre-optimisation implementation, kept as the oracle."""
    covered = bytearray(len(data))
    for sec in sections:
        start = sec["marker"]
        end = start + 2
        if sec.get("interface"):
            end = start + 2 + len(sec["interface"])
        for (*_, rec_end) in sec["records"]:
            if rec_end > end:
                end = rec_end
        end = min(end, len(data))
        covered[start:end] = b"\x01" * (end - start)

    gaps = []
    start = None
    for pos, is_covered in enumerate(covered):
        if not is_covered:
            if start is None:
                start = pos
        elif start is not None:
            gaps.append((start, pos))
            start = None
    if start is not None:
        gaps.append((start, len(data)))

    def _is_download_trailer(s, e):
        return (e == len(data) and 2 <= e - s <= 8
                and data[s] == 0x76 and data[s + 1] == 0x00)

    return [(s, e) for s, e in gaps if not _is_download_trailer(s, e)]


def _section(marker, records, interface=None):
    section = {"marker": marker, "trep": 0x21, "records": records}
    if interface is not None:
        section["interface"] = interface
    return section


def test_no_sections_means_the_whole_download_is_unsigned():
    assert _unsigned_gaps(b"x" * 10, []) == [(0, 10)]


def test_fully_covered_download_has_no_gaps():
    data = b"x" * 20
    assert _unsigned_gaps(data, [_section(0, [(2, 0x01, 1, 1, 20)])]) == []


def test_leading_and_trailing_bytes_are_reported():
    data = b"x" * 30
    sections = [_section(5, [(7, 0x01, 1, 1, 20)])]
    assert _unsigned_gaps(data, sections) == [(0, 5), (20, 30)]


def test_overlapping_sections_do_not_emit_an_empty_gap():
    data = b"x" * 40
    sections = [_section(0, [(2, 0x01, 1, 1, 20)]),
                _section(10, [(12, 0x01, 1, 1, 30)])]
    assert _unsigned_gaps(data, sections) == [(30, 40)]


def test_a_download_trailer_is_not_unsigned_payload():
    data = b"x" * 20 + b"\x76\x00"
    sections = [_section(0, [(2, 0x01, 1, 1, 20)])]
    assert _unsigned_gaps(data, sections) == []


def test_the_interface_transfer_body_counts_as_covered():
    data = b"x" * 20
    sections = [_section(0, [], interface=b"\x02\x02")]
    assert _unsigned_gaps(data, sections) == [(4, 20)]


def test_record_ends_beyond_the_buffer_are_clamped():
    data = b"x" * 10
    assert _unsigned_gaps(data, [_section(0, [(2, 0x01, 1, 1, 99)])]) == []


def test_randomised_layouts_match_the_byte_map_reference():
    rng = random.Random(20261020)
    for _ in range(300):
        size = rng.randint(0, 64)
        data = bytes(rng.getrandbits(8) for _ in range(size))
        sections = []
        for _ in range(rng.randint(0, 5)):
            marker = rng.randint(0, max(size, 1))
            records = []
            cursor = marker + 2
            for _ in range(rng.randint(0, 4)):
                cursor += rng.randint(0, 6)
                records.append((cursor, 0x01, 1, 1, cursor + rng.randint(0, 8)))
            sections.append(_section(marker, records))
        assert _unsigned_gaps(data, sections) == _reference_gaps(data, sections), (
            size, sections)
