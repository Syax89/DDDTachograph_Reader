"""A sensor daily record is only published when its own day supports it.

The ``TRTP 11`` sensor payload is a manufacturer extension (no regulation defines
it), so the empirical layout is read leniently — but the three values of a daily
block are one record: ``midnight`` + ``first_event`` + a count of speed samples.
A block whose ``first_event`` does not fall in its own midnight day is not a day
at all (the reader is looking at a false marker inside another block), and a block
with no sample holds nothing to publish. Reporting either invents a day of data:
before this rule a download could claim days before the sensor existed, days after
the download was taken, and rows with no speed at all.

Every value below is synthetic.
"""
import struct

from core.decoders.vu_g1 import _decode_sensor_block

TIME = 1712345678               # synthetic, clearly not a corpus timestamp
MIDNIGHT = (TIME // 86_400) * 86_400
DAY = 86_400


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"},
            "activities": [], "events": [], "faults": [], "inserted_drivers": [],
            "card_iw_records": [], "places": [], "specific_conditions": [],
            "overspeeding_events": [], "overspeeding_control": [],
            "time_adjustments": [], "calibrations": [], "workshops": [],
            "calibration_vins": set(), "vu_info": {}, "vu_overview": {},
            "company_locks": [], "control_activities": [], "company_info": {},
            "speed_blocks": []}


def _sensor_body(*days):
    """TOC header(17) + Sensor ID block(168) + the daily blocks."""
    sensor = bytearray(168)
    sensor[0:4] = struct.pack(">I", MIDNIGHT - 30 * DAY)      # first_date
    sensor[4:8] = struct.pack(">I", MIDNIGHT)                 # last_date
    sensor[10:12] = struct.pack(">H", 90)                     # max speed
    sensor[12:14] = struct.pack(">H", 60)                     # average speed
    sensor[14:16] = struct.pack(">H", 500)                    # distance
    sensor[100] = 0x01
    sensor[101] = 0x1A
    sensor[102:118] = b"T00000000000001\x00"[:16]
    return b"\x00" * 17 + bytes(sensor) + b"".join(days)


def _day_block(midnight, first_event, samples):
    return (struct.pack(">I", midnight) + struct.pack(">I", first_event)
            + struct.pack(">H", len(samples)) + bytes(samples))


def test_a_block_with_no_sample_publishes_no_day():
    results = _results()
    _decode_sensor_block(_sensor_body(_day_block(MIDNIGHT - DAY,
                                                 MIDNIGHT - DAY + 60, b"")),
                         results, offset=0)
    assert results.get("sensor_daily_records") in (None, [])


def test_a_first_event_outside_its_own_day_publishes_no_day():
    results = _results()
    # Valid TimeReal, wrong day: 2049 is neither the midnight's day nor the
    # download's, so no day may be reported for those samples.
    _decode_sensor_block(_sensor_body(_day_block(MIDNIGHT - DAY, 2_500_000_000,
                                                b"\x28\x32")),
                         results, offset=0)
    assert results.get("sensor_daily_records") in (None, [])


def test_a_consistent_day_is_still_published():
    results = _results()
    _decode_sensor_block(_sensor_body(
        _day_block(MIDNIGHT - DAY, MIDNIGHT - DAY + 3_600, b"\x0A\x14\x1E")),
        results, offset=0)
    records = results["sensor_daily_records"]
    assert len(records) == 1
    record = records[0]
    assert record["speed_samples"] == 3
    assert record["speed_min"] == 10 and record["speed_max"] == 30
    assert record["first_event"].endswith("01:00:00+00:00")
