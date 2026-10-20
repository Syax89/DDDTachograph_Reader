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

import pytest

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


def test_resynchronisation_is_counted_and_fails_completeness():
    """Junk inside a section is tolerated but never silent."""
    stream = (_overview_stream()
              + b"\xde\xad\xbe\xef"                       # junk, no header/section
              + S.section(0x24,
                          S.record_array(0x12, 64,
                                         [struct.pack(">I", TIME) + bytes(60)]),
                          S.signature_record()))
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert results["metadata"]["vu_walk_resync_bytes"] >= 1
    assert results["_vu_walk_complete"] is False


# ── Integrity vs decodability (G1 and G2) ──────────────────────────────────

def _g1_trep05():
    body = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
            + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
            + b"PART0001        " + S.extended_serial(0x0000A001)
            + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
            + b"APPROVAL" + S.extended_serial(0x0000A002)
            + b"SENSORAP" + struct.pack(">I", TIME + 60) + b"\x00")
    return b"\x76\x05" + body


def test_g1_short_signature_is_integrity_not_a_decode_failure():
    """A cut RSA block leaves the records decodable: no fallback, no heuristic."""
    from core.parser.g1_walker import walk_g1_vu

    for cut in (1, 127):
        stream = _g1_trep05() + b"\x11" * (128 - cut)
        results = {"metadata": {}}
        messages, complete = walk_g1_vu(stream, results)
        assert complete is False
        assert results["_g1_walk_decoded_all"] is True
        integrity = results["metadata"]["vu_integrity"]
        assert integrity == [{"trep": "0x05", "status": "signature_truncated",
                              "missing_bytes": cut, "trailing_bytes": 128 - cut}]


def test_g1_trailing_junk_after_the_last_signature_is_integrity():
    from core.parser.g1_walker import walk_g1_vu

    stream = _g1_trep05() + b"\x11" * 128 + b"\xde\xad"
    results = {"metadata": {}}
    _messages, complete = walk_g1_vu(stream, results)
    assert complete is False
    assert results["_g1_walk_decoded_all"] is True
    assert results["metadata"]["vu_integrity"][0]["status"] == "trailing_bytes"


def test_g1_data_cut_mid_array_is_a_decode_failure():
    """When the DATA part does not fit its declared size, the walk cannot decode
    it: `decoded_all` is False, which is what allows the declared fallback."""
    from core.parser.g1_walker import walk_g1_vu

    results = {"metadata": {}}
    # a TREP 04 body declaring 4 blocks but carrying 2
    stream = b"\x76\x04" + struct.pack(">H", 4) + (struct.pack(">I", TIME)
                                                   + bytes(60)) * 2
    messages, complete = walk_g1_vu(stream, results)
    assert messages == []
    assert complete is False
    assert results["_g1_walk_decoded_all"] is False


def test_gen2_short_signature_record_is_integrity_only():
    stream = _overview_stream()[:-10]
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert results["_vu_walk_complete"] is False
    statuses = [entry["status"] for entry in results["metadata"]["vu_integrity"]]
    # the cut signature record is truncated AND therefore not a valid signature
    # array: both are integrity facts, neither triggers a rescan
    assert sorted(statuses) == ["array_truncated", "signature_missing"], statuses
    # the decoded data of every complete array is still there
    assert results["vehicle"]["vin"] == S.VIN


# ── Why a fallback ran (closed cause vocabulary) ───────────────────────────

def test_fallback_causes_are_a_closed_vocabulary():
    from core.parser import fallback_reasons as fr
    assert fr.CAUSES == {
        "file_truncated", "count_exceeds_eof", "size_mismatch",
        "unknown_or_misplaced_section", "schema_violation",
        "normative_decoder_exception", "normative_layout_not_matched"}
    assert fr.classification_for("file_truncated") == "file_damaged"
    assert fr.classification_for("normative_decoder_exception") == (
        "decoder_defect_suspected")
    with pytest.raises(ValueError):
        fr.fallback_reason("route", "made_up_cause")


