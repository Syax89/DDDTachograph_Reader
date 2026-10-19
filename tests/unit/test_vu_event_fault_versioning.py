"""Version-aware EventFaultType assignment + manufacturer identity (Gen2 VU).

``EventFaultType`` (Annex 1C Appendix 1 point 2.70) has three value
assignments, and the download request's TREP says which one applies to a
section (Appendix 7, DDP_011):

===================  ====  ==========================================
data transfer type   TRTP  point-2.70 table
===================  ====  ==========================================
Events and faults     '03' generation 1 (Annex 1B)
Events and faults     '23' "Generation 2, version 1" (Reg. 2018/502)
Events and faults     '33' "Generation 2, version 2" (Reg. 2021/1228)
===================  ====  ==========================================

Version 2 added '0F'H (GNSS anomaly), '1C'H (motion/activity inconsistency)
and '3A'H (internal sensor fault); the version-1 text still says RFU for all
three. A record therefore has to be read against *its section's* table — never
against the file's hardware generation, and never against RGM/device names.

The manufacturer half of the record is §2.95
``manufacturerSpecificEventFaultData``: a ``ManufacturerCode`` byte plus a
3-byte vendor error code. The code byte is looked up in the European
Commission's registry (65 assigned codes); the three bytes stay raw and
low-confidence because no public wire-level mapping exists.
"""
import glob
import os
import re
import struct
import tempfile
import unittest

from app import gui
from app.engine import TachoParser
from core.parser import vu_dispatcher
from core.parser.vu_dispatcher import (
    VU_EVENT_RECORD_SIZE, VU_FAULT_RECORD_SIZE, decode_event_fault_record,
    decode_vu_record, event_fault_version_for_trep, walk_vu_record_arrays)
from core.utils import event_codes
from core.utils.event_codes import (
    EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2, EVENT_FAULT_VERSION_UNKNOWN,
    GEN2_V2_ONLY_TYPES, TYPE_ASSIGNED, TYPE_MANUFACTURER_SPECIFIC,
    TYPE_RESERVED, TYPE_UNKNOWN_VERSION, describe_event, describe_fault)
from core.utils.manufacturer_codes import (
    MANUFACTURER_CODES, MANUFACTURER_STATUS_NOT_REGISTERED,
    MANUFACTURER_STATUS_REGISTERED, manufacturer_name)
from core.utils.report_format import HIDDEN_KEYS as REPORT_HIDDEN_KEYS
from core.utils.report_format import humanize_key, visible_columns

#: Obviously synthetic card number (never a real one).
SYNTHETIC_CARD = b"T" + b"0" * 14 + b"9"
BEGIN = 1751277600          # 2025-06-30 10:00:00 UTC
END = BEGIN + 600
REGISTERED_CODE = 0xA2      # Stoneridge Electronics AB in the official registry
REGISTERED_NAME = "Stoneridge Electronics AB"
SYNTHETIC_ERROR = b"\x01\x02\x03"

HIDDEN_VERSION_KEYS = ("event_fault_version", "type_status", "manufacturer_status")
CATALOGS = sorted(glob.glob(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "locale", "*", "LC_MESSAGES", "tacho.po")))


def _card(generation=0x02):
    return bytes([0x01, 0x1A]) + SYNTHETIC_CARD + bytes([generation])


EMPTY = b"\xff" * 19


def _event_record(event_type=0x04, begin=BEGIN, end=END, similar=0x03,
                  manufacturer_code=REGISTERED_CODE, error=SYNTHETIC_ERROR):
    return (bytes([event_type, 0x00]) + struct.pack(">II", begin, end)
            + _card() + EMPTY + _card() + EMPTY
            + bytes([similar, manufacturer_code]) + error)


