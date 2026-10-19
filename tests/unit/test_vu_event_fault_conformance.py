"""Gen2 VuEventRecord / VuFaultRecord decoding and conformance verdict.

Both record types are defined in full by Reg. (EU) 2016/799, Annex 1C,
Appendix 1: §2.198 VuEventRecord (91 bytes in generation 2) and §2.201
VuFaultRecord (90 bytes). Only manufacturerSpecificEventFaultData (§2.95,
manufacturerCode + 3-byte error code) is left to the manufacturer.

Every decoded record therefore carries an explicit, machine-readable verdict:
``normative: True`` / ``confidence: "high"`` when its fields match the standard,
``normative: False`` / ``confidence: "low"`` with a ``conformance_reason``
otherwise — and a non-conforming record is still surfaced, never dropped.
"""
import os
import struct
import tempfile
import unittest

import glob
import re

from app import gui
from app.engine import TachoParser
from core.decoders.vu_g1 import _parse_trep_03_events_faults
from core.parser import vu_dispatcher
from core.parser.vu_dispatcher import (
    VU_EVENT_RECORD_SIZE, VU_FAULT_RECORD_SIZE, walk_vu_record_arrays)
from core.utils.event_codes import EVENT_TYPES, FAULT_TYPES
from core.utils.report_format import humanize_key, visible_columns
from tests.unit.real_data import real_ddd_files, requires_real_files

#: Conformance bookkeeping stays in the JSON: it is hidden from every table
#: (GUI `HIDDEN_KEYS` and `report_format.HIDDEN_KEYS`), like ``confidence``.
HIDDEN_CONFORMANCE_KEYS = (
    "normative", "spec_reference", "conformance_reason",
    "low_confidence_fields", "end_semantics", "manufacturer_error_code")

#: Obviously synthetic card numbers (never a real one): asserted against DDD/ below.
DRIVER_NUMBER = b"I" + b"0" * 14 + b"1"
COMPANY_NUMBER = b"X" + b"9" * 14 + b"7"

BEGIN = 1751277600          # 2025-06-30 10:00:00 UTC
END = BEGIN + 600
MANUFACTURER_CODE = 0xA2
MANUFACTURER_ERROR = b"\x01\x02\x03"


def _card(card_type=0x01, nation=0x1A, number=DRIVER_NUMBER, generation=0x02):
    """FullCardNumberAndGeneration (19): cardType + nation + number(16) + generation."""
    assert len(number) == 16
    return bytes([card_type, nation]) + number + bytes([generation])


EMPTY_FF = b"\xff" * 19
# The other empty-slot encoding seen from real units (manufacturer code 162):
# cardType 0, nation 0, 16 spaces, generation 0xFF.
EMPTY_ZERO = bytes([0x00, 0x00]) + b" " * 16 + bytes([0xFF])


def _event_record(event_type=0x04, purpose=0x00, begin=BEGIN, end=END,
                  slots=None, similar=0x03, manufacturer_code=MANUFACTURER_CODE,
                  manufacturer_error=MANUFACTURER_ERROR):
    slots = slots if slots is not None else [
        _card(), EMPTY_FF, _card(), EMPTY_ZERO]
    return (bytes([event_type, purpose]) + struct.pack(">II", begin, end)
            + b"".join(slots) + bytes([similar, manufacturer_code])
            + manufacturer_error)


def _fault_record(fault_type=0x35, purpose=0x00, begin=BEGIN, end=END,
                  slots=None, manufacturer_code=MANUFACTURER_CODE,
                  manufacturer_error=MANUFACTURER_ERROR):
    slots = slots if slots is not None else [
        _card(), EMPTY_FF, _card(), EMPTY_ZERO]
    return (bytes([fault_type, purpose]) + struct.pack(">II", begin, end)
            + b"".join(slots) + bytes([manufacturer_code]) + manufacturer_error)


def _record_array(record_type, records):
    size = len(records[0])
    assert all(len(r) == size for r in records)
    return struct.pack(">BHH", record_type, size, len(records)) + b"".join(records)


def _g1_overview_body():
    """Annex 1B TREP 01 overview body: manufacturer, address, serial, VIN, VRN."""
    def text(value, size):
        return value.encode("latin-1").ljust(size)[:size]

    return (text("SYNTHETIC MANUFACTURER", 36) + text("SOME ROAD 1", 36)
            + b"SN000001" + text("WDB9066571P123456", 17)
            + bytes([0x1A]) + text("AB123CD", 14))


def _decode(record_type, record):
    return vu_dispatcher.decode_vu_record(record_type, record)


class TestRecordLayout(unittest.TestCase):
    def test_synthetic_records_have_the_normative_sizes(self):
        self.assertEqual(len(_event_record()), VU_EVENT_RECORD_SIZE)
        self.assertEqual(len(_fault_record()), VU_FAULT_RECORD_SIZE)