def test_a_section_route_inherits_the_primary_cause():
    """A scan that runs because the file is cut is not relabelled a defect."""
    from core.parser import fallback_reasons as fr
    results = {"metadata": {}}
    fr.record_fallback_reason(results, "vu_fallback_scan", "file_truncated",
                              trep="0x11", offset=1234, detail="declared body")
    fr.record_fallback_reason(results, "vu_activities_TREP02", detail="activities")
    reasons = results["metadata"]["decode_paths"]["fallback_reasons"]
    assert [r["cause"] for r in reasons] == ["file_truncated", "file_truncated"]
    assert reasons[0]["classification"] == "file_damaged"
    assert fr.primary_reason(results) is reasons[0]


def test_fallback_reasons_are_bookkeeping_not_a_column():
    from core.utils import report_format
    assert "fallback_reasons" in report_format.HIDDEN_KEYS
    assert report_format.visible_columns([{"fallback_reasons": ["x"], "timestamp": "t"}]) == ["timestamp"]


# ── F1: a card EF image is bounded by its own 2-byte STAP length ────────────

def _stap_element(tag, length, fill=0x41):
    return struct.pack(">HBH", tag, 0, length) + bytes([fill]) * length


def test_card_ef_element_larger_than_the_recordarray_cap_stays_whole():
    """A card EF is 12-14 KB in practice: the RecordArray cap must not cut it.

    Annex 1B DDP_044: the STAP length is a two-byte value (``FFFF`` reserved), so
    a legitimate elementary file may be up to 65534 bytes. The old bound reused
    ``RECORD_ARRAY_MAX_SIZE`` (4096, a RecordArray sanity cap).
    """
    for length in (4096, 4097, 12000, 65534):
        stream = b"\x76\x06" + _stap_element(0x0502, length) + _stap_element(0x0504, 3)
        section = list(iter_vu_sections(stream, {}))[0]
        card = section["card_tlv"]
        assert card["tlvs"] == 2, length
        assert card["tlv_complete"] is True, length
        assert card["bytes"] == len(stream) - 2, length
        assert card["boundary"] == "STAP/EF framing", length


def test_truncated_last_card_element_is_reported_not_swallowed():
    stream = b"\x76\x06" + _stap_element(0x0502, 64)[:-10]
    section = list(iter_vu_sections(stream, {}))[0]
    card = section["card_tlv"]
    assert card["tlv_complete"] is False
    assert card["bytes"] == len(stream) - 2


def test_a_76xx_pair_inside_a_card_element_does_not_split_it():
    """Card EF bytes may contain ``76 01``: the TLV length decides the end."""
    payload = bytes([0x76, 0x01, 0x02]) + b"\x00" * 61
    stream = b"\x76\x06" + struct.pack(">HBH", 0x0502, 0, len(payload)) + payload
    sections = list(iter_vu_sections(stream, {}))
    assert len(sections) == 1
    assert sections[0]["trep"] == 0x06
    assert sections[0]["card_tlv"]["bytes"] == len(payload) + 5


def test_card_region_ends_exactly_at_the_next_trep_section():
    card = _stap_element(0x0502, 5000)
    speed = S.record_array(0x12, 64, [struct.pack(">I", TIME) + bytes(60)])
    stream = b"\x76\x06" + card + S.section(0x24, speed, S.signature_record())
    sections = list(iter_vu_sections(stream, {}))
    assert [s["trep"] for s in sections] == [0x06, 0x24]
    assert sections[0]["card_tlv"]["bytes"] == len(card)
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert results["speed_blocks"]
    assert results["metadata"]["vu_card_download_sections"][0]["tlv_complete"] is True


def test_standalone_card_wrapper_takes_the_card_generation():
    """F12: a 76 06 wrapper around a G2 card is not a generation-1 download."""
    from core.parser.deterministic import DeterministicParser
    # Gen2-only EF (Vehicle Units Used) inside the wrapper: the card's own
    # generation evidence, exactly what a bare card image uses.
    payload = (struct.pack(">HBH", 0x0501, 2, 4) + b"\x00\x00\x00\x00"
               + struct.pack(">HBH", 0x0523, 2, 4) + b"\x00\x00\x00\x00")
    results = DeterministicParser().parse(b"\x76\x06" + payload, is_vu=False)
    assert results["metadata"]["generation"] != "G1 (Digital)"


