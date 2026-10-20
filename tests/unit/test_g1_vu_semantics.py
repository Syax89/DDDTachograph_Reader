"""Generation 1 VU TREP 01-05: source-grounded field semantics.

Each assertion below traces to the readable generation-1 text (Annex 1B /
Annex 1C Appendix 1), never to the generation-2 wording:

* §2.28 ``CardSlotsStatus`` — one octet ``'ccccdddd'B`` with five assigned card
  types; the published short word stays, the typed nibble travels model-only.
* §2.44 ``ControlType`` — ``'cvpdxxxx'B`` in generation 1 (``xxxx`` not used), so
  bit 0x08 is **not** the generation-2 roadside-calibration check.
* §2.70 generation-1 EventFaultType — from the consolidated Annex 1C list: '0A'H
  is *Vehicle Motion Conflict*, and everything generation 2 added ('0B'H time
  conflict, GNSS/RCM/ITS groups) is RFU.
* §2.51 ``EntryTypeDailyWorkPeriod`` — 0..5, so place types 4/5 ("assumed by
  VU") are legal generation-1 entries and must not be dropped.
* §2.154 ``SpecificConditionType`` — '03'H is a single Ferry/Train crossing and
  '04'H is RFU in generation 1.
* §2.118 ``VuCalibrationRecord`` — the *activation* calibration ("parameters
  known at VU activation") legally carries an empty VIN and ``l = 0``; the old
  acceptance gate deleted it from the download.
* §2.56 ``ExtendedSerialNumber`` — the VU and sensor serial numbers are structured
  (serial/monthYear BCD/type/manufacturerCode), not opaque hex.

Every value below is synthetic.
"""
import struct

from core.decoders.vu_g1 import (
    _parse_trep_02_g1_structured, _parse_trep_03_structured,
    _parse_trep_04_speed, _parse_trep_05_technical, parse_g1_vu_overview)
from core.utils.event_codes import EVENT_FAULT_VERSION_G1
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME
SIG = b"\x00" * 128


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"},
            "activities": [], "events": [], "faults": [],
            "inserted_drivers": [], "card_iw_records": [], "places": [],
            "specific_conditions": [], "overspeeding_events": [],
            "overspeeding_control": [], "time_adjustments": [],
            "calibrations": [], "workshops": [], "calibration_vins": set(),
            "vu_info": {}, "vu_overview": {}, "company_locks": [],
            "control_activities": [], "company_info": {}, "speed_blocks": []}


# ── TREP 01 ─────────────────────────────────────────────────────────────────

def _overview_body(slots=0x41, n_locks=1, n_controls=1,
                   lock_in=TIME, control_time=TIME + 60):
    body = bytearray()
    body += b"\x00" * 194 + b"\x00" * 194                     # two certificates
    body += S.VIN.encode("ascii")                              # VIN (17)
    body += bytes([0x1A]) + S.coded_string(S.PLATE, code_page=1, length=14)
    body += struct.pack(">III", TIME, TIME - 86_400, TIME)     # current/min/max
    body += bytes([slots])
    body += struct.pack(">I", TIME) + S.full_card_number() + S.coded_string(
        "SYNTH DOWNLOADER", code_page=1, length=36)
    body += bytes([n_locks])
    for _ in range(n_locks):
        body += (struct.pack(">II", lock_in, lock_in + 3_600)
                 + S.coded_string("SYNTH COMPANY", code_page=1, length=36)
                 + S.coded_string("SYNTH ROAD 2", code_page=1, length=36)
                 + S.full_card_number(card_type=0x04))
    body += bytes([n_controls])
    for _ in range(n_controls):
        body += (bytes([0xE8]) + struct.pack(">I", control_time)
                 + S.full_card_number(card_type=0x03)
                 + struct.pack(">II", TIME - 86_400, TIME))
    return bytes(body)


def test_g1_card_slots_are_typed_per_nibble():
    results = _results()
    parse_g1_vu_overview(_overview_body(slots=0x41), results)
    slots = results["vu_overview"]["card_slot_status"]
    assert slots["raw"] == "0x41"
    assert slots["driver_slot"] == "occupied"
    assert slots["codriver_slot"] == "occupied"
    # Complete typing is model-only.
    assert slots["driver_slot_code"] == 0x01
    assert slots["driver_slot_type"] == "driver"
    assert slots["codriver_slot_type"] == "company"
    assert slots["driver_slot_status"] == "assigned"