def _fault_record(fault_type=0x35, begin=BEGIN, end=END,
                  manufacturer_code=REGISTERED_CODE, error=SYNTHETIC_ERROR):
    return (bytes([fault_type, 0x00]) + struct.pack(">II", begin, end)
            + _card() + EMPTY + _card() + EMPTY
            + bytes([manufacturer_code]) + error)


def _record_array(record_type, records):
    size = len(records[0])
    assert all(len(r) == size for r in records)
    return struct.pack(">BHH", record_type, size, len(records)) + b"".join(records)


def _decode(record_type, record, version=EVENT_FAULT_VERSION_UNKNOWN):
    return decode_vu_record(record_type, record, version=version)


class TestSectionVersionMapping(unittest.TestCase):
    """The TREP is the only source of the point-2.70 table (DDP_011)."""

    def test_the_two_gen2_events_faults_treps_map_to_their_version(self):
        self.assertEqual(event_fault_version_for_trep(0x23), EVENT_FAULT_VERSION_1)
        self.assertEqual(event_fault_version_for_trep(0x33), EVENT_FAULT_VERSION_2)

    def test_everything_else_is_unknown(self):
        # '03' is the generation-1 events/faults TREP: Annex 1B's own table, not
        # a Gen2 one. '24' is the speed section, shared by v1 and v2. '00'/'31'
        # are the overview. None is an events/faults context.
        for trep in (0x03, 0x21, 0x24, 0x25, 0x00, 0x31, 0x35, 0x06, 0x99, None):
            with self.subTest(trep=trep):
                self.assertEqual(event_fault_version_for_trep(trep),
                                 EVENT_FAULT_VERSION_UNKNOWN)


class TestEveryTypeByte(unittest.TestCase):
    """All 256 byte values × event/fault × the three versions."""

    RECORD_SIZES = {0x15: VU_EVENT_RECORD_SIZE, 0x18: VU_FAULT_RECORD_SIZE}

    def _records(self):
        for code in range(0x100):
            yield 0x15, _event_record(event_type=code)
            yield 0x18, _fault_record(fault_type=code)

    def test_every_byte_has_a_status_and_keeps_its_raw_value(self):
        for record_type, record in self._records():
            is_event = record_type == 0x15
            for version in (EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2,
                            EVENT_FAULT_VERSION_UNKNOWN):
                with self.subTest(record=hex(record_type), code=hex(record[0]),
                                  version=version):
                    self.assertEqual(len(record), self.RECORD_SIZES[record_type])
                    out = _decode(record_type, record, version)
                    # The raw byte and the reference are untouched by the
                    # version question.
                    self.assertEqual(out["type_code"], record[0])
                    self.assertEqual(out["spec_reference"],
                                     "Annex 1C App.1 2.198" if is_event
                                     else "Annex 1C App.1 2.201")
                    self.assertEqual(out["event_fault_version"], version)
                    self.assertIn(out["type_status"],
                                  (TYPE_ASSIGNED, TYPE_RESERVED,
                                   TYPE_MANUFACTURER_SPECIFIC, TYPE_UNKNOWN_VERSION))
                    self.assertTrue(out["description"])
                    # A type meaning we cannot state is a field-level flag; the
                    # verdict about the *structure* stays what the bytes say.
                    self.assertTrue(out["normative"], out.get("conformance_reason"))
                    type_key = "event_type_code" if is_event else "fault_type_code"
                    self.assertEqual(type_key in out["low_confidence_fields"],
                                     out["type_status"] != TYPE_ASSIGNED)

    def test_only_the_three_amending_act_codes_differ_between_v1_and_v2(self):
        differing = set()
        for code in range(0x100):
            for is_event in (True, False):
                v1 = event_codes.describe_event_fault_type(code, is_event,
                                                          EVENT_FAULT_VERSION_1)
                v2 = event_codes.describe_event_fault_type(code, is_event,
                                                          EVENT_FAULT_VERSION_2)
                if v1 != v2:
                    differing.add(code)
        self.assertEqual(differing, {0x0F, 0x1C, 0x3A})
        self.assertEqual(frozenset(differing), GEN2_V2_ONLY_TYPES)

    def test_unknown_version_differs_from_v1_only_for_those_codes(self):
        for code in range(0x100):
            for is_event in (True, False):
                v1 = event_codes.describe_event_fault_type(code, is_event,
                                                          EVENT_FAULT_VERSION_1)
                unknown = event_codes.describe_event_fault_type(
                    code, is_event, EVENT_FAULT_VERSION_UNKNOWN)
                with self.subTest(code=hex(code), is_event=is_event):
                    self.assertEqual(v1 != unknown, code in GEN2_V2_ONLY_TYPES)

    def test_the_unknown_default_is_not_a_second_version(self):
        # decode_event_fault_record's default is "unknown", never version 2.
        out = decode_event_fault_record(_event_record(event_type=0x0F), True)
        self.assertEqual(out["event_fault_version"], EVENT_FAULT_VERSION_UNKNOWN)
        self.assertEqual(out["type_status"], TYPE_UNKNOWN_VERSION)
        self.assertNotEqual(out["description"], "GNSS anomaly")

    def test_a_meaningless_version_argument_is_not_trusted(self):
        for bad in ("v2", "", "generation 3", 2, None):
            with self.subTest(version=repr(bad)):
                out = decode_event_fault_record(
                    _fault_record(fault_type=0x3A), False, version=bad)
                self.assertEqual(out["event_fault_version"],
                                 EVENT_FAULT_VERSION_UNKNOWN)
                self.assertEqual(out["type_status"], TYPE_UNKNOWN_VERSION)


