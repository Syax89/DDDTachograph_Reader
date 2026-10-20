"""Deterministic VU RecordArray dispatcher (Gen2 / Gen2.2).

Vehicle Unit downloads are NOT organised by the 0x05xx tags used in driver-card
files. They are a stream of **RecordArrays indexed by recordType** (Annex 1C
Appendix 7), grouped into TREP sections each prefixed by a 2-byte container
marker ``0x76 0xNN`` and terminated by a SignatureRecordArray (recordType 0x08):

    0x7631  Overview                0x7632  Activities (one section per day)
    0x7633  Events & Faults         0x7634  Detailed speed
    (0x762x are the Gen2 equivalents.)

RecordArray header = recordType(1) + recordSize(2 BE) + noOfRecords(2 BE).

This module owns the canonical VU RecordArray semantic API: full VU streams
use :func:`walk_vu_record_arrays`, while the legacy tag-keyed adapter uses
:func:`decode_vu_tag_record` for an already-isolated array. recordType→size has been confirmed empirically
against the real files in ``DDD/`` (see ``specs/vu_recordtype_map.md``). Records
with a confirmed byte-level structure are fully decoded; the rest are surfaced
raw with an explicit ``confidence`` flag rather than guessed values.

The walker also reconstructs daily activity records (date + odometer + activity
changes) in the same shape the rest of the app consumes via ``results['activities']``,
which the legacy heuristic TREP parser failed to produce for Gen2/2.2 VU files.
"""
import struct
from datetime import datetime, timezone

from core.utils.logger import get_logger
from core import decoders
from core.decoders.common import (
    decode_extended_serial_number, decode_previous_vehicle_info,
    describe_manual_input_flag, is_known_nation, serial_text,
    with_serial_text)
from core.utils.constants import (
    RECORD_ARRAY_MAX_RECORDS, RECORD_ARRAY_MAX_SIZE, VU_MAX_TOTAL_RECORDS)
from core.utils.event_codes import (
    EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2, EVENT_FAULT_VERSION_UNKNOWN,
    EVENT_FAULT_VERSIONS, describe_event_fault_type,
    describe_fault, describe_calibration_purpose, describe_control_type,
    describe_record_purpose, event_fault_type_status, TYPE_ASSIGNED)
from core.utils.manufacturer_codes import (
    MANUFACTURER_STATUS_NOT_REGISTERED, MANUFACTURER_STATUS_REGISTERED,
    manufacturer_name)

_log = get_logger(__name__)

# recordType → (human name, confidence). Names are AUTHORITATIVE: they were
# obtained by matching the observed recordType order in real files against the
# RecordArray order the regulation mandates per TREP (Appendix 7, DDP_029..033),
# then cross-checked by size. confidence reflects how fully each record is
# *decoded* here:
#   high   : structure decoded and confirmed against spec + real data
#   medium : key fields decoded, remaining bytes surfaced raw
#   low    : identified by name/size, body surfaced raw (not yet field-decoded)
RECORD_TYPES = {
    0x01: ("VuActivityDailyRecord", "high"),       # ActivityChangeInfo (2)
    0x02: ("CardSlotsStatus", "high"),             # (1)
    0x03: ("CurrentDateTime", "high"),             # TimeReal (4)
    0x04: ("MemberStateCertificate", "low"),       # (205) raw cert
    0x05: ("OdometerValueMidnight", "high"),       # OdometerShort (3)
    0x06: ("DateOfDayDownloaded", "high"),         # TimeReal (4)
    0x07: ("SensorPaired", "low"),                 # G1 SensorPaired (20) — Annex 1C §2.120
    0x08: ("SignatureRecord", "high"),             # ECC (64)
    0x09: ("VuSpecificConditionRecord", "high"),   # entryTime(4)+type(1)=5
    0x0A: ("VehicleIdentificationNumber", "medium"),
    0x0B: ("VehicleRegistrationNumber", "medium"), # G2 (14)
    0x0C: ("VuCalibrationRecord", "low"),          # (222/252)
    0x0D: ("VuCardIWRecord", "low"),               # (131) §2.177 full decode
    0x0E: ("VuCardRecord", "high"),                # (45) cardAndGen+serial+ver+number
    0x0F: ("VUCertificate", "low"),                # (205) raw cert
    0x10: ("VuCompanyLocksRecord", "low"),         # (99)
    0x11: ("VuControlActivityRecord", "low"),      # (32)
    0x12: ("VuDetailedSpeedBlock", "low"),         # detailed speed
    0x13: ("VuDownloadablePeriod", "high"),        # (8)
    0x14: ("VuDownloadActivityData", "medium"),    # (59)
    0x15: ("VuEventRecord", "high"),               # (91) §2.198 full decode
    0x16: ("VuGNSSADRecord", "high"),              # (56/57) GNSS accumulated driving
    0x17: ("VuITSConsentRecord", "low"),           # (20)
    0x18: ("VuFaultRecord", "high"),               # (90) §2.201 full decode
    0x19: ("VuIdentification", "low"),             # (126/138)
    0x1A: ("VuOverSpeedingControlData", "high"),   # (9)
    0x1B: ("VuOverSpeedingEventRecord", "medium"), # (32)
    0x1C: ("VuPlaceDailyWorkPeriodRecord", "high"),# (40/41)
    0x1D: ("VuTimeAdjustmentGNSSRecord", "high"),  # (8) oldTimeValue+newTimeValue — Annex 1C §2.120
    0x1E: ("VuTimeAdjustmentRecord", "high"),      # (99) old+new+name+addr+cardAndGen
    0x1F: ("VuPowerSupplyInterruptionRecord", "medium"),  # (87)
    0x20: ("VuSensorPairedRecord", "medium"),      # (28) serial+approval+date
    0x21: ("VuSensorExternalGNSSCoupledRecord", "medium"),  # (28) serial+approval+date
    0x22: ("VuBorderCrossingRecord", "high"),      # (55)
    0x23: ("VuLoadUnloadRecord", "high"),          # (58)
    0x24: ("VehicleRegistrationIdentification", "medium"),  # G2.2 (15)
    # Codes above the normative Value-assignment (0x24) have NO name in Annex
    # 1C §2.120: 0x25..0x7F are RFU, 0x80..0xFF manufacturer-specific. The
    # entries below are observed meanings on specific units, kept only as a
    # hint — ``is_normative_record_type`` reports them as unmapped (D2-005).
    0x29: ("RFU_0x29_Slot2Activity", "medium"),
    0x40: ("RFU_0x40_DetailedSpeedSample", "low"),
    0x60: ("RFU_0x60_Terminator", "low"),
}

# Annex 1C §2.120 RecordType Value-assignment enumerates 36 record types which,
# in declaration order, occupy the contiguous codes 0x01..0x24. Any code above
# 0x24 is RFU or manufacturer-specific and therefore has no normative name:
# such records must be surfaced as unmapped, never labelled as if defined.
NORMATIVE_RECORD_TYPES = frozenset(range(0x01, 0x25))


#: RecordArray order per generation-2 transfer, read from Appendix 7 of
#: Reg. (EU) 2021/1228 (the amending act prints the tables as *text*):
#:
#:   DDP_029  Overview        TREP 21 / 31
#:   DDP_030  Activities      TREP 22 / 32
#:   DDP_031  Events&Faults   TREP 23 / 33
#:   DDP_032  Detailed speed  TREP 24
#:   DDP_033  Technical data  TREP 25 / 35
#:
#: Each slot lists the record types the source allows there. The only
#: multi-valued slot is the vehicle registration of the Overview: DDP_029 names
#: ``VehicleRegistrationNumberRecordArray`` for TREP 31 while the Appendix 1
#: data dictionary (and every observed download) uses
#: ``VehicleRegistrationIdentification`` (0x24, 15 bytes). The conflict is
#: carried here instead of being resolved by preference.
#:
#: A header with ``noOfRecords = 0`` is *normative* for an empty array ("If the
#: section is empty, an array header with noOfRecords = 0 is sent"), so a
#: zero-record array is reported, never treated as a defect.
TREP_ARRAY_SCHEMA = {
    0x21: ((0x04,), (0x0F,), (0x0A,), (0x0B, 0x24), (0x03,), (0x13,), (0x02,),
           (0x14,), (0x10,), (0x11,), (0x08,)),
    0x31: ((0x04,), (0x0F,), (0x0A,), (0x0B, 0x24), (0x03,), (0x13,), (0x02,),
           (0x14,), (0x10,), (0x11,), (0x08,)),
    0x22: ((0x06,), (0x05,), (0x0D,), (0x01,), (0x1C,), (0x16,), (0x09,),
           (0x08,)),
    0x32: ((0x06,), (0x05,), (0x0D,), (0x01,), (0x1C,), (0x16,), (0x09,),
           (0x22,), (0x23,), (0x08,)),
    0x23: ((0x18,), (0x15,), (0x1A,), (0x1B,), (0x1E,), (0x08,)),
    0x33: ((0x18,), (0x15,), (0x1A,), (0x1B,), (0x1E,), (0x08,)),
    0x24: ((0x12,), (0x08,)),
    0x25: ((0x19,), (0x20,), (0x21,), (0x0C,), (0x0E,), (0x17,), (0x1F,),
           (0x08,)),
    0x35: ((0x19,), (0x20,), (0x21,), (0x0C,), (0x0E,), (0x17,), (0x1F,),
           (0x08,)),
}


#: A SignatureRecordArray holds exactly one record (DDP_029..DDP_033: "Signature
#: RecordArray ECC signature of all preceding data"), and its record size is the
#: signature length the curve allows: 64 bytes for P-256, 96 for P-384 and 128 for
#: P-512 (Appendix 1 ``Signature``; the exact per-curve mapping lives in Appendix
#: 11, which is not read here). The range is checked, never a single constant.
SIGNATURE_RECORD_SIZE_RANGE = (64, 132)


def validate_section_schema(trep, observed, signature_size=None):
    """Check one section against the Appendix-7 array order of *trep*.

    *observed* is a sequence of ``(record_type, no_of_records)`` in file order and
    *signature_size* the declared recordSize of the signature array. The result is
    descriptive: ``status`` is ``complete`` only when every prescribed array is
    present, exactly once, in order, closed by a well-formed signature array —
    duplicates, unexpected arrays, an out-of-order slot and a malformed signature
    all make it ``incomplete``. Nothing here suppresses a record: the section has
    already been decoded by the time this runs, and a finding is an INTEGRITY
    observation, never a reason to re-scan the bytes.
    """
    schema = TREP_ARRAY_SCHEMA.get(trep)
    if schema is None:
        return {"status": "not applicable (no RecordArray list in Appendix 7)",
                "missing_arrays": [], "out_of_order": [], "unexpected_arrays": [],
                "duplicate_arrays": [], "zero_record_arrays": [],
                "signature_problem": None}
    types = [rt for rt, _nr in observed]
    position = 0
    missing, out_of_order = [], []
    for slot in schema:
        match = next((rt for rt in slot if rt in types), None)
        if match is None:
            missing.append(f"0x{slot[0]:02X}")
            continue
        idx = types.index(match)
        if idx < position:
            out_of_order.append(f"0x{match:02X}")
        else:
            position = idx
    allowed = {rt for slot in schema for rt in slot}
    unexpected = [f"0x{rt:02X}" for rt in types if rt not in allowed]
    # An array type appears at most once per section: two 0x15 arrays are not the
    # "events" the standard prescribes.
    duplicates = sorted({f"0x{rt:02X}" for rt in types if types.count(rt) > 1})
    signature_problem = None
    if 0x08 in types:
        sig_counts = [nr for rt, nr in observed if rt == 0x08]
        if len(sig_counts) > 1:
            signature_problem = f"duplicate signature arrays ({len(sig_counts)})"
        elif sig_counts[0] != 1:
            signature_problem = f"noOfRecords={sig_counts[0]}"
        elif signature_size is not None and not (
                SIGNATURE_RECORD_SIZE_RANGE[0] <= signature_size
                <= SIGNATURE_RECORD_SIZE_RANGE[1]):
            signature_problem = f"recordSize={signature_size}"
    elif 0x08 in allowed:
        signature_problem = "signature array missing"
    complete = not (missing or out_of_order or unexpected or duplicates
                    or signature_problem)
    return {
        "status": "complete" if complete else "incomplete",
        "missing_arrays": missing,
        "out_of_order": out_of_order,
        "unexpected_arrays": unexpected,
        "duplicate_arrays": duplicates,
        "signature_problem": signature_problem,
        "zero_record_arrays": [f"0x{rt:02X}" for rt, nr in observed if nr == 0],
    }


def is_normative_record_type(record_type: int) -> bool:
    """True when ``record_type`` is one defined by the Annex 1C enumeration."""
    return record_type in NORMATIVE_RECORD_TYPES


#: Byte length of the full Generation 2 VuCardIWRecord (Annex 1C §2.177).
#: Generation 1 carries the same structure in 129 bytes because its
#: FullCardNumber is 18 bytes (no generation byte) and its PreviousVehicleInfo is
#: 19 bytes (no vuGeneration).
CARD_IW_RECORD_SIZE = 131

# Canonical result-list names for record types shared by full VU streams and
# tag-keyed RecordArray payloads. Keep consumer-facing key ownership here.
VU_RECORD_RESULT_KEYS = {
    0x22: "border_crossings",
    0x23: "load_unload_records",
    0x1C: "places",
    0x09: "specific_conditions",
    0x16: "gnss_ad_records",
    0x1B: "overspeeding_events",
    0x1A: "overspeeding_control",
    0x1F: "power_interruptions",
    0x17: "its_consents",
    0x1E: "time_adjustments",
    0x1D: "time_adj_gnss",
    0x10: "company_locks",
    0x11: "control_activities",
    0x19: "vu_identifications",
    0x0C: "calibrations",
    0x0D: "card_iw_records",
    0x0E: "card_records",
    0x13: "downloadable_periods",
    0x14: "download_activities",
    0x20: "sensor_pairings",
    0x21: "sensor_gnss_couplings",
    0x12: "speed_blocks",
    # recordType 0x29 is an ActivityChangeInfo that the VU partitions into the
    # co-driver slot on some Gen2.2 models (observed on Stoneridge V6006). It
    # is decoded by ``_decode_record``; without a result key it was decoded and
    # then silently discarded (XB-F6 / D2-006).
    0x29: "co_driver_activities",
}

# 0x05xx tags are used only by the tag-keyed adapter. The mapped record types
# share the full-VU record semantics above; tag-only variants are handled by
# ``decode_vu_tag_record`` below.
VU_TAG_RECORD_TYPES = {
    0x0509: 0x0E,
    0x050A: 0x0D,
    0x050B: 0x13,
    0x050D: 0x1E,
    0x050F: 0x10,
    0x0510: 0x20,
    0x0511: 0x21,
    0x0512: 0x17,
    0x052C: 0x12,
    0x052D: 0x1B,
    0x052E: 0x1A,
    0x0530: 0x1F,
    0x0532: 0x21,
    0x0533: 0x20,
}