def test_g1_unassigned_slot_nibble_is_reported_as_unassigned():
    results = _results()
    parse_g1_vu_overview(_overview_body(slots=0x0A), results)
    slots = results["vu_overview"]["card_slot_status"]
    assert slots["driver_slot"] == "reserved"
    assert slots["driver_slot_status"] == "unassigned"
    assert slots["driver_slot_type"] == "unassigned"
    assert slots["codriver_slot"] == "empty"          # nibble 0000: no card


def test_g1_control_type_has_no_roadside_calibration_bit():
    results = _results()
    parse_g1_vu_overview(_overview_body(), results)
    control = results["control_activities"][0]
    # 0xE8 = card + VU downloaded + printing + bit 0x08, which generation 1
    # leaves "not used": the label must not claim a roadside calibration check.
    assert "Roadside calibration" not in control["control_type_label"]
    assert "Printing" in control["control_type_label"]
    assert control["control_type_bits"] == ["Card downloaded", "VU downloaded",
                                           "Printing"]


def test_g1_lock_records_are_kept_even_with_an_out_of_range_time():
    """A VU clock outside 2000..2100 is corrupt data, not a reason to delete the
    company-lock record: the raw values and a status are preferable."""
    results = _results()
    parse_g1_vu_overview(_overview_body(lock_in=0xFF000000), results)
    locks = results["company_locks"]
    assert len(locks) == 1
    assert locks[0]["lock_in_raw"] == 0xFF000000
    assert locks[0]["lock_in_time"] is None
    assert locks[0]["time_status"] == "invalid"


def test_g1_control_records_are_kept_even_with_an_out_of_range_time():
    results = _results()
    parse_g1_vu_overview(_overview_body(control_time=0xFF000000), results)
    controls = results["control_activities"]
    assert len(controls) == 1
    assert controls[0]["control_time"] is None
    assert controls[0]["control_time_raw"] == 0xFF000000
    assert controls[0]["time_status"] == "invalid"
    assert "Roadside calibration" not in controls[0]["control_type_label"]


# ── TREP 02 ─────────────────────────────────────────────────────────────────

def _trep02_body(entry_types=(0x04, 0x05), n_changes=2, conditions=(0x03, 0x04)):
    body = bytearray()
    body += struct.pack(">I", TIME) + (654_321).to_bytes(3, "big")
    body += struct.pack(">H", 1)
    body += (S.coded_string("SYNTH", code_page=1, length=36)
             + S.coded_string("DRIVER", code_page=1, length=36)
             + S.full_card_number()
             + struct.pack(">I", TIME + 60)
             + struct.pack(">I", TIME + 120) + (1000).to_bytes(3, "big")
             + bytes([0x01])
             + struct.pack(">I", TIME + 7200) + (1200).to_bytes(3, "big")
             + bytes([0x1A]) + S.coded_string(S.PLATE, code_page=1, length=14)
             + struct.pack(">I", TIME + 60)
             + bytes([0x00]))
    body += struct.pack(">H", n_changes)
    body += struct.pack(">H", 0x10F3) * n_changes
    body += bytes([len(entry_types)])
    for code in entry_types:
        body += (S.full_card_number() + struct.pack(">I", TIME + 300)
                 + bytes([code, 0x1A, 0x07]) + (2000).to_bytes(3, "big"))
    body += struct.pack(">H", len(conditions))
    for code in conditions:
        body += struct.pack(">I", TIME + 400) + bytes([code])
    return bytes(body)


def test_g1_place_entry_types_4_and_5_are_legal():
    results = _results()
    assert _parse_trep_02_g1_structured(_trep02_body(), results) is True
    codes = [p["type_code"] for p in results["places"]]
    assert codes == [0x04, 0x05]
    assert results["places"][0]["entry_type"] == "START"
    assert results["places"][0]["entry_type_description"] == "Begin assumed by VU"
    assert results["places"][1]["entry_type_description"] == "End assumed by VU"