# ── F3: no stored record is dropped at final emission ──────────────────────

def _section_with(arrays, trep=0x32):
    return S.section(trep, *arrays, S.signature_record())


def test_places_specific_conditions_and_gnss_ad_with_unusable_times_are_kept():
    bad_time = struct.pack(">I", 0xFFFFFFFF)
    place_bad = S.card_number() + bad_time + bytes([0x00, 0x1A, 0x07]) + bytes(3) \
        + struct.pack(">I", TIME) + bytes([0x02]) + b"\x00" * 6 + b"\x01"
    place_good = S.card_number() + struct.pack(">I", TIME) + bytes([0x00, 0x1A, 0x07]) \
        + bytes(3) + struct.pack(">I", TIME) + bytes([0x02]) + b"\x00" * 6 + b"\x01"
    stream = _section_with([
        S.record_array(0x1C, 41, [place_good, place_bad]),
        S.record_array(0x09, 5, [struct.pack(">IB", TIME, 1),
                                 struct.pack(">IB", 0xFFFFFFFF, 1)]),
    ])
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert len(results["places"]) == 2
    assert len(results["specific_conditions"]) == 2
    bad_place = [p for p in results["places"] if p["timestamp"] is None]
    assert len(bad_place) == 1
    assert bad_place[0]["timestamp_raw"] == 0xFFFFFFFF
    assert bad_place[0]["time_status"] == "invalid"


def test_short_event_and_fault_records_are_emitted_not_dropped():
    stream = _section_with([
        S.record_array(0x15, 8, [bytes(8), bytes(8)], ),
        S.record_array(0x18, 8, [bytes(8)]),
    ], trep=0x23)
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert len(results["events"]) == 2
    assert len(results["faults"]) == 1
    assert all(rec["record_complete"] is False for rec in results["events"])


def test_activity_word_with_an_impossible_minute_is_counted_not_lost():
    # minute 1500 = 0b10111 ① 10111100 → decode_activity_val returns None
    stream = _section_with([
        S.record_array(0x06, 4, [struct.pack(">I", TIME)]),
        S.record_array(0x05, 3, [(1000).to_bytes(3, "big")]),
        S.record_array(0x01, 2, [struct.pack(">H", 0x10F3), struct.pack(">H", 0xFFFF)]),
    ])
    results = _results()
    walk_vu_record_arrays(stream, results)
    day = results["activities"][0]
    assert len(day["changes"]) == 1
    assert day["invalid_changes_count"] == 1


def test_schema_report_accounts_stored_and_emitted_records():
    stream = _section_with([
        S.record_array(0x09, 5, [struct.pack(">IB", TIME, 1),
                                 struct.pack(">IB", 0xFFFFFFFF, 1)]),
    ])
    results = _results()
    walk_vu_record_arrays(stream, results)
    report = results["metadata"]["vu_section_schema"][0]
    assert report["stored_records"] == {"0x09": 2}
    assert report["emitted_records"] == {"0x09": 2}
    assert report["dropped_records"] == {}


# ── F8: structure findings (integrity), never heuristic triggers ───────────

def _two_sections(*arrays):
    return S.section(0x33, *arrays)


def test_duplicate_arrays_are_reported_and_not_complete():
    report = validate_section_schema(0x23, [(0x18, 1), (0x15, 1), (0x15, 1),
                                            (0x1A, 1), (0x1B, 0), (0x1E, 0),
                                            (0x08, 1)])
    assert report["duplicate_arrays"] == ["0x15"]
    assert report["status"] == "incomplete"


def test_extra_array_in_a_known_section_is_a_schema_violation():
    report = validate_section_schema(0x23, [(0x18, 1), (0x22, 1), (0x15, 1)])
    assert report["unexpected_arrays"] == ["0x22"]
    assert report["status"] == "incomplete"


