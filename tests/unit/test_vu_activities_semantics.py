"""Gen2 / Gen2.2 Activities (TREP 22 / 32) — specification-grounded readings.

Three confirmed limits this file pins down:

* ``EntryTypeDailyWorkPeriod`` (Annex 1B §2.51, shared by every generation) has
  six assigned values — card-insertion/withdrawal, manually entered, and
  *assumed by the VU* — but ``decode_place_daily`` only knew 0..3 and printed a
  bare hex code for the rest.
* A GNSS position of exactly 0°/0° is a **real** fix in the Gulf of Guinea, not
  the "unknown position" sentinel: ``decode_geo_coordinates`` discarded it.
  Coordinates must also be range-checked (latitude ±90°, longitude ±180°) and a
  value outside that range must never be published as a position.
* The GNSS-place *variant* (11-byte ``GNSSPlaceRecord`` vs 12-byte
  ``GNSSPlaceAuthRecord``) belongs to the section version — generation 2,
  version 2 introduced the authentication status — not to a record length.

Every value below is synthetic.
"""
import struct

from core.parser.vu_dispatcher import (
    decode_geo_coordinates, decode_place_daily, decode_gnss_ad,
    decode_specific_condition, walk_vu_record_arrays)
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME
GEO_ZERO = b"\x00\x00\x00" * 2


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"}}


def _place_record(entry_type=0x00, geo=GEO_ZERO, auth=None):
    """PlaceRecord (G2, 40 B) / PlaceAuthRecord (G2.2, 41 B), §2.116/§2.116a."""
    body = (S.card_number() + struct.pack(">I", TIME) + bytes([entry_type, 0x1A, 0x07])
            + (123_456).to_bytes(3, "big") + struct.pack(">I", TIME) + bytes([0x02]) + geo)
    if auth is not None:
        body += bytes([auth])
    return body


# ── EntryTypeDailyWorkPeriod ────────────────────────────────────────────────

def test_place_entry_types_use_the_shared_six_value_assignment():
    expected = {
        0x00: "BEGIN", 0x01: "END", 0x02: "BEGIN", 0x03: "END",
        0x04: "BEGIN", 0x05: "END",
    }
    for code, short in expected.items():
        out = decode_place_daily(_place_record(entry_type=code))
        assert out["entry_type"] == short, code
        assert out["type_code"] == code


def test_place_entry_type_meaning_covers_the_vu_assumed_variants():
    out = decode_place_daily(_place_record(entry_type=0x04))
    assert out["entry_type_meaning"] == "Begin assumed by VU"
    out = decode_place_daily(_place_record(entry_type=0x03))
    assert out["entry_type_meaning"] == "End manually entered"


def test_unassigned_place_entry_type_is_kept_as_a_code():
    out = decode_place_daily(_place_record(entry_type=0x09))
    assert out["type_code"] == 0x09
    assert out["entry_type"] == "0x09"
    # The generation-2 enumeration is a figure in every accessible edition, so a
    # code above the shared six is "unknown", never declared "unassigned".
    assert out["entry_type_meaning"] == "unknown (0x09)"
    assert out["entry_type_status"].startswith("unknown")


def test_g1_entry_type_assignment_also_has_the_vu_assumed_values():
    """Annex 1B §2.51 is the readable text; 4/5 exist in generation 1 too."""
    from core.decoders.common import (entry_type_daily_work_period,
                                      entry_type_daily_work_period_status)
    assert entry_type_daily_work_period(0x04) == ("BEGIN", "Begin assumed by VU")
    assert entry_type_daily_work_period(0x05) == ("END", "End assumed by VU")
    assert entry_type_daily_work_period(0x00) == (
        "BEGIN", "Begin (card insertion time)")
    # Generation 1 assigns 0..5 and nothing else: above that it is not assigned.
    assert entry_type_daily_work_period_status(0x06, "G1") == "not assigned"
    assert "not assigned" in entry_type_daily_work_period(0x06, "G1")[1]
    # Generation 2 keeps the same six but its upper bound is not readable here.
    assert entry_type_daily_work_period_status(0x06, "G2").startswith("unknown")


# ── GNSS coordinates ────────────────────────────────────────────────────────

def test_zero_zero_is_a_valid_position_not_a_missing_fix():
    geo = decode_geo_coordinates(GEO_ZERO, 0)
    assert geo["fix"] is True
    assert geo["latitude_deg"] == 0.0
    assert geo["longitude_deg"] == 0.0
    assert geo["position_status"] == "valid"