class TestEventRecordDecode(unittest.TestCase):
    def test_every_field_round_trips(self):
        out = _decode(0x15, _event_record())
        self.assertEqual(out["record_type"], "0x15")
        self.assertEqual(out["description"], "Driving without an appropriate card")
        self.assertEqual(out["type_code"], 0x04)
        self.assertEqual(out["record_purpose"], 0x00)
        self.assertTrue(out["begin"].startswith("2025-06-30T10:00:00"))
        self.assertTrue(out["end"].startswith("2025-06-30T10:10:00"))
        self.assertEqual(out["similar_events"], 0x03)
        self.assertEqual(out["manufacturer_code"], MANUFACTURER_CODE)
        self.assertEqual(out["manufacturer_error_code"], MANUFACTURER_ERROR.hex())
        for name in ("card_driver_begin", "card_codriver_begin",
                     "card_driver_end", "card_codriver_end"):
            self.assertIn(name, out)
        driver = out["card_driver_begin"]
        self.assertTrue(driver["present"])
        self.assertEqual(driver["card_type"], 0x01)
        self.assertEqual(driver["nation"], "I")
        self.assertEqual(driver["card_number"], DRIVER_NUMBER.decode())
        self.assertEqual(driver["generation"], 0x02)

    def test_conformance_verdict_of_a_conforming_record(self):
        out = _decode(0x15, _event_record())
        self.assertTrue(out["normative"])
        self.assertEqual(out["confidence"], "high")
        self.assertEqual(out["spec_reference"], "Annex 1C App.1 2.198")
        self.assertNotIn("conformance_reason", out)
        # Only the manufacturer-specific pair is outside the standard.
        self.assertEqual(out["low_confidence_fields"],
                         ["manufacturer_code", "manufacturer_error_code"])

    def test_fault_record_is_90_bytes_without_similar_events(self):
        out = _decode(0x18, _fault_record())
        self.assertEqual(out["size"], VU_FAULT_RECORD_SIZE)
        self.assertNotIn("similar_events", out)
        self.assertEqual(out["description"], "Sensor fault")
        self.assertEqual(out["manufacturer_code"], MANUFACTURER_CODE)
        self.assertEqual(out["manufacturer_error_code"], MANUFACTURER_ERROR.hex())
        self.assertTrue(out["normative"])
        self.assertEqual(out["confidence"], "high")
        self.assertEqual(out["spec_reference"], "Annex 1C App.1 2.201")

    def test_both_empty_slot_encodings_are_absent_cards(self):
        for empty in (EMPTY_FF, EMPTY_ZERO):
            with self.subTest(empty=empty[:2].hex()):
                out = _decode(0x15, _event_record(slots=[empty] * 4))
                for name in ("card_driver_begin", "card_codriver_begin",
                             "card_driver_end", "card_codriver_end"):
                    self.assertFalse(out[name]["present"])
                self.assertTrue(out["normative"])
                self.assertEqual(out["confidence"], "high")

    def test_present_cards_of_generation_1_and_2(self):
        slots = [
            _card(0x01, 0x1A, DRIVER_NUMBER, 0x01),
            _card(0x01, 0x1A, DRIVER_NUMBER, 0x02),
            _card(0x04, 0x1A, COMPANY_NUMBER, 0x01),
            _card(0x04, 0x1A, COMPANY_NUMBER, 0x02),
        ]
        out = _decode(0x15, _event_record(slots=slots))
        self.assertEqual(out["card_driver_begin"]["generation"], 0x01)
        self.assertEqual(out["card_codriver_begin"]["generation"], 0x02)
        self.assertEqual(out["card_driver_end"]["card_type"], 0x04)
        self.assertEqual(out["card_codriver_end"]["card_number"],
                         COMPANY_NUMBER.decode())
        self.assertTrue(out["normative"])

    def test_zero_similar_events_flags_the_field_not_the_record(self):
        # §2.151: similarEventsNumber 0 is "not used", but 52 of the 121 real
        # events carry it. The structure is valid, so the record stays
        # normative; only the field's value is outside the standard.
        out = _decode(0x15, _event_record(similar=0x00))
        self.assertTrue(out["normative"])
        self.assertEqual(out["confidence"], "high")
        self.assertIn("similar_events", out["low_confidence_fields"])
        self.assertNotIn("conformance_reason", out)

        out = _decode(0x15, _event_record(similar=0x01))
        self.assertTrue(out["normative"])
        self.assertNotIn("similar_events", out["low_confidence_fields"])

    def test_time_conflict_end_may_precede_begin(self):
        # §2.198: the two timestamps are two clocks, not a range — either order
        # is legitimate for the time-conflict event, and `end` says what it is.
        out = _decode(0x15, _event_record(event_type=0x0B, begin=BEGIN, end=BEGIN - 60))
        self.assertTrue(out["normative"], out.get("conformance_reason"))
        self.assertEqual(out["confidence"], "high")
        self.assertEqual(out["end_semantics"], "GNSS date and time")

    def test_end_before_begin_is_flagged_outside_the_time_conflict(self):
        out = _decode(0x15, _event_record(event_type=0x04, begin=BEGIN, end=BEGIN - 60))
        self.assertFalse(out["normative"])
        self.assertIn("end time precedes begin time", out["conformance_reason"])
        # A fault record never gets the exemption, not even with the '0B' code.
        out = _decode(0x18, _fault_record(fault_type=0x0B, begin=BEGIN, end=BEGIN - 60))
        self.assertFalse(out["normative"])
        self.assertIn("end time precedes begin time", out["conformance_reason"])

    def test_time_conflict_end_is_the_gnss_time(self):
        # Annex 1C §2.198: for a time conflict (EventFaultType '0B'H) the begin
        # time is the recording equipment time and the end time is the GNSS time.
        gnss = BEGIN + 90
        out = _decode(0x15, _event_record(event_type=0x0B, begin=BEGIN, end=gnss))
        self.assertEqual(out["end_semantics"], "GNSS date and time")
        self.assertTrue(out["end"].startswith("2025-06-30T10:01:30"))
        self.assertTrue(out["normative"])
        self.assertEqual(out["confidence"], "high")