def test_g1_specific_condition_03_is_ferry_crossing_and_04_is_kept_unknown():
    results = _results()
    _parse_trep_02_g1_structured(_trep02_body(conditions=(0x03, 0x04)), results)
    by_code = {c["type_code"]: c for c in results["specific_conditions"]}
    assert by_code[0x03]["condition"] == "Ferry/Train crossing"
    assert by_code[0x03]["condition_status"] == "assigned"
    # 0x04 is RFU in generation 1: the record is retained, never labelled with
    # the generation-2 "Ferry/Train End" meaning.
    assert by_code[0x04]["condition"] == "0x04"
    assert by_code[0x04]["condition_status"] == "not assigned"


def test_g1_zero_change_day_is_emitted():
    results = _results()
    assert _parse_trep_02_g1_structured(_trep02_body(n_changes=0), results) is True
    assert len(results["activities"]) == 1
    assert results["activities"][0]["changes"] == []
    assert results["activities"][0]["changes_count"] == 0
    # the day keeps its deterministic provenance even when a scan re-reads it
    assert results["activities"][0]["source"] == "vu_trep02"


def test_g1_iw_records_keep_their_day_association():
    results = _results()
    _parse_trep_02_g1_structured(_trep02_body(), results)
    iw = results["card_iw_records"][0]
    assert iw["day_date"] == "05/04/2024"          # synthetic BASE_TIME
    # Generation 1 PreviousVehicleInfo is 19 bytes: no vuGeneration byte exists
    # (Annex 1B §2.85 vs Annex 1C §2.118).
    assert "vu_generation" not in iw["previous_vehicle"]
    assert iw["record_day"] == iw["day_date"]


# ── TREP 03 ─────────────────────────────────────────────────────────────────

def _event_record(event_type=0x0A):
    return (bytes([event_type, 0x00]) + struct.pack(">II", TIME, TIME + 60)
            + S.full_card_number() + b"\x00" * 18 * 0
            + S.full_card_number() + S.full_card_number()
            + S.full_card_number() + bytes([0x01]))


def _fault_record(fault_type=0x31):
    return bytes([fault_type, 0x00]) + struct.pack(">II", TIME, TIME + 60) + \
        S.full_card_number() + S.full_card_number() + S.full_card_number() + \
        S.full_card_number()


def _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(0,), n_adj=(99,)):
    body = bytearray()
    body += bytes([1]) + _fault_record(fault_type)
    body += bytes([1]) + _event_record(event_type)
    body += struct.pack(">II", TIME, TIME) + bytes([0x02])       # overspeed ctrl
    body += bytes([len(n_over)])
    for size in n_over:
        rec = (bytes([0x07, 0x00]) + struct.pack(">II", TIME, TIME + 30)
               + bytes([0x5A, 0x50]) + S.full_card_number() + bytes([0x01]))
        body += (rec + b"\x00" * size)[:31]
    body += bytes([len(n_adj)])
    for size in n_adj:
        rec = (struct.pack(">II", TIME, TIME + 30)
               + S.coded_string("SYNTH WORKSHOP", code_page=1, length=36)
               + S.coded_string("SYNTH STREET 3", code_page=1, length=36)
               + S.full_card_number(card_type=0x02))
        body += (rec + b"\x00" * size)[:size]
    return bytes(body)


def test_g1_event_0a_is_vehicle_motion_conflict_not_rfu():
    results = _results()
    assert _parse_trep_03_structured(_trep03_body(event_type=0x0A), results) is True
    event = results["events"][0]
    assert event["description"] == "Vehicle motion conflict"
    assert event["event_fault_version"] == EVENT_FAULT_VERSION_G1
    assert event["type_status"] == "assigned"


def test_g1_generation_2_only_code_is_rfu_in_a_generation_1_section():
    results = _results()
    _parse_trep_03_structured(_trep03_body(event_type=0x0B), results)
    event = results["events"][0]
    # 0x0B is the GNSS/VU time conflict only from generation 2 on.
    assert event["description"] == "Reserved for future use (0x0B)"
    assert event["type_status"] == "reserved"


def test_g1_generation_2_fault_range_is_reserved():
    results = _results()
    _parse_trep_03_structured(_trep03_body(fault_type=0x37), results)
    fault = results["faults"][0]
    assert fault["description"] == "Reserved for future use (0x37)"


def test_g1_empty_overspeed_and_time_adjustment_variants_are_explicit():
    results = _results()
    assert _parse_trep_03_structured(_trep03_body(n_over=(), n_adj=()),
                                     results) is True
    assert results["overspeeding_events"] == []
    assert results["time_adjustments"] == []


