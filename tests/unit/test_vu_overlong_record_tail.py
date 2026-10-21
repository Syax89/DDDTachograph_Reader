"""A record LONGER than its canonical size reports a tail, never negative "missing".

Two decoders computed ``canonical - len(rec)`` on both sides of the size rule:

* VuDetailedSpeedBlock (0x12, 64 bytes) — a 65-byte body published
  ``missing_bytes: -1`` and put the WHOLE record in ``raw_tail_hex``;
* VuTimeAdjustmentRecord (0x1E, 99 bytes) — a 100-byte body published
  ``missing_bytes: -1`` as well.

A negative shortfall is not a fact a file can state: the bytes past the canonical
size are an extension (``raw_tail_bytes``/``raw_tail_hex``), exactly as every
other type publishes them.
"""
from core.parser.vu_dispatcher import (DETAILED_SPEED_BLOCK_SIZE,
                                       TIME_ADJUSTMENT_RECORD_SIZE,
                                       decode_vu_record)


def _speed_block(length):
    return b"\x00\x00\x00\x10" + bytes(range(4, length))


def _time_adjustment(length):
    return b"\x00\x00\x00\x10" * 2 + bytes(range(8, length))


def test_an_overlong_speed_block_reports_its_tail_not_a_negative_shortfall():
    record = decode_vu_record(0x12, _speed_block(DETAILED_SPEED_BLOCK_SIZE + 1),
                              trep=0x35)
    assert record["record_complete"] is False
    assert "missing_bytes" not in record
    assert record["raw_tail_bytes"] == 1
    assert record["raw_tail_hex"] == _speed_block(
        DETAILED_SPEED_BLOCK_SIZE + 1)[DETAILED_SPEED_BLOCK_SIZE:].hex()


def test_a_short_speed_block_still_reports_what_is_missing():
    record = decode_vu_record(0x12, _speed_block(DETAILED_SPEED_BLOCK_SIZE - 1),
                              trep=0x35)
    assert record["record_complete"] is False
    assert record["missing_bytes"] == 1
    assert "raw_tail_bytes" not in record


def test_an_overlong_time_adjustment_reports_its_tail():
    record = decode_vu_record(
        0x1E, _time_adjustment(TIME_ADJUSTMENT_RECORD_SIZE + 1), trep=0x35)
    assert record["record_complete"] is False
    assert "missing_bytes" not in record
    assert record["raw_tail_bytes"] == 1
    assert record["raw_tail_hex"] == _time_adjustment(
        TIME_ADJUSTMENT_RECORD_SIZE + 1)[TIME_ADJUSTMENT_RECORD_SIZE:].hex()


def test_a_short_time_adjustment_still_reports_what_is_missing():
    record = decode_vu_record(
        0x1E, _time_adjustment(TIME_ADJUSTMENT_RECORD_SIZE - 1), trep=0x35)
    assert record["record_complete"] is False
    assert record["missing_bytes"] == 1
    assert "raw_tail_bytes" not in record


def test_no_published_record_carries_a_negative_shortfall():
    for record_type, canonical in ((0x12, DETAILED_SPEED_BLOCK_SIZE),
                                   (0x1E, TIME_ADJUSTMENT_RECORD_SIZE)):
        for length in range(canonical - 2, canonical + 3):
            record = decode_vu_record(record_type, bytes(length), trep=0x35)
            if record is None:
                continue
            assert (record.get("missing_bytes") or 0) > 0 or \
                "missing_bytes" not in record, (record_type, length, record)