class TestConformanceFailures(unittest.TestCase):
    """Non-conforming records: normative=False, low confidence, a reason — and
    still decoded (never silently dropped)."""

    def _assert_non_conforming(self, out, fragment):
        self.assertFalse(out["normative"])
        self.assertEqual(out["confidence"], "low")
        self.assertIn(fragment, out["conformance_reason"])
        self.assertIsNotNone(out["description"])
        self.assertIn("begin", out)

    def test_card_type_outside_the_defined_equipment_types(self):
        slots = [_card(0x20), EMPTY_FF, EMPTY_FF, EMPTY_FF]
        self._assert_non_conforming(
            _decode(0x15, _event_record(slots=slots)), "card type 0x20")

    def test_card_types_1_to_5_are_accepted(self):
        # §2.67: driver, workshop, control, company, manufacturing cards.
        for card_type in (0x01, 0x02, 0x03, 0x04, 0x05):
            with self.subTest(card_type=hex(card_type)):
                out = _decode(0x15, _event_record(
                    slots=[_card(card_type), EMPTY_FF, EMPTY_FF, EMPTY_FF]))
                self.assertTrue(out["normative"], out.get("conformance_reason"))
                self.assertTrue(out["card_driver_begin"]["present"])

    def test_equipment_that_is_not_a_card_is_rejected(self):
        # A FullCardNumber identifies a *tachograph card*: the VU, motion sensor,
        # GNSS facility, RCM, ITS module, plaque, adapter, ERCA, MSCA and the
        # external GNSS connection are equipment, never a card in a slot.
        for card_type in (0x06, 0x08, 0x0F):
            with self.subTest(card_type=hex(card_type)):
                out = _decode(0x15, _event_record(
                    slots=[_card(card_type), EMPTY_FF, EMPTY_FF, EMPTY_FF]))
                self.assertFalse(out["normative"])
                self.assertIn("cannot appear in a card slot", out["conformance_reason"])
                self.assertIn("other equipment", out["conformance_reason"])

    def test_card_type_unused_and_rfu_are_rejected_with_their_own_wording(self):
        out = _decode(0x15, _event_record(
            slots=[_card(0x10), EMPTY_FF, EMPTY_FF, EMPTY_FF]))
        self.assertFalse(out["normative"])
        self.assertIn("card type 0x10", out["conformance_reason"])
        self.assertIn("Unused", out["conformance_reason"])
        self.assertNotIn("not a defined EquipmentType", out["conformance_reason"])

        out = _decode(0x15, _event_record(
            slots=[_card(0x11), EMPTY_FF, EMPTY_FF, EMPTY_FF]))
        self.assertFalse(out["normative"])
        self.assertIn("RFU", out["conformance_reason"])

    def test_empty_slots_stay_valid_whatever_the_card_types(self):
        for empty in (EMPTY_FF, EMPTY_ZERO):
            with self.subTest(empty=empty[:2].hex()):
                out = _decode(0x15, _event_record(slots=[empty] * 4))
                self.assertTrue(out["normative"])

    def test_card_generation_outside_generation_1_and_2(self):
        slots = [_card(generation=0x00), EMPTY_FF, EMPTY_FF, EMPTY_FF]
        self._assert_non_conforming(
            _decode(0x15, _event_record(slots=slots)), "card generation 0x00")

    def test_issuing_member_state_not_a_known_nation(self):
        slots = [_card(nation=0x40), EMPTY_FF, EMPTY_FF, EMPTY_FF]
        self._assert_non_conforming(
            _decode(0x15, _event_record(slots=slots)), "member state 0x40")

    def test_issuing_member_state_must_be_a_real_country(self):
        # 0x00 "no information available", 0xFD EC, 0xFE Europe, 0xFF World: none
        # of them is a Member State that can have issued a card.
        for nation in (0x00, 0xFD, 0xFE, 0xFF):
            with self.subTest(nation=hex(nation)):
                slots = [_card(nation=nation), EMPTY_FF, EMPTY_FF, EMPTY_FF]
                out = _decode(0x15, _event_record(slots=slots))
                self.assertFalse(out["normative"])
                self.assertIn(f"member state 0x{nation:02X}", out["conformance_reason"])
                self.assertIn("not a Member State", out["conformance_reason"])
        # A real issuing state stays conformant.
        out = _decode(0x15, _event_record())
        self.assertTrue(out["normative"])

    def test_record_size_not_the_normative_one(self):
        # A 90-byte record in the event array (and vice versa): the layout is
        # unknown, so the prefix decode is kept and nothing else is claimed.
        out = _decode(0x15, _event_record()[:-1])
        self._assert_non_conforming(out, "record is 90 bytes, the standard defines 91")
        self.assertIn("raw_tail_hex", out)
        self.assertNotIn("card_driver_begin", out)

        out = _decode(0x18, _fault_record() + b"\x00")
        self._assert_non_conforming(out, "record is 91 bytes, the standard defines 90")

    def test_implausible_begin_time(self):
        out = _decode(0x15, _event_record(begin=0xFFFFFFFF))
        self._assert_non_conforming(out, "plausibility")
        # The wording says "plausibility window", not "the standard forbids it":
        # TimeReal itself runs to 2106.
        self.assertIn("2000-2100", out["conformance_reason"])

    def test_end_time_before_begin_time(self):
        out = _decode(0x18, _fault_record(begin=BEGIN, end=BEGIN - 60))
        self._assert_non_conforming(out, "end time precedes begin time")

    def test_reserved_record_purpose(self):
        out = _decode(0x15, _event_record(purpose=0x08))
        self._assert_non_conforming(out, "record purpose 0x08 is RFU")

    def test_non_conforming_record_is_still_surfaced_by_the_walker(self):
        bad = _event_record(slots=[_card(0x20), EMPTY_FF, EMPTY_FF, EMPTY_FF])
        stream = b"\x76\x23" + _record_array(0x15, [bad])
        results = {}
        walk_vu_record_arrays(stream, results)

        self.assertEqual(len(results["events"]), 1)
        event = results["events"][0]
        self.assertFalse(event["normative"])
        self.assertEqual(event["confidence"], "low")
        self.assertIn("card type 0x20", event["conformance_reason"])
        self.assertEqual(event["source"], "vu_recordarray")
        # Counted as heuristic, never as normative.
        self.assertEqual(results["metadata"]["decode_paths"]["vu_events"],
                         {"normative": 0, "non_normative": 1})


