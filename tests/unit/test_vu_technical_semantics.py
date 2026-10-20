"""Gen2 / Gen2.2 Technical data (TREP 25 / 35) — serial, seal and calibration detail.

The record *boundaries* were already right; the subfields were not decoded:

* ``ExtendedSerialNumber`` (Annex 1B §2.56 / Annex 1C §2.56) is ``serialNumber
  INTEGER(0..2^32-1) + monthYear BCDString(SIZE(2)) + type OCTET STRING(1) +
  manufacturerCode``. VU, sensor, external-GNSS, RCM and card serials were shown
  as 8 raw hex bytes.
* ``ExtendedSealIdentifier`` (Reg. (EU) 2021/1228, ``SealDataVu``) is
  ``manufacturerCode IA5String(SIZE(2)) + sealIdentifier IA5String(SIZE(8))``;
  the code kept all ten bytes as one hex string under the equipment type.
* ``VuCalibrationRecord`` is exactly 222 bytes in generation 2 and 252 bytes in
  generation 2 version 2 (2021/1228 adds three ``ExtendedSerialNumber`` values,
  ``SealDataVu``, ``byDefaultLoadType``, ``calibrationCountry`` and
  ``calibrationCountryTimestamp``).

Every serial, seal and date below is synthetic.
"""
import struct

from core.parser.vu_dispatcher import (
    decode_calibration, decode_extended_seal_identifier, decode_extended_serial_number,
    decode_sensor_paired, decode_vu_card_record, decode_vu_identification,
    walk_vu_record_arrays)
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"}}


# ── ExtendedSerialNumber ────────────────────────────────────────────────────

def test_extended_serial_number_decodes_every_subfield():
    raw = S.extended_serial(0x0102A3B4, year_suffix=24, month=11,
                            equipment_type=0x81, manufacturer=0xA2)
    out = decode_extended_serial_number(raw, 0)
    assert out["serial_number"] == 0x0102A3B4
    assert out["month"] == 11
    # §2.56 assigns only the two *last* digits of the year: no century is
    # reconstructed from them.
    assert out["year_suffix"] == 24
    assert "year" not in out
    assert out["month_year_bcd"] == "1124"
    assert out["equipment_type"] == 0x81
    assert out["equipment_type_status"] == "manufacturer specific"
    assert out["manufacturer_code"] == 0xA2
    assert out["manufacturer_status"] == "registered"


def test_extended_serial_number_reserved_type_is_labelled():
    raw = S.extended_serial(0x00000001, equipment_type=0xFF)
    out = decode_extended_serial_number(raw, 0)
    assert out["equipment_type_status"] == "reserved (0xFF)"


def test_extended_serial_number_offset_must_be_bounded():
    raw = S.extended_serial(1)
    assert decode_extended_serial_number(raw, -1) is None
    assert decode_extended_serial_number(raw, 4) is None
    assert decode_extended_serial_number(raw, 0)["serial_number"] == 1


def test_extended_serial_number_rejects_a_non_bcd_month():
    raw = struct.pack(">I", 7) + b"\x1A\x24" + b"\x01\x0C"   # month nibble 'A'
    out = decode_extended_serial_number(raw, 0)
    assert out["month"] is None
    assert out["month_year_status"] == "invalid BCD / month"
    assert out["month_year_bcd"] == "1a24"


def test_vu_identification_serial_keeps_hex_and_gains_the_fields():
    serial = S.extended_serial(0x0A0B0C0D)
    rec = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
           + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
           + b"PART0001        " + serial
           + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
           + b"APPROVAL")
    assert len(rec) == 116
    out = decode_vu_identification(rec)
    assert out["serial_number"] == serial.hex()
    assert out["serial"]["serial_number"] == 0x0A0B0C0D
    assert out["serial"]["manufacturer_code"] == 0x0C
    assert out["serial"]["manufacturer_status"] == "not_registered"


def test_sensor_paired_serial_keeps_hex_and_gains_the_fields():
    serial = S.extended_serial(0x0000BEEF)
    rec = serial + b"APPROVAL        " + struct.pack(">I", TIME)
    assert len(rec) == 28
    out = decode_sensor_paired(rec)
    assert out["sensor_serial"] == serial.hex()
    assert out["sensor_serial_extended"]["serial_number"] == 0x0000BEEF