def test_g1_short_time_adjustment_is_not_dropped_silently():
    results = _results()
    _parse_trep_03_structured(_trep03_body(n_adj=(40,)), results)
    records = results["time_adjustments"]
    assert len(records) == 1
    assert records[0]["record_complete"] is False
    assert records[0]["record_bytes"] == 40
    assert records[0]["raw_tail_hex"]


# ── TREP 04 ─────────────────────────────────────────────────────────────────

def test_g1_speed_blocks_keep_every_sample_including_ff_fill():
    body = struct.pack(">H", 2)
    body += struct.pack(">I", TIME) + bytes(range(60))
    body += struct.pack(">I", TIME + 60) + bytes([0xFF] * 60)
    results = _results()
    _parse_trep_04_speed(body, results)
    runs = results["speed_blocks"]
    assert len(runs) == 1
    run = runs[0]
    # The published row is an *application* aggregation of consecutive
    # one-minute blocks; the normative blocks travel underneath it.
    assert run["aggregation"].startswith("application")
    assert run["minutes"] == 2
    assert len(run["_chart_speeds_kmh"]) == 120
    blocks = run["blocks"]
    assert [b["record_bytes"] for b in blocks] == [64, 64]
    assert blocks[0]["samples"] == 60
    assert blocks[0]["_chart_speeds_kmh"] == list(range(60))
    # 0xFF is the "no information" fill, not a 255 km/h sample.
    assert blocks[1]["samples"] == 0
    assert blocks[1]["_chart_speeds_kmh"] == [None] * 60


def test_g1_speed_block_with_an_unusable_time_keeps_its_samples():
    body = struct.pack(">H", 1) + struct.pack(">I", 0xFF000000) + bytes([50] * 60)
    results = _results()
    _parse_trep_04_speed(body, results)
    assert len(results["speed_blocks"]) == 1
    run = results["speed_blocks"][0]
    assert run["time_status"] == "invalid"
    assert run["blocks"][0]["samples"] == 60


# ── TREP 05 ─────────────────────────────────────────────────────────────────

def _g1_calibration(purpose=0x04, vin=S.VIN, l_const=0x0C80, old_time=TIME):
    body = (bytes([purpose])
            + S.coded_string("SYNTH WORKSHOP", code_page=1, length=36)
            + S.coded_string("SYNTH STREET 9", code_page=1, length=36)
            + S.full_card_number(card_type=0x02)
            + struct.pack(">I", TIME + 86_400)
            + vin.encode("ascii")
            + bytes([0x1A]) + S.coded_string(S.PLATE, code_page=1, length=14)
            + struct.pack(">HHH", 0x1F40, 0x2710, l_const)
            + S.coded_string("315/70R22.5", code_page=1, length=15)
            + bytes([0x5A])
            + (100_000).to_bytes(3, "big") + (100_123).to_bytes(3, "big")
            + struct.pack(">III", old_time, old_time + 30, old_time + 2_592_000))
    assert len(body) == 167, len(body)
    return body


def _trep05_body(calibrations):
    body = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
            + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
            + b"PART0001        " + S.extended_serial(0x0000A001)
            + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
            + b"APPROVAL" + S.extended_serial(0x0000A002)
            + b"SENSORAP" + struct.pack(">I", TIME + 60))
    body += bytes([len(calibrations)]) + b"".join(calibrations)
    return body


def test_g1_activation_calibration_with_empty_vin_and_l_zero_is_kept():
    activation = _g1_calibration(purpose=0x01, vin=" " * 17, l_const=0)
    results = _results()
    _parse_trep_05_technical(_trep05_body([activation]), results)
    cals = results["calibrations"]
    assert len(cals) == 1, cals
    assert cals[0]["purpose_code"] == 0x01
    assert cals[0]["vin"] == ""
    assert cals[0]["vin_status"] == "empty (activation parameters)"
    assert cals[0]["l_tyre_circumference"] == 0
    assert cals[0]["field_status"]["l_tyre_circumference"] == (
        "zero (activation, parameters known at VU activation)")
    assert cals[0]["decode_path"].startswith("normative")


