"""Per-TREP RecordArray schema, signature/trailing accounting, mixed card TLV.

The array order of every generation-2 transfer is written out in Appendix 7 of
Reg. (EU) 2021/1228 (DDP_029 / DDP_030 / DDP_031 / DDP_032 / DDP_033), including
the sentence *"If the section is empty, an array header with noOfRecords = 0 is
sent"*. The walker used to accept whatever headers it found without ever asking
whether the prescribed arrays were there, in order, or whether the signature
record closed the section.

Three consequences are pinned here:

* a section missing a prescribed array (or carrying one out of order) is
  reported in ``metadata.vu_section_schema`` instead of passing silently;
* ``_vu_walk_complete`` must not be claimed when a section's trailing bytes are
  a truncated signature record;
* a ``76 06`` card-download marker inside a VU stream is delegated to the card
  EF/TLV parser over a bounded byte range, never to a byte scan.

Every value below is synthetic.
"""
import struct

from core.parser import vu_dispatcher
from core.parser.vu_dispatcher import (
    TREP_ARRAY_SCHEMA, iter_vu_sections, validate_section_schema,
    walk_vu_record_arrays)
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"}}


def _overview_stream(include_slots=True):
    arrays = [
        S.record_array(0x04, 4, [b"\x00\x01\x02\x03"]),
        S.record_array(0x0F, 4, [b"\x00\x01\x02\x03"]),
        S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
        S.record_array(0x24, 15, [bytes([0x1A]) + S.coded_string(
            S.PLATE, code_page=1, length=14)]),
        S.record_array(0x03, 4, [struct.pack(">I", TIME)]),
        S.record_array(0x13, 8, [struct.pack(">II", TIME - 86400, TIME)]),
    ]
    if include_slots:
        arrays.append(S.record_array(0x02, 1, [bytes([S.SLOTS_DRIVER_AND_COMPANY])]))
    arrays += [
        S.record_array(0x14, 4, [struct.pack(">I", TIME)]),
        S.record_array(0x10, 0, []),        # legal empty array header
        S.record_array(0x11, 0, []),
        S.signature_record(),
    ]
    return S.section(0x31, *arrays)


# ── Schema table ────────────────────────────────────────────────────────────

def test_schema_table_covers_every_gen2_transfer():
    assert set(TREP_ARRAY_SCHEMA) == {0x21, 0x22, 0x23, 0x24, 0x25,
                                      0x31, 0x32, 0x33, 0x35}


def test_overview_schema_accepts_the_documented_registration_ambiguity():
    # DDP_029 names VehicleRegistrationNumberRecordArray for TREP 31 too, while
    # the data dictionary (and every observed download) uses the 15-byte
    # VehicleRegistrationIdentification. Both are accepted; nothing is claimed.
    slot = TREP_ARRAY_SCHEMA[0x31][3]
    assert set(slot) == {0x0B, 0x24}


def test_complete_overview_section_validates():
    section = list(iter_vu_sections(_overview_stream()))[0]
    report = validate_section_schema(0x31, [(rt, nr) for (_p, rt, _rs, nr, _e)
                                            in section["records"]])
    assert report["status"] == "complete"
    assert report["missing_arrays"] == []
    assert report["out_of_order"] == []
    assert report["zero_record_arrays"] == ["0x10", "0x11"]


def test_missing_array_is_reported_not_silently_accepted():
    section = list(iter_vu_sections(_overview_stream(include_slots=False)))[0]
    report = validate_section_schema(0x31, [(rt, nr) for (_p, rt, _rs, nr, _e)
                                            in section["records"]])
    assert report["status"] == "incomplete"
    assert report["missing_arrays"] == ["0x02"]


def test_out_of_order_arrays_are_reported():
    order = [(0x04, 1), (0x0F, 1), (0x0A, 1), (0x24, 1), (0x03, 1),
             (0x13, 1), (0x02, 1), (0x14, 1), (0x10, 0), (0x11, 0), (0x08, 1)]
    swapped = order[:5] + [order[6], order[5]] + order[7:]
    report = validate_section_schema(0x31, swapped)
    assert report["out_of_order"] == ["0x02"]


def test_unknown_array_in_a_known_section_is_flagged():
    order = [(0x04, 1), (0x0F, 1), (0x0A, 1), (0x24, 1), (0x03, 1),
             (0x13, 1), (0x02, 1), (0x14, 1), (0x10, 0), (0x11, 0),
             (0x29, 1), (0x08, 1)]
    report = validate_section_schema(0x31, order)
    assert report["unexpected_arrays"] == ["0x29"]


def test_walker_publishes_the_schema_report_per_section():
    results = _results()
    walk_vu_record_arrays(_overview_stream(include_slots=False), results)
    report = results["metadata"]["vu_section_schema"]
    assert len(report) == 1
    assert report[0]["trep"] == "0x31"
    assert report[0]["status"] == "incomplete"
    assert report[0]["missing_arrays"] == ["0x02"]
    # Structural, not a recovery: the records are still emitted.
    assert results["metadata"].get("heuristic_fields") is None
    assert results["metadata"]["current_datetime"]