class TestTheThreeExclusiveCodes(unittest.TestCase):
    """'0F'H/'1C'H/'3A'H: what each version's own text says, nothing more."""

    V2_MEANINGS = {0x0F: "GNSS anomaly",
                   0x1C: "Inconsistency between motion data and stored driver activity data",
                   0x3A: "Internal sensor fault"}

    def test_version_1_calls_them_reserved(self):
        for code, meaning in self.V2_MEANINGS.items():
            with self.subTest(code=hex(code)):
                for is_event, record_type in ((True, 0x15), (False, 0x18)):
                    record = (_event_record(event_type=code) if is_event
                              else _fault_record(fault_type=code))
                    out = _decode(record_type, record, EVENT_FAULT_VERSION_1)
                    self.assertEqual(out["type_status"], TYPE_RESERVED)
                    self.assertEqual(out["description"],
                                     f"Reserved for future use (0x{code:02X})")
                    self.assertNotEqual(out["description"], meaning)
                    self.assertTrue(out["normative"])

    def test_version_2_names_them(self):
        for code, meaning in self.V2_MEANINGS.items():
            with self.subTest(code=hex(code)):
                out = _decode(0x15, _event_record(event_type=code),
                              EVENT_FAULT_VERSION_2)
                self.assertEqual(out["type_status"], TYPE_ASSIGNED)
                self.assertEqual(out["description"], meaning)
                self.assertNotIn("event_type_code", out["low_confidence_fields"])

    def test_unknown_version_is_neither_v2_nor_reserved(self):
        for code, meaning in self.V2_MEANINGS.items():
            with self.subTest(code=hex(code)):
                event = _decode(0x15, _event_record(event_type=code))
                fault = _decode(0x18, _fault_record(fault_type=code))
                self.assertEqual(event["type_status"], TYPE_UNKNOWN_VERSION)
                self.assertEqual(fault["type_status"], TYPE_UNKNOWN_VERSION)
                self.assertEqual(event["description"], f"Unknown event (0x{code:02X})")
                self.assertEqual(fault["description"], f"Unknown fault (0x{code:02X})")
                # "Unknown" must not be presented as "definitely reserved"…
                self.assertNotIn("Reserved", event["description"])
                self.assertNotIn("Reserved", fault["description"])
                # …nor as the version-2 meaning.
                self.assertNotEqual(event["description"], meaning)

    def test_generation_1_sections_never_upgrade(self):
        # '03'H carries Annex 1B data; this change does not pretend to know its
        # table, so a Gen2-only code stays unknown there too.
        stream = b"\x76\x03" + _record_array(0x15, [_event_record(event_type=0x0F)])
        results = {}
        walk_vu_record_arrays(stream, results)
        self.assertEqual(results["events"][0]["event_fault_version"],
                         EVENT_FAULT_VERSION_UNKNOWN)
        self.assertEqual(results["events"][0]["type_status"], TYPE_UNKNOWN_VERSION)