class TestTypeCodeAssignment(unittest.TestCase):
    """EventFaultType is checked against the amended generation-2 value assignment."""

    #: "Generation 2, version 2" value assignment of EventFaultType (point 2.70 of
    #: Annex 1C Appendix 1, as replaced by Reg. (EU) 2021/1228 Annex point (n)(ii);
    #: the version-1 set of Reg. (EU) 2018/502 is a subset of it). Read from the act
    #: text, not from the code: 00-0F general events, 10-1C VU security events,
    #: 20-25 sensor events, 30-3A recording-equipment faults, 40 card faults;
    #: 1D-1F, 26-2F, 3B-3F, 41-4F and 50-7F are RFU, 80-FF manufacturer specific.
    STANDARD_TYPES = (set(range(0x00, 0x10)) | set(range(0x10, 0x1D))
                      | set(range(0x20, 0x26)) | set(range(0x30, 0x3B)) | {0x40})

    def test_type_tables_match_the_amended_regulation(self):
        self.assertEqual(set(EVENT_TYPES) | set(FAULT_TYPES), self.STANDARD_TYPES)
        self.assertEqual(set(EVENT_TYPES),
                         {c for c in self.STANDARD_TYPES if c < 0x30})
        self.assertEqual(set(FAULT_TYPES),
                         {c for c in self.STANDARD_TYPES if c >= 0x30})

    def test_rfu_event_type_flags_the_field_only(self):
        out = _decode(0x15, _event_record(event_type=0x1D))
        self.assertTrue(out["normative"], out.get("conformance_reason"))
        self.assertEqual(out["confidence"], "high")
        self.assertIn("event_type_code", out["low_confidence_fields"])

    def test_rfu_fault_type_flags_the_field_only(self):
        out = _decode(0x18, _fault_record(fault_type=0x3B))
        self.assertTrue(out["normative"], out.get("conformance_reason"))
        self.assertIn("fault_type_code", out["low_confidence_fields"])

    def test_manufacturer_specific_type_flags_the_field_only(self):
        # 80-FF: a legal range whose meaning is not public.
        for record_type, code, key in ((0x15, 0x80, "event_type_code"),
                                       (0x18, 0xA5, "fault_type_code")):
            with self.subTest(record_type=hex(record_type), code=hex(code)):
                out = (_decode(0x15, _event_record(event_type=code)) if record_type == 0x15
                       else _decode(0x18, _fault_record(fault_type=code)))
                self.assertTrue(out["normative"])
                self.assertIn(key, out["low_confidence_fields"])

    def test_amended_defined_types_are_not_flagged(self):
        # Codes assigned by Reg. 2018/502 and 2021/1228: legitimately defined.
        for code in (0x0C, 0x0F, 0x1C):
            with self.subTest(event=hex(code)):
                out = _decode(0x15, _event_record(event_type=code))
                self.assertNotIn("event_type_code", out["low_confidence_fields"])
        for code in (0x36, 0x38, 0x3A):
            with self.subTest(fault=hex(code)):
                out = _decode(0x18, _fault_record(fault_type=code))
                self.assertNotIn("fault_type_code", out["low_confidence_fields"])


class TestThroughTheEngine(unittest.TestCase):
    """The RecordArray path end to end: source, decode_paths, no heuristic."""

    def _write(self, data):
        handle = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
        handle.write(data)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def _g2_download(self):
        overview = b"\x76\x21" + _record_array(0x0A, [b"WDB9066571P123456"])
        events_faults = (b"\x76\x23"
                         + _record_array(0x15, [_event_record()])
                         + _record_array(0x18, [_fault_record()]))
        return overview + events_faults

    def test_events_and_faults_come_out_fully_normative(self):
        results = TachoParser(self._write(self._g2_download())).parse()

        self.assertEqual(results["metadata"]["generation"], "G2 (Smart)")
        self.assertEqual(len(results["events"]), 1)
        self.assertEqual(len(results["faults"]), 1)
        for key, spec in (("events", "Annex 1C App.1 2.198"),
                          ("faults", "Annex 1C App.1 2.201")):
            record = results[key][0]
            self.assertEqual(record["source"], "vu_recordarray")
            self.assertTrue(record["normative"])
            self.assertEqual(record["confidence"], "high")
            self.assertEqual(record["spec_reference"], spec)
        # A clean download is provably 100% normative, with no heuristic trace.
        self.assertEqual(results["metadata"]["decode_paths"],
                         {"vu_events": {"normative": 1, "non_normative": 0},
                          "vu_faults": {"normative": 1, "non_normative": 0}})
        self.assertFalse(results["metadata"].get("heuristic_fields"))


