import struct

from app.gui import detailed_speed_blocks_by_day, detailed_speed_by_day
from core.decoders.vu_g1 import _parse_trep_04_speed


def test_detailed_speed_groups_samples_by_utc_day_and_keeps_gaps():
    data = {
        "speed_blocks": [{
            "begin": "2025-06-30T23:59:59+00:00",
            "_chart_speeds_kmh": [88, None, 95],
        }],
        "detailed_speed": [{
            "timestamp": "2025-07-01T00:00:03+00:00",
            "speeds_kmh": [0xFF, 62],
        }],
    }

    assert detailed_speed_by_day(data) == {
        "2025-06-30": [(86399, 88)],
        "2025-07-01": [(1, 95), (4, 62)],
    }


def test_g1_speed_parser_retains_all_samples_for_chart_data():
    timestamp = 1751277540
    first = struct.pack(">I", timestamp) + bytes([40, 0xFF]) + bytes([41] * 58)
    second = struct.pack(">I", timestamp + 60) + bytes([42] * 60)
    results = {}

    _parse_trep_04_speed(struct.pack(">H", 2) + first + second, results)

    block = results["speed_blocks"][0]
    assert block["minutes"] == 2
    assert len(block["_chart_speeds_kmh"]) == 120
    assert block["_chart_speeds_kmh"][:3] == [40, None, 41]
    assert block["_chart_speeds_kmh"][-1] == 42


def test_detailed_speed_raw_blocks_are_available_for_each_utc_day():
    block = {
        "begin": "2025-06-30T23:59:59+00:00",
        "_chart_speeds_kmh": [88, 91],
    }

    assert detailed_speed_blocks_by_day([block]) == {
        "2025-06-30": [block],
        "2025-07-01": [block],
    }