class TestSharedCodes(unittest.TestCase):
    """Codes both versions define keep their exact description."""

    SHARED = {0x00: "No further details", 0x04: "Driving without an appropriate card",
              0x0B: "Time conflict (GNSS vs VU internal clock)",
              0x0E: "Communication error with the external GNSS facility",
              0x1B: "External GNSS facility certificate expired",
              0x20: "Sensor security breach attempt, no further details",
              0x25: "Sensor hardware sabotage",
              0x31: "VU internal fault", 0x39: "ITS interface fault",
              0x40: "Card fault, no further details"}

    def test_shared_codes_are_identical_in_every_version(self):
        for code, meaning in self.SHARED.items():
            for version in (EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2,
                            EVENT_FAULT_VERSION_UNKNOWN):
                with self.subTest(code=hex(code), version=version):
                    out = _decode(0x15, _event_record(event_type=code), version)
                    self.assertEqual(out["description"], meaning)
                    self.assertEqual(out["type_status"], TYPE_ASSIGNED)

    def test_the_generic_describers_keep_their_old_behaviour(self):
        # Card and generation-1 decoders call these with no section context;
        # the default wording must not change under them.
        self.assertEqual(describe_event(0x0F), "GNSS anomaly")
        self.assertEqual(describe_fault(0x3A), "Internal sensor fault")
        self.assertEqual(describe_event(0x0F),
                         event_codes.describe_event_fault_type(
                             0x0F, True, EVENT_FAULT_VERSION_2))
        self.assertEqual(describe_fault(0x99), "Manufacturer specific fault (0x99)")


class TestMixedSections(unittest.TestCase):
    """Each section decodes against its own table, in the same download."""

    def test_v1_and_v2_sections_side_by_side(self):
        stream = (b"\x76\x23"
                  + _record_array(0x15, [_event_record(event_type=0x0F),
                                         _event_record(event_type=0x04)])
                  + _record_array(0x18, [_fault_record(fault_type=0x3A)])
                  + b"\x76\x33"
                  + _record_array(0x18, [_fault_record(fault_type=0x3A)])
                  + _record_array(0x15, [_event_record(event_type=0x0F)]))
        results = {}
        walk_vu_record_arrays(stream, results)

        v1_events = results["events"][:2]
        v2_event = results["events"][2]
        v1_fault, v2_fault = results["faults"]

        self.assertEqual([r["event_fault_version"] for r in v1_events],
                         [EVENT_FAULT_VERSION_1] * 2)
        self.assertEqual(v1_events[0]["description"], "Reserved for future use (0x0F)")
        # A shared code in the same version-1 section keeps its meaning.
        self.assertEqual(v1_events[1]["description"],
                         "Driving without an appropriate card")
        self.assertEqual(v1_fault["event_fault_version"], EVENT_FAULT_VERSION_1)
        self.assertEqual(v1_fault["description"], "Reserved for future use (0x3A)")

        self.assertEqual(v2_event["event_fault_version"], EVENT_FAULT_VERSION_2)
        self.assertEqual(v2_event["description"], "GNSS anomaly")
        self.assertEqual(v2_fault["event_fault_version"], EVENT_FAULT_VERSION_2)
        self.assertEqual(v2_fault["description"], "Internal sensor fault")

    def test_every_emitted_record_carries_its_section_version(self):
        stream = (b"\x76\x23" + _record_array(0x15, [_event_record()])
                  + b"\x76\x33" + _record_array(0x18, [_fault_record()]))
        results = {}
        walk_vu_record_arrays(stream, results)
        self.assertEqual(results["events"][0]["event_fault_version"],
                         EVENT_FAULT_VERSION_1)
        self.assertEqual(results["faults"][0]["event_fault_version"],
                         EVENT_FAULT_VERSION_2)