def test_activities_schema_includes_the_version_2_arrays_only_for_trep_32():
    v1 = {rt for slot in TREP_ARRAY_SCHEMA[0x22] for rt in slot}
    v2 = {rt for slot in TREP_ARRAY_SCHEMA[0x32] for rt in slot}
    assert {0x22, 0x23} - v1        # border crossing / load-unload are v2 only
    assert {0x22, 0x23} <= v2


# ── Signature / trailing accounting ─────────────────────────────────────────

def test_truncated_signature_record_is_not_a_complete_walk():
    stream = _overview_stream()[:-10]          # 54 of the 64 signature bytes
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert results["_vu_walk_complete"] is False
    assert results["metadata"]["vu_walk_truncated_bytes"] > 0
    assert results["metadata"]["vu_section_schema"][0]["missing_arrays"] == ["0x08"]


def test_clean_stream_stays_complete():
    results = _results()
    walk_vu_record_arrays(_overview_stream(), results)
    assert results["_vu_walk_complete"] is True
    assert "vu_walk_truncated_bytes" not in results["metadata"]


# ── Mixed card download (TREP 06 inside a VU stream) ────────────────────────

def _card_tlv_image():
    """A minimal card EF image in STAP framing: tag(2) + dtype(1) + length(2)."""
    value = b"T" + b"0" * 14
    return b"\x05\x01\x00" + struct.pack(">H", len(value)) + value


def test_card_download_marker_inside_a_vu_stream_uses_the_tlv_parser():
    card = _card_tlv_image()
    stream = (S.section(0x31, S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
                        S.signature_record())
              + b"\x76\x06" + card + b"\x76\x24"
              + S.record_array(0x12, 64, [struct.pack(">I", TIME) + bytes(60)])
              + S.signature_record())
    results = _results()
    walk_vu_record_arrays(stream, results)
    # The card payload is a bounded TLV region, reported as such.
    sections = results["metadata"]["vu_card_download_sections"]
    assert len(sections) == 1
    assert sections[0]["bytes"] == len(card)
    assert sections[0]["tlv_complete"] is True
    assert sections[0]["tlvs"] == 1
    assert sections[0]["boundary"] == "STAP/EF framing"
    # ... and the speed section that follows is still walked.
    assert results["speed_blocks"]


def test_mixed_card_download_is_decoded_by_the_card_ef_layer():
    """The bounded card region is handed to the existing card decoder."""
    # A card EF_Identification image (0x0520) in STAP framing.
    payload = (S.coded_string("TACHO", code_page=1, length=2)      # nation alpha?
               + b"T" + b"0" * 15)
    card = b"\x05\x20\x00" + struct.pack(">H", len(payload)) + payload
    results = _results()
    walk_vu_record_arrays(b"\x76\x06" + card, results)
    # The region was recognised ...
    assert results["metadata"]["vu_card_download_sections"][0]["tlv_complete"] is True
    # ... and handed to the card decoder (which may reject a tiny synthetic
    # image, but the delegation itself is observable through the marker).
    assert results["metadata"]["vu_card_download_sections"][0]["delegated"] is True


# ── G1 signature / trailing accounting ─────────────────────────────────────

def test_g1_truncated_signature_is_not_a_complete_walk():
    from core.parser.g1_walker import walk_g1_vu

    body = _g1_technical_body()
    stream = b"\x76\x05" + body + b"\x11" * 100      # 100 of the 128 bytes
    messages, complete = walk_g1_vu(stream, {})
    assert [m["trep"] for m in messages] == [0x05]
    assert complete is False


def test_g1_padding_after_the_last_signature_stays_complete():
    from core.parser.g1_walker import walk_g1_vu

    stream = b"\x76\x05" + _g1_technical_body() + b"\x00" * 128 + b"\x00\x00"
    messages, complete = walk_g1_vu(stream, {})
    assert complete is True
    assert messages[-1]["sig_len"] == 128


def _g1_technical_body():
    """TREP 05 body: VuIdentification(116) + SensorPaired(20) + 0 calibrations."""
    body = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
            + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
            + b"PART0001        " + S.extended_serial(0x0000A001)
            + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
            + b"APPROVAL" + S.extended_serial(0x0000A002)
            + b"SENSORAP" + struct.pack(">I", TIME + 60))
    return body + b"\x00"


# ── Raw preservation and certificate bodies ────────────────────────────────

def test_unknown_record_keeps_every_byte_not_a_48_byte_prefix():
    record = bytes(range(0x40, 0x40 + 80))         # 80-byte unknown body
    out = vu_dispatcher.decode_vu_record(0x5A, record)
    assert out["raw_hex"] == record.hex()
    assert len(out["raw_hex"]) == 160


def test_certificate_record_uses_the_existing_cvc_parser():
    """Structure comes from the CVC layer; trust stays a separate verdict."""
    from core.crypto.vu_signature import parse_cvc
    cert = bytes.fromhex(
        "7f2181a5020101020101020104020104" + "00" * 4)   # header-only fixture
    out = vu_dispatcher.decode_vu_record(0x0F, cert)
    if parse_cvc(cert) is None:
        # A body the CVC layer cannot recognise stays raw and says so.
        assert out["raw_hex"] == cert.hex()
        assert out["parse_status"].startswith("unrecognised")
    else:
        assert out["confidence"] == "high"
        assert "public_point" not in out