class TestVisibleColumns(unittest.TestCase):
    """The verdict stays in the JSON: tables keep their existing columns."""

    CATALOGS = sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "locale", "*", "LC_MESSAGES", "tacho.po")))

    def _catalog_msgids(self):
        """{catalogue path: its msgid set} — one entry per shipped language."""
        msgids = {}
        for path in self.CATALOGS:
            with open(path, encoding="utf-8") as handle:
                msgids[path] = {m.group(1) for m in
                                re.finditer(r'^msgid "(.*)"$', handle.read(), re.M)}
        return msgids

    def test_only_standard_defined_fields_are_shown(self):
        bad = _event_record(slots=[_card(0x20), EMPTY_FF, EMPTY_FF, EMPTY_FF])
        stream = (b"\x76\x23" + _record_array(0x15, [_event_record(), bad])
                  + _record_array(0x18, [_fault_record()]))
        results = {}
        walk_vu_record_arrays(stream, results)
        catalogs = self._catalog_msgids()
        self.assertTrue(self.CATALOGS, "no catalogs found")

        for key, required in (("events", {"card_driver_begin", "card_codriver_begin",
                                          "card_driver_end", "card_codriver_end",
                                          "similar_events", "manufacturer_code"}),
                              ("faults", {"card_driver_begin", "card_codriver_begin",
                                          "card_driver_end", "card_codriver_end",
                                          "manufacturer_code"})):
            records = results[key]
            for name, cols in (("report", visible_columns(records)),
                               ("gui", gui._columns_for(records, None))):
                with self.subTest(section=key, path=name):
                    self.assertTrue(required <= set(cols), cols)
                    for hidden in HIDDEN_CONFORMANCE_KEYS:
                        self.assertNotIn(hidden, cols)
                    # No new user-visible text: every column label is a msgid
                    # EVERY catalogue already carries (not merely one of them).
                    for col in cols:
                        label = humanize_key(col)
                        for path, msgids in catalogs.items():
                            self.assertIn(label, msgids, f"{path}: {label}")

    def test_the_json_keeps_all_six_keys(self):
        bad = _event_record(slots=[_card(0x20), EMPTY_FF, EMPTY_FF, EMPTY_FF])
        stream = (b"\x76\x23"
                  + _record_array(0x15, [_event_record(event_type=0x0B, end=BEGIN + 90), bad])
                  + _record_array(0x18, [_fault_record()]))
        results = {}
        walk_vu_record_arrays(stream, results)
        conflict, non_conforming = results["events"]
        fault = results["faults"][0]

        self.assertTrue(conflict["normative"])
        self.assertEqual(conflict["end_semantics"], "GNSS date and time")
        self.assertFalse(non_conforming["normative"])
        self.assertIn("conformance_reason", non_conforming)
        for record in (conflict, non_conforming, fault):
            self.assertEqual(record["spec_reference"],
                             "Annex 1C App.1 2.198" if record is not fault
                             else "Annex 1C App.1 2.201")
            self.assertIn("manufacturer_error_code", record)
            self.assertIn("low_confidence_fields", record)