class TestThroughTheEngine(unittest.TestCase):
    """Real ``TachoParser``: the file's generation must not decide for a section."""

    def _write(self, data):
        handle = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
        handle.write(data)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_a_g22_file_with_a_version_1_events_section_decodes_as_version_1(self):
        # The leading '33'H marker makes the whole file "G2.2 (Smart V2)"; the
        # Events&Faults section is a '23'H (version 1) one, as a version-2 unit
        # may legitimately produce for a legacy request.
        data = (b"\x76\x33" + _record_array(0x0A, [b"WDB9066571P123456"])
                + b"\x76\x23" + _record_array(0x15, [_event_record(event_type=0x0F)])
                + b"\x76\x33" + _record_array(0x18, [_fault_record(fault_type=0x3A)]))
        results = TachoParser(self._write(data)).parse()

        self.assertTrue(results["metadata"]["generation"].startswith("G2.2"),
                        results["metadata"]["generation"])
        event, = results["events"]
        fault, = results["faults"]
        self.assertEqual(event["source"], "vu_recordarray")
        self.assertEqual(event["event_fault_version"], EVENT_FAULT_VERSION_1)
        self.assertEqual(event["type_status"], TYPE_RESERVED)
        self.assertEqual(event["description"], "Reserved for future use (0x0F)")
        self.assertEqual(fault["event_fault_version"], EVENT_FAULT_VERSION_2)
        self.assertEqual(fault["description"], "Internal sensor fault")
        # Neither verdict changed: the structures are conformant either way.
        self.assertTrue(event["normative"] and fault["normative"])
        self.assertEqual(results["metadata"]["decode_paths"],
                         {"vu_events": {"normative": 1, "non_normative": 0},
                          "vu_faults": {"normative": 1, "non_normative": 0}})
        # Manufacturer identity survives the engine hop intact.
        for record in (event, fault):
            self.assertEqual(record["manufacturer_code"], REGISTERED_CODE)
            self.assertEqual(record["manufacturer"], REGISTERED_NAME)
            self.assertEqual(record["manufacturer_error_code"],
                             SYNTHETIC_ERROR.hex())


class TestIsolatedRoutes(unittest.TestCase):
    """No section, no version — and the tag adapter does not invent one."""

    def test_an_isolated_record_reports_an_unknown_version(self):
        # `decode_vu_record` is the tag-adapter entry point: one array, no TREP.
        out = decode_vu_record(0x15, _event_record(event_type=0x0F))
        self.assertEqual(out["event_fault_version"], EVENT_FAULT_VERSION_UNKNOWN)
        self.assertEqual(out["type_status"], TYPE_UNKNOWN_VERSION)
        self.assertEqual(out["description"], "Unknown event (0x0F)")
        # The manufacturer half is shared logic, so it is still resolved.
        self.assertEqual(out["manufacturer"], REGISTERED_NAME)
        self.assertEqual(out["manufacturer_status"], MANUFACTURER_STATUS_REGISTERED)
        self.assertEqual(out["manufacturer_error_code"], SYNTHETIC_ERROR.hex())

    def test_the_tag_adapter_has_no_events_faults_tag(self):
        # There is deliberately no 0x05xx tag for VuEventRecord/VuFaultRecord, so
        # the tag route cannot reach them and cannot guess a version for them.
        self.assertNotIn(0x15, vu_dispatcher.VU_TAG_RECORD_TYPES.values())
        self.assertNotIn(0x18, vu_dispatcher.VU_TAG_RECORD_TYPES.values())

    def test_an_unrelated_tag_route_gains_no_version_bookkeeping(self):
        from core.decoders.vu_g2 import parse_g2_vu_record
        results = {}
        # 0x0530 → VuPowerSupplyInterruptionRecord (0x1F), a record with no
        # EventFaultType assignment of its own.
        body = b"\x00" * 87
        parse_g2_vu_record(_record_array(0x1F, [body]), results, 0x0530)
        records = results["power_interruptions"]
        self.assertEqual(len(records), 1)
        for key in HIDDEN_VERSION_KEYS:
            self.assertNotIn(key, records[0])


