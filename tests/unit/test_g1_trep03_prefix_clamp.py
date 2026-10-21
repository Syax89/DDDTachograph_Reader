"""The count-clamped TREP 03 prefix keeps every COMPLETE time adjustment.

``_complete_prefix_body`` rewrites the counts of a message body cut by the end of
the file so its own handler can read the complete records before the cut. In
TREP 03 only the overspeeding array is preceded by the 9-byte
``VuOverSpeedingControlData``; the time-adjustment array that follows carries
nothing but its own count byte (Annex 1B §2.120). Treating the second tail as if
it also had a control block shifted the adjustment array by 9 bytes, so a
complete 98-byte record was dropped and a 9-byte phantom one published.

Every value below is synthetic.
"""
import struct

from core.decoders.vu_g1 import _complete_prefix_body, _parse_trep_03_structured
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


def _adjustment_record(offset=0):
    return (struct.pack(">II", TIME + offset, TIME + offset + 30)
            + S.coded_string("SYNTH WORKSHOP", code_page=1, length=36)
            + S.coded_string("SYNTH STREET 3", code_page=1, length=36)
            + S.full_card_number(card_type=0x02))


def _body(n_adjustments=3):
    body = bytearray()
    body += bytes([0])                                   # no faults
    body += bytes([0])                                   # no events
    body += struct.pack(">II", TIME, TIME) + bytes([0])   # control data, none stored
    body += bytes([0])                                   # no overspeeding events
    body += bytes([n_adjustments])
    for i in range(n_adjustments):
        body += _adjustment_record(offset=i * 60)
    return bytes(body)


def test_clamped_prefix_covers_every_complete_adjustment():
    body = _body(n_adjustments=3)
    # Cut inside the third adjustment: the first two are whole 98-byte records.
    cut = len(body) - 98
    clamped, consumed = _complete_prefix_body(0x03, body[:cut])
    # The clamped body must reach the start of the cut record: 1 + 1 + 9 + 1 + 1
    # header bytes plus two complete records.
    assert consumed == cut
    assert len(clamped) == consumed

    results = _results()
    assert _parse_trep_03_structured(clamped, results, partial=True) is True
    records = results["time_adjustments"]
    assert [r["record_bytes"] for r in records] == [98, 98]
    assert all(r["record_complete"] for r in records)
    assert len({r["old_time"] for r in records}) == 2     # two distinct records


def test_clamped_prefix_keeps_the_control_block_once():
    body = _body(n_adjustments=1)
    clamped, consumed = _complete_prefix_body(0x03, body)
    assert consumed == len(body)
    assert len(clamped) == len(body)
    # The 9-byte control block and both count bytes survive exactly once each.
    assert clamped[:14] == body[:14]
    assert clamped[14:] == body[14:]