# ── ExtendedSealIdentifier ──────────────────────────────────────────────────

def test_extended_seal_identifier_splits_manufacturer_and_seal():
    raw = b"9X" + b"SEAL0001"
    out = decode_extended_seal_identifier(raw)
    assert out["manufacturer_code"] == "9X"
    assert out["seal_identifier"] == "SEAL0001"


def test_seal_record_keeps_equipment_type_and_full_raw():
    seal = bytes([0x03]) + b"9X" + b"SEAL0001"
    from core.parser.vu_dispatcher import _decode_seal_data
    out = _decode_seal_data(seal * 5)
    assert len(out) == 5
    assert out[0]["equipment_type"] == 0x03
    assert out[0]["manufacturer_code"] == "9X"
    assert out[0]["seal_identifier"] == "SEAL0001"
    # The ten identifier bytes stay available as their hex form.
    assert out[0]["extended_seal_identifier"] == seal[1:].hex()


# ── VuCalibrationRecord variants ────────────────────────────────────────────

def _calibration(size):
    """One synthetic VuCalibrationRecord of *size* (222 = G2, 252 = G2.2)."""
    body = (
        bytes([0x04])                                        # periodic inspection
        + S.coded_string("SYNTH WORKSHOP", code_page=1, length=36)
        + S.coded_string("SYNTH STREET 9", code_page=1, length=36)
        + S.full_card_number(card_type=0x02)                 # workshop card (18)
        + struct.pack(">I", TIME + 86_400)
        + S.VIN.encode("ascii")                              # 17
        + bytes([0x1A]) + S.coded_string(S.PLATE, code_page=1, length=14)
        + struct.pack(">HHH", 0x1F40, 0x2710, 0x0C80)        # W, K, L
        + S.coded_string("315/70R22.5", code_page=1, length=15)
        + bytes([0x5A])                                      # authorised speed
        + (100_000).to_bytes(3, "big") + (100_123).to_bytes(3, "big")
        + struct.pack(">III", TIME, TIME + 30, TIME + 2_592_000)
    )
    assert len(body) == 167, len(body)
    if size == 252:
        body += (S.extended_serial(0x0000A001) + S.extended_serial(0x0000A002)
                 + S.extended_serial(0x0000A003)
                 + (bytes([0x01]) + b"9X" + b"SEAL0001") * 5
                 + bytes([0x02]) + bytes([0x1A]) + struct.pack(">I", TIME + 60))
    else:
        body += (bytes([0x01]) + b"9X" + b"SEAL0001") * 5
    return body


def test_calibration_167_byte_base_covers_every_field():
    out = decode_calibration(_calibration(222))
    assert out["workshop_name"] == "SYNTH WORKSHOP"
    assert out["workshop_card"]["card_type"] == 0x02
    assert out["vin"] == S.VIN
    assert out["vehicle_registration"]["nation"] == "I"
    assert out["vehicle_registration"]["plate"] == S.PLATE
    assert out["w_vehicle_constant"] == 0x1F40
    assert out["k_constant"] == 0x2710
    assert out["l_tyre_circumference"] == 0x0C80
    assert out["tyre_size"] == "315/70R22.5"
    assert out["authorised_speed_kmh"] == 0x5A
    assert out["old_odometer_km"] == 100_000
    assert out["new_odometer_km"] == 100_123
    assert out["next_calibration_date"] is not None
    assert out["record_complete"] is True
    assert out["calibration_variant"] == "generation 2 (222)"
    assert out["calibration_variant_source"] == "record length (no section context)"


def test_generation_2_calibration_has_only_the_seal_block():
    out = decode_calibration(_calibration(222))
    assert len(out["seal_data_vu"]) == 5
    assert "sensor_serial_number" not in out
    assert out["raw_tail_bytes"] == 0