def test_g1_empty_vu_and_sensor_serials_are_decoded_as_structures():
    results = _results()
    _parse_trep_05_technical(_trep05_body([_g1_calibration()]), results)
    info = results["vu_info"]
    # one row per serial: the hex row carries the compact decoded reading too
    assert info["serial_number"].startswith(S.extended_serial(0x0000A001).hex().upper())
    assert "40961 \u00b7 " in info["serial_number"]
    assert info["vu_serial_decoded"]["serial_number"] == 0x0000A001
    assert "40962 \u00b7 " in info["sensor_serial_number"]
    assert info["sensor_serial_extended"]["serial_number"] == 0x0000A002


def test_g1_calibration_times_keep_hour_and_minute():
    results = _results()
    _parse_trep_05_technical(_trep05_body([_g1_calibration()]), results)
    cal = results["calibrations"][0]
    # One timestamp column per value, carrying date AND time of day (the table
    # renders it in the same format as every other timestamp column).
    assert "T" in cal["old_time"]
    assert "T" in cal["new_time"]
    assert "T" in cal["next_calibration_date"]
    assert cal["old_time_iso"] == cal["old_time"]


def test_g1_stored_fault_with_an_unusable_time_is_retained():
    """A stored fault is not deleted because its clock value is corrupt."""
    body = bytearray(_trep03_body())
    struct.pack_into(">I", body, 1 + 2, 0xFF000000)     # fault begin, first record
    results = _results()
    assert _parse_trep_03_structured(bytes(body), results) is True
    fault = results["faults"][0]
    assert fault["begin_time"] is None
    assert fault["begin_time_raw"] == 0xFF000000
    assert fault["time_status"] == "invalid"


# ── F2: no value-based existence gate on the structured TREP 03 path ───────

def test_trep03_all_corrupt_clocks_keeps_the_records_and_skips_the_scan():
    body = _trep03_body(event_type=0x0A, fault_type=0x31)
    body = bytearray(body)
    struct.pack_into(">I", body, 1 + 2, 0)          # fault begin = 0
    struct.pack_into(">I", body, 1 + 6, 0)          # fault end = 0
    struct.pack_into(">I", body, 84 + 2, 0)         # event begin = 0
    struct.pack_into(">I", body, 84 + 6, 0)         # event end = 0
    results = _results()
    assert _parse_trep_03_structured(bytes(body), results) is True
    assert len(results["faults"]) == 1
    assert len(results["events"]) == 1
    assert results["faults"][0]["time_status"] == "invalid"
    assert results["events"][0]["time_status"] == "invalid"
    assert results["events"][0]["begin_time"] is None
    # nothing was invented: an event keeps its own type, not a scan guess
    assert results["events"][0]["type_code"] == 0x0A


def test_trep03_mixed_good_and_bad_clocks_keeps_both():
    body = bytearray(_trep03_body(event_type=0x0A, fault_type=0x31))
    struct.pack_into(">I", body, 84 + 2, 0)         # only the event clock is bad
    results = _results()
    assert _parse_trep_03_structured(bytes(body), results) is True
    assert [f["time_status"] for f in results["faults"]] == ["valid"]
    assert [e["time_status"] for e in results["events"]] == ["invalid"]


def test_trep03_zero_counts_emit_nothing_and_are_still_structural():
    results = _results()
    body = bytes([0, 0]) + struct.pack(">II", TIME, TIME) + bytes([0, 0, 0])
    assert _parse_trep_03_structured(body, results) is True
    assert results["faults"] == [] and results["events"] == []
    # the control record is emitted even with no data (DDP_031 default value)
    assert len(results["overspeeding_control"]) == 1


def test_trep03_overspeed_records_with_an_unusable_clock_are_kept():
    body = bytearray(_trep03_body(n_over=(31,), n_adj=()))
    # the overspeed record starts after the 9-byte control block
    start = len(body) - 1 - 31 - 1 + 1          # count byte + record
    struct.pack_into(">I", body, start + 2, 5)  # begin = 5 (outside the calendar)
    results = _results()
    assert _parse_trep_03_structured(bytes(body), results) is True
    rec = results["overspeeding_events"][0]
    assert rec["begin"] is None
    assert rec["begin_raw"] == 5
    assert rec["time_status"] == "invalid"


def test_trep03_truncated_body_still_fails_structurally():
    """A count whose records do not fit the bytes is a decode failure (fallback
    with a reason), never a silently shortened list."""
    results = _results()
    body = bytes([2]) + _trep03_body()[1:1 + 82]      # declares 2 faults, holds 1
    assert _parse_trep_03_structured(body, results) is False
    assert results.get("faults", []) == []