VU_TAG_RESULT_KEYS = {
    tag: VU_RECORD_RESULT_KEYS[record_type]
    for tag, record_type in VU_TAG_RECORD_TYPES.items()
}
VU_TAG_RESULT_KEYS.update({
    0x052B: "vu_controller",
    0x052F: "time_adj_gnss",
    0x0531: "sensor_faults",
})

# TREP marker (second byte after 0x76) → section name. Covers G1/G2/G2.2.
TREP_SECTIONS = {
    0x01: "Overview", 0x21: "Overview", 0x31: "Overview",
    0x02: "Activities", 0x22: "Activities", 0x32: "Activities",
    0x03: "EventsFaults", 0x23: "EventsFaults", 0x33: "EventsFaults",
    0x04: "DetailedSpeed", 0x24: "DetailedSpeed",
    0x05: "TechnicalData", 0x25: "TechnicalData", 0x35: "TechnicalData",
}

# ── TREP 00: DownloadInterfaceVersion (generation 2, version 2 only) ────────
#
# Annex 1C point 2.60a, inserted by Reg. (EU) 2021/1228 (30)(n)(j):
#
#   DownloadInterfaceVersion  Value assignment: 'aabb'H
#     'aa'H  '00'H not used, '01'H Generation 2 vehicle unit
#     'bb'H  '00'H not used, '01'H version 2 of the Generation 2 vehicle unit
#
# DDP_028a (same act, Appendix 7) describes the very same transfer as
# "Generation and version of the VU: 02,02 Hex for Generation 2, version 2".
# The two texts disagree about the coding of the two transfer bytes; the only
# observed value in a local G2.2 download is `01 01`, i.e. the point-2.60a
# assignment. No erratum was established, so the bytes are published raw with
# both readings recorded and the conflict stated, never re-coded to one of them.
TREP_DOWNLOAD_INTERFACE = 0x00
TREP_CARD_DOWNLOAD = 0x06
INTERFACE_VERSION_SIZE = 2
INTERFACE_GENERATION_CODES = {0x00: "not used",
                              0x01: "Generation 2 vehicle unit"}
INTERFACE_VERSION_CODES = {0x00: "not used",
                           0x01: "version 2 of the Generation 2 vehicle unit"}
#: DDP_028a's comment column for the same transfer (see the block comment).
INTERFACE_DDP_028A_COMMENT = "02,02 Hex for Generation 2, version 2"


def _u24(b):
    """Unsigned 24-bit big-endian."""
    return (b[0] << 16) | (b[1] << 8) | b[2]


def _s24(b):
    """Signed 24-bit big-endian (two's complement)."""
    v = _u24(b)
    return v - 0x1000000 if v & 0x800000 else v


def _iso(ts):
    if ts == 0:
        return "\u2014"
    return (datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if 946684800 <= ts <= 4102444800 else None)


def _time_fields(ts, *, key="timestamp"):
    """A stored TimeReal as three fields: value, raw integer and status.

    ``TimeReal`` is a uint32 (Annex 1C §2.51); a value the reader cannot render as a
    timestamp — zero (the "not set" value a VU writes before its clock is valid) and
    anything outside the calendar alike — is *withheld*, never used to deny that the
    record exists. The raw integer always travels so nothing is lost, and the status
    matches the generation-1 decoders for the same value.
    """
    readable = ts not in (None, 0) and bool(_iso(ts))
    return {key: _iso(ts) if readable else None, f"{key}_raw": ts,
            "time_status": "valid" if readable else "invalid"}


def decode_name(data, off, length=36):
    """Name / Address type: codePage(1) + chars(length-1). Returns the text.

    Decodes via the declared code page (defaults to latin-1) so accented
    characters in names/addresses are preserved instead of dropped.
    """
    if off + length > len(data):
        return ""
    return decoders.decode_string(data[off:off + length])


def decode_company_lock(rec):
    """VuCompanyLocksRecord (99): lockInTime(4) + lockOutTime(4) + companyName(36)
    + companyAddress(36) + companyCardNumberAndGen(19)."""
    if len(rec) < 99:
        return None
    return {
        "confidence": "medium",
        "lock_in_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "lock_out_time": _iso(struct.unpack(">I", rec[4:8])[0]),
        "company_name": decode_name(rec, 8),
        "company_address": decode_name(rec, 44),
        "company_card": decode_full_card_number_gen(rec, 80),
    }


def decode_control_activity(rec):
    """VuControlActivityRecord (32): controlType(1) + controlTime(4) +
    controlCardNumberAndGen(19) + downloadPeriodBegin(4) + downloadPeriodEnd(4)."""
    if len(rec) < 32:
        return None
    return {
        "confidence": "medium",
        "control_type": rec[0],
        "control_type_label": describe_control_type(rec[0]),
        "control_time": _iso(struct.unpack(">I", rec[1:5])[0]),
        "control_card": decode_full_card_number_gen(rec, 5),
        "download_period_begin": _iso(struct.unpack(">I", rec[24:28])[0]),
        "download_period_end": _iso(struct.unpack(">I", rec[28:32])[0]),
    }


def decode_vu_identification(rec):
    """VuIdentification (126/138): vuManufacturerName(36) + vuManufacturerAddress(36)
    + vuPartNumber(16) + vuSerialNumber(8) + software/date/generation fields."""
    if len(rec) < 96:
        return None
    out = {
        "confidence": "high",
        "manufacturer_name": decode_name(rec, 0),
        "manufacturer_address": decode_name(rec, 36),
        "part_number": _ascii(rec, 72, 16),
        # vuSerialNumber is an ExtendedSerialNumber (§2.56): the hex form is
        # kept and the four normative subfields are decoded next to it.
        "serial_number": rec[88:96].hex(),
        "serial": decode_extended_serial_number(rec, 88),
    }
    if len(rec) >= 108:
        out.update({
            "software_version": _ascii(rec, 96, 4),
            "software_installation_date": _iso(struct.unpack(">I", rec[100:104])[0]),
            "manufacturing_date": _iso(struct.unpack(">I", rec[104:108])[0]),
        })
    if len(rec) >= 124:
        out["approval_number"] = _ascii(rec, 108, 16)
    if len(rec) >= 126:
        out["vu_generation"] = rec[124]
        out["vu_ability"] = rec[125]
    # Canonical generation-2 sizes are 126 and (generation 2 version 2) 138
    # bytes. A longer record keeps its extension verbatim and is not "complete".
    canonical = 138 if len(rec) >= 138 else 126
    out["record_bytes"] = len(rec)
    out["record_complete"] = len(rec) == canonical
    if len(rec) > canonical:
        out["raw_tail_bytes"] = len(rec) - canonical
        out["raw_tail_hex"] = rec[canonical:].hex()
    if len(rec) >= 138:
        # digitalMapVersion (generation 2, version 2 only). Reg. (EU) 2021/1228
        # prints the ASN.1 as ``VuDigitalMapVersion ::= IA5String (SIZE(12))``
        # (amendment ASN.1 figure, 2.60x), so the field is exactly twelve IA5
        # characters (0x00..0x7F); the record therefore ends at byte 138.
        #
        # Only the *type* is normative here: the standard says nothing about the
        # grammar of the characters, so the value is never parsed into a
        # century/date or matched against an allow-list, and it is not claimed to
        # be an official map identifier. The existing visible reading is kept
        # unchanged and everything after byte 126 is preserved verbatim (a longer
        # record keeps its extension in raw_tail, not in this field).
        out["digital_map_version"] = _ascii(rec, 126, 12)
        out["digital_map_version_raw"] = rec[126:].hex()
        raw_field = bytes(rec[126:138])
        if all(octet <= 0x7F for octet in raw_field):
            out["digital_map_version_status"] = "valid (IA5String(12))"
        else:
            out["digital_map_version_status"] = "invalid IA5 (kept raw)"
    return out


def _ascii(data, off, length):
    return "".join(chr(b) if 0x20 <= b < 0x7F else "" for b in data[off:off + length]).strip()


#: ExtendedSerialNumber (Annex 1B §2.56 / Annex 1C §2.56) is 8 bytes:
#: serialNumber INTEGER (0..2^32-1), monthYear BCDString(SIZE(2)), type
#: OCTET STRING(SIZE(1)) — "manufacturer specific, with FFh reserved value" — and
#: manufacturerCode.
EXTENDED_SERIAL_NUMBER_SIZE = 8

#: SealRecord (SealDataVu) = equipmentType(1) + ExtendedSealIdentifier(10), where
#: ExtendedSealIdentifier ::= SEQUENCE { manufacturerCode IA5String(SIZE(2)),
#: sealIdentifier IA5String(SIZE(8)) } (Reg. (EU) 2021/1228).
SEAL_RECORD_SIZE = 11
EXTENDED_SEAL_IDENTIFIER_SIZE = 10
EXTENDED_SEAL_MANUFACTURER_LEN = 2


def _bcd_byte(value):
    """One BCD octet → its decimal value, or ``None`` when a nibble exceeds 9."""
    high, low = value >> 4, value & 0x0F
    if high > 9 or low > 9:
        return None
    return high * 10 + low





def decode_extended_seal_identifier(data):
    """Decode an ExtendedSealIdentifier (10 bytes, Reg. (EU) 2021/1228)."""
    raw = bytes(data[:EXTENDED_SEAL_IDENTIFIER_SIZE])
    if len(raw) < EXTENDED_SEAL_IDENTIFIER_SIZE:
        return {"raw_hex": raw.hex(), "record_complete": False}
    manufacturer = _ascii(raw, 0, EXTENDED_SEAL_MANUFACTURER_LEN)
    seal = _ascii(raw, EXTENDED_SEAL_MANUFACTURER_LEN,
                  EXTENDED_SEAL_IDENTIFIER_SIZE - EXTENDED_SEAL_MANUFACTURER_LEN)
    return {
        "manufacturer_code": manufacturer,
        "seal_identifier": seal,
        "record_complete": True,
    }


def _decode_seal_data(data):
    """SealDataVu: five SealRecord entries, equipmentType(1) + seal(10)."""
    records = []
    for off in range(0, min(len(data), 5 * SEAL_RECORD_SIZE), SEAL_RECORD_SIZE):
        rec = data[off:off + SEAL_RECORD_SIZE]
        if len(rec) < SEAL_RECORD_SIZE:
            break
        seal = decode_extended_seal_identifier(rec[1:])
        records.append({
            "equipment_type": rec[0],
            # The ten identifier bytes stay available as hex (the pre-existing
            # key) next to the two IA5String fields they carry.
            "extended_seal_identifier": rec[1:].hex(),
            "manufacturer_code": seal.get("manufacturer_code"),
            "seal_identifier": seal.get("seal_identifier"),
        })
    return records


def _load_type_label(code):
    return {0x00: "undefined", 0x01: "goods", 0x02: "passengers"}.get(code, "RFU")


#: VuCalibrationRecord sizes: 167 bytes is the generation-1-length base that
#: generation 2 extends with ``sealDataVu`` (55 → 222) and generation 2 version 2
#: extends again with three ExtendedSerialNumber values (24), SealDataVu (55),
#: byDefaultLoadType(1), calibrationCountry(1) and its TimeReal (4) → 252.
CALIBRATION_BASE_SIZE = 167
CALIBRATION_G2_SIZE = 222
CALIBRATION_G22_SIZE = 252


def _decode_calibration_extension(rec):
    """Decode the generation-specific tail after nextCalibrationDate.

    The variant follows the declared record size, which the regulation fixes
    (222 for generation 2, 252 for generation 2 version 2); the serial numbers
    are ExtendedSerialNumber values (§2.56) and the seal block is SealDataVu.
    Both the old hex rendering and the decoded fields are returned.
    """
    if len(rec) >= CALIBRATION_G22_SIZE:
        return {
            # One column per serial: the hex cell keeps the hex and carries the
            # compact decoded reading, so the table never has two columns for one
            # datum (the same rule as the timestamp columns).
            "sensor_serial_hex": rec[167:175].hex(),
            "sensor_serial": serial_text(decode_extended_serial_number(rec, 167)),
            "sensor_serial_decoded": decode_extended_serial_number(rec, 167),
            "sensor_gnss_serial_hex": rec[175:183].hex(),
            "sensor_gnss_serial": serial_text(decode_extended_serial_number(rec, 175)),
            "sensor_gnss_serial_decoded": decode_extended_serial_number(rec, 175),
            "rcm_serial_hex": rec[183:191].hex(),
            "rcm_serial": serial_text(decode_extended_serial_number(rec, 183)),
            "rcm_serial_decoded": decode_extended_serial_number(rec, 183),
            "seal_data_vu": _decode_seal_data(rec[191:246]),
            "by_default_load_type": rec[246],
            "by_default_load_type_label": _load_type_label(rec[246]),
            "calibration_country": decoders.get_nation(rec[247]),
            "calibration_country_timestamp": _iso(struct.unpack(">I", rec[248:252])[0]),
        }
    if len(rec) >= CALIBRATION_G2_SIZE:
        return {"seal_data_vu": _decode_seal_data(rec[167:222])}
    return {}


#: Normative VuCalibrationRecord size per section generation: generation 2 ends
#: after SealDataVu (222), generation 2 version 2 adds the three
#: ExtendedSerialNumber values and the load-type/country tail (252).
CALIBRATION_SIZE_BY_GENERATION = {"G2": CALIBRATION_G2_SIZE,
                                  "G2.2": CALIBRATION_G22_SIZE}


