"""Regression tests for core.parser.record_array.decode_g2_daily_record.

L7: the inline ActivityChangeInfo bit-splitting duplicated
core.decoders.decode_activity_val but dropped bit 13 (card_not_inserted), so
changes lacked the 'card_inserted' key. Decoding now goes through
decode_activity_val, which also keeps the invalid-minute (None) semantics.
"""

import struct

from core.parser.record_array import decode_g2_daily_record


def _daily_record_payload(changes):
    """Build a minimal 112-byte G2 daily record with the given change counters."""
    counters = [0x0000, 0x0100, 0x0200] + changes + [0] * (11 - 3 - len(changes))
    return (
        b"\x76\x22"                       # [0:2]   pseudo-tag (G2)
        + b"\x05"                         # [2]     dtype
        + b"\x00\x00"                     # [3:5]   length
        + struct.pack(">I", 42)           # [5:9]   daily_counter
        + b"\x00" * 8                     # [9:17]  pseudo-STAP header
        + struct.pack(">H", 0)            # [17:19] day_field
        + b"\x00"                         # [19]    marker
        + struct.pack(">H", len(changes))  # [20:22] changes_count
        + struct.pack(">11H", *counters)  # [22:44] 11 counters
        + b"\x00"                         # [44]
        + b"\x40"                         # [45]    sig_len
        + b"\x00\x01"                     # [46:48]
        + b"\x00" * 64                    # [48:112] signature
    )


def test_g2_daily_record_bit13_sets_card_inserted():
    """Counters with/without bit 13 yield card_inserted False/True."""
    # 0x2000 = bit 13 (card_not_inserted), 0x1000 = activity 2 (WORK),
    # 0x01E0 = 480 minutes (08:00).
    with_bit13 = 0x2000 | 0x1000 | 0x01E0
    without_bit13 = 0x1000 | 0x01E0

    record = decode_g2_daily_record(_daily_record_payload([with_bit13, without_bit13]), 0)

    assert record is not None
    assert record["changes"] == [
        {"time": "08:00", "activity": "WORK", "slot": "First",
         "crew": False, "card_inserted": False},
        {"time": "08:00", "activity": "WORK", "slot": "First",
         "crew": False, "card_inserted": True},
    ]


def test_g2_daily_record_invalid_minute_skipped():
    """Minutes > 1439 are dropped (decode_activity_val returns None)."""
    invalid = 0x1000 | 0x07FF  # WORK at 2047 minutes
    valid = 0x1000 | 0x01E0    # WORK at 08:00

    record = decode_g2_daily_record(_daily_record_payload([invalid, valid]), 0)

    assert record is not None
    assert [c["time"] for c in record["changes"]] == ["08:00"]
