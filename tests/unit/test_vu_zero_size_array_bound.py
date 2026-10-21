"""A zero-size RecordArray must not amplify into hundreds of thousands of records.

``noOfRecords`` records of ``recordSize`` 0 occupy no bytes, so the declared count
is not bounded by the file: a five-byte header could claim 20 000 records and one
kilobyte of such headers claimed the whole 500 000-record cap (187 MB of decoded
dicts, ~0.6 s for a 1 KB file) — exactly the amplification the walk's own
``VU_MAX_TOTAL_RECORDS`` docstring says it prevents.

The header is still accepted (never resynchronised as junk) and the extension is
still reported; it just cannot yield more than the one placeholder record its zero
bytes can describe.
"""
import time

from core.parser.vu_dispatcher import walk_vu_record_arrays
from tests.unit import vu_synthetic as S

#: Record type of the observed empirical extension that is stored with size 0.
ZERO_SIZE_TYPE = 0x60


def _zero_size_array(count):
    return (bytes([ZERO_SIZE_TYPE]) + b"\x00\x00" + count.to_bytes(2, "big"))


def test_a_zero_size_header_yields_one_placeholder_record():
    results = {}
    walk_vu_record_arrays(S.section(0x32, _zero_size_array(1)), results)
    assert results["vu_record_arrays"][0]["record_counts"] == {
        f"0x{ZERO_SIZE_TYPE:02X}": 1}


def test_a_densely_packed_zero_size_stream_stays_bounded():
    data = S.section(0x32, *[_zero_size_array(20000) for _ in range(200)])
    results = {}
    started = time.time()
    walk_vu_record_arrays(data, results)
    elapsed = time.time() - started

    assert results.get("_vu_walk_record_cap") is None
    # 200 headers describe 200 placeholders, not 4 000 000 records
    assert results["vu_record_arrays"][0]["record_counts"] == {
        f"0x{ZERO_SIZE_TYPE:02X}": 200}
    # the extension row counts what was actually decoded, never the claim
    assert results["unmapped_record_types"][0]["record_count"] <= 200
    assert elapsed < 0.5, elapsed


def test_the_zero_size_header_is_accepted_not_junk():
    """The bytes are an extension, not resync junk: the walk stays quiet about them."""
    data = S.section(0x32, _zero_size_array(5), S.signature_record())
    results = {}
    walk_vu_record_arrays(data, results)
    assert "vu_walk_resync_bytes" not in (results["metadata"] or {})
    assert results["vu_unmapped_record_types"] == [f"0x{ZERO_SIZE_TYPE:02X}"]