def decode_calibration(rec, generation=None):
    """VuCalibrationRecord — offsets confirmed against real data (recordSize 222 G2 /
    252 G2.2). Base layout (Annex 1C §2.174):
      calibrationPurpose(1) workshopName(36) workshopAddress(36)
      workshopCardNumber[FullCardNumber](18) workshopCardExpiryDate(4)
      vehicleIdentificationNumber(17) vehicleRegistrationIdentification(15)
      wVehicleCharacteristicConstant(2) kConstantOfRecordingEquipment(2)
      lTyreCircumference(2) tyreSize(15) authorisedSpeed(1)
      oldOdometerValue(3) newOdometerValue(3)
      oldTimeValue(4) newTimeValue(4) nextCalibrationDate(4) → 167
      then sealDataVu (G2) / sensorSerialNumber (G2.2) tail.
    """
    if len(rec) < CALIBRATION_BASE_SIZE:
        return None
    # The record size is normative and generation-bound: 222 for generation 2
    # and 252 for generation 2 version 2. The section's generation is the
    # authority when the caller has one — a 252-byte body inside a generation 2
    # (222) section is *not* a decoded v2 record, and vice versa. Only without a
    # section context does the record length select the variant, and then the
    # old hex rendering is kept with the variant named.
    expected = CALIBRATION_SIZE_BY_GENERATION.get(generation)
    if expected is None:
        expected = (CALIBRATION_G22_SIZE if len(rec) >= CALIBRATION_G22_SIZE
                    else CALIBRATION_G2_SIZE if len(rec) >= CALIBRATION_G2_SIZE
                    else CALIBRATION_BASE_SIZE)
        variant_source = "record length (no section context)"
    else:
        variant_source = f"section (generation {generation})"
    matches = len(rec) == expected
    out = {
        "confidence": "high" if matches else "low",
        "record_bytes": len(rec),
        "record_complete": matches,
        "calibration_variant_source": variant_source,
        # The label describes the record that was actually decoded (its own
        # size); the section's expectation is reported separately so a mismatch is
        # visible instead of a 252-byte record being called "generation 2 (222)".
        "calibration_variant": (
            "generation 2, version 2 (252)" if len(rec) >= CALIBRATION_G22_SIZE
            else "generation 2 (222)" if len(rec) >= CALIBRATION_G2_SIZE
            else "base only (167-221)"),
        "calibration_variant_expected": (
            "generation 2, version 2 (252)" if expected == CALIBRATION_G22_SIZE
            else "generation 2 (222)" if expected == CALIBRATION_G2_SIZE
            else "base only (167-221)"),
        "calibration_variant_mismatch": not matches,
        "calibration_purpose": rec[0],
        "calibration_purpose_label": describe_calibration_purpose(rec[0]),
        "workshop_name": decode_name(rec, 1),
        "workshop_address": decode_name(rec, 37),
        "workshop_card": {
            "card_type": rec[73],
            "nation": decoders.get_nation(rec[74]),
            "card_number": _ascii(rec, 75, 16),
        },
        "workshop_card_expiry": _iso(struct.unpack(">I", rec[91:95])[0]),
        "vin": _ascii(rec, 95, 17),
        "vehicle_registration": {
            "nation": decoders.get_nation(rec[112]),
            # VehicleRegistrationNumber = codePage(1) + 13 characters (§2.167);
            # the code page is kept so the plate is not silently transliterated.
            "code_page": rec[113],
            # VehicleRegistrationNumber = codePage + 13 characters: decode the
            # text through the declared code page, not just report the byte.
            "plate": decoders.decode_coded_text(rec[113:127]),
        },
        "w_vehicle_constant": struct.unpack(">H", rec[127:129])[0],
        "k_constant": struct.unpack(">H", rec[129:131])[0],
        "l_tyre_circumference": struct.unpack(">H", rec[131:133])[0],
        "tyre_size": _ascii(rec, 133, 15),
        "authorised_speed_kmh": rec[148],
        "old_odometer_km": _u24(rec[149:152]),
        "new_odometer_km": _u24(rec[152:155]),
        # The three calibration TimeReals carry a time of day: one column each,
        # rendered in the same timestamp format as the neighbouring tables (the
        # formatter shortens an ISO value to 'YYYY-MM-DD HH:MM'), N/A when the
        # value is unusable. No duplicate '... Full' columns.
        "old_time": _iso(struct.unpack(">I", rec[155:159])[0]),
        "new_time": _iso(struct.unpack(">I", rec[159:163])[0]),
        "next_calibration_date": _iso(struct.unpack(">I", rec[163:167])[0]),
    }
    out.update(_decode_calibration_extension(rec))
    # Every byte the normative structure does not cover is preserved verbatim:
    # nothing past 167/222/252 bytes is interpreted.
    interpreted = CALIBRATION_BASE_SIZE
    if len(rec) >= CALIBRATION_G2_SIZE:
        interpreted = CALIBRATION_G2_SIZE
    if len(rec) >= CALIBRATION_G22_SIZE:
        interpreted = CALIBRATION_G22_SIZE
    out["raw_tail_bytes"] = len(rec) - interpreted
    out["raw_tail_hex"] = rec[interpreted:].hex()
    return out


def decode_card_iw(rec):
    """VuCardIWRecord — Annex 1C §2.177, the full Generation 2 layout (131 B)::

        holderSurname(36) holderFirstNames(36)
        fullCardNumberAndGeneration(19) cardExpiryDate(4)
        cardInsertionTime(4) vehicleOdometerValueAtInsertion(3) cardSlotNumber(1)
        cardWithdrawalTime(4) vehicleOdometerValueAtWithdrawal(3)
        previousVehicleInfo(20) manualInputFlag(1)

    ``previousVehicleInfo`` (§2.118) = vehicleRegistrationIdentification(15) +
    cardWithdrawalTime(4) + vuGeneration(1) — generation 2 adds the last byte to
    the 19-byte generation 1 structure (§2.85). It describes the *previous*
    vehicle of that one insertion cycle, so it stays on the record and never
    replaces the file-level vehicle.

    A record of any other length is not a canonical VuCardIWRecord: the prefix
    that is present is still decoded (it is unchanged between the generations),
    but the record is reported incomplete/low and every byte the layout does not
    cover is preserved verbatim in ``raw_tail_hex`` instead of being interpreted.
    """
    if len(rec) < 110:
        return None
    out = {
        "confidence": "low",
        "holder_surname": decode_name(rec, 0),
        "holder_first_names": decode_name(rec, 36),
        "card": decode_full_card_number_gen(rec, 72),
        "card_expiry": _iso(struct.unpack(">I", rec[91:95])[0]),
        "insertion_time": _iso(struct.unpack(">I", rec[95:99])[0]),
        "odometer_insertion_km": _u24(rec[99:102]),
        "card_slot": rec[102],
        "withdrawal_time": _iso(struct.unpack(">I", rec[103:107])[0]),
        "odometer_withdrawal_km": _u24(rec[107:110]),
        "record_bytes": len(rec),
    }
    if len(rec) >= CARD_IW_RECORD_SIZE:
        # [110:130] PreviousVehicleInfo, [130] manualInputFlag: exact offsets.
        out.update({
            "previous_vehicle": decode_previous_vehicle_info(
                rec, 110, with_vu_generation=True),
            # Keep the raw code: the enumeration defines 0/1 only, so a non-zero
            # byte is NOT proof that the holder made manual entries.
            "manual_input_flag": rec[130],
            "manual_input_flag_meaning": describe_manual_input_flag(rec[130]),
        })
    out["record_complete"] = len(rec) == CARD_IW_RECORD_SIZE
    if len(rec) < CARD_IW_RECORD_SIZE:
        out["missing_bytes"] = CARD_IW_RECORD_SIZE - len(rec)
        out["raw_tail_hex"] = rec[110:].hex()
    elif len(rec) > CARD_IW_RECORD_SIZE:
        # An extension past the normative record size carries no Annex 1C
        # meaning here: preserved, never interpreted.
        out["raw_tail_bytes"] = len(rec) - CARD_IW_RECORD_SIZE
        out["raw_tail_hex"] = rec[CARD_IW_RECORD_SIZE:].hex()
    else:
        out["confidence"] = "high"
    return out


def decode_download_activity(rec):
    """VuDownloadActivityData (59): downloadingTime(4) + fullCardNumberAndGen(19)
    + companyOrWorkshopName(36)."""
    if len(rec) < 59:
        return None
    return {
        "confidence": "medium",
        "downloading_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "card": decode_full_card_number_gen(rec, 4),
        "company_or_workshop_name": decode_name(rec, 23),
    }


def decode_sensor_paired(rec):
    """SensorPairedRecord — G2 (28): sensorSerialNumber(8) +
    sensorApprovalNumber(16) + sensorPairingDate(4).

    Shorter variants (e.g. 20/24 bytes from some G2.2 tag-keyed arrays) keep
    the serial first and the TimeReal date last, with a shorter approval
    number in between; they are decoded with ``confidence: low`` instead of
    being dropped."""
    if len(rec) < 12:
        return None
    full = len(rec) >= 28
    approval_end = 24 if full else len(rec) - 4
    date_off = 24 if full else len(rec) - 4
    return {
        "confidence": "medium" if full else "low",
        # The hex stays (it is the column that existed); the decoded compact form
        # is appended to the same cell so the two are not two columns of the same
        # thing.
        "sensor_serial": with_serial_text(rec[0:8].hex(), rec, 0),
        "sensor_serial_extended": decode_extended_serial_number(rec, 0),
        "sensor_approval": _ascii(rec, 8, approval_end - 8),
        "pairing_date": _iso(struct.unpack(">I", rec[date_off:date_off + 4])[0]),
    }


def decode_sensor_gnss_coupled(rec):
    """SensorExternalGNSSCoupledRecord — G2 (28): sensorSerialNumber(8) +
    sensorApprovalNumber(16) + sensorCouplingDate(4).

    Shorter variants (e.g. 20 bytes from some G2.2 tag-keyed arrays) are
    decoded with the same serial-first / date-last layout, ``confidence: low``."""
    if len(rec) < 12:
        return None
    full = len(rec) >= 28
    approval_end = 24 if full else len(rec) - 4
    date_off = 24 if full else len(rec) - 4
    return {
        "confidence": "medium" if full else "low",
        # The hex stays (it is the column that existed); the decoded compact form
        # is appended to the same cell so the two are not two columns of the same
        # thing.
        "sensor_serial": with_serial_text(rec[0:8].hex(), rec, 0),
        "sensor_serial_extended": decode_extended_serial_number(rec, 0),
        "sensor_approval": _ascii(rec, 8, approval_end - 8),
        "coupling_date": _iso(struct.unpack(">I", rec[date_off:date_off + 4])[0]),
    }


def decode_vu_card_record(rec):
    """VuCardRecord (45): cardNumberAndGenerationInformation(19) +
    cardExtendedSerialNumber(8) + cardStructureVersion(2) + cardNumber(16).
    Confirmed against real G2/G2.2 VU downloads."""
    if len(rec) < 19:
        return None
    out = {"confidence": "medium", "card": decode_full_card_number_gen(rec, 0),
           "record_bytes": len(rec)}
    if len(rec) >= 45:
        # 45 bytes is the normative VuCardRecord size: an extension is kept
        # verbatim and does not make the record a complete canonical one.
        out["confidence"] = "high" if len(rec) == 45 else "medium"
        out["record_complete"] = len(rec) == 45
        out["card_extended_serial"] = with_serial_text(rec[19:27].hex(), rec, 19)
        out["card_serial"] = decode_extended_serial_number(rec, 19)
        out["card_structure_version"] = rec[27:29].hex()
        # CardStructureVersion 'aabb'H (Annex 1B §2.29): 'aa' indexes structural
        # changes, 'bb' changes in the use of the data elements of that
        # structure. Both bytes are kept as numbers next to the hex form.
        out["card_structure_version_parts"] = {
            "structure_index": rec[27], "data_elements_index": rec[28]}
        out["card_number"] = _ascii(rec, 29, 16)
        if len(rec) > 45:
            out["raw_tail_bytes"] = len(rec) - 45
            out["raw_tail_hex"] = rec[45:].hex()
    else:
        out["record_complete"] = False
        out["missing_bytes"] = 45 - len(rec)
        out["raw_tail_hex"] = rec[19:].hex()
    return out


def decode_full_card_number_gen(data, off):
    """FullCardNumberAndGeneration (19 bytes): cardType(1) + nation(1) +
    cardNumber(16) + generation(1). Confirmed against real border-crossing data."""
    if off + 19 > len(data):
        return None
    rec = data[off:off + 19]
    if rec == b"\xff" * 19:
        return {"present": False}
    card_type = rec[0]
    nation = decoders.get_nation(rec[1])
    number = _ascii(rec, 2, 16)
    generation = rec[18]
    if not number:
        # Zero/partial filler (cardType 0, generation 0xFF): no card in slot.
        return {"present": False}
    return {
        "present": True,
        "card_type": card_type,
        "nation": nation,
        "card_number": number,
        "generation": generation,
    }