class TestManufacturerIdentity(unittest.TestCase):
    """The code byte is identity (official registry); the 3 bytes stay opaque."""

    #: All 65 codes assigned in the Commission's registry
    #: (https://dtc.jrc.europa.eu/dtc_manufacturer_code.php), transcribed as a
    #: fixture so a wrong or missing entry in the table is caught.
    OFFICIAL_CODES = frozenset({
        0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
        0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x28, 0x29,
        0x30, 0x32, 0x35, 0x36, 0x38, 0x39,
        0x40, 0x43, 0x44, 0x45, 0x48, 0x49, 0x4A,
        0x50, 0x51, 0x52, 0x53, 0x55,
        0x60, 0x61, 0x68, 0x69,
        0x78, 0x79,
        0x81, 0x82, 0x84, 0x88, 0x89, 0x8A,
        0x98,
        0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF,
        0xB0, 0xB1,
        0xD8,
        0xE0,
    })

    #: A few entries checked by name against the same page (the examples the
    #: project's own documentation cites, plus two non-Latin-1 spellings).
    OFFICIAL_NAMES = {
        0x10: "Actia S.A.",
        0x53: "Intellic Germany GmbH - ZF Group CVS (formerly Intellic GmbH)",
        0x18: "BARBÉ S.R.L.",
        0xA1: "AUMOVIO Germany GmbH (formerly Continental Automotive Technologies "
              "GmbH - Continental Automotive GmbH - Siemens AG - Siemens VDO "
              "Automotive - Siemens Automotive)",
        0xA2: "Stoneridge Electronics AB",
        0xE0: "Turker Roll Paper Trade",
    }

    def test_the_table_holds_exactly_the_65_assigned_codes(self):
        self.assertEqual(frozenset(MANUFACTURER_CODES), self.OFFICIAL_CODES)
        self.assertEqual(len(MANUFACTURER_CODES), 65)

    def test_known_names_match_the_registry(self):
        for code, name in self.OFFICIAL_NAMES.items():
            with self.subTest(code=hex(code)):
                self.assertEqual(manufacturer_name(code), name)

    def test_a_registered_code_identifies_the_record_manufacturer(self):
        out = _decode(0x15, _event_record(), EVENT_FAULT_VERSION_2)
        self.assertEqual(out["manufacturer_code"], REGISTERED_CODE)
        self.assertEqual(out["manufacturer"], REGISTERED_NAME)
        self.assertEqual(out["manufacturer_status"], MANUFACTURER_STATUS_REGISTERED)
        # Identified, so no longer presented as an uninterpreted value…
        self.assertNotIn("manufacturer_code", out["low_confidence_fields"])
        # …while the proprietary payload stays raw and low confidence.
        self.assertIn("manufacturer_error_code", out["low_confidence_fields"])
        self.assertEqual(out["manufacturer_error_code"], "010203")

    def test_unassigned_and_sentinel_bytes_stay_unknown(self):
        # 0x00/0xFF are "no information" sentinels; 0x27/0xF0 are unassigned.
        for code in (0x00, 0x27, 0xF0, 0xFF):
            with self.subTest(code=hex(code)):
                self.assertIsNone(manufacturer_name(code))
                out = _decode(0x18, _fault_record(manufacturer_code=code),
                              EVENT_FAULT_VERSION_2)
                self.assertEqual(out["manufacturer_code"], code)
                self.assertIsNone(out["manufacturer"])
                self.assertEqual(out["manufacturer_status"],
                                 MANUFACTURER_STATUS_NOT_REGISTERED)
                self.assertIn("manufacturer_code", out["low_confidence_fields"])

    def test_no_error_code_is_invented_from_the_raw_bytes(self):
        # §2.95 leaves the 3 bytes to the manufacturer: no "000000 ⇒ no error",
        # no dashboard/DTC number, no mapping at all.
        for raw in (b"\x00\x00\x00", b"\xff\xff\xff", b"\xde\xad\xbe"):
            with self.subTest(raw=raw.hex()):
                out = _decode(0x15, _event_record(error=raw), EVENT_FAULT_VERSION_2)
                self.assertEqual(out["manufacturer_error_code"], raw.hex())
                self.assertIn("manufacturer_error_code", out["low_confidence_fields"])

    def test_only_the_manufacturer_fields_are_version_independent(self):
        record = _event_record(manufacturer_code=0x81)
        decoded = {v: _decode(0x15, record, v)
                   for v in (EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2,
                             EVENT_FAULT_VERSION_UNKNOWN)}
        names = {d["manufacturer"] for d in decoded.values()}
        self.assertEqual(names, {manufacturer_name(0x81)})


