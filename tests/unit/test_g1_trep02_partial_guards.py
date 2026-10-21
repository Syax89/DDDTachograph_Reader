"""A cut TREP 02 body keeps the day it really carries.

TREP 02 (Annex 1B §4.5.3.2.3) is a sequence of count-prefixed arrays, so a body
cut by the end of the file still holds whole records: the day, its inserted card
and its activity changes are all present. The ``partial`` guards that stop the
walk at the cut must therefore run *before* the byte they protect — reading the
next count first turned a complete day into an ``IndexError`` and the whole
message fell back to the heuristic scan.

Every value below is synthetic.
"""
import struct

from core.decoders.vu_g1 import _complete_prefix_body, _parse_trep_02_g1_structured
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME
PLATE_FREE_ODO = 12_345


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


def _iw_record():
    return (S.coded_string("SYNTH SURNAME", code_page=1, length=36)
            + S.coded_string("SYNTH GIVEN", code_page=1, length=36)
            + S.full_card_number() + b"\x00" * 4
            + struct.pack(">I", TIME) + PLATE_FREE_ODO.to_bytes(3, "big")
            + bytes([0x01]) + struct.pack(">I", TIME + 60)
            + PLATE_FREE_ODO.to_bytes(3, "big") + b"\x00" * 19 + bytes([0x00]))


def _place_record():
    return (S.full_card_number() + struct.pack(">I", TIME + 120)
            + bytes([0x00, 0x1A, 0x01]) + PLATE_FREE_ODO.to_bytes(3, "big"))


#: Byte offsets of one whole TREP 02 body (1 inserted card, 2 changes, 2 places).
_BODY = (struct.pack(">I", TIME) + PLATE_FREE_ODO.to_bytes(3, "big")
         + struct.pack(">H", 1) + _iw_record()
         + struct.pack(">H", 2) + struct.pack(">HH", 0x0102, 0x0102)
         + bytes([2]) + _place_record() + _place_record()
         + struct.pack(">H", 1) + struct.pack(">I", TIME) + bytes([0x01]))

_IW_END = 7 + 2 + 129            # 138: the activity-change count follows
_CHANGES_END = _IW_END + 2 + 4   # 144: the place count follows
_PLACES_END = _CHANGES_END + 1 + 2 * 28   # 201: the specific-condition count


def test_a_body_cut_before_the_place_count_keeps_the_day():
    results = _results()
    assert _parse_trep_02_g1_structured(_BODY[:_CHANGES_END], results,
                                        partial=True) is True
    assert len(results["activities"]) == 1
    assert results["activities"][0]["changes_count"] == 2
    assert len(results["card_iw_records"]) == 1


def test_a_body_cut_before_the_condition_count_keeps_the_places():
    results = _results()
    assert _parse_trep_02_g1_structured(_BODY[:_PLACES_END], results,
                                        partial=True) is True
    assert len(results["activities"]) == 1
    assert len(results["places"]) == 2


def test_the_clamped_prefix_of_the_same_body_publishes_the_day():
    """The walker re-reads a cut message through the count-clamped prefix."""
    clamped, consumed = _complete_prefix_body(0x02, _BODY[:_CHANGES_END])
    assert consumed == _CHANGES_END
    results = _results()
    assert _parse_trep_02_g1_structured(clamped, results, partial=True) is True
    assert len(results["activities"]) == 1
    assert results["activities"][0]["changes_count"] == 2
    assert len(results["card_iw_records"]) == 1
