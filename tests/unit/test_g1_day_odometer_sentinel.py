"""The day odometer of a TREP 02 goes through the sentinel helper.

``odometerValueMidnight`` (Annex 1B §2.2.6.2) is 3 bytes, so ``FFFFFF`` is the
"not available" value: the activity day must report no distance for it, exactly
as every other odometer in the decoder does, instead of publishing 16 777 215 km.

Every value below is synthetic.
"""
import struct

from core.decoders.common import odometer_km
from core.decoders.vu_g1 import _parse_trep_02_g1_structured
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


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


def _day(odo):
    """A TREP 02 body: one day, no card insertion, one change, no places."""
    return (struct.pack(">I", TIME) + odo.to_bytes(3, "big")
            + b"\x00\x00" + struct.pack(">H", 1) + struct.pack(">H", 0x1180)
            + bytes([0]) + struct.pack(">H", 0))


def test_the_not_available_odometer_publishes_no_distance():
    assert odometer_km(0xFFFFFF) is None          # the helper's verdict
    results = _results()
    assert _parse_trep_02_g1_structured(_day(0xFFFFFF), results) is True
    day = results["activities"][0]
    assert day["odometer_km"] is None
    assert day["date"] == "05/04/2024"


def test_a_real_day_odometer_is_kept():
    results = _results()
    assert _parse_trep_02_g1_structured(_day(120_000), results) is True
    assert results["activities"][0]["odometer_km"] == 120_000
