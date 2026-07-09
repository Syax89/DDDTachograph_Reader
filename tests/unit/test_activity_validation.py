import struct

from app.engine import TachoParser
from core.decoders.common import decode_activity_val, parse_cyclic_buffer_activities
from core.decoders.vu_g1 import _parse_trep_02_g1_structured
from core.parser.vu_dispatcher import _decode_record


def test_activity_dedup_only_removes_structurally_identical_records():
    original = {
        "date": "01/01/2025",
        "daily_counter": 0,
        "changes": [{"time": "00:00", "metadata": {"codes": [1, 2]}}],
    }
    duplicate = {
        "changes": [{"metadata": {"codes": [1, 2]}, "time": "00:00"}],
        "daily_counter": 0,
        "date": "01/01/2025",
    }
    distinct_change = {
        "date": "01/01/2025",
        "daily_counter": 0,
        "changes": [{"time": "00:00", "metadata": {"codes": [2, 1]}}],
    }
    distinct_counter = {
        "date": "01/01/2025",
        "daily_counter": 1,
        "changes": [{"time": "00:00", "metadata": {"codes": [1, 2]}}],
    }
    parser = TachoParser.__new__(TachoParser)
    parser.results = {"activities": [original, duplicate, distinct_change, distinct_counter]}

    parser._dedup_and_sort_activities()

    assert parser.results["activities"] == [original, distinct_change, distinct_counter]


def test_decode_activity_val_rejects_invalid_minutes_and_retains_midnight():
    assert decode_activity_val(0)["time"] == "00:00"
    assert decode_activity_val(1439)["time"] == "23:59"
    assert decode_activity_val(1440) is None
    assert decode_activity_val(0x07FF) is None


def test_invalid_activity_values_are_not_added_to_daily_activities():
    header = struct.pack(">HHI", 0, 14, 1_700_000_000)
    data = b"\x00\x00\x00\x00" + header + b"\x00\x00\x00\x00" + struct.pack(">H", 1440)
    results = {"activities": []}

    parse_cyclic_buffer_activities(data, results)

    assert results["activities"] == []


def test_invalid_activity_values_are_not_added_to_structured_vu_activities():
    data = (
        struct.pack(">I", 1_700_000_000)
        + b"\x00\x00\x00"
        + struct.pack(">H", 0)
        + struct.pack(">H", 1)
        + struct.pack(">H", 1440)
        + b"\x00"
        + struct.pack(">H", 0)
    )
    results = {}

    assert _parse_trep_02_g1_structured(data, results)
    assert results.get("activities", []) == []


def test_record_array_activity_rejects_invalid_minutes():
    assert "raw_hex" in _decode_record(0x01, struct.pack(">H", 1440))
    assert "raw_hex" in _decode_record(0x29, struct.pack(">H", 1440))

    decoded = _decode_record(0x29, struct.pack(">H", 1439))
    assert decoded["activity"]["time"] == "23:59"