class TestNoSilentBackup(unittest.TestCase):
    """A backup route must announce itself and can never look spec-verified."""

    def _write(self, data):
        handle = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
        handle.write(data)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_failing_walker_is_logged_and_recorded(self):
        data = (b"\x76\x21" + _record_array(0x0A, [b"WDB9066571P123456"])
                + b"\x76\x23" + _record_array(0x15, [_event_record()]))
        original = vu_dispatcher.walk_vu_record_arrays

        def _boom(raw_data, results):
            raise RuntimeError("synthetic walker failure")

        vu_dispatcher.walk_vu_record_arrays = _boom
        self.addCleanup(setattr, vu_dispatcher, "walk_vu_record_arrays", original)
        try:
            with self.assertLogs("app.engine", level="WARNING") as captured:
                results = TachoParser(self._write(data)).parse()
        finally:
            vu_dispatcher.walk_vu_record_arrays = original

        self.assertTrue(any("RecordArray walk raised RuntimeError" in line
                            for line in captured.output), captured.output)
        fallback = results["metadata"]["decode_paths"]["fallback"]
        self.assertTrue(any("RecordArray walk raised RuntimeError" in reason
                            for reason in fallback), fallback)
        # Nothing recovered by the backup route may claim conformance.
        for key in ("events", "faults"):
            for record in results.get(key) or []:
                self.assertFalse(record.get("normative"))
                self.assertNotEqual(record.get("confidence"), "high")

    def test_real_mid_walk_failure_keeps_the_first_section_and_does_not_rescan(self):
        # A section is emitted as soon as it is walked, so a failure while
        # emitting the second one must leave the first section's records in
        # place: no rescan over the same stream (that would decode them twice,
        # once per route) and no lost sections.
        stream = (b"\x76\x23" + _record_array(0x15, [_event_record()])
                  + b"\x76\x24" + _record_array(0x12, [b"\x00" * 4 + bytes([50] * 60)]))
        original_emit = vu_dispatcher._emit_section
        calls = []

        def _emit_then_fail(section, results):
            calls.append(section["name"])
            if len(calls) == 2:
                raise RuntimeError("synthetic failure on the second section")
            original_emit(section, results)

        vu_dispatcher._emit_section = _emit_then_fail
        self.addCleanup(setattr, vu_dispatcher, "_emit_section", original_emit)
        try:
            with self.assertLogs("app.engine", level="WARNING") as captured:
                results = TachoParser(self._write(stream)).parse()
        finally:
            vu_dispatcher._emit_section = original_emit

        self.assertEqual(calls, ["EventsFaults", "DetailedSpeed"])
        # The first section survives, exactly once, and keeps its own verdict.
        self.assertEqual(len(results["events"]), 1)
        self.assertTrue(results["events"][0]["normative"])
        self.assertEqual(results["events"][0]["confidence"], "high")
        # The switch is declared, the stream is not re-scanned, and the walk is
        # not claiming to be complete.
        self.assertTrue(any("synthetic failure on the second section" in line
                            for line in captured.output), captured.output)
        self.assertTrue(results["metadata"]["decode_paths"]["fallback"])
        self.assertFalse(results["metadata"].get("heuristic_fields"))
        self.assertIs(results["_vu_walk_complete"], False)
        self.assertEqual(len(results["vu_record_arrays"]), 1)

    # ── the rescan guard: no scan over output the walk already produced ──

    def _scan_spy(self):
        """Replace the byte scan with a recorder; returns the call list."""
        from core import decoders

        calls = []
        real_scan = decoders.parse_vu_download_messages

        def _spy(raw_data, results):
            calls.append(len(raw_data))
            real_scan(raw_data, results)

        decoders.parse_vu_download_messages = _spy
        self.addCleanup(setattr, decoders, "parse_vu_download_messages", real_scan)
        return calls

    def _guard_stream(self):
        # Two sections: the first one the failure will hit, the second one to
        # prove the walk stopped where it stopped.
        return (b"\x76\x23" + _record_array(0x15, [_event_record()])
                + b"\x76\x24" + _record_array(0x12, [b"\x00" * 4 + bytes([50] * 60)]))

    def _assert_guarded_fallback(self, results, captured, calls):
        """No rescan, nothing heuristic, the switch declared and logged."""
        self.assertEqual(calls, [], "the byte scan ran over the walker's own output")
        self.assertFalse(results["metadata"].get("heuristic_fields"))
        self.assertTrue(results["metadata"]["decode_paths"]["fallback"])
        self.assertIs(results["_vu_walk_complete"], False)
        self.assertTrue(any("no heuristic rescan" in line
                            for line in captured.output), captured.output)

    def test_first_section_failure_after_writing_does_not_rescan(self):
        # A real _emit_section emits the first section completely and only then
        # raises: every record it wrote must survive untouched.
        original_emit = vu_dispatcher._emit_section
        calls = []

        def _emit_then_raise(section, results):
            calls.append(section["name"])
            original_emit(section, results)
            raise RuntimeError("synthetic failure after the first section emit")

        vu_dispatcher._emit_section = _emit_then_raise
        scan_calls = self._scan_spy()
        self.addCleanup(setattr, vu_dispatcher, "_emit_section", original_emit)
        try:
            with self.assertLogs("app.engine", level="WARNING") as captured:
                results = TachoParser(self._write(self._guard_stream())).parse()
        finally:
            vu_dispatcher._emit_section = original_emit

        self.assertEqual(calls, ["EventsFaults"])
        self.assertEqual(len(results["events"]), 1, "the emitted event was lost or doubled")
        self.assertTrue(results["events"][0]["normative"])
        self._assert_guarded_fallback(results, captured, scan_calls)

    def test_failure_inside_the_first_emit_after_writing_does_not_rescan(self):
        # The failure lands *inside* the first _emit_section, after it already
        # appended a record (the counter runs right after each append).
        original_count = vu_dispatcher._count_decode_path

        def _count_then_raise(results, key, normative):
            original_count(results, key, normative)
            raise RuntimeError("synthetic failure inside the first section emit")

        vu_dispatcher._count_decode_path = _count_then_raise
        scan_calls = self._scan_spy()
        self.addCleanup(setattr, vu_dispatcher, "_count_decode_path", original_count)
        try:
            with self.assertLogs("app.engine", level="WARNING") as captured:
                results = TachoParser(self._write(self._guard_stream())).parse()
        finally:
            vu_dispatcher._count_decode_path = original_count

        self.assertEqual(len(results["events"]), 1, "the emitted event was lost or doubled")
        self.assertEqual(results["vu_record_arrays"], [])
        self._assert_guarded_fallback(results, captured, scan_calls)

    def test_walk_failing_before_emitting_anything_still_scans(self):
        # Nothing was written, so the byte scan is still the walk's only chance:
        # it must run exactly as before, declared and heuristic-only.
        from core import decoders

        original_decode = vu_dispatcher._decode_record
        calls = []

        def _decode_then_raise(record_type, rec):
            raise RuntimeError("synthetic failure before the first emit")

        def _fake_scan(raw_data, results):
            calls.append(len(raw_data))
            results.setdefault("events", []).append(
                {"description": "scanned event", "type_code": 0x04})

        real_scan = decoders.parse_vu_download_messages
        vu_dispatcher._decode_record = _decode_then_raise
        decoders.parse_vu_download_messages = _fake_scan
        self.addCleanup(setattr, vu_dispatcher, "_decode_record", original_decode)
        self.addCleanup(setattr, decoders, "parse_vu_download_messages", real_scan)
        try:
            with self.assertLogs("app.engine", level="WARNING") as captured:
                results = TachoParser(self._write(self._guard_stream())).parse()
        finally:
            vu_dispatcher._decode_record = original_decode
            decoders.parse_vu_download_messages = real_scan

        self.assertEqual(len(calls), 1, "the backup scan must still run")
        self.assertTrue(any("heuristic byte scan recovered events" in line
                            for line in captured.output), captured.output)
        self.assertEqual(
            results["metadata"]["heuristic_fields"]["vu_fallback_scan"], ["events"])
        self.assertFalse(results["events"][0].get("normative"))
        self.assertNotEqual(results["events"][0].get("confidence"), "high")

    def _g1_stream(self):
        """A G1 VU download whose walk writes a fault but cannot cover the file.

        Message = ``76 03`` + Annex 1B TREP 03 body (one 82-byte VuFaultRecord)
        + the 128-byte RSA signature. A second marker with an impossible body
        length stops the walk early, so it wrote its records and still reports
        incompleteness — the case where Gen1 keeps falling through to the scan.
        The trailing TREP 03 block sits past that stop, so only the scan reaches
        it: it is the data the scan gains.
        """
        def body(begin):
            fault = (bytes([0x31, 0x00]) + struct.pack(">II", begin, begin + 60)
                     + b"\x01\x1a" + DRIVER_NUMBER    # FullCardNumber (18), no generation
                     + b"\xff" * 18 * 3)              # three empty card slots
            return (bytes([0x01]) + fault             # noOfVuFaults + record
                    + bytes([0x00])                   # noOfVuEvents
                    + b"\x00" * 9                    # VuOverSpeedingControlData
                    + bytes([0x00]) + bytes([0x00]))  # over-speeding / adjustment counts

        walked = b"\x76\x03" + body(BEGIN) + b"\x00" * 128
        stopped = b"\x76\x03" + b"\x05"
        # Past the stop: a TREP 03 body the count-prefixed layout rejects, so the
        # scan's own heuristic route recovers it and marks it — exactly the
        # mechanism base had (asserted below), independent of this change.
        scan_only = (b"\x76\x03" + bytes([0x00, 0x04])
                     + struct.pack(">II", BEGIN + 3600, BEGIN + 3660) + b"\x00" * 84)
        return walked + stopped + scan_only

    def test_g1_incomplete_walk_still_scans_and_declares_it(self):
        # Gen1 behaviour is deliberately unchanged: an incomplete walk always
        # falls through to the byte scan (its own dedupe + mark_heuristic handle
        # the overlap), and the switch is declared. The G2 guard from C9 must not
        # leak into this branch.
        scan_calls = self._scan_spy()
        with self.assertLogs("app.engine", level="WARNING") as captured:
            results = TachoParser(self._write(self._g1_stream())).parse()

        self.assertTrue(results.get("faults"), "the walk itself wrote nothing")
        self.assertEqual(len(scan_calls), 1,
                         "an incomplete G1 walk must still fall through to the scan")
        self.assertTrue(results["metadata"]["decode_paths"]["fallback"])
        self.assertTrue(any("heuristic byte scan recovered" in line
                            for line in captured.output), captured.output)
        heuristic = results["metadata"]["heuristic_fields"]
        # The scan's own sub-parsers mark their sections, and the engine marks
        # what the scan added: the backup route is visible even when the scan's
        # gain is not one its sub-parsers flags.
        self.assertIn("vu_events_faults_TREP03", heuristic)
        self.assertIn("vu_fallback_scan", heuristic)
        # Whatever the scan added is present and never claims conformance.
        self.assertGreater(len(results["faults"]), 1)
        recovered = [f for f in results["faults"] if not f.get("normative")]
        self.assertTrue(recovered)

    def test_fallback_warning_names_what_the_metadata_lists(self):
        # Stub the walk to fail before writing anything, on a stream whose bytes
        # the byte scan can still recover: the WARNING and heuristic_fields must
        # describe the same set of sections.
        data = (b"\x76\x01" + _g1_overview_body()
                + b"\x76\x23" + _record_array(0x15, [_event_record()]))
        original = vu_dispatcher.walk_vu_record_arrays

        def _boom(raw_data, results):
            raise RuntimeError("synthetic walker failure")

        vu_dispatcher.walk_vu_record_arrays = _boom
        self.addCleanup(setattr, vu_dispatcher, "walk_vu_record_arrays", original)
        try:
            with self.assertLogs("app.engine", level="WARNING") as captured:
                results = TachoParser(self._write(data)).parse()
        finally:
            vu_dispatcher.walk_vu_record_arrays = original

        sections = sorted(results["metadata"]["heuristic_fields"])
        self.assertTrue(sections, "nothing was marked heuristic")
        warning = next(line for line in captured.output
                       if "heuristic byte scan recovered" in line)
        for section in sections:
            self.assertIn(section, warning,
                          f"{section} is in heuristic_fields but not in the warning")
        self.assertNotIn("recovered nothing", warning)

    def test_record_less_section_then_failure_still_scans(self):
        # A section that emits no records leaves the result mappings untouched, so
        # it must not be mistaken for "the walk wrote data": the scan still runs.
        stream = (b"\x76\x24" + struct.pack(">BHH", 0x12, 64, 0)
                  + b"\x76\x23" + _record_array(0x15, [_event_record()]))
        original_emit = vu_dispatcher._emit_section
        calls = []

        def _emit_then_raise(section, results):
            calls.append(section["name"])
            if len(calls) == 2:
                raise RuntimeError("synthetic failure after the record-less section")
            original_emit(section, results)

        vu_dispatcher._emit_section = _emit_then_raise
        scan_calls = self._scan_spy()
        self.addCleanup(setattr, vu_dispatcher, "_emit_section", original_emit)
        try:
            with self.assertLogs("app.engine", level="WARNING") as captured:
                results = TachoParser(self._write(stream)).parse()
        finally:
            vu_dispatcher._emit_section = original_emit

        self.assertEqual(calls, ["DetailedSpeed", "EventsFaults"])
        self.assertEqual(len(scan_calls), 1,
                         "a record-less section must not block the backup scan")
        self.assertTrue(results["metadata"]["decode_paths"]["fallback"])
        self.assertTrue(any("heuristic byte scan" in line for line in captured.output))

    def test_records_from_the_backup_scan_are_marked_heuristic(self):
        from core import decoders

        data = (b"\x76\x21" + _record_array(0x0A, [b"WDB9066571P123456"])
                + b"\x76\x23" + _record_array(0x15, [_event_record()]))
        original = vu_dispatcher.walk_vu_record_arrays

        def _boom(raw_data, results):
            raise RuntimeError("synthetic walker failure")

        def _fake_scan(raw_data, results):
            # Stands in for the byte scan: it can only produce plain records,
            # never one carrying a conformance verdict.
            results.setdefault("events", []).append(
                {"description": "scanned event", "type_code": 0x04})

        vu_dispatcher.walk_vu_record_arrays = _boom
        real_scan = decoders.parse_vu_download_messages
        decoders.parse_vu_download_messages = _fake_scan
        self.addCleanup(setattr, vu_dispatcher, "walk_vu_record_arrays", original)
        self.addCleanup(setattr, decoders, "parse_vu_download_messages", real_scan)
        try:
            with self.assertLogs("app.engine", level="WARNING"):
                results = TachoParser(self._write(data)).parse()
        finally:
            vu_dispatcher.walk_vu_record_arrays = original
            decoders.parse_vu_download_messages = real_scan

        self.assertEqual(
            results["metadata"]["heuristic_fields"]["vu_fallback_scan"], ["events"])
        self.assertFalse(results["events"][0].get("normative"))
        self.assertNotEqual(results["events"][0].get("confidence"), "high")

    def test_g1_heuristic_events_are_marked_and_never_normative(self):
        # A TREP 03 body that the count-prefixed layout rejects: whatever the
        # heuristic recovers is flagged, and carries no conformance verdict.
        data = bytes([0x00, 0x04]) + struct.pack(">II", BEGIN, END) + b"\x00" * 84
        results = {}
        # Every decoder module logs through the shared "ddd_tacho" logger.
        with self.assertLogs("ddd_tacho", level="WARNING") as captured:
            _parse_trep_03_events_faults(data, results)
        self.assertTrue(any("heuristic scan supplied faults" in line
                            for line in captured.output), captured.output)

        self.assertEqual(
            results["metadata"]["heuristic_fields"]["vu_events_faults_TREP03"],
            ["faults"])
        self.assertTrue(results["faults"])
        for record in results["faults"]:
            self.assertFalse(record.get("normative"))
            self.assertNotEqual(record.get("confidence"), "high")


