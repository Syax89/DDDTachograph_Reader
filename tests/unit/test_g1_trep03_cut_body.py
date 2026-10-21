"""A TREP 03 body cut inside its count framing keeps the records it really holds.

A message cut by the end of the file is decoded with ``partial=True``: every
fixed-size record before the cut is complete and must be published, and the cut
itself must stay visible (an integrity finding — the file is partial, not clean).

Two cuts are pinned here, both at a count byte the walk would read next:

* before the ``VuTimeAdjustmentData`` count — the LAST array of a TREP 03 body
  (Annex 1B §2.2.6.3 / App. 1 §2.120), so the body carries a complete fault, event,
  ``VuOverSpeedingControlData`` block and overspeeding record and nothing after them;
* on the overspeeding array's count byte (§2.119), right after the 9-byte control
  block — the body carries complete faults, events and a complete control block.

Returning early without emitting them lost every record of the message; reading
the missing count first rejected the whole message instead.

Every value below is synthetic.
"""
import struct

import pytest

from core.decoders.vu_g1 import _parse_trep_03_structured
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


def _results():
    return {"metadata": {}, "events": [], "faults": [],
            "overspeeding_events": [], "overspeeding_control": [],
            "time_adjustments": []}


def _fault_record(event_type=0x13):
    """VuFaultRecord (82 bytes, Appendix 1 §2.87) with synthetic values."""
    rec = bytearray(82)
    rec[0] = event_type
    rec[1] = 0                                          # recordPurpose
    struct.pack_into(">I", rec, 2, TIME)                # beginTime
    struct.pack_into(">I", rec, 6, TIME + 3600)         # endTime
    return bytes(rec)


def _event_record(event_type=0x03):
    """VuEventRecord (83 bytes, Appendix 1 §2.132) with synthetic values."""
    rec = bytearray(83)
    rec[0] = event_type
    rec[1] = 1
    struct.pack_into(">I", rec, 2, TIME)
    struct.pack_into(">I", rec, 6, TIME + 600)
    return bytes(rec)


def _overspeed_record():
    """VuOverSpeedingEventRecord (31 bytes, Appendix 1 §2.119)."""
    rec = bytearray(31)
    rec[0] = 0x0F
    rec[1] = 1
    struct.pack_into(">I", rec, 2, TIME)
    struct.pack_into(">I", rec, 6, TIME + 300)
    rec[10] = 95                                        # maxSpeed
    rec[11] = 80                                        # averageSpeed
    return bytes(rec)


def _body():
    """faults + events + control block + overspeeding, cut before the adj count."""
    return (bytes([1]) + _fault_record()
            + bytes([1]) + _event_record()
            + struct.pack(">IIB", TIME, TIME - 86_400, 1)   # VuOverSpeedingControlData
            + bytes([1]) + _overspeed_record())


def _adj_findings(results):
    return [f for f in results["metadata"].get("vu_integrity") or []
            if f.get("trep") == "0x03" and f.get("status") == "array_truncated"]


def test_cut_body_publishes_every_complete_record_before_the_cut():
    results = _results()
    assert _parse_trep_03_structured(_body(), results, partial=True) is True
    assert len(results["faults"]) == 1
    assert len(results["events"]) == 1
    # The 9-byte control block was read before the cut: it is a stored record
    # ("default value if no data", DDP_031) and travels with its overspeeding
    # record, not dropped with the array that never arrived.
    assert len(results["overspeeding_control"]) == 1
    assert results["overspeeding_control"][0]["number_of_overspeed"] == 1
    assert len(results["overspeeding_events"]) == 1
    assert results["overspeeding_events"][0]["max_speed_kmh"] == 95
    # The array that was cut is empty — nothing is invented.
    assert results["time_adjustments"] == []


def test_cut_body_reports_the_truncation_as_an_integrity_finding():
    results = _results()
    _parse_trep_03_structured(_body(), results, partial=True)
    findings = _adj_findings(results)
    assert len(findings) == 1
    assert findings[0]["missing_bytes"] >= 1
    assert "time-adjustment" in findings[0]["detail"].lower()


def test_an_intact_body_reports_no_truncation():
    results = _results()
    body = _body() + bytes([0])            # the adjustment count byte arrived
    assert _parse_trep_03_structured(body, results, partial=True) is True
    assert _adj_findings(results) == []


@pytest.mark.parametrize("missing_tail", [0, 9, 97])
def test_the_finding_never_duplicates_when_the_body_is_read_twice(missing_tail):
    """The walk may re-read a clamped body: one cut is one finding."""
    results = _results()
    body = _body() + bytes([1]) + b"\x00" * missing_tail
    _parse_trep_03_structured(body, results, partial=True)
    _parse_trep_03_structured(body, results, partial=True)
    assert len(_adj_findings(results)) <= 1


# ── Cut on the overspeeding count byte ───────────────────────────────────────
#
# The 9-byte ``VuOverSpeedingControlData`` block sits between the event array and
# the overspeeding array's own count byte (§2.119 follows §2.120). A body that
# ends exactly on that count byte therefore still holds complete faults, events
# and a complete control block; reading the count first turned the whole message
# into a rejected one and dropped every record it carried.

def _body_cut_on_overspeed_count():
    """faults + events + control block, ending on the overspeeding count byte."""
    return (bytes([1]) + _fault_record()
            + bytes([1]) + _event_record()
            + struct.pack(">IIB", TIME, TIME - 86_400, 1))


def _overspeed_findings(results):
    return [f for f in results["metadata"].get("vu_integrity") or []
            if f.get("trep") == "0x03"
            and "overspeeding" in str(f.get("detail", "")).lower()]


def test_cut_on_the_overspeeding_count_publishes_faults_events_and_control():
    results = _results()
    body = _body_cut_on_overspeed_count()
    assert _parse_trep_03_structured(body, results, partial=True) is True
    assert len(results["faults"]) == 1
    assert len(results["events"]) == 1
    assert len(results["overspeeding_control"]) == 1
    assert results["overspeeding_control"][0]["number_of_overspeed"] == 1
    # Nothing after the cut is invented.
    assert results["overspeeding_events"] == []
    assert results["time_adjustments"] == []


def test_cut_on_the_overspeeding_count_is_reported_as_a_finding():
    results = _results()
    _parse_trep_03_structured(_body_cut_on_overspeed_count(), results, partial=True)
    findings = _overspeed_findings(results)
    assert len(findings) == 1
    assert findings[0]["status"] == "array_truncated"
    assert findings[0]["missing_bytes"] == 1


def test_the_overspeeding_count_guard_is_for_partial_bodies_only():
    """A complete message that ends on the count byte stays rejected."""
    results = _results()
    assert _parse_trep_03_structured(
        _body_cut_on_overspeed_count(), results, partial=False) is False
    assert results["faults"] == []
    assert results["events"] == []