def _coord_to_deg(raw):
    """Convert a signed GeoCoordinates value (±DDMM.M ×10) to decimal degrees."""
    sign = -1 if raw < 0 else 1
    v = abs(raw) / 10.0          # DDMM.M
    deg = int(v // 100)
    minutes = v - deg * 100
    return round(sign * (deg + minutes / 60.0), 5)


def decode_geo_coordinates(data, off):
    """GeoCoordinates (6 bytes): latitude(3) + longitude(3), signed int24,
    each coded as ±DDMM.M ×10 (Annex 1C §2.76). Unknown position is encoded
    as 0x7FFFFF (per coordinate); all-0xFF marks an empty/padded record.

    A coordinate that is all-0xFF (empty) on ONE axis but not the other, or a
    wholly zeroed record, is a half-erased / cleared fix — it must NOT be
    published as a real position near Null Island.
    """
    if off + 6 > len(data):
        return None
    lat_raw = data[off:off + 3]
    lon_raw = data[off + 3:off + 6]
    _empty = b"\xff\xff\xff"
    _unknown = b"\x7f\xff\xff"
    # No fix if either axis carries the empty (all-FF) marker or the
    # per-coordinate "unknown position" sentinel 0x7FFFFF (§2.76).
    if lat_raw in (_empty, _unknown) or lon_raw in (_empty, _unknown):
        return {"fix": False, "position_status": "unknown"}
    lat = _s24(lat_raw)
    lon = _s24(lon_raw)
    latitude = _coord_to_deg(lat)
    longitude = _coord_to_deg(lon)
    # A position of exactly 0°/0° is a REAL coordinate (Gulf of Guinea), not the
    # unknown sentinel: it must not be suppressed. Range-checking replaces the
    # old all-zero heuristic — latitude beyond ±90° or longitude beyond ±180°
    # is not a legal GeoCoordinates value and is never published as a position.
    if abs(latitude) > 90.0 or abs(longitude) > 180.0:
        return {
            "fix": False,
            "position_status": "out_of_range",
            "latitude_raw": lat,
            "longitude_raw": lon,
        }
    return {
        "fix": True,
        "position_status": "valid",
        "latitude_raw": lat,
        "longitude_raw": lon,
        "latitude_deg": latitude,
        "longitude_deg": longitude,
    }


def decode_gnss_place_auth(data, off):
    """GNSSPlaceAuthRecord (12 bytes): timeStamp(4) + gnssAccuracy(1) +
    geoCoordinates(6) + authenticationStatus(1)."""
    if off + 12 > len(data):
        return None
    rec = data[off:off + 12]
    ts = struct.unpack(">I", rec[0:4])[0]
    return {
        "timestamp": _iso(ts),
        "gnss_accuracy": rec[4],
        "geo": decode_geo_coordinates(rec, 5),
        "authentication_status": rec[11],
    }


def decode_gnss_place(data, off, with_auth):
    """GNSSPlaceRecord (G2, 11 bytes) or GNSSPlaceAuthRecord (G2.2, 12 bytes)."""
    size = 12 if with_auth else 11
    if off + size > len(data):
        return None
    rec = data[off:off + size]
    out = {
        "timestamp": _iso(struct.unpack(">I", rec[0:4])[0]),
        "gnss_accuracy": rec[4],
        "geo": decode_geo_coordinates(rec, 5),
    }
    if with_auth:
        out["authentication_status"] = rec[11]
    return out


def decode_place_daily(rec, with_auth=None, variant_source=None, generation=None):
    """VuPlaceDailyWorkPeriodRecord — G2 (40 bytes) / G2.2 (41 bytes):
    fullCardNumberAndGen(19) + entryTime(4) + entryType(1) + country(1) +
    region(1) + odometer(3) + GNSSPlace(11 G2 / 12 G2.2).

    *with_auth* selects the GNSS-place variant. Generation 2, version 2 added
    ``authenticationStatus`` to the place record (``PlaceAuthRecord``,
    Annex 1C §2.116a), so the variant belongs to the **section version** — the
    caller passes it. Without a section context the record length is the only
    available hint; that fallback is labelled through ``variant_source`` so the
    field is never presented as section-derived.
    """
    if len(rec) < 40:
        return None
    if with_auth is None:
        with_auth = len(rec) >= 41
        variant_source = "record length (no section context)"
    entry_type = rec[23]
    # The entry-type assignment is generation-local: generation 1 assigns 0..5,
    # generation 2 keepts those six and its own upper bound is not readable in
    # the accessible edition (see core.decoders.common).
    generation = generation or "G2"
    short, meaning = decoders.entry_type_daily_work_period(entry_type, generation)
    meaning_status = decoders.entry_type_daily_work_period_status(
        entry_type, generation)
    return {
        "confidence": "high" if with_auth == (len(rec) >= 41) else "medium",
        "record_bytes": len(rec),
        "variant_source": variant_source,
        "card_driver": decode_full_card_number_gen(rec, 0),
        **_time_fields(struct.unpack(">I", rec[19:23])[0]),
        "entry_type": short,
        "entry_type_description": meaning,
        "entry_type_status": meaning_status,
        "type_code": entry_type,
        "nation": decoders.get_nation(rec[24]),
        "region": rec[25],
        "odometer_km": _u24(rec[26:29]),
        "gnss_place": decode_gnss_place(rec, 29, with_auth),
    }


def decode_specific_condition(rec, generation="G2"):
    """VuSpecificConditionRecord (5 bytes): entryTime(4) + specificConditionType(1).

    Type codes per Annex 1B §2.154 / Annex 1C §2.154:
      0x01/0x02 = out of scope Begin/End,
      0x03      = ferry/train crossing (generation 2 splits it into
                  Begin 0x03 / End 0x04),
      0x04      = generation 1 RFU, generation 2 crossing End.
    The label therefore depends on the *section's* generation; an unassigned
    code keeps its numeric value and is labelled unassigned instead of being
    given the other generation's meaning.
    """
    if len(rec) < 5:
        return None
    from core.utils.event_codes import specific_condition_label
    code = rec[4]
    label = specific_condition_label(code, generation=generation)
    assigned = label != f"0x{code:02X}"
    return {
        "confidence": "high",
        **_time_fields(struct.unpack(">I", rec[0:4])[0]),
        "condition": label,
        "type_code": code,
        "condition_status": "assigned" if assigned else "not assigned",
    }


def decode_gnss_ad(rec, with_auth=None):
    """VuGNSSADRecord — GNSS accumulated driving, G2 (56) / G2.2 (57):
    timeStamp(4) + cardDriver(19) + cardCodriver(19) + GNSSPlace(11/12) + odometer(3).

    ``with_auth`` comes from the section version (see :func:`decode_place_daily`);
    without one, the record length is used and the field is marked as such.
    """
    if len(rec) < 56:
        return None
    if with_auth is None:
        with_auth = len(rec) >= 57
    # ts(4) + cardDriver(19) + cardCodriver(19) + GNSSPlace(11/12) + odometer(3)
    odo_off = 42 + (12 if with_auth else 11)
    return {
        "confidence": "high",
        **_time_fields(struct.unpack(">I", rec[0:4])[0]),
        "card_driver": decode_full_card_number_gen(rec, 4),
        "card_codriver": decode_full_card_number_gen(rec, 23),
        "gnss_place": decode_gnss_place(rec, 42, with_auth),
        "odometer_km": _u24(rec[odo_off:odo_off + 3]) if odo_off + 3 <= len(rec) else None,
    }


def decode_overspeeding_control(rec):
    """VuOverSpeedingControlData (9 bytes): lastOverspeedControlTime(4) +
    firstOverspeedSince(4) + numberOfOverspeedSince(1)."""
    if len(rec) < 9:
        return None
    return {
        "confidence": "high",
        "last_control_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "first_overspeed_since": _iso(struct.unpack(">I", rec[4:8])[0]),
        "number_of_overspeed": rec[8],
    }


def decode_overspeeding_event(rec, version=EVENT_FAULT_VERSION_UNKNOWN):
    """VuOverSpeedingEventRecord (32 bytes): eventType(1) + recordPurpose(1) +
    beginTime(4) + endTime(4) + maxSpeed(1) + avgSpeed(1) +
    cardNumberAndGenDriverSlotBegin(19) + similarEventsNumber(1).

    The ``eventType`` byte is an EventFaultType, so it is read against the
    containing section's point-2.70 assignment (*version*) exactly like the
    event/fault arrays — '0F'H/'1C'H/'3A'H exist only in version 2.
    """
    if len(rec) < 32:
        return None
    return {
        "confidence": "high",
        "event_type": rec[0],
        "event_type_label": describe_event_fault_type(rec[0], True, version),
        "event_fault_version": version,
        "type_status": event_fault_type_status(rec[0], version),
        "record_purpose": rec[1],
        "record_purpose_label": describe_record_purpose(rec[1]),
        "begin": _iso(struct.unpack(">I", rec[2:6])[0]),
        "end": _iso(struct.unpack(">I", rec[6:10])[0]),
        "max_speed_kmh": rec[10],
        "average_speed_kmh": rec[11],
        "card_driver": decode_full_card_number_gen(rec, 12),
        "similar_events": rec[31],
    }


def decode_power_interruption(rec, version=EVENT_FAULT_VERSION_UNKNOWN):
    """VuPowerSupplyInterruptionRecord (87 bytes): eventType(1) + recordPurpose(1)
    + beginTime(4) + endTime(4) + 4×FullCardNumberAndGen(19) + similarEventsNumber(1).

    ``eventType`` is an EventFaultType: the section's point-2.70 version decides
    which codes it assigns (see :func:`decode_overspeeding_event`).
    """
    if len(rec) < 86:
        return None
    out = {
        "confidence": "medium",
        "event_type": rec[0],
        "event_type_label": describe_event_fault_type(rec[0], True, version),
        "event_fault_version": version,
        "type_status": event_fault_type_status(rec[0], version),
        "record_purpose": rec[1],
        "record_purpose_label": describe_record_purpose(rec[1]),
        "begin": _iso(struct.unpack(">I", rec[2:6])[0]),
        "end": _iso(struct.unpack(">I", rec[6:10])[0]),
        "card_driver_begin": decode_full_card_number_gen(rec, 10),
        "card_driver_end": decode_full_card_number_gen(rec, 29),
        "card_codriver_begin": decode_full_card_number_gen(rec, 48),
        "card_codriver_end": decode_full_card_number_gen(rec, 67),
    }
    if len(rec) >= 87:
        out["similar_events_number"] = rec[86]
    return out


def decode_its_consent(rec):
    """VuITSConsentRecord (20 bytes): cardNumberAndGen(19) + consent(1)."""
    if len(rec) < 20:
        return None
    return {
        "confidence": "high",
        "card": decode_full_card_number_gen(rec, 0),
        # VuITSConsentRecord carries a BOOLEAN. ASN.1 notation alone does not
        # establish the wire rule (Appendix 1 §1.1 separates syntax from
        # encoding and points at aligned PER when a transfer encodes ASN.1), so
        # the low-bit reading is kept as measured and the raw octet travels with
        # it — the value is never presented as a decided boolean.
        "consent": bool(rec[19] & 0x01),
        "consent_raw": rec[19],
        "consent_status": "raw (BOOLEAN wire encoding not established by ASN.1 alone)",
    }


#: VuTimeAdjustmentRecord is exactly 99 bytes (Annex 1C §2.212): oldTimeValue(4)
#: + newTimeValue(4) + workshopName(36) + workshopAddress(36) +
#: workshopCardNumberAndGeneration(19).
TIME_ADJUSTMENT_RECORD_SIZE = 99


def decode_time_adjustment(rec):
    """VuTimeAdjustmentRecord (99): oldTimeValue(4) + newTimeValue(4) +
    workshopName(36) + workshopAddress(36) + workshopCardNumberAndGen(19).

    The record size is normative: a shorter body is *not* a decoded adjustment.
    Its two leading TimeReal values are still read (they are unambiguous), but
    the record is reported ``low``/``record_complete: False`` with every
    remaining byte preserved, instead of being labelled a complete record.
    """
    if len(rec) < 8:
        return None
    out = {
        "confidence": "low",
        "record_bytes": len(rec),
        "record_complete": len(rec) == TIME_ADJUSTMENT_RECORD_SIZE,
        "old_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "new_time": _iso(struct.unpack(">I", rec[4:8])[0]),
    }
    if out["record_complete"]:
        out["confidence"] = "high"
        out["workshop_name"] = decode_name(rec, 8)
        out["workshop_address"] = decode_name(rec, 44)
        out["workshop_card"] = decode_full_card_number_gen(rec, 80)
    else:
        out["missing_bytes"] = TIME_ADJUSTMENT_RECORD_SIZE - len(rec)
        out["raw_tail_hex"] = rec[8:].hex()
    return out


def decode_border_crossing(rec):
    """VuBorderCrossingRecord (55 bytes) — confirmed on real data."""
    if len(rec) < 55:
        return None
    return {
        "confidence": "high",
        "card_driver": decode_full_card_number_gen(rec, 0),
        "card_codriver": decode_full_card_number_gen(rec, 19),
        "country_left": decoders.get_nation(rec[38]),
        "country_entered": decoders.get_nation(rec[39]),
        "gnss_place": decode_gnss_place_auth(rec, 40),
        "odometer_km": _u24(rec[52:55]),
    }


def decode_load_unload(rec):
    """VuLoadUnloadRecord (58 bytes): timeStamp(4) + operationType(1) +
    cardDriver(19) + cardCodriver(19) + gnssPlaceAuth(12) + odometer(3)."""
    if len(rec) < 58:
        return None
    ts = struct.unpack(">I", rec[0:4])[0]
    op = rec[4]
    op_names = {0x01: "load", 0x02: "unload", 0x03: "simultaneous"}
    return {
        "confidence": "medium",
        **_time_fields(ts),
        "operation_type": op_names.get(op, f"0x{op:02X}"),
        "card_driver": decode_full_card_number_gen(rec, 5),
        "card_codriver": decode_full_card_number_gen(rec, 24),
        "gnss_place": decode_gnss_place_auth(rec, 43),
        "odometer_km": _u24(rec[55:58]),
    }


# ── Gen2 VuEventRecord (0x15) / VuFaultRecord (0x18) ─────────────────────
#
# Reg. (EU) 2016/799, Annex 1C Appendix 1 (generation 2 layouts):
#   §2.198 VuEventRecord = eventType(1) + eventRecordPurpose(1) +
#          eventBeginTime(4) + eventEndTime(4) +
#          4 × FullCardNumberAndGeneration(19) + similarEventsNumber(1) +
#          manufacturerSpecificEventFaultData(4) = 91 bytes
#   §2.201 VuFaultRecord = the same without similarEventsNumber = 90 bytes
#   §2.74  FullCardNumberAndGeneration = FullCardNumber(18) + generation(1)
#   §2.73  FullCardNumber = cardType(1 EquipmentType) + nation(1) + number(16)
#   §2.95  ManufacturerSpecificEventFaultData = manufacturerCode(1) +
#          OCTET STRING SIZE(3)
#
# The manufacturer-specific pair is the ONLY part of the record the standard
# leaves to the manufacturer, so only those two fields are low confidence; every
# other field can be checked against the standard, which is what
# ``decode_event_fault_record`` reports through ``normative``.
VU_EVENT_RECORD_SIZE = 91
VU_FAULT_RECORD_SIZE = 90
#: VuDetailedSpeedBlock (§2.188): TimeReal + 60 per-second values, exactly 64.
DETAILED_SPEED_BLOCK_SIZE = 64
VU_EVENT_SPEC = "Annex 1C App.1 2.198"
VU_FAULT_SPEC = "Annex 1C App.1 2.201"
# EventFaultType '0B'H (§2.70 generation 2): for a time conflict the two
# timestamps are redefined — begin is the recording equipment time and end is
# the GNSS time, i.e. ``end`` is not an end at all (see decode_* below).
TIME_CONFLICT_EVENT = 0x0B
# Fields whose value the standard does not define (manufacturer-specific).
_MANUFACTURER_FIELDS = ["manufacturer_code", "manufacturer_error_code"]
# FullCardNumberAndGeneration slots: driver/codriver at begin, then at end.
_CARD_SLOT_OFFSETS = (
    (10, "card_driver_begin"), (29, "card_codriver_begin"),
    (48, "card_driver_end"), (67, "card_codriver_end"))
# EquipmentType (§2.67) codes that identify a *tachograph card*, i.e. the only
# values a FullCardNumber slot can carry: 1 driver, 2 workshop, 3 control,
# 4 company, 5 manufacturing. 0 designates a Member State/Europe (certificates),
# 6..15 are other equipment (VU, motion sensor, GNSS facility, RCM, ITS, plaque,
# adapter, ERCA, MSCA, external GNSS connection), 16 is "Unused" (SealDataVu only)
# and 17..255 are RFU.
_TACHOGRAPH_CARD_TYPES = frozenset(range(0x01, 0x06))
# Generation (§2.75): '01'H generation 1, '02'H generation 2; rest RFU.
_DEFINED_CARD_GENERATIONS = frozenset((0x01, 0x02))
# TimeReal plausibility bound used across the decoders (2000-01-01..2100-01-01).
# This is a *plausibility* bound, not a rule of the standard: TimeReal itself runs
# to 2^32-1 (2106-02-07), and outer values are treated as a corrupt field.
_PLAUSIBLE_TIME = (946684800, 4102444800)
# The EventFaultType value assignment (point 2.70) belongs to the section, not to
# the file, and comes in two generation-2 versions (see core/utils/event_codes.py
# for the tables and the amending-act citations). Appendix 7 fixes which block
# carries which: DDP_031 defines the events-and-faults data structures "under the
# SID 76 Hex, the TREP 03, 23 or 33 Hex" and DDP_034 keeps SID and TREP in the
# stored download; DDP_011 is the request table. Any other context — another
# section, an isolated record, the tag-keyed adapter that sees one array with no
# stream around it — is ``unknown``: version 2 is never assumed, because
# '0F'H/'1C'H/'3A'H mean something only there.
#
# ``metadata.generation`` is the *file's* hardware generation: a version-2 VU can
# still produce a version-1 download, so it never upgrades a section.
EVENT_FAULT_VERSION_BY_TREP = {
    0x23: EVENT_FAULT_VERSION_1,
    0x33: EVENT_FAULT_VERSION_2,
}


def event_fault_version_for_trep(trep):
    """The point-2.70 schema version an Events&Faults TREP section carries."""
    return EVENT_FAULT_VERSION_BY_TREP.get(trep, EVENT_FAULT_VERSION_UNKNOWN)


def _is_empty_card_slot(slot):
    """True for the two empty-slot encodings real vehicle units write.

    Either all-0xFF (no card known at that instant), or cardType 0 + nation 0 +
    a blank card number + generation 0xFF, which is what manufacturer 162 units
    write when the slot never held a card.
    """
    if slot == b"\xff" * 19:
        return True
    return (slot[0] == 0x00 and slot[1] in (0x00, 0xFF) and slot[18] in (0x00, 0xFF)
            and not slot[2:18].strip(b"\x00 "))


def _card_slot_problem(name, slot):
    """Return why a FullCardNumberAndGeneration slot is malformed, else None.

    An empty slot is not a defect: "no card in this slot" is a legal state of an
    event record, and both encodings above are in use in the field.
    """
    if _is_empty_card_slot(slot):
        return None
    if slot[0] not in _TACHOGRAPH_CARD_TYPES:
        # One wording that is true for every rejected value: the field identifies a
        # tachograph card, and only 1..5 are cards.
        return (f"{name}: card type 0x{slot[0]:02X} cannot appear in a card slot "
                f"(a tachograph card is 1..5; 6..15 are other equipment, "
                f"16 is Unused, 17+ RFU)")
    if slot[18] not in _DEFINED_CARD_GENERATIONS:
        return f"{name}: card generation 0x{slot[18]:02X} is not a defined Generation"
    # A card slot carries a Member State that issued the card. 0x00 is "no
    # information available", 0xFD/0xFE are the EC/Europe and 0xFF is "World":
    # none of them is an issuing country, and neither are unassigned codes.
    if not is_known_nation(slot[1]) or slot[1] in (0x00, 0xFD, 0xFE, 0xFF):
        return (f"{name}: issuing member state 0x{slot[1]:02X} is not a Member State "
                f"(no information / EC / Europe / World are not issuing countries)")
    number = slot[2:18]
    if any(b < 0x20 or b > 0x7E for b in number) or not number.strip():
        return f"{name}: card number is not 16 printable characters"
    return None


def _event_fault_problems(is_event, rec, begin_ts, end_ts):
    """Every way a correctly sized record can still break the standard.

    The type code is not one of them: a code the amended assignment does not
    define (RFU, or a manufacturer-specific one whose meaning is not public) is
    flagged through ``low_confidence_fields`` while the record stays conformant —
    the structure is what the standard fixes there.
    """
    problems = [p for p in (_card_slot_problem(name, rec[off:off + 19])
                            for off, name in _CARD_SLOT_OFFSETS) if p]
    purpose = rec[1]
    # EventFaultRecordPurpose (§2.69): '00'..'07'H defined, '08'..'7F'H RFU,
    # '80'..'FF'H manufacturer specific (meaning unknown, but not a defect).
    if 0x07 < purpose < 0x80:
        problems.append(f"record purpose 0x{purpose:02X} is RFU")
    if not _PLAUSIBLE_TIME[0] <= begin_ts <= _PLAUSIBLE_TIME[1]:
        problems.append(f"begin time {begin_ts} is outside the 2000-2100 "
                        f"plausibility window")
    # endTime 0 marks an event/fault that has not ended (purpose '07'H).
    elif end_ts != 0 and not _PLAUSIBLE_TIME[0] <= end_ts <= _PLAUSIBLE_TIME[1]:
        problems.append(f"end time {end_ts} is outside the 2000-2100 "
                        f"plausibility window")
    # A time conflict is the one record whose two timestamps are not ordered:
    # they are the VU clock and the GNSS clock (§2.198).
    elif end_ts and end_ts < begin_ts and not (is_event and rec[0] == TIME_CONFLICT_EVENT):
        problems.append("end time precedes begin time")
    return problems


def decode_event_fault_record(rec, is_event, version=EVENT_FAULT_VERSION_UNKNOWN):
    """Decode a Gen2 VuEventRecord (91) / VuFaultRecord (90) with its verdict.

    A record whose bytes match the standard is decoded field by field and
    reported ``normative: True`` / ``confidence: "high"`` for those fields; a
    record that does not match keeps the 10-byte prefix decode of older versions
    and is reported ``normative: False`` / ``confidence: "low"`` with a
    ``conformance_reason``. Neither is ever dropped.

    *version* is the point-2.70 schema version of the section the record came
    from — ``generation2version1`` for a '23'H Events&Faults section,
    ``generation2version2`` for a '33'H one, ``unknown`` for anything else
    (isolated record, tag-keyed array, another section). The default is
    ``unknown`` on purpose: the version-2 meanings of '0F'H/'1C'H/'3A'H are never
    assumed, they are only used where the section says version 2.
    """
    if len(rec) < 10:
        # Not even eventType + purpose + the two TimeReals: the canonical prefix
        # is not inside the record, so no field is claimed (the record itself is
        # still emitted by the caller with its bytes preserved).
        return None
    if version not in EVENT_FAULT_VERSIONS:
        version = EVENT_FAULT_VERSION_UNKNOWN
    spec = VU_EVENT_SPEC if is_event else VU_FAULT_SPEC
    type_code = rec[0]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    type_status = event_fault_type_status(type_code, version)
    out = {
        "type_code": type_code,
        "description": describe_event_fault_type(type_code, is_event, version),
        "record_purpose": rec[1],
        "begin": _iso(begin_ts),
        "begin_raw": begin_ts,
        "end": _iso(end_ts),
        "end_raw": end_ts,
        "time_status": "valid" if _iso(begin_ts) else "invalid",
        "spec_reference": spec,
        # Bookkeeping, never a column: which point-2.70 table was used, and how
        # that table assigns this byte (see ``event_codes.TYPE_*``).
        "event_fault_version": version,
        "type_status": type_status,
        "low_confidence_fields": list(_MANUFACTURER_FIELDS),
    }
    expected = VU_EVENT_RECORD_SIZE if is_event else VU_FAULT_RECORD_SIZE
    if len(rec) != expected:
        out.update(
            normative=False,
            confidence="low",
            record_bytes=len(rec),
            record_complete=False,
            conformance_reason=(
                f"record is {len(rec)} bytes, the standard defines {expected}"),
            # Size does not match the standard, so nothing after the prefix can
            # be interpreted by offsets: keep the prefix + raw tail view.
            raw_tail_hex=rec[min(len(rec), 10):].hex(),
        )
        return out

    out["record_bytes"] = len(rec)
    out["record_complete"] = True
    for off, name in _CARD_SLOT_OFFSETS:
        out[name] = decode_full_card_number_gen(rec, off)
    manufacturer_code = rec[87] if is_event else rec[86]
    manufacturer_error = rec[88:91] if is_event else rec[87:90]
    name = manufacturer_name(manufacturer_code)
    out["manufacturer_code"] = manufacturer_code
    out["manufacturer_error_code"] = manufacturer_error.hex()
    out["manufacturer"] = name
    out["manufacturer_status"] = (MANUFACTURER_STATUS_REGISTERED if name is not None
                                  else MANUFACTURER_STATUS_NOT_REGISTERED)
    # An unregistered byte keeps the old "value not interpretable" mark; a
    # registered one identifies the manufacturer, so only the vendor error code
    # stays raw (no verified three-byte wire-format mapping was obtained).
    low = [] if name is not None else ["manufacturer_code"]
    low.append("manufacturer_error_code")
    if is_event and rec[86] == 0:
        # §2.151: "0 is not used" — but 52 of the 121 events in the real corpus
        # carry 0, so the value is outside the standard's value assignment while
        # the record structure is perfectly valid. Flag the field alone; the
        # record stays normative.
        low.append("similar_events")
    if type_status != TYPE_ASSIGNED:
        # Not a code this version defines (RFU, manufacturer specific, or a
        # version-2-only code in an unresolved section): flag the field, keep the
        # record conformant. The key is the one the emitted record carries.
        low.append("event_type_code" if is_event else "fault_type_code")
    out["low_confidence_fields"] = low
    if is_event:
        out["similar_events"] = rec[86]
        if type_code == TIME_CONFLICT_EVENT:
            # §2.198: begin is the recording equipment time, end the GNSS time.
            out["end_semantics"] = "GNSS date and time"

    problems = _event_fault_problems(is_event, rec, begin_ts, end_ts)
    out["normative"] = not problems
    out["confidence"] = "low" if problems else "high"
    if problems:
        out["conformance_reason"] = "; ".join(problems)
    return out


#: TREP → hardware generation of the section. The transfer number fixes the
#: generation (DDP_011 / DDP_029..DDP_035); the file-level generation only says
#: which unit produced the download, which is why nothing here reads it.
TREP_GENERATIONS = {
    0x01: "G1", 0x02: "G1", 0x03: "G1", 0x04: "G1", 0x05: "G1", 0x06: "G1",
    0x21: "G2", 0x22: "G2", 0x23: "G2", 0x24: "G2", 0x25: "G2",
    0x31: "G2.2", 0x32: "G2.2", 0x33: "G2.2", 0x35: "G2.2", 0x00: "G2.2",
}


def section_generation(trep):
    """Hardware generation implied by a TREP byte, or ``None`` when unknown."""
    return TREP_GENERATIONS.get(trep)


def section_uses_auth_place(trep):
    """True when *trep* is a generation-2-version-2 section.

    ``GNSSPlaceAuthRecord`` / ``PlaceAuthRecord`` and the extra
    ``authenticationStatus`` byte were introduced by Reg. (EU) 2021/1228 for
    generation 2, version 2 only, so the *section* chooses the place variant
    (DDP_032/DDP_033/DDP_035). ``None`` means "no section context".
    """
    if trep is None:
        return None
    return TREP_GENERATIONS.get(trep) == "G2.2"


_RECORD_DECODERS = {
    0x22: decode_border_crossing,
    0x23: decode_load_unload,
    0x1A: decode_overspeeding_control,
    0x1B: decode_overspeeding_event,
    0x1E: decode_time_adjustment,
    0x1F: decode_power_interruption,
    0x17: decode_its_consent,
    0x10: decode_company_lock,
    0x11: decode_control_activity,
    0x19: decode_vu_identification,
    0x0C: decode_calibration,
    0x0D: decode_card_iw,
    0x0E: decode_vu_card_record,
    0x14: decode_download_activity,
    0x20: decode_sensor_paired,
    0x21: decode_sensor_gnss_coupled,
}

_with_serial_text = with_serial_text


def _decode_record(record_type, rec, version=EVENT_FAULT_VERSION_UNKNOWN,
                   trep=None):
    """Decode a single record by recordType. Returns a dict (always includes
    record_type, size, confidence).

    *version* is the point-2.70 schema version of the containing section, used
    by the event/fault records; see :func:`decode_event_fault_record`. *trep* is
    the section's transfer number, which fixes the field variants that changed
    between generation 2 version 1 and version 2 (see
    :func:`section_uses_auth_place`); ``None`` means the record is isolated and
    the decoder must say so instead of assuming a variant.
    """
    name, confidence = RECORD_TYPES.get(record_type, (f"Unknown_0x{record_type:02X}", "low"))
    out = {"record_type": f"0x{record_type:02X}", "name": name,
           "size": len(rec), "confidence": confidence}
    if record_type not in NORMATIVE_RECORD_TYPES:
        # Outside the Annex 1C §2.120 Value-assignment there is no normative
        # name; flag the record so a non-standard type is never presented as a
        # defined record type (D2-005 / VU-UNMAPPED-RECORDS).
        out["normative"] = False

    # Records whose layout or labels changed between generation 2 version 1 and
    # version 2 need the section context: it is passed positionally below.
    if record_type == 0x1C:
        decoded = decode_place_daily(
            rec, with_auth=section_uses_auth_place(trep),
            variant_source=(f"section (TREP 0x{trep:02X})" if trep is not None
                            else None),
            generation=section_generation(trep))
        if decoded:
            out.update(decoded)
        else:
            out["raw_hex"] = rec.hex()
        return out
    if record_type == 0x16:
        decoded = decode_gnss_ad(rec, with_auth=section_uses_auth_place(trep))
        if decoded:
            out.update(decoded)
            out["variant_source"] = (f"section (TREP 0x{trep:02X})"
                                     if trep is not None
                                     else "record length (no section context)")
        else:
            out["raw_hex"] = rec.hex()
        return out
    if record_type == 0x09:
        generation = section_generation(trep)
        decoded = decode_specific_condition(
            rec, generation=generation or "G2")
        if decoded:
            out.update(decoded)
        else:
            out["raw_hex"] = rec.hex()
        return out

    if record_type == 0x0C:
        decoded = decode_calibration(rec, generation=section_generation(trep))
        if decoded:
            out.update(decoded)
            out["confidence"] = decoded["confidence"]
        else:
            out["raw_hex"] = rec.hex()
        return out

    if record_type in (0x1B, 0x1F):
        decoder = (decode_overspeeding_event if record_type == 0x1B
                   else decode_power_interruption)
        decoded = decoder(rec, version=version)
        if decoded:
            out.update(decoded)
        else:
            out["raw_hex"] = rec.hex()
        return out

    if record_type in _RECORD_DECODERS:
        decoded = _RECORD_DECODERS[record_type](rec)
        if decoded:
            out.update(decoded)
            _apply_size_rule(record_type, rec, out, trep)
        else:
            out.update(record_bytes=len(rec), record_complete=False,
                       confidence="low", raw_hex=rec.hex())
        return out
    if record_type == 0x01 and len(rec) >= 2:
        value = struct.unpack(">H", rec[0:2])[0]
        activity = decoders.decode_activity_val(value)
        if activity is not None:
            out["activity"] = activity
        else:
            # Undecodable word (e.g. minute > 1439): kept and counted, not lost.
            out["activity_status"] = "undecodable ActivityChangeInfo"
            out["activity_raw"] = value
            out["raw_hex"] = rec.hex()
        return out
    if record_type == 0x29 and len(rec) >= 2:
        val = struct.unpack(">H", rec[0:2])[0]
        activity = decoders.decode_activity_val(val)
        # 0x29 is strongly suspected to be the co-driver slot's
        # ActivityChangeInfo on VU models that partition by slot (observed on
        # Stoneridge V6006 G2.2).  The bit layout is identical to 0x01.
        if activity is not None:
            out["activity"] = activity
            out["confidence"] = "medium"
            out["note"] = "probable co-driver slot (ActivityChangeInfo, recordType 0x29)"
            return out
        out["raw_hex"] = rec[:2].hex()
        return out
    if record_type in (0x03, 0x06) and len(rec) >= 4:
        out["time"] = _iso(struct.unpack(">I", rec[0:4])[0])
        return out
    if record_type == 0x05 and len(rec) >= 3:
        out["odometer_km"] = _u24(rec[0:3])
        return out
    if record_type in (0x15, 0x18):
        decoded = decode_event_fault_record(rec, is_event=(record_type == 0x15),
                                            version=version)
        if decoded:
            out.update(decoded)
        else:
            # Stored but shorter than the canonical prefix: the record is kept
            # (never dropped) with no field claimed and every byte preserved.
            out.update(confidence="low", record_bytes=len(rec),
                       record_complete=False, time_status=None, raw_hex=rec.hex())
        return out
    if record_type == 0x24 and len(rec) >= 15:
        # VehicleRegistrationIdentification (15): nation(1) +
        # VehicleRegistrationNumber = codePage(1) + 13 characters (§2.167).
        # Decoded through the declared code page: a VRN may carry accented
        # letters, so filtering it down to ASCII would corrupt a valid plate.
        out["nation"] = decoders.get_nation(rec[0])
        out["code_page"] = rec[1]
        out["plate"] = decoders.decode_coded_text(rec[1:15])
        return out
    if record_type == 0x0A and len(rec) >= 17:
        out["confidence"] = "high"
        out["vin"] = decoders.decode_string(rec[:17], is_id=True)
        return out
    if record_type == 0x0B and len(rec) >= 14:
        # Annex 1C Table 42 (VehicleRegistrationNumber, 14 bytes): byte 1 is the
        # code page, bytes 2-14 are the registration number. This record carries
        # NO nation field — decoding the code-page byte as a NationNumeric would
        # fabricate a registration country (0x01 -> "A") the record does not
        # contain. The registration *nation* is only defined for 0x24
        # (VehicleRegistrationIdentification, below).
        #
        # The 13 characters are decoded through the declared code page (a VRN is
        # text, not an identifier: ISO/IEC 8859 accented letters are legal).
        out["confidence"] = "high"
        out["code_page"] = rec[0]
        out["plate"] = decoders.decode_coded_text(rec[0:14])
        return out
    if record_type == 0x02 and len(rec) >= 1:
        out["confidence"] = "high"
        out["card_slots_status"] = rec[0]
        # 'ccccdddd'B: the raw octet alone is not the slot state (§2.28).
        out["slots"] = decode_card_slots_status(rec[0])
        return out
    if record_type == 0x13 and len(rec) >= 8:
        out["confidence"] = "high"
        out["min_downloadable_time"] = _iso(struct.unpack(">I", rec[0:4])[0])
        out["max_downloadable_time"] = _iso(struct.unpack(">I", rec[4:8])[0])
        return out
    if record_type == 0x12 and len(rec) >= 5:
        # VuDetailedSpeedBlock (§2.188) is exactly 64 bytes: speedBlockBeginDate
        # (4) + 60 one-byte values, one per second. A shorter body is not a speed
        # block — its leading TimeReal is still read (unambiguous), but the
        # record is reported incomplete/low instead of a high-confidence block.
        begin_ts = struct.unpack(">I", rec[0:4])[0]
        out["begin"] = _iso(begin_ts)
        out["begin_raw"] = begin_ts
        out["time_status"] = "valid" if _iso(begin_ts) else "invalid"
        out["record_bytes"] = len(rec)
        out["record_complete"] = len(rec) == DETAILED_SPEED_BLOCK_SIZE
        if not out["record_complete"]:
            out["confidence"] = "low"
            out["missing_bytes"] = DETAILED_SPEED_BLOCK_SIZE - len(rec)
            out["raw_tail_hex"] = rec.hex()
            return out
        out["confidence"] = "high"
        # Summarised (not expanded) to avoid a 60×N value dump.
        raw_speeds = [None if s == 0xFF else s for s in rec[4:64]]
        samples = [s for s in raw_speeds if s is not None]
        # Internal chart data: excluded from GUI tables and exports.
        out["_chart_speeds_kmh"] = raw_speeds
        if samples:
            out["max_speed_kmh"] = max(samples)
            out["min_speed_kmh"] = min(samples)
            out["avg_speed_kmh"] = round(sum(samples) / len(samples), 1)
            out["samples"] = len(samples)
        return out
    if record_type == 0x08:
        # ECC SignatureRecord — opaque crypto blob; recognised, nothing to decode.
        out["confidence"] = "high"
        out["type"] = "ECC signature"
        return out
    if record_type in (0x04, 0x0F):
        # Certificate body. The *structure* is decoded with the existing CVC
        # parser (core.crypto.vu_signature), whose fields are the Appendix-11
        # ones; trust (signature validity, ERCA anchoring, temporal validity) is
        # a separate verdict produced by the crypto layer and is NOT claimed
        # here. The raw bytes stay available.
        out["confidence"] = "medium"
        out["type"] = "certificate"
        try:
            from core.crypto.vu_signature import parse_cvc
            parsed = parse_cvc(rec)
        except Exception:                                # parser must not break the walk
            parsed = None
        if parsed:
            out.update({k: v for k, v in parsed.items() if k != "public_point"})
            out["confidence"] = "high"
        else:
            out["raw_hex"] = rec.hex()
            out["parse_status"] = "unrecognised CVC body (kept raw)"
        return out

    # Unconfirmed: surface raw bytes (truncated) instead of inventing values.
    # Unknown record: every byte is preserved verbatim (never a prefix). The
    # key is hidden from tables/exports, so this costs nothing on screen.
    out["raw_hex"] = rec.hex()
    return out


#: Canonical record size per RecordType for the generation-2 sections (Annex 1C
#: Appendix 1). A record of exactly this size is a standard record; any other size
#: is published as an incomplete/low record whose canonical prefix is decoded only
#: as far as the bytes allow, with the rest preserved (the shared size rule).
#: Where the size depends on the section version the shorter variant is listed and
#: the version-aware decoders accept their own canonical size as well.
CANONICAL_RECORD_SIZES = {
    0x02: 1, 0x03: 4, 0x05: 3, 0x06: 4, 0x07: 20, 0x09: 5, 0x0A: 17,
    0x0B: 14, 0x0D: CARD_IW_RECORD_SIZE, 0x0E: 45, 0x10: 99, 0x11: 32,
    0x12: 64, 0x13: 8, 0x14: 59, 0x15: VU_EVENT_RECORD_SIZE, 0x16: 56,
    0x17: 20, 0x18: VU_FAULT_RECORD_SIZE, 0x19: 126, 0x1A: 9, 0x1B: 32,
    0x1C: 40, 0x1D: 8, 0x1E: 99, 0x1F: 87, 0x20: 28, 0x21: 28, 0x22: 55,
    0x23: 58, 0x24: 15,
}


#: Record types whose canonical size depends on the section version (generation 2
#: version 2 added ``authenticationStatus`` to the GNSS place/GNSS-AD records and
#: ``digitalMapVersion`` to VuIdentification). Keyed by record type → (v1, v2).
VERSION_DEPENDENT_RECORD_SIZES = {0x16: (56, 57), 0x1C: (40, 41), 0x19: (126, 138)}


def _canonical_size(record_type, trep=None):
    """Canonical record size for *record_type* in the section *trep* (or a set)."""
    sizes = VERSION_DEPENDENT_RECORD_SIZES.get(record_type)
    if sizes is None:
        return {CANONICAL_RECORD_SIZES.get(record_type)} - {None}
    auth = section_uses_auth_place(trep)
    if auth is None:
        return set(sizes)           # no section context: either variant is legal
    return {sizes[1] if auth else sizes[0]}


def _apply_size_rule(record_type, rec, out, trep=None):
    """Mark a record whose size is not the canonical one for its type.

    ``record_complete``/``confidence`` are set here for every fixed-size type, so
    a decoder that merely checked a minimum length can no longer report a
    non-canonical body with high confidence. The canonical prefix stays decoded
    (the decoder read only offsets inside the record) and every byte past it is
    preserved in ``raw_tail_hex``.
    """
    accepted = _canonical_size(record_type, trep)
    if not accepted or "record_complete" in out:
        return out
    canonical = min(accepted)
    complete = len(rec) in accepted
    out["record_complete"] = complete
    out["record_bytes"] = len(rec)
    if not complete:
        out["confidence"] = "low"
        if len(rec) > canonical:
            out["raw_tail_bytes"] = len(rec) - canonical
            out["raw_tail_hex"] = rec[canonical:].hex()
        else:
            out["missing_bytes"] = canonical - len(rec)
    return out


def decode_vu_record(record_type, rec, version=EVENT_FAULT_VERSION_UNKNOWN,
                     trep=None):
    """Decode one isolated VU RecordArray record in the canonical app shape.

    This deliberately accepts a single record, not a complete TREP stream, so
    the tag-keyed adapter can share semantics without calling the stream walker.

    Having no section, an isolated record has no point-2.70 schema version: the
    default ``unknown`` says so instead of assuming a generation-2 version-2
    meaning for '0F'H/'1C'H/'3A'H. Callers that *do* know the section (the stream
    walker) pass ``version=`` explicitly.
    """
    return _apply_size_rule(record_type, rec,
                            _decode_record(record_type, rec, version, trep=trep),
                            trep)


def _stap_extent(data, start):
    """Walk one embedded card EF stream (STAP framing) and return its end.

    A card download inside a VU stream is a card EF image, not a RecordArray
    list: its elements are ``tag(2 BE) + dtype(1) + length(2 BE) + value`` (the
    same STAP framing :mod:`core.parser.deterministic` recognises). The extent is
    therefore *derived from the framing*, one element at a time — not guessed by
    scanning for a marker. Returns ``(end, element_count)``; ``end == start``
    when the first bytes are not a STAP element.
    """
    pos = start
    count = 0
    n = len(data)
    while pos + 5 <= n:
        tag, dtype, length = struct.unpack(">HBH", data[pos:pos + 5])
        if tag in (0x0000, 0xFFFF, 0x5555) or dtype > 0x0F:
            break
        # The element length is its OWN two-byte field (Annex 1B DDP_044:
        # "length is a two byte value", `FFFF` reserved), so a real elementary
        # file — 12-14 KB in practice — fits. `RECORD_ARRAY_MAX_SIZE` is a
        # RecordArray sanity cap and must never bound card data.
        if length == 0xFFFF or pos + 5 + length > n:
            break
        pos += 5 + length
        count += 1
    return pos, count


def iter_vu_sections(data, state=None):
    """Yield sections from a VU RecordArray stream as {marker, trep, records: [(pos, rt, rs, nr, end), ...]}.

    This is the canonical section iterator shared by ``walk_vu_record_arrays``
    and ``vu_signature_verifier._iter_sections``.

    When *state* is a dict it is updated with ``{"truncated": bool}``: True when
    a RecordArray declares more bytes (``rs * nr``) than remain before EOF. In
    that case the walk skips to the next section marker (instead of aborting the
    whole stream) so later genuine sections are still recovered, while callers
    can fail the stream closed as partial/truncated.
    """
    n = len(data)
    pos = 0
    cur = None
    # Valid TREP bytes following a 0x76 section marker (G1/G2/G2.2 + card download).
    # `06` is the only card-download TREP in every generation (DDP_029..DDP_035);
    # `26`/`36` have no transfer definition in any of them, so they are not
    # accepted as aliases here — an undefined transfer has no layout to decode.
    trep_bytes = set(TREP_SECTIONS) | {0x06, TREP_DOWNLOAD_INTERFACE}
    # `pos + 2` (not `pos + 5`): a two-byte DownloadInterfaceVersion section at
    # EOF is only 4 bytes long, so a 5-byte window would step over it.
    while pos + 2 <= n:
        if data[pos] == 0x76 and data[pos + 1] in trep_bytes:
            if cur:
                yield cur
                cur = None
            trep = data[pos + 1]
            if trep == TREP_CARD_DOWNLOAD:
                # TREP 06 is a card EF image (all generations: DDP_029..035 keep
                # 06 for card download). Its length has no header, so it is
                # bounded by walking the card's own STAP framing. Only when that
                # walk yields nothing does the section fall back to the next
                # section marker, and the fallback is recorded as such.
                end, count = _stap_extent(data, pos + 2)
                tlv_complete = count > 0 and (
                    end == n or (data[end] == 0x76 and end + 1 < n
                                 and data[end + 1] in trep_bytes))
                if not tlv_complete:
                    # No parseable EF chain: fall back to the next section
                    # marker (labelled in the report) so a following transfer is
                    # still found.
                    end = pos + 2
                    while end < n and not (end + 1 < n and data[end] == 0x76
                                           and data[end + 1] in trep_bytes):
                        end += 1
                    if end == n and state is not None:
                        # A bare marker with no card behind it (a truncated
                        # download): the bytes are trailing, not a card region.
                        state["trailing_bytes"] = int(state.get("trailing_bytes")
                                                     or 0) + (end - (pos + 2))
                yield {"marker": pos, "trep": trep, "records": [],
                       "card_tlv": {"offset": pos + 2, "bytes": end - (pos + 2),
                                    "tlvs": count, "tlv_complete": tlv_complete,
                                    "boundary": ("STAP/EF framing" if tlv_complete
                                                 else "resynchronised to next section marker")}}
                pos = end
                continue
            if trep == TREP_DOWNLOAD_INTERFACE:
                # DDP_028a: SID + TREP 00 + DownloadInterfaceVersion, which point
                # 2.60a defines as exactly two octets ('aabb'H). There are no
                # RecordArrays and no signature record in this transfer.
                end = pos + 2 + INTERFACE_VERSION_SIZE
                if end > n:
                    if state is not None:
                        state["truncated"] = True
                    pos += 1
                    continue
                yield {"marker": pos, "trep": trep, "records": [],
                       "interface": data[pos + 2:end]}
                pos = end
                continue
            cur = {"marker": pos, "trep": trep, "records": []}
            pos += 2
            continue
        if pos + 5 > n:
            # Fewer than five bytes left: no RecordArray header can fit. The run
            # is counted as trailing bytes (the caller decides whether such a
            # remainder is legal padding or a truncated record) instead of being
            # silently stepped over.
            if state is not None:
                remainder = data[pos:]
                if any(byte not in (0x00, 0xFF) for byte in remainder):
                    state["trailing_bytes"] = n - pos
            break
        rt = data[pos]
        rs = struct.unpack(">H", data[pos + 1:pos + 3])[0]
        nr = struct.unpack(">H", data[pos + 3:pos + 5])[0]
        if rt < 0x01 or rt > 0x60 or rs > RECORD_ARRAY_MAX_SIZE or nr > RECORD_ARRAY_MAX_RECORDS or (rs == 0 and nr > 0 and rt != 0x60):
            # Resync one byte at a time: skipping a whole header width here
            # could jump over the start of a valid RecordArray after junk. It is
            # never silent — every skipped byte is counted so the caller can tell
            # a clean walk from one that had to tolerate junk.
            if state is not None:
                state["resync_bytes"] = state.get("resync_bytes", 0) + 1
            pos += 1
            continue
        if pos + 5 + rs * nr > n:
            # Header declares more bytes than exist before EOF: EOF truncation
            # or a lying noOfRecords. Flag it and skip to the next section
            # marker (the remaining bytes are a partial payload, not new
            # headers) instead of aborting the walk, so a genuine section that
            # follows is still recovered.
            if state is not None:
                state["truncated"] = True
            pos += 1
            while pos + 5 <= n and not (data[pos] == 0x76 and data[pos + 1] in trep_bytes):
                pos += 1
            continue
        if cur is not None:
            cur["records"].append((pos, rt, rs, nr, pos + 5 + rs * nr))
        pos += 5 + rs * nr
    if cur:
        yield cur
    if state is not None:
        state.setdefault("truncated", False)
        if pos < n and "trailing_bytes" not in state:
            # The loop can only inspect positions with two bytes left; a shorter
            # remainder (a lone marker prefix, for instance) is counted here so the
            # caller never mistakes it for padding. 0x00/0xFF fill *is* padding (a
            # VU fills unused space with FF), so it is not counted.
            remainder = data[pos:]
            if any(byte not in (0x00, 0xFF) for byte in remainder):
                state["trailing_bytes"] = n - pos


def walk_vu_record_arrays(data, results):
    """Walk the VU RecordArray stream, dispatch by recordType, and populate
    ``results``. Returns a list of section summaries (also stored under
    ``results['vu_record_arrays']``).

    The number of decoded records is bounded globally by ``VU_MAX_TOTAL_RECORDS``
    so a small, densely packed untrusted file cannot amplify into hundreds of MB
    of dicts (per-array ``RECORD_ARRAY_MAX_RECORDS`` alone does not bound the
    stream). Completeness is derived from the real walk outcome: if the bound is
    hit or any declared array exceeds EOF, ``results['_vu_walk_complete']`` is
    False so the caller fails the stream closed as partial rather than reporting
    it complete.
    """
    data = bytes(data)
    sections = []
    state = {}
    total_records = 0
    capped = False
    unmapped = set()
    # Published up-front as the live list (and the walk declared incomplete):
    # sections are emitted as they are walked, so a failure mid-walk must leave
    # both the already-emitted records and their section list in place — the
    # caller can then tell "sections exist, walk incomplete" from "nothing came
    # out" and must not re-scan the same bytes on top of them.
    results["vu_record_arrays"] = sections
    results["_vu_walk_complete"] = False
    schema_reports = []
    dropped_any = False
    structure_findings = []
    observations = []

    for sec in iter_vu_sections(data, state):
        # The section fixes the EventFaultType assignment (DDP_011), each one
        # independently: a download may mix a '23'H and a '33'H Events&Faults
        # section, and the file-wide ``metadata.generation`` says nothing about
        # either of them.
        section_version = event_fault_version_for_trep(sec["trep"])
        if sec["trep"] == TREP_DOWNLOAD_INTERFACE:
            _emit_interface_version(sec.get("interface") or b"", results)
        if sec.get("card_tlv"):
            # An incomplete card region is an INTEGRITY finding (CONTINUE4
            # vocabulary): the card bytes are there but do not close, so the
            # download is partial — never silently complete, and never re-scanned.
            if not sec["card_tlv"].get("tlv_complete"):
                structure_findings.append({
                    "trep": f"0x{sec['trep']:02X}",
                    "status": "card_download_incomplete",
                    "detail": "card EF stream does not close",
                    "missing_bytes": 0,
                    "trailing_bytes": int(sec["card_tlv"].get("bytes") or 0),
                })
            # Card-download payload: bounded by its own STAP framing, reported,
            # and handed to the existing card EF/TLV decoder over exactly that
            # byte range. A card EF is never read as a RecordArray here.
            info = dict(sec["card_tlv"])
            start = info["offset"]
            chunk = data[start:start + info["bytes"]]
            info["delegated"] = _delegate_card_download(chunk, results)
            results.setdefault("metadata", {}).setdefault(
                "vu_card_download_sections", []).append(info)
        current = {"trep": sec["trep"], "name": TREP_SECTIONS.get(sec["trep"], f"TREP_0x{sec['trep']:02X}"),
                   "records": {}}
        for (pos, rt, rs, nr, _end) in sec["records"]:
            if capped:
                break
            if rt not in NORMATIVE_RECORD_TYPES:
                # A record type with no Annex 1C §2.120 name (RFU/manufacturer
                # specific) is decoded but must be flagged, not silently
                # presented as a known record type (D2-005).
                unmapped.add(rt)
            rpos = pos + 5
            for _ in range(nr):
                if total_records >= VU_MAX_TOTAL_RECORDS:
                    capped = True
                    break
                rec = data[rpos:rpos + rs]
                current["records"].setdefault(rt, []).append(
                    decode_vu_record(rt, rec, version=section_version,
                                     trep=sec["trep"]))
                rpos += rs
                total_records += 1
        emitted = _emit_section(current, results) or {}
        # Appendix-7 schema check (DDP_029..DDP_033): the prescribed arrays must
        # be present and in order. The report is descriptive — the records above
        # are already decoded, and a defect here is a structural observation, not
        # a recovery route, so it never sets ``metadata.heuristic_fields``.
        sig_size = next((rs for (_p, rt, rs, _nr, _e) in sec["records"]
                         if rt == 0x08), None)
        schema_report = validate_section_schema(
            sec["trep"], [(rt, nr) for (_p, rt, _rs, nr, _e) in sec["records"]],
            signature_size=sig_size)
        schema_report["trep"] = f"0x{sec['trep']:02X}"
        # stored == declared by the array counters; emitted == what reached the
        # result lists. A difference is a defect of ours (a record the standard
        # declares was dropped), reported and marked partial.
        # Only record types with a result list can "reach the results": identity,
        # certificates, the current date/time, the slot word and the signature are
        # consumed into the panels/metadata by design and are not counted here.
        stored = {f"0x{rt:02X}": nr for (rt, nr) in
                  dict.fromkeys((rt, nr) for (_p, rt, _rs, nr, _e) in sec["records"])
                  if rt in VU_RECORD_RESULT_KEYS}
        emitted_counts = {f"0x{rt:02X}": n for rt, n in emitted.items()
                          if isinstance(rt, int) and f"0x{rt:02X}" in stored}
        dropped = {rt: stored[rt] - emitted_counts.get(rt, 0)
                   for rt in stored if stored[rt] != emitted_counts.get(rt, 0)}
        schema_report["stored_records"] = stored
        schema_report["emitted_records"] = emitted_counts
        schema_report["dropped_records"] = dropped
        if dropped:
            schema_report["status"] = "incomplete"
            _log.warning(
                "VU section 0x%02X emitted %s of its stored records (%s)",
                sec["trep"], emitted_counts, dropped)
            dropped_any = True
        schema_reports.append(schema_report)
        if schema_report["status"] == "incomplete" and not dropped:
            _log.warning(
                "VU section 0x%02X does not match Appendix 7: missing %s, "
                "out of order %s, duplicate %s, unexpected %s, signature %s",
                sec["trep"], schema_report["missing_arrays"],
                schema_report["out_of_order"], schema_report["duplicate_arrays"],
                schema_report["unexpected_arrays"],
                schema_report["signature_problem"])
        # An array whose record type is outside the normative enumeration (RFU
        # 25-7F, manufacturer-specific 80-FF, and the observed 0x29/0x40/0x60
        # extensions) is an empirical extension, not a structure defect: it is
        # reported as unmapped and the download stays complete. Missing or
        # out-of-order prescribed arrays, and unexpected *normative* types, are
        # defects.
        observed = [rt for rt in schema_report["unexpected_arrays"]
                    if not is_normative_record_type(int(rt, 16))]
        if observed:
            # Reported, but NOT a structure defect: an empirical extension keeps
            # the download complete (the owner's rule: a manufacturer extension is
            # not a fallback).
            observations.append({
                "trep": f"0x{sec['trep']:02X}",
                "status": "unmapped_record_type",
                "detail": ("observed record type(s) outside the normative "
                           "enumeration, kept raw"),
                "record_types": observed,
                "missing_bytes": 0, "trailing_bytes": 0,
            })
            schema_report["empirical_arrays"] = observed
            schema_report["unexpected_arrays"] = [
                rt for rt in schema_report["unexpected_arrays"]
                if rt not in observed]
            if not (schema_report["missing_arrays"]
                    or schema_report["out_of_order"]
                    or schema_report["unexpected_arrays"]):
                schema_report["status"] = "complete"
        if (schema_report["missing_arrays"] or schema_report["out_of_order"]
                or schema_report["unexpected_arrays"]):
            # The prescribed arrays are absent, out of order or not defined for
            # this transfer: a structure violation, reported and partial exactly
            # like a malformed signature array. The records above are already
            # emitted; only the verdict changes.
            structure_findings.append({
                "trep": f"0x{sec['trep']:02X}",
                "status": "schema_violation",
                "detail": (f"missing {schema_report['missing_arrays']}, "
                           f"out of order {schema_report['out_of_order']}, "
                           f"unexpected {schema_report['unexpected_arrays']}"),
                "missing_arrays": schema_report["missing_arrays"],
                "out_of_order": schema_report["out_of_order"],
                "unexpected_arrays": schema_report["unexpected_arrays"],
                "missing_bytes": 0,
                "trailing_bytes": 0,
            })
        if schema_report["signature_problem"]:
            # A malformed/absent signature array is an INTEGRITY finding (the
            # data above it is decoded): reported, partial, never re-scanned.
            structure_findings.append({
                "trep": f"0x{sec['trep']:02X}",
                "status": ("signature_missing"
                           if schema_report["signature_problem"] ==
                           "signature array missing" else "signature_malformed"),
                "detail": schema_report["signature_problem"],
                "missing_bytes": 0, "trailing_bytes": 0})
        for rt_name in schema_report["duplicate_arrays"]:
            structure_findings.append({"trep": f"0x{sec['trep']:02X}",
                                       "status": "duplicate_array",
                                       "detail": rt_name,
                                       "missing_bytes": 0, "trailing_bytes": 0})
        # Only once its records reached the results: a failure while emitting a
        # section must not announce a section the user never got.
        sections.append({
            "trep": f"0x{current['trep']:02X}",
            "section": current["name"],
            "record_counts": {f"0x{rt:02X}": len(v) for rt, v in current["records"].items()},
        })
        if capped:
            break

    if schema_reports:
        results.setdefault("metadata", {})["vu_section_schema"] = schema_reports
    results["_vu_walk_complete"] = (not capped
                                   and not state.get("truncated", False)
                                   and not state.get("trailing_bytes")
                                   and not state.get("resync_bytes"))
    if observations:
        # Model-only notes: recorded in vu_integrity for the report, without making
        # the walk incomplete.
        results.setdefault("metadata", {}).setdefault(
            "vu_integrity", []).extend(observations)
    if structure_findings:
        results.setdefault("metadata", {}).setdefault(
            "vu_integrity", []).extend(structure_findings)
        results["_vu_walk_complete"] = False
    if dropped_any:
        # A stored record that did not reach the results is our defect: the
        # download is partial (never silently complete).
        results["_vu_walk_complete"] = False
    integrity = []
    if state.get("truncated"):
        integrity.append({"trep": None, "status": "array_truncated",
                          "missing_bytes": int(state.get("trailing_bytes") or 0),
                          "trailing_bytes": int(state.get("trailing_bytes") or 0)})
    if state.get("trailing_bytes"):
        # A remainder that is not 0x00/0xFF fill is a truncated marker or junk, not
        # padding: the walk is incomplete and the bytes are reported, exactly as the
        # generation-1 walker does for the same file.
        if not integrity:
            integrity.append({"trep": None, "status": "trailing_bytes",
                              "missing_bytes": 0,
                              "trailing_bytes": int(state["trailing_bytes"])})
    if integrity:
        # Integrity, not decodability: the sections that were read are decoded
        # normatively, the download is reported partial (see
        # docs/developer/normative-completion.md §11).
        results.setdefault("metadata", {}).setdefault(
            "vu_integrity", []).extend(integrity)
    if state.get("resync_bytes"):
        # Junk inside a section's byte run: reported, and fatal to the
        # completeness claim (a valid stream never needs it).
        results.setdefault("metadata", {})["vu_walk_resync_bytes"] = int(
            state["resync_bytes"])
        _log.warning("VU walk resynchronised over %d byte(s) after a section "
                     "boundary", state["resync_bytes"])
    if state.get("trailing_bytes"):
        # Bytes after the last complete RecordArray: carried in metadata so a
        # remainder is never silently absorbed by the walk, and fatal to the
        # completeness claim — a cut signature record looks exactly like this.
        results.setdefault("metadata", {})["vu_walk_truncated_bytes"] = int(
            state["trailing_bytes"])
    if state.get("truncated"):
        # A declared structure that runs past EOF: the shortfall is the remainder
        # the array claimed but the bytes do not hold.
        results.setdefault("metadata", {}).setdefault(
            "vu_walk_truncated_bytes", int(state.get("trailing_bytes") or 0))
    if capped:
        results["_vu_walk_record_cap"] = VU_MAX_TOTAL_RECORDS
    if unmapped:
        results["vu_unmapped_record_types"] = sorted(f"0x{rt:02X}" for rt in unmapped)
    return sections


def _delegate_card_download(chunk, results):
    """Run the card EF/TLV decoder over one bounded card-download region.

    Reuses the generation-1 embedded-image helper (itself a call into
    :class:`core.parser.deterministic.DeterministicParser` with ``is_vu=False``)
    so a mixed VU/card stream decodes card EFs through their registered
    decoders instead of scanning bytes. Returns True when the delegation ran.
    """
    if not chunk:
        return False
    try:
        from core.decoders.vu_g1 import _decode_embedded_card_image
    except ImportError:                                  # pragma: no cover
        return False
    _decode_embedded_card_image(bytes(chunk), results)
    return True


def _count_decode_path(results, key, normative):
    """Tally how an emitted event/fault was decoded: ``metadata.decode_paths``.

    ``non_normative`` counts records the *deterministic* path decoded but whose
    fields failed the conformance check. Records recovered by a backup route are
    never counted here: those are declared by ``decode_paths.fallback``,
    ``heuristic_fields`` and a WARNING, and carry no verdict at all.
    """
    meta = results.setdefault("metadata", {})
    bucket = meta.setdefault("decode_paths", {}).setdefault(
        key, {"normative": 0, "non_normative": 0})
    bucket["normative" if normative else "non_normative"] += 1


#: CardSlotsStatus nibble ('ccccdddd'B) → slot state. Annex 1B §2.28 defines
#: the nibble vocabulary once for every generation: 0000 no card, 0001 driver,
#: 0010 workshop, 0011 control, 0100 company card, 0101..1111 unassigned.
CARD_SLOT_TYPES = {0x00: "empty", 0x01: "driver", 0x02: "workshop",
                   0x03: "control", 0x04: "company"}


def decode_card_slots_status(value):
    """Decode one CardSlotsStatus octet into its two typed nibbles.

    The high nibble is the co-driver slot, the low nibble the driver slot. Both
    the short state word (``driver``/``company``/``empty``/``reserved``), the
    numeric code and an explicit assignment status are returned so a caller can
    publish the raw octet without pretending the state word is the only reading.
    """
    out = {}
    for name, nibble in (("driver_slot", value & 0x0F),
                         ("codriver_slot", (value >> 4) & 0x0F)):
        card_type = CARD_SLOT_TYPES.get(nibble)
        # Same vocabulary the generation-1 panel publishes (§2.28): a slot is
        # empty / occupied / unassigned-code. The card type itself travels as a
        # model-only companion so both generations read identically on screen.
        out[name] = "empty" if nibble == 0x00 else ("occupied" if nibble <= 0x04
                                                   else "reserved")
        out[f"{name}_card_type"] = card_type or "unassigned"
        out[f"{name}_code"] = nibble
        out[f"{name}_status"] = "assigned" if card_type else "unassigned"
    out["raw"] = f"0x{value:02X}"
    return out


def _emit_interface_version(interface, results):
    """Publish TREP 00 DownloadInterfaceVersion (Annex 1C §2.60a) as raw bytes.

    The two octets are interpreted with the point-2.60a value assignment and the
    DDP_028a comment is carried alongside, because the two primary texts of the
    same amending act disagree ("02,02 Hex" vs ``'aa'``/``'bb'`` = 01). Neither
    reading is promoted: ``status`` says the value is raw.
    """
    if len(interface) < INTERFACE_VERSION_SIZE:
        results.setdefault("metadata", {})["download_interface_version"] = {
            "raw": bytes(interface).hex(),
            "status": "truncated (DDP_028a defines two transfer bytes)",
        }
        return
    first, second = interface[0], interface[1]
    # One readable row in the VU Overview panel: the two octets as hex plus the
    # Annex 1C point-2.60a reading. The DDP_028a '02,02' comment stays in the JSON
    # (and the docs) — it is a source conflict, not a fact of the file.
    if first == 0x01 and second == 0x01:
        readable = "Generation 2, version 2"
    else:
        readable = (f"{INTERFACE_GENERATION_CODES.get(first, f'0x{first:02X}')}, "
                    f"{INTERFACE_VERSION_CODES.get(second, f'0x{second:02X}')}")
    results.setdefault("vu_overview", {})["download_interface_version"] = (
        f"{bytes(interface[:2]).hex()} \u00b7 {readable}")
    results.setdefault("metadata", {})["download_interface_version"] = {
        "raw": bytes(interface[:2]).hex(),
        "generation_code": first,
        "generation_status": INTERFACE_GENERATION_CODES.get(
            first, f"not assigned (0x{first:02X})"),
        "version_code": second,
        "version_status": INTERFACE_VERSION_CODES.get(
            second, f"not assigned (0x{second:02X})"),
        "status": "raw (DDP_028a comment vs Annex 1C \u00a72.60a)",
        "source_conflict": True,
        "ddp_028a_comment": INTERFACE_DDP_028A_COMMENT,
    }


def _emit_section(section, results):
    """Map decoded section records into the app's existing result lists.

    Every record the array counters declare is emitted: the regulation defines
    count-prefixed *stored* records (DDP_029..DDP_033), so a record with an
    unusable value is published with the value withheld (``None``/N/A, raw value
    and a status next to it), never deleted. Returns ``{record_type: emitted}``
    so the walker can prove stored == emitted per array.
    """
    recs = section["records"]
    emitted = {}

    def _emit(rt, key, record):
        results.setdefault(key, []).append(record)
        emitted[rt] = emitted.get(rt, 0) + 1

    # Overview-only records. ``CurrentDateTime`` (0x03) and ``CardSlotsStatus``
    # (0x02) were decoded per record and then dropped here: the VU's own clock
    # and the state of its two card slots are normative Overview fields
    # (DDP_029/DDP_031), so they are published. The keys are the ones the G1
    # TREP 01 path already uses, so nothing on screen changes.
    for r in recs.get(0x03, []):
        current = r.get("time")
        if current and results.setdefault("metadata", {}).get(
                "current_datetime") in (None, "N/A"):
            results["metadata"]["current_datetime"] = current
            # The VU's own clock is an Overview datum (DDP_029/DDP_031): shown in
            # the same panel the generation-1 path uses.
            results.setdefault("vu_overview", {}).setdefault(
                "current_date_time", current)
            break
    for r in recs.get(0x02, []):
        raw = r.get("card_slots_status")
        if isinstance(raw, int):
            results.setdefault("vu_overview", {}).setdefault(
                "card_slot_status", decode_card_slots_status(raw))
            break

    # Vehicle identification: write the first found VIN, plate, nation
    # into results["vehicle"]. G2 uses 0x0B (VehicleRegistrationNumber),
    # G2.2 uses 0x24 (VehicleRegistrationIdentification), both use 0x0A (VIN).
    for rt in (0x0A, 0x0B, 0x24):
        for r in recs.get(rt, []):
            vin = r.get("vin")
            nation = r.get("nation")
            plate = r.get("plate")
            if vin and results["vehicle"]["vin"] == "N/A":
                results["vehicle"]["vin"] = vin
            if nation and results["vehicle"]["registration_nation"] == "N/A":
                results["vehicle"]["registration_nation"] = nation
            if plate and results["vehicle"]["plate"] == "N/A":
                results["vehicle"]["plate"] = plate

    # Border crossings (0x22) and load/unload (0x23) — confirmed structures.
    # Every one of these is a stored record: the timestamp is published only when
    # it is a real date (otherwise None + raw + time_status), but the record
    # itself is never withheld.
    for rt in (0x22, 0x23, 0x1C, 0x09, 0x16, 0x12):
        key = VU_RECORD_RESULT_KEYS[rt]
        for r in recs.get(rt, []):
            _emit(rt, key, r)
    handled_record_types = {0x22, 0x23, 0x1C, 0x09, 0x16, 0x12}
    for rt, key in VU_RECORD_RESULT_KEYS.items():
        if rt in handled_record_types:
            continue
        for r in recs.get(rt, []):
            _emit(rt, key, r)

    # VuEventRecord (0x15) → events, VuFaultRecord (0x18) → faults. Each record
    # carries its own conformance verdict (``normative``) from the decoder, so
    # the sources keep their keys/columns and gain the fields the standard
    # defines plus the one manufacturer-specific pair. The point-2.70 schema
    # version resolved from this section (``event_fault_version``) and the
    # registry status of the manufacturer byte travel with the record — both are
    # JSON bookkeeping and stay out of every table (``HIDDEN_KEYS``).
    for rt, key in ((0x15, "events"), (0x18, "faults")):
        type_key = "event_type_code" if key == "events" else "fault_type_code"
        for r in recs.get(rt, []):
            # A record shorter than the standard prefix is still a stored record:
            # it is emitted with the type withheld and every byte preserved (see
            # the shared size rule in decode_event_fault_record).
            record = {
                "description": r.get("description"),
                type_key: r.get("type_code"),
                "record_complete": r.get("record_complete"),
                "record_bytes": r.get("record_bytes"),
                "time_status": r.get("time_status"),
                "record_purpose": r.get("record_purpose"),
                "begin": r.get("begin") or "N/A",
                "end": r.get("end") or "N/A",
                "card_driver_begin": r.get("card_driver_begin"),
                "card_codriver_begin": r.get("card_codriver_begin"),
                "card_driver_end": r.get("card_driver_end"),
                "card_codriver_end": r.get("card_codriver_end"),
                "manufacturer_code": r.get("manufacturer_code"),
                "manufacturer": r.get("manufacturer"),
                "manufacturer_error_code": r.get("manufacturer_error_code"),
                "manufacturer_status": r.get("manufacturer_status"),
                "event_fault_version": r.get("event_fault_version",
                                            EVENT_FAULT_VERSION_UNKNOWN),
                "type_status": r.get("type_status"),
                "normative": bool(r.get("normative")),
                "spec_reference": r.get("spec_reference"),
                "low_confidence_fields": r.get("low_confidence_fields") or [],
                "confidence": r.get("confidence", "low"),
                "source": "vu_recordarray",
            }
            if key == "events":
                record["similar_events"] = r.get("similar_events")
            if r.get("end_semantics"):
                record["end_semantics"] = r["end_semantics"]
            if r.get("conformance_reason"):
                record["conformance_reason"] = r["conformance_reason"]
            _emit(rt, key, record)
            _count_decode_path(results, f"vu_{key}", record["normative"])

    # Daily activities: an Activities section carries date(0x06)+odometer(0x05)+
    # activityChangeInfo(0x01). Rebuild a daily record matching results['activities'].
    if section["name"] == "Activities" and recs.get(0x06):
        # A day is identified by its DateOfDayDownloaded; a section without one
        # (a corrupt/partial Activities header) yields no invented "N/A" day.
        date_str = "N/A"
        for r in recs.get(0x06, []):
            t = r.get("time")
            if not isinstance(t, str) or t == "—":
                continue
            try:
                date_str = datetime.fromisoformat(t).strftime("%d/%m/%Y")
            except ValueError:
                continue
            break
        km = 0
        for r in recs.get(0x05, []):
            if r.get("odometer_km"):
                km = r["odometer_km"]
                break
        # Daily changes come from BOTH the driver (0x01) and the co-driver
        # (0x29) ActivityChangeInfo arrays, so slot-2 activities are not lost.
        # An ActivityChangeInfo the layout cannot decode (minute > 1439) is
        # counted, never silently dropped, and the day is emitted either way.
        changes, invalid_changes = [], 0
        for rt in (0x01, 0x29):
            for r in recs.get(rt, []):
                if r.get("activity"):
                    changes.append(r["activity"])
                elif r.get("activity_status"):
                    invalid_changes += 1
        results.setdefault("activities", []).append(
            {"date": date_str, "odometer_km": int(km), "changes": changes,
             "invalid_changes_count": invalid_changes,
             "source": "vu_recordarray"})
        emitted["activity_day"] = emitted.get("activity_day", 0) + 1
    return emitted


# ── Additional G2.2 record decoders (moved from g2_decoders) ──────────────


def decode_time_adj_gnss(rec):
    """VuTimeAdjustmentGNSSRecord (8 bytes): oldTimeValue(4) + newTimeValue(4)."""
    if len(rec) < 8:
        return None
    old_ts = struct.unpack(">I", rec[0:4])[0]
    new_ts = struct.unpack(">I", rec[4:8])[0]
    return {
        "old_time": _iso(old_ts) or "N/A",
        "new_time": _iso(new_ts) or "N/A",
    }


# recordType 0x1D (VuTimeAdjustmentGNSSRecord) shares the 8-byte old/new layout
# of the tag-only 0x052F record; register it so a full VU stream decodes it
# instead of leaving it raw.
_RECORD_DECODERS[0x1D] = decode_time_adj_gnss


def decode_sensor_fault(rec):
    """VuSensorFaultData (90 bytes): event header + sensor-specific payload."""
    if len(rec) < 90:
        return None
    evt_type = rec[0]
    evt_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    fault_hint = {
        0x01: "communication_error", 0x02: "data_integrity",
        0x03: "sensor_timeout", 0x04: "power_supply",
        0x05: "signal_error", 0x0B: "generic_sensor_fault",
        0x0C: "internal_vu_fault",
    }.get(evt_type, "unknown")
    payload = rec[10:]
    non_zero = []
    run_start = None
    for i, b in enumerate(payload):
        if b not in (0x00, 0xFF):
            if run_start is None:
                run_start = i
        elif run_start is not None:
            non_zero.append((run_start, i))
            run_start = None
    if run_start is not None:
        non_zero.append((run_start, len(payload)))
    return {
        "description": describe_fault(evt_type),
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "fault_type_hint": fault_hint,
        "begin_time": _iso(begin_ts) or "N/A",
        "end_time": _iso(end_ts) or "N/A",
        "card_driver_begin": decode_full_card_number_gen(rec, 10),
        "card_driver_end": decode_full_card_number_gen(rec, 29),
        "card_codriver_begin": decode_full_card_number_gen(rec, 48),
        "card_codriver_end": decode_full_card_number_gen(rec, 67),
        "payload_bytes": len(payload),
        "payload_hex": payload[:32].hex() + ("..." if len(payload) > 32 else ""),
        "non_zero_regions": non_zero,
        "confidence": "low",
    }


def decode_detailed_speed(rec):
    """VuDetailedSpeedData (64 bytes): timestamp(4) + 60 x speed UInt8 km/h."""
    if len(rec) < 64:
        return None
    timestamp = struct.unpack(">I", rec[0:4])[0]
    speeds = list(rec[4:64])
    valid = [s for s in speeds if s != 0xFF]
    return {
        "timestamp": _iso(timestamp) or "N/A",
        "speeds_kmh": speeds,
        "valid_speed_count": len(valid),
        "max_speed_kmh": max(valid) if valid else None,
        "avg_speed_kmh": round(sum(valid) / len(valid), 2) if valid else None,
        "confidence": "medium",
    }


def _read_coded_string(data, off):
    """Read codePage(1) + size(1) + text(size) from binary data."""
    if off + 2 > len(data):
        return "", off
    code_page = data[off]
    size = data[off + 1]
    off += 2
    if off + size > len(data):
        return "", min(off, len(data))
    enc = {0x01: "iso-8859-1", 0x02: "iso-8859-2", 0x03: "iso-8859-3",
           0x04: "iso-8859-4", 0x05: "iso-8859-5", 0x06: "iso-8859-6",
           0x07: "iso-8859-7", 0x08: "iso-8859-8", 0x09: "iso-8859-9",
           0x0A: "iso-8859-10", 0x0B: "iso-8859-11",
           0x0D: "iso-8859-13", 0x0E: "iso-8859-14",
           0x0F: "iso-8859-15", 0x10: "iso-8859-16"}.get(code_page, "latin-1")
    text = data[off:off + size].decode(enc, errors="replace").strip()
    return text, off + size


def decode_controller_identification(rec):
    """VuControllerIdentification: manufacturer + HW/SW versions + approval + serial."""
    if len(rec) < 2:
        return None
    try:
        pos = 0
        mfg_code = rec[pos]
        pos += 1
        mfg_name, pos = _read_coded_string(rec, pos)
        hw_ver, pos = _read_coded_string(rec, pos)
        sw_ver, pos = _read_coded_string(rec, pos)
        if pos + 18 > len(rec):
            return None
        approval = struct.unpack(">Q", rec[pos:pos + 8])[0]
        pos += 8
        serial = struct.unpack(">Q", rec[pos:pos + 8])[0]
        pos += 8
        mfg_year = rec[pos] if pos < len(rec) else 0
        return {
            "manufacturer_code": mfg_code,
            "manufacturer_name": mfg_name,
            "hardware_version": hw_ver,
            "software_version": sw_ver,
            "approval_number": f"0x{approval:016X}",
            "serial_number": f"0x{serial:016X}",
            "manufacturing_year": mfg_year + 2000 if mfg_year else "N/A",
            "confidence": "medium",
        }
    except (struct.error, IndexError):
        return None


def decode_vu_tag_record(tag, rec):
    """Decode an isolated 0x05xx VU tag record in the canonical result shape.

    Most tag-keyed records have an equivalent full-VU record type. The three
    remaining tag-only formats retain their dedicated decoder and result key.
    """
    record_type = VU_TAG_RECORD_TYPES.get(tag)
    if record_type is not None:
        return decode_vu_record(record_type, rec)
    tag_decoders = {
        0x052B: decode_controller_identification,
        0x052F: decode_time_adj_gnss,
        0x0531: decode_sensor_fault,
    }
    decoder = tag_decoders.get(tag)
    return decoder(rec) if decoder else None