def test_generation_2_v2_calibration_adds_serials_load_type_and_country():
    out = decode_calibration(_calibration(252))
    assert out["calibration_variant"] == "generation 2, version 2 (252)"
    assert out["sensor_serial_number"] == S.extended_serial(0x0000A001).hex()
    assert out["sensor_serial"]["serial_number"] == 0x0000A001
    assert out["sensor_gnss_serial"]["serial_number"] == 0x0000A002
    assert out["rcm_serial"]["serial_number"] == 0x0000A003
    assert out["by_default_load_type"] == 0x02
    assert out["by_default_load_type_label"] == "passengers"
    assert out["calibration_country"] == "I"
    assert out["calibration_country_timestamp"] is not None


def test_calibration_variant_follows_the_section_generation():
    """A 252-byte body inside a generation-2 (222) section is not decoded as v2."""
    out = decode_calibration(_calibration(252), generation="G2")
    assert out["record_complete"] is False
    assert out["confidence"] == "low"
    assert out["calibration_variant_source"] == "section (generation G2)"
    out = decode_calibration(_calibration(252), generation="G2.2")
    assert out["record_complete"] is True
    # the label now describes the record's own size; the section expectation and
    # the mismatch flag carry the context
    assert out["calibration_variant"] == "generation 2, version 2 (252)"
    assert out["calibration_variant_expected"] == "generation 2, version 2 (252)"
    assert out["calibration_variant_mismatch"] is False


def test_calibration_plate_is_decoded_through_its_code_page():
    body = bytearray(_calibration(222))
    body[113] = 0x01                      # code page 1 = latin-1
    body[114:127] = "T\u00c9STPLATE123".encode("latin-1")
    out = decode_calibration(bytes(body))
    assert out["vehicle_registration"]["plate"] == "T\u00c9STPLATE123"


def test_non_normative_calibration_length_is_kept_raw_and_low():
    body = _calibration(222)[:200]
    out = decode_calibration(body)
    assert out["record_complete"] is False
    assert out["confidence"] == "low"
    assert out["record_bytes"] == 200
    assert out["raw_tail_hex"]
    assert out["vin"] == S.VIN          # unambiguous fields still decoded


# ── VuCardRecord structure version ──────────────────────────────────────────

def test_vu_card_record_decodes_the_structure_version_halves():
    rec = (S.card_number() + S.extended_serial(0x0001C0DE)
           + bytes([0x02, 0x03]) + b"SYNTHCARDNUMBER1")
    assert len(rec) == 45
    out = decode_vu_card_record(rec)
    assert out["card_number"] == "SYNTHCARDNUMBER1"
    assert out["card_structure_version"] == "0203"
    # CardStructureVersion 'aabb'H: aa = structure index, bb = data-element use.
    assert out["card_structure_version_parts"] == {
        "structure_index": 0x02, "data_elements_index": 0x03}
    assert out["card_serial"]["serial_number"] == 0x0001C0DE


# ── The records survive final emission ──────────────────────────────────────

def test_technical_records_reach_the_results():
    cal = S.record_array(0x0C, 252, [_calibration(252)])
    stream = S.section(0x35, cal, S.signature_record())
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert results["calibrations"][0]["sensor_serial"]["serial_number"] == 0x0000A001


# ── Unresolved encodings stay raw ───────────────────────────────────────────

def test_digital_map_version_is_an_ia5_string_of_twelve():
    rec = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
           + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
           + b"PART0001        " + S.extended_serial(0x0000C0DE)
           + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
           + b"APPROVAL" + bytes([0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B])
           + bytes(range(12)))
    assert len(rec) == 138
    out = decode_vu_identification(rec)
    # The existing visible reading is unchanged; the raw bytes (all of them,
    # not a 12-byte clip) travel as a hidden companion.
    assert out["digital_map_version_raw"] == bytes(range(12)).hex()
    assert out["digital_map_version"] == ""      # non-printable bytes, unchanged
    assert out["digital_map_version_status"] == "valid (IA5String(12))"


