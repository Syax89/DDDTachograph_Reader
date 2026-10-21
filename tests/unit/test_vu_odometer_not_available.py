"""An Activities day whose odometer is "not available" must not say 0 km.

``odometer_km()`` deliberately returns ``None`` for the reserved sentinel
(``FF FF FF``), and the generation-1 path keeps that ``None``. The generation-2
day builder defaulted its distance to ``0`` and then consulted
``if r.get("odometer_km")``, which is also false for ``None``: a day whose
OdometerValueMidnight was "not available" was published as **0 km** — a distance
the file never stated.
"""
from core.decoders.common import ODOMETER_NOT_AVAILABLE
from core.parser.vu_dispatcher import walk_vu_record_arrays
from tests.unit import vu_synthetic as S

DATE = S.BASE_TIME
NOT_AVAILABLE = 0xFFFFFF
REAL_KM = 123_456


def _activity(activity_byte=0x11):
    """One ActivityChangeInfo word (slot, crew, status, minute) — 2 bytes."""
    return bytes([activity_byte, 0x00])


def _activities_section(odometer):
    return S.section(
        0x32,
        S.record_array(0x06, 4, [DATE.to_bytes(4, "big")]),
        S.record_array(0x05, 3, [odometer.to_bytes(3, "big")]),
        S.record_array(0x01, 2, [_activity()]),
        S.signature_record())


def _day(odometer):
    results = {}
    walk_vu_record_arrays(_activities_section(odometer), results)
    return results["activities"][0]


def test_the_sentinel_is_reported_as_no_distance_at_all():
    assert NOT_AVAILABLE in ODOMETER_NOT_AVAILABLE
    day = _day(NOT_AVAILABLE)
    assert day["odometer_km"] is None
    assert day["date"] == "05/04/2024"


def test_a_real_odometer_value_is_still_published():
    day = _day(REAL_KM)
    assert day["odometer_km"] == REAL_KM


def test_the_day_and_its_activity_changes_are_still_emitted():
    day = _day(NOT_AVAILABLE)
    assert day["changes"], "the activity changes must not be lost with the odometer"
    results = {}
    walk_vu_record_arrays(_activities_section(NOT_AVAILABLE), results)
    assert results["metadata"]["vu_section_schema"][0]["dropped_records"] == {}