def test_unknown_sentinels_remain_no_fix():
    assert decode_geo_coordinates(b"\xff" * 6, 0)["fix"] is False
    assert decode_geo_coordinates(b"\x7f\xff\xff" + b"\x00\x00\x01", 0)["fix"] is False


def test_out_of_range_coordinate_is_not_published_as_a_position():
    # 95°12.3' latitude: not a legal GeoCoordinates value (§2.76).
    raw = (952123).to_bytes(3, "big") + (137_00).to_bytes(3, "big")
    geo = decode_geo_coordinates(raw, 0)
    assert geo["fix"] is False
    assert geo["position_status"] == "out_of_range"
    assert geo["latitude_raw"] == 952123


def test_negative_coordinates_keep_their_sign():
    # -33°52.1' = -(33521); 151°12.9' = 151129.
    raw = (-33521).to_bytes(3, "big", signed=True) + (151129).to_bytes(3, "big")
    geo = decode_geo_coordinates(raw, 0)
    assert geo["fix"] is True
    assert geo["latitude_deg"] < 0
    assert geo["longitude_deg"] > 0


# ── Section-decided GNSS place variant ──────────────────────────────────────

def _activities_section(trep, auth_variant):
    geo = GEO_ZERO if auth_variant is None else b"\x00\x00\x00\x00\x00\x00"
    record = _place_record(geo=geo, auth=auth_variant)
    return S.section(
        trep,
        S.record_array(0x06, 4, [struct.pack(">I", TIME)]),
        S.record_array(0x05, 3, [(654_321).to_bytes(3, "big")]),
        S.record_array(0x01, 2, [struct.pack(">H", 0x10F3)]),
        S.record_array(0x1C, len(record), [record]),
        S.signature_record())


def test_section_version_selects_the_place_variant():
    results = _results()
    walk_vu_record_arrays(_activities_section(0x22, None), results)
    place = results["places"][0]
    assert place["record_bytes"] == 40
    assert place["variant_source"] == "section (TREP 0x22)"
    assert "authentication_status" not in (place["gnss_place"] or {})

    results = _results()
    walk_vu_record_arrays(_activities_section(0x32, 0x01), results)
    place = results["places"][0]
    assert place["record_bytes"] == 41
    assert place["variant_source"] == "section (TREP 0x32)"
    assert place["gnss_place"]["authentication_status"] == 0x01


def test_isolated_record_keeps_length_fallback_but_says_so():
    from core.parser.vu_dispatcher import decode_vu_record
    out = decode_vu_record(0x1C, _place_record(auth=0x00))
    assert out["variant_source"] == "record length (no section context)"


# ── GNSS accumulated driving keeps every normative field ────────────────────

def test_gnss_ad_g2_v1_keeps_the_odometer_at_56_bytes():
    rec = (struct.pack(">I", TIME) + S.card_number() + S.EMPTY_CARD
           + struct.pack(">I", TIME) + bytes([0x02]) + GEO_ZERO
           + (777_777).to_bytes(3, "big"))
    assert len(rec) == 56
    out = decode_gnss_ad(rec, with_auth=False)
    assert out["odometer_km"] == 777_777
    assert out["gnss_place"]["geo"]["fix"] is True


def test_gnss_ad_g2_v2_reads_the_authentication_status():
    rec = (struct.pack(">I", TIME) + S.card_number() + S.EMPTY_CARD
           + struct.pack(">I", TIME) + bytes([0x03]) + GEO_ZERO + b"\x01"
           + (888_888).to_bytes(3, "big"))
    assert len(rec) == 57
    out = decode_gnss_ad(rec, with_auth=True)
    assert out["odometer_km"] == 888_888
    assert out["gnss_place"]["authentication_status"] == 0x01


# ── Specific conditions: generation-aware labels ────────────────────────────

def test_specific_condition_labels_follow_the_section_generation():
    rec = struct.pack(">I", TIME) + b"\x03"
    assert decode_specific_condition(rec)["condition"] == "Ferry/Train Begin"
    assert decode_specific_condition(rec, generation="G1")["condition"] == (
        "Ferry/Train crossing")
    rfu = struct.pack(">I", TIME) + b"\x04"
    assert decode_specific_condition(rfu, generation="G1")["condition"] == (
        "0x04")
    assert decode_specific_condition(rfu, generation="G1")["condition_status"] == (
        "not assigned")