class TestSyntheticIdentifiers(unittest.TestCase):
    """The test fixtures never carry a real card number (they are personal data)."""

    def test_synthetic_numbers_are_absent_from_the_private_corpus(self):
        for number in (DRIVER_NUMBER, COMPANY_NUMBER):
            with self.subTest(number=number):
                self.assertEqual(len(number), 16)
                for path in real_ddd_files():
                    with open(path, "rb") as handle:
                        self.assertNotIn(number, handle.read(),
                                         f"test fixture {number!r} occurs in DDD/")


@requires_real_files
class TestPrivateCorpus(unittest.TestCase):
    """The real corpus: no file falls back, the Gen2 VU records are all normative."""

    #: Gen2/Gen2.2 TRTP markers on the leading message (Annex 1C TRTP table).
    _G2_TRTP = {0x21, 0x22, 0x23, 0x24, 0x25, 0x31, 0x32, 0x33, 0x35}

    @classmethod
    def setUpClass(cls):
        cls._parses = {}

    def _parse(self, path):
        if path not in self._parses:
            self._parses[path] = TachoParser(path).parse()
        return self._parses[path]

    def _gen2_vu_files(self):
        files = []
        for path in real_ddd_files():
            with open(path, "rb") as handle:
                head = handle.read(2)
            if len(head) == 2 and head[0] == 0x76 and head[1] in self._G2_TRTP:
                files.append(path)
        return files

    def test_no_file_needs_a_backup_route(self):
        files = real_ddd_files()
        self.assertTrue(files, "No .ddd files found in DDD/")
        for path in files:
            results = self._parse(path)
            meta = results["metadata"]
            with self.subTest(file=os.path.basename(path)):
                # A clean download decodes on the deterministic path only: no
                # heuristic recovery and no declared fallback, anywhere.
                self.assertFalse(meta.get("heuristic_fields"),
                                 f"{os.path.basename(path)}: heuristic recovery used")
                self.assertFalse((meta.get("decode_paths") or {}).get("fallback"),
                                 f"{os.path.basename(path)}: decode fallback declared")

    def _assert_cards_are_tachograph_cards(self, record):
        """Real records carry driver (1) and company (4) cards — never equipment."""
        for key in ("card_driver_begin", "card_codriver_begin",
                    "card_driver_end", "card_codriver_end"):
            card = record.get(key) or {}
            if card.get("present"):
                self.assertIn(card["card_type"], (1, 2, 3, 4, 5),
                              f"{key}: {card['card_type']}")

    def test_every_gen2_event_and_fault_is_normative(self):
        files = self._gen2_vu_files()
        if not files:
            self.skipTest("No private Gen2/Gen2.2 VU download available")

        events = faults = 0
        for path in files:
            results = self._parse(path)
            with self.subTest(file=os.path.basename(path)):
                paths = results["metadata"]["decode_paths"]
                for key in ("vu_events", "vu_faults"):
                    if key in paths:
                        self.assertEqual(paths[key]["non_normative"], 0)
                for record in results.get("events") or []:
                    self.assertTrue(record["normative"],
                                    f"event {record['event_type_code']:#04x}: "
                                    f"{record.get('conformance_reason')}")
                    self._assert_cards_are_tachograph_cards(record)
                    events += 1
                for record in results.get("faults") or []:
                    self.assertTrue(record["normative"],
                                    f"fault {record['fault_type_code']:#04x}: "
                                    f"{record.get('conformance_reason')}")
                    self._assert_cards_are_tachograph_cards(record)
                    faults += 1

        # Field counts of the corpus itself (121 events / 14 faults over the six
        # Gen2/G2.2 VU downloads): a regression on either side must be seen.
        self.assertEqual((events, faults), (121, 14))


if __name__ == "__main__":
    unittest.main()