def test_digital_map_version_is_not_clipped_to_its_corpus_width():
    rec = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
           + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
           + b"PART0001        " + S.extended_serial(0x0000C0DE)
           + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
           + b"APPROVAL" + bytes(range(10)) + bytes(range(16)))
    assert len(rec) == 142
    out = decode_vu_identification(rec)
    assert out["digital_map_version_raw"] == bytes(range(16)).hex()
    assert out["digital_map_version_status"] == "valid (IA5String(12))"
    assert out["record_complete"] is False
    assert out["raw_tail_bytes"] == 4


def test_its_consent_keeps_the_raw_octet_next_to_the_reading():
    from core.parser.vu_dispatcher import decode_its_consent
    out = decode_its_consent(S.card_number() + b"\x02")
    assert out["consent"] is False        # low bit clear
    assert out["consent_raw"] == 0x02
    assert out["consent_status"].startswith("raw")


def test_card_route_keeps_a_zero_zero_position():
    """Obs 5: the shared GeoCoordinates reading is used by card routes too.

    ``core.decoders.common._decode_gnss_coord`` never suppressed (0°,0°) — it
    already only rejects the 0x7FFFFF sentinel and out-of-range values, so the
    VU-side all-zero heuristic was the outlier. Pinned here so a future "fix"
    cannot re-introduce it on the card path.
    """
    from core.decoders.common import _decode_gnss_coord
    assert _decode_gnss_coord(b"\x00\x00\x00", 0, maximum_degrees=90) == 0.0
    assert _decode_gnss_coord(b"\x00\x00\x00", 0, maximum_degrees=180) == 0.0
    assert _decode_gnss_coord(b"\x7f\xff\xff", 0) is None


def test_digital_map_version_flags_a_non_ia5_octet():
    """IA5String(12) is ASCII only: a high octet is reported, bytes kept."""
    rec = bytearray(S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
                    + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
                    + b"PART0001        " + S.extended_serial(0x0000C0DE)
                    + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
                    + b"APPROVAL" + bytes(range(10)) + b"MAP-VER-0001")
    assert len(rec) == 138
    rec[130] = 0xE9                      # not an IA5 octet
    out = decode_vu_identification(bytes(rec))
    assert out["digital_map_version_status"] == "invalid IA5 (kept raw)"
    assert out["digital_map_version_raw"] == bytes(rec[126:138]).hex()


# ── F10: generation-aware calibration purpose and honest variant label ─────

def test_generation_1_calibration_purpose_05_and_06_are_not_generation_2_meanings():
    from core.utils.event_codes import describe_calibration_purpose
    assert describe_calibration_purpose(0x05, generation="G2") == (
        "Entry of VRN by company")
    # generation 1 defines 00..04 only (Reg. 2016/799 Appendix 1 point 2.71)
    assert describe_calibration_purpose(0x05, generation="G1") == (
        "Reserved for future use (0x05)")
    assert describe_calibration_purpose(0x06, generation="G1") == (
        "Reserved for future use (0x06)")
    assert describe_calibration_purpose(0x04, generation="G1") == (
        "Periodic inspection")


def test_g1_calibration_records_use_the_generation_1_purpose_labels():
    from core.decoders.vu_g1 import _parse_trep_05_technical
    from tests.unit.test_g1_vu_semantics import _g1_calibration, _results, _trep05_body
    results = _results()
    _parse_trep_05_technical(_trep05_body([_g1_calibration(purpose=0x05)]), results)
    assert results["calibrations"][0]["purpose"] == "Reserved for future use (0x05)"


def test_variant_label_describes_the_record_actually_decoded():
    """A 252-byte record inside a generation-2 (222) section keeps the section
    expectation separately and is labelled by its own size."""
    out = decode_calibration(_calibration(252), generation="G2")
    assert out["calibration_variant"] == "generation 2, version 2 (252)"
    assert out["calibration_variant_expected"] == "generation 2 (222)"
    assert out["calibration_variant_mismatch"] is True
    assert out["record_complete"] is False


def test_matching_variant_is_not_flagged_as_a_mismatch():
    out = decode_calibration(_calibration(252), generation="G2.2")
    assert out["calibration_variant_mismatch"] is False
    assert out["calibration_variant_expected"] == "generation 2, version 2 (252)"
