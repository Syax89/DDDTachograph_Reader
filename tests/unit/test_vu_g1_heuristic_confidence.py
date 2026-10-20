"""Heuristic Gen1 VU recovery must stay visibly low confidence and plausible.

Owner's rule for this decoder: *"Il decoding deve essere sempre prima come
normativa e quindi Ok, poi euristico e quindi bassa confidenza."* The
deterministic (Annex 1B) layout is authoritative and needs no warning; whatever
the emergency scans synthesize is inferred and must say so per record
(``confidence: low``, the convention used by ``core/parser/vu_dispatcher.py``).

Second rule: an inferred record may never be dated after the newest time the
file itself already established. ~73 % of arbitrary 4-byte values land inside
the plausible TimeReal window, so the TREP 03 byte-scan used to invent events
decades in the future on a truncated download (a VU records nothing after the
moment the download was taken).

All streams below are synthetic: CI carries no DDD/ sample.
"""
import struct

from core.decoders.vu_g1 import (
    _newest_known_time,
    _parse_trep_02_activities,
    _parse_trep_03_events_faults,
)

# Synthetic download/message time (not taken from any real corpus file); a G1
# VU download carries the equivalent value in TREP 01.
_DOWNLOAD_TIME = "2023-02-14T08:30:00+00:00"

_TS_2022_06 = 1_654_041_600          # 2022-06-01T00:00:00Z
_TS_2022_06_END = 1_654_045_200      # 2022-06-01T01:00:00Z
_TS_2060 = 2_840_000_000             # 2060-01-02T13:20:00Z
_TS_2063 = 2_960_000_000             # 2063-10-31T21:20:00Z


# ── TREP 03 byte-scan stream ────────────────────────────────────────────────

def _byte_scan_body(*records):
    """TREP 03 body that only the byte-scan can decode.

    data[0] = 0xFF makes the count-prefixed walk bail out (255 fault records
    never fit in the body), and the zero bytes after it stop the
    structured-heuristic attempt before it decodes anything, so the
    byte-by-byte scan is the only path left.
    """
    body = bytearray(b"\xff\x00\x00\x00\x00\x00\x00")
    for ev_type, ts1, ts2 in records:
        body += bytes([ev_type]) + struct.pack(">II", ts1, ts2)
    return bytes(body) + b"\x00" * 12


def test_byte_scan_never_invents_a_record_after_the_files_own_timeline():
    """A record dated 2060/2063 is a scanner false positive, not data."""
    body = _byte_scan_body(
        (0x03, _TS_2060, _TS_2063),
        (0x03, _TS_2022_06, _TS_2022_06_END),
    )
    # Horizon established by a record the file already carries (not metadata).
    results = {"events": [{"type_code": 0x04, "begin_time": "2023-03-10T09:00:00+00:00"}]}

    _parse_trep_03_events_faults(body, results)

    begins = [e["begin_time"] for e in results["events"]]
    assert begins == [
        "2023-03-10T09:00:00+00:00",     # pre-existing, untouched
        "2022-06-01T00:00:00+00:00",     # recovered: inside the horizon
    ]
    assert not any(b.startswith("2060") or b.startswith("2063") for b in begins)
    # The scan still ran, and is still declared as a heuristic.
    assert results["metadata"]["heuristic_fields"]["vu_events_faults_TREP03"] == ["events"]


def test_byte_scan_record_inside_the_horizon_is_still_recovered_as_low_confidence():
    """Recovery must not regress — only be labelled for what it is."""
    body = _byte_scan_body((0x03, _TS_2022_06, _TS_2022_06_END))
    results = {"metadata": {"current_datetime": _DOWNLOAD_TIME}}

    _parse_trep_03_events_faults(body, results)

    events = results["events"]
    assert [e["begin_time"] for e in events] == ["2022-06-01T00:00:00+00:00"]
    assert events[0]["end_time"] == "2022-06-01T01:00:00+00:00"
    assert events[0]["description"] == "Time overlap"
    assert events[0]["confidence"] == "low"


# ── record-boundary attempts stay labelled too ──────────────────────────────

def _record_boundary_body(record):
    """TREP 03 body the count-prefixed walk rejects: noOfVuFaults = 0xFF, so
    the record-boundary heuristic reads ``record`` at offset 1."""
    return b"\xff" + record


def test_record_boundary_fault_is_low_confidence():
    """The 82-byte record-boundary guess must carry confidence low."""
    fault = (bytes([0x05, 0x01])
             + struct.pack(">II", _TS_2022_06, _TS_2022_06_END)
             + b"\x00" * 72)
    results = {"metadata": {"current_datetime": _DOWNLOAD_TIME}}

    _parse_trep_03_events_faults(_record_boundary_body(fault), results)

    assert [f["fault_type"] for f in results["faults"]] == [0x05]
    assert results["faults"][0]["confidence"] == "low"


def test_record_boundary_event_is_low_confidence():
    """The 83-byte record-boundary guess must carry confidence low.

    A leading 0x00 byte (never a valid fault type) is the only way the scan
    falls through from the 82-byte fault layout to the 83-byte event layout.
    """
    event = (bytes([0x00, 0x01])
             + struct.pack(">II", _TS_2022_06, _TS_2022_06_END)
             + b"\x00" * 72
             + bytes([1]))
    results = {"metadata": {"current_datetime": _DOWNLOAD_TIME}}

    _parse_trep_03_events_faults(_record_boundary_body(event), results)

    assert [e["type_code"] for e in results["events"]] == [0x00]
    assert results["events"][0]["confidence"] == "low"


# ── TREP 02 timestamp-scan stream ───────────────────────────────────────────