class TestRecordShapeInvariants(unittest.TestCase):
    """Nothing about the other verdicts/fallbacks moved with this change."""

    def test_a_record_shorter_than_the_prefix_is_not_decoded(self):
        # Nine bytes are not even the type + purpose + two TimeReals: the
        # decoder returns nothing, and the record keeps the raw view instead of
        # a fabricated type/version pair.
        for record_type, record, is_event in ((0x15, _event_record()[:9], True),
                                              (0x18, _fault_record()[:9], False)):
            with self.subTest(record=hex(record_type)):
                self.assertIsNone(
                    decode_event_fault_record(record, is_event, EVENT_FAULT_VERSION_2))
                out = _decode(record_type, record, EVENT_FAULT_VERSION_2)
                self.assertNotIn("type_code", out)
                self.assertNotIn("event_fault_version", out)
                self.assertIn("raw_hex", out)

    def test_a_wrongly_sized_record_keeps_the_prefix_view_and_its_version(self):
        for record_type, record, message in (
                (0x15, _event_record() + b"\x00", "record is 92 bytes, the standard defines 91"),
                (0x18, _fault_record()[:-1], "record is 89 bytes, the standard defines 90")):
            for version in (EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2,
                            EVENT_FAULT_VERSION_UNKNOWN):
                with self.subTest(record=hex(record_type), version=version):
                    out = _decode(record_type, record, version)
                    self.assertFalse(out["normative"])
                    self.assertEqual(out["confidence"], "low")
                    self.assertIn(message, out["conformance_reason"])
                    self.assertIn("raw_tail_hex", out)
                    # No field offset is trusted, so neither is the manufacturer.
                    self.assertEqual(out["low_confidence_fields"],
                                     ["manufacturer_code", "manufacturer_error_code"])
                    self.assertNotIn("manufacturer", out)
                    self.assertEqual(out["event_fault_version"], version)

    def test_time_conflict_rule_is_version_independent(self):
        for version in (EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2,
                        EVENT_FAULT_VERSION_UNKNOWN):
            with self.subTest(version=version):
                conflict = _decode(0x15, _event_record(event_type=0x0B, end=BEGIN - 60),
                                   version)
                self.assertTrue(conflict["normative"])
                self.assertEqual(conflict["end_semantics"], "GNSS date and time")
                other = _decode(0x15, _event_record(event_type=0x04, end=BEGIN - 60),
                                version)
                self.assertFalse(other["normative"])
                self.assertIn("end time precedes begin time",
                              other["conformance_reason"])

    def test_similar_events_flag_is_appended_after_the_manufacturer_fields(self):
        out = _decode(0x15, _event_record(similar=0), EVENT_FAULT_VERSION_2)
        self.assertEqual(out["low_confidence_fields"],
                         ["manufacturer_error_code", "similar_events"])

    def test_a_too_short_event_in_a_section_is_skipped_not_guessed(self):
        stream = b"\x76\x33" + _record_array(0x15, [b"\x0f" * 5])
        results = {}
        walk_vu_record_arrays(stream, results)
        self.assertEqual(results.get("events", []), [])