# ── F5: a stored record's identity is its position, not its fields ─────────

def test_two_locks_with_corrupt_clocks_and_the_same_card_are_both_kept():
    body = bytearray(_overview_body(n_locks=2, n_controls=0))
    # lock area starts after the 433-byte prefix + 58-byte download activity + the
    # lock count byte; two records with clocks 0/1 and the same card+company.
    base = 433 + 58 + 1
    body[base:base + 8] = struct.pack(">II", 0, 1)
    body[base + 98:base + 98 + 8] = struct.pack(">II", 1, 0)
    results = _results()
    parse_g1_vu_overview(bytes(body), results)
    assert len(results["company_locks"]) == 2


def test_three_controls_with_corrupt_clocks_are_all_kept():
    body = _overview_body(n_locks=0, n_controls=3)
    results = _results()
    parse_g1_vu_overview(body, results)
    # the fixture writes the same control three times: three stored records
    assert len(results["control_activities"]) == 3


def test_two_places_in_the_same_second_with_different_cards_are_kept():
    body = bytearray(_trep02_body(entry_types=(0x00, 0x00)))
    # same timestamp for both place records, different card number
    places_start = 7 + 2 + 129 + 2 + 2 * 2 + 1
    struct.pack_into(">I", body, places_start + 18, TIME + 300)
    struct.pack_into(">I", body, places_start + 28 + 18, TIME + 300)
    body[places_start + 30:places_start + 46] = b"S" + b"1" * 15
    results = _results()
    assert _parse_trep_02_g1_structured(bytes(body), results) is True
    assert len(results["places"]) == 2


def test_two_calibrations_with_the_same_fields_are_both_kept():
    same = _g1_calibration(purpose=0x04)
    results = _results()
    _parse_trep_05_technical(_trep05_body([same, same]), results)
    assert len(results["calibrations"]) == 2


def test_revisit_of_the_same_body_is_still_emitted_once():
    """Dedup survives for a re-read body: identity is the message offset."""
    body = _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(), n_adj=())
    results = _results()
    assert _parse_trep_03_structured(body, results, message_offset=4096) is True
    assert _parse_trep_03_structured(body, results, message_offset=4096) is True
    assert len(results["events"]) == 1
    assert len(results["faults"]) == 1
    # A different *body* that decodes to the same values is the same stored
    # record re-read (the fallback scan re-reads a byte range the walk already
    # decoded), so it is still emitted once ...
    assert _parse_trep_03_structured(body, results, message_offset=8192) is True
    assert len(results["events"]) == 1
    # ... while a body with different values adds its own record.
    other = _trep03_body(event_type=0x02, fault_type=0x31, n_over=(), n_adj=())
    assert _parse_trep_03_structured(other, results, message_offset=8192) is True
    assert [e["type_code"] for e in results["events"]] == [0x0A, 0x02]


# ── F6/F7: structure, not values, decides what is decodable ────────────────

def test_blank_vin_still_decodes_the_whole_overview():
    body = _overview_body()
    body = bytearray(body)
    body[388:405] = b" " * 17
    results = _results()
    parse_g1_vu_overview(bytes(body), results)
    assert results["vehicle"]["vin"] == "N/A"
    assert results["vehicle"]["plate"] == S.PLATE
    assert results["metadata"]["current_datetime"]
    assert len(results["company_locks"]) == 1
    assert len(results["control_activities"]) == 1
    assert results["metadata"].get("heuristic_fields") is None


def test_unusable_overview_clock_is_withheld_not_the_overview():
    body = bytearray(_overview_body())
    struct.pack_into(">I", body, 420, 0xFF000000)
    results = _results()
    parse_g1_vu_overview(bytes(body), results)
    assert results["metadata"]["current_datetime"] is None
    assert results["vu_overview"]["current_date_time_raw"] == 0xFF000000
    assert len(results["company_locks"]) == 1


def test_a_day_with_more_than_one_hundred_iw_records_is_decoded():
    base = _trep02_body()
    iw_start = 7 + 2
    iw = base[iw_start:iw_start + 129]
    rest = base[iw_start + 129:]
    body = base[:7] + struct.pack(">H", 101) + iw * 101 + rest
    results = _results()
    assert _parse_trep_02_g1_structured(body, results) is True
    assert len(results["card_iw_records"]) == 101
    assert results["metadata"].get("heuristic_fields") is None