def _trep02_timestamp_scan_body(daily_ts):
    """Minimal TREP 02 body that only the timestamp scan can read."""
    payload = bytearray()
    payload += struct.pack(">I", 1_700_000_000)  # header timestamp (valid)
    payload += b"\x00\x00\x00"                   # rest of the binary header
    payload += b"\xff\xff"                       # n_iw -> structured parser bails
    payload += b"\x00"
    payload += b"SMITH".ljust(36, b" ")          # surname
    payload += b"\x01"                           # codepage
    payload += b"JOHN".ljust(36, b" ")           # first names
    payload += b"\x01"                           # codepage
    payload += struct.pack(">I", daily_ts)       # daily timestamp
    payload += b"\x00\x00\x01"                   # odometer at midnight
    payload += b"\x01"                           # card inserted
    payload += struct.pack(">H", 2)              # noOfActivityChanges
    payload += struct.pack(">HH", 60, 0)         # REST at 01:00
    payload += struct.pack(">HH", 0, 0)          # (0, 0) terminator
    payload += b"\x00" * 8
    return bytes(payload)


def test_trep02_timestamp_scan_records_are_low_confidence():
    """The scanned day is inferred: it must carry confidence low."""
    results = {}
    _parse_trep_02_activities(_trep02_timestamp_scan_body(1_700_000_001), results)

    records = results["activities"]
    assert len(records) == 1
    assert records[0]["confidence"] == "low"
    # The driver block of the same scan is inferred too (unchanged behaviour).
    assert results["metadata"]["heuristic_fields"]["vu_activities_TREP02"] == [
        "activities", "inserted_drivers"]


def test_trep02_timestamp_scan_day_after_the_download_is_dropped():
    """A day the file cannot have recorded (after its own download) is dropped."""
    body = _trep02_timestamp_scan_body(1_700_000_001)  # 2023-11-14

    without_horizon = {}
    _parse_trep_02_activities(body, without_horizon)
    assert len(without_horizon["activities"]) == 1

    with_horizon = {"metadata": {"current_datetime": _DOWNLOAD_TIME}}  # file's own download time
    _parse_trep_02_activities(body, with_horizon)
    assert with_horizon.get("activities", []) == []


# ── the deterministic path stays unlabelled ─────────────────────────────────

def _trep03_deterministic_body():
    """Count-prefixed TREP 03 body the structured walk accepts."""
    fault = bytearray(82)
    fault[0] = 0x05                     # faultType
    fault[1] = 0x01                     # faultPurpose
    struct.pack_into(">I", fault, 2, 1_600_000_000)
    struct.pack_into(">I", fault, 6, 1_600_000_100)
    return (bytes([1]) + bytes(fault)   # noOfVuFaults + record
            + bytes([0])                # noOfVuEvents
            + b"\x00" * 9               # VuOverSpeedingControlData
            + bytes([0])                # noOfVuOverSpeedingEvents
            + bytes([0]))               # noOfVuTimeAdjustments


def test_deterministic_records_carry_no_confidence_field():
    """Rule-of-spec output is 'Ok': no low-confidence marker, no heuristic note."""
    results = {}
    _parse_trep_03_events_faults(_trep03_deterministic_body(), results)

    faults = results["faults"]
    assert [f["fault_type"] for f in faults] == [0x05]
    assert "confidence" not in faults[0]
    assert "heuristic_fields" not in results.get("metadata", {})


# ── the horizon helper itself ───────────────────────────────────────────────

def test_newest_known_time_ignores_garbage_and_empty_results():
    assert _newest_known_time({}) is None
    assert _newest_known_time({"metadata": {"current_datetime": "N/A"}}) is None
    assert _newest_known_time({"metadata": {"current_datetime": "not a date"}}) is None
    assert _newest_known_time({"activities": [{"timestamp": "1999-01-01T00:00:00+00:00"}]}) is None
    assert _newest_known_time({"activities": ["not a dict"]}) is None


def test_newest_known_time_returns_the_maximum_over_every_section():
    results = {
        "metadata": {"current_datetime": _DOWNLOAD_TIME},
        "events": [{"begin_time": "2023-03-10T09:00:00+00:00"},
                   {"end_time": "2023-03-11T00:00:00+00:00"}],
        "faults": [{"begin_time": "2024-02-25T00:00:00+00:00"}],
        "places": [{"timestamp": "2024-03-01T00:00:00+00:00"}],
        "overspeeding_events": [{"begin": "2023-12-31T00:00:00+00:00",
                                 "end": "N/A"}],
    }
    assert _newest_known_time(results) == 1_709_251_200  # 2024-03-01T00:00:00Z


def test_newest_known_time_reads_control_download_insertion_and_adjustment_times():
    """The horizon must also see these four sources (all synthetic values)."""
    assert _newest_known_time(
        {"control_activities": [{"control_time": "2023-03-01T00:00:00+00:00"}]}
    ) == 1_677_628_800
    assert _newest_known_time(
        {"download_activities": [{"downloading_time": "2023-03-02T00:00:00+00:00"}]}
    ) == 1_677_715_200
    assert _newest_known_time(
        {"card_iw_records": [{"insertion_time": "2023-03-03T00:00:00+00:00"}]}
    ) == 1_677_801_600
    # A backward clock adjustment: the pre-adjustment time is the later bound.
    assert _newest_known_time(
        {"time_adjustments": [{"old_time": "2023-03-04T00:00:00+00:00",
                               "new_time": "2022-12-15T04:37:00+00:00"}]}
    ) == 1_677_888_000
    # A forward clock adjustment: the post-adjustment time wins.
    assert _newest_known_time(
        {"time_adjustments": [{"old_time": "2022-12-15T04:37:00+00:00",
                               "new_time": "2023-03-05T00:00:00+00:00"}]}
    ) == 1_677_974_400