class TestReportingSurface(unittest.TestCase):
    """JSON bookkeeping stays out of the tables; no new untranslated text."""

    def _records(self):
        stream = (b"\x76\x23" + _record_array(0x15, [_event_record(event_type=0x0F)])
                  + b"\x76\x33" + _record_array(0x18, [_fault_record(fault_type=0x3A)]))
        results = {}
        walk_vu_record_arrays(stream, results)
        return results["events"] + results["faults"]

    def test_new_bookkeeping_keys_are_hidden_on_both_paths(self):
        for key in HIDDEN_VERSION_KEYS:
            self.assertIn(key, REPORT_HIDDEN_KEYS)
            self.assertIn(key, gui.HIDDEN_KEYS)
        for records in (self._records(),):
            for name, columns in (("report", visible_columns(records)),
                                  ("gui", gui._columns_for(records, None))):
                with self.subTest(path=name):
                    for key in HIDDEN_VERSION_KEYS:
                        self.assertNotIn(key, columns)

    def test_the_manufacturer_column_reuses_the_existing_label(self):
        records = self._records()
        for columns in (visible_columns(records),
                        gui._columns_for(records, None)):
            self.assertIn("manufacturer", columns)
            self.assertEqual(humanize_key("manufacturer"), "Manufacturer")

    def test_the_json_keeps_every_raw_value(self):
        for record in self._records():
            self.assertIsInstance(record["manufacturer_code"], int)
            self.assertRegex(record["manufacturer_error_code"], r"^[0-9a-f]{6}$")
            self.assertIn(record["event_fault_version"],
                          (EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2))
            self.assertIn(record["type_status"],
                          (TYPE_ASSIGNED, TYPE_RESERVED, TYPE_MANUFACTURER_SPECIFIC,
                           TYPE_UNKNOWN_VERSION))
            self.assertIn("low_confidence_fields", record)

    def test_the_new_wording_already_exists_in_every_catalog(self):
        # Only three heads are new to a description ("Reserved for future use",
        # "Unknown event", "Unknown fault"); each must be a msgid in all 33
        # catalogs, or a translated UI would leak English.
        self.assertEqual(len(CATALOGS), 33, CATALOGS)
        heads = set()
        for code in range(0x100):
            for is_event in (True, False):
                for version in (EVENT_FAULT_VERSION_1,
                                EVENT_FAULT_VERSION_UNKNOWN):
                    text = event_codes.describe_event_fault_type(code, is_event, version)
                    baseline = describe_event(code) if is_event else describe_fault(code)
                    if text != baseline:
                        heads.add(text.rsplit(" (0x", 1)[0])
        self.assertEqual(heads, {"Reserved for future use",
                                 "Unknown event", "Unknown fault"})
        for path in CATALOGS:
            with open(path, encoding="utf-8") as handle:
                msgids = {m.group(1) for m in
                          re.finditer(r'^msgid "(.*)"$', handle.read(), re.M)}
            for head in heads | {"Manufacturer"}:
                with self.subTest(catalog=os.path.basename(os.path.dirname(
                        os.path.dirname(path))), head=head):
                    self.assertIn(head, msgids)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
