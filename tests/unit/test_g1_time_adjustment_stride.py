"""G1 VuTimeAdjustmentRecord is 98 bytes: a declared count is never inflated.

The TREP 03 tail declares its stored time-adjustment records with one count byte
(Annex 1B §2.120: ``VuTimeAdjustmentRecord`` = oldTimeValue(4) + newTimeValue(4)
+ workshop card number(18) + company name(36) + company address(36) = 98). A body
that declares more records than it holds is a cut message: the records that are
really there are published, and no zero-byte placeholder is invented for the rest.

Every value below is synthetic.
"""
import struct

from core.decoders.vu_g1 import _parse_trep_03_structured
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


def _adjustment_record():
    """One 98-byte VuTimeAdjustmentRecord (Annex 1B §2.120)."""
    return (struct.pack(">II", TIME, TIME + 30)
            + S.coded_string("SYNTH WORKSHOP", code_page=1, length=36)
            + S.coded_string("SYNTH STREET 3", code_page=1, length=36)
            + S.full_card_number(card_type=0x02))


def _body(declared, held):
    body = bytearray()
    body += bytes([0])                                  # no faults
    body += bytes([0])                                  # no events
    body += struct.pack(">II", TIME, TIME) + bytes([0])  # VuOverSpeedingControlData
    body += bytes([0])                                  # no overspeeding events
    body += bytes([declared]) + _adjustment_record() * held
    return bytes(body)


def test_declared_count_beyond_the_body_publishes_only_the_records_held():
    results = _results()
    assert _parse_trep_03_structured(_body(declared=5, held=2), results) is True
    records = results["time_adjustments"]
    assert len(records) == 2
    # Both records are whole 98-byte records, and nothing is invented for the
    # three the count declares but the body does not carry.
    assert [r["record_bytes"] for r in records] == [98, 98]
    assert all(r["record_complete"] for r in records)
    assert all(r["old_time"] for r in records)
    assert all(r["workshop_name"].startswith("SYNTH") for r in records)


def test_a_partly_stored_adjustment_record_is_still_kept():
    """A record whose own bytes were cut is kept (`record_complete` false)."""
    results = _results()
    body = _body(declared=1, held=1)[:-(98 - 40)]
    assert _parse_trep_03_structured(body, results) is True
    records = results["time_adjustments"]
    assert len(records) == 1
    assert records[0]["record_bytes"] == 40
    assert records[0]["record_complete"] is False


def test_a_declared_count_with_no_record_bytes_publishes_nothing():
    results = _results()
    body = _body(declared=3, held=0)
    assert _parse_trep_03_structured(body, results) is True
    assert results["time_adjustments"] == []