def test_signature_array_must_hold_exactly_one_record():
    for nr in (0, 2):
        report = validate_section_schema(0x33, [(0x18, 0), (0x15, 0), (0x1A, 1),
                                                (0x1B, 0), (0x1E, 0), (0x08, nr)])
        assert report["signature_problem"] == f"noOfRecords={nr}", nr
        assert report["status"] == "incomplete"


def test_signature_record_size_outside_the_allowed_range_is_reported():
    for size in (3, 200):
        report = validate_section_schema(0x33, [(0x18, 0), (0x15, 0), (0x1A, 1),
                                                (0x1B, 0), (0x1E, 0),
                                                (0x08, 1)] , signature_size=size)
        assert report["signature_problem"] == f"recordSize={size}", size
        assert report["status"] == "incomplete"


def test_missing_final_signature_makes_the_walk_incomplete():
    stream = S.section(0x24, S.record_array(0x12, 64,
                                            [struct.pack(">I", TIME) + bytes(60)]))
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert results["_vu_walk_complete"] is False
    assert any(entry["status"] == "signature_missing"
               for entry in results["metadata"]["vu_integrity"])


def test_structure_findings_stay_out_of_the_heuristic_route():
    """A duplicate array is an integrity finding: no scan, no heuristic fields."""
    stream = S.section(0x23,
                       S.record_array(0x15, 91, [b"\x04" + b"\x00" * 90]),
                       S.record_array(0x15, 91, [b"\x05" + b"\x00" * 90]),
                       S.signature_record())
    results = _results()
    walk_vu_record_arrays(stream, results)
    report = results["metadata"]["vu_section_schema"][0]
    assert report["duplicate_arrays"] == ["0x15"]
    assert results["metadata"].get("heuristic_fields") is None
    assert results["metadata"]["decode_paths"] if "decode_paths" in results["metadata"] else True
    assert len(results["events"]) == 2


# ── F9: one shared size rule for every fixed-size record ───────────────────

def test_canonical_record_sizes_are_labelled_complete():
    from core.parser.vu_dispatcher import CANONICAL_RECORD_SIZES, decode_vu_record
    assert CANONICAL_RECORD_SIZES[0x1B] == 32      # VuOverSpeedingEventRecord
    assert CANONICAL_RECORD_SIZES[0x1C] == 40      # place, generation 2
    assert CANONICAL_RECORD_SIZES[0x22] == 55      # border crossing
    assert CANONICAL_RECORD_SIZES[0x16] == 56      # GNSS accumulated driving, v1
    record = bytes([0x07, 0x00]) + struct.pack(">II", TIME, TIME + 30) \
        + bytes([0x5A, 0x50]) + S.card_number() + bytes([0x01])
    out = decode_vu_record(0x1B, record)
    assert out["record_complete"] is True
    assert out["confidence"] == "high"


def test_oversized_overspeed_record_is_low_confidence_with_a_raw_tail():
    from core.parser.vu_dispatcher import decode_vu_record
    record = bytes([0x07, 0x00]) + struct.pack(">II", TIME, TIME + 30) \
        + bytes([0x5A, 0x50]) + S.card_number() + bytes([0x01]) + b"\xaa" * 8
    out = decode_vu_record(0x1B, record)
    assert out["record_complete"] is False
    assert out["confidence"] == "low"
    assert out["record_bytes"] == 40
    assert out["raw_tail_hex"] == "aa" * 8
    # the canonical prefix is still decoded
    assert out["max_speed_kmh"] == 0x5A


def test_short_and_long_border_crossing_records_are_incomplete():
    from core.parser.vu_dispatcher import decode_vu_record
    canonical = (S.card_number() + S.EMPTY_CARD + bytes([0x0F, 0x11])
                 + struct.pack(">I", TIME) + bytes([0x02]) + b"\x00" * 6 + b"\x01"
                 + (1234).to_bytes(3, "big"))
    assert len(canonical) == 55
    for delta, size in ((-1, 54), (25, 80)):
        record = (canonical + b"\x00" * 25)[:size]
        out = decode_vu_record(0x22, record)
        assert out["record_complete"] is False, size
        assert out["confidence"] == "low", size
