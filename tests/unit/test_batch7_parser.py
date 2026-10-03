"""Batch 7 MEDIA / PARSER regression tests (red->green).

One test class per confirmed family from ``FIX-PLAN.md`` batch 7:

* CARD-COORD-BOUND (XA-F1)          — EF coordinate bounds never enforced
* CARD-ODOMETER-SENTINEL (XA-F2)    — 0xFFFFFF odometer published as 16 777 215
* CARD-EF-WHITELIST (D2-003)        — signed EF outside the whitelist dropped
* CARD-GENERATION-FLIP (XD-F3)      — a stray dtype-0x02 record flips G1 -> G2
* CARD-UNKNOWN-ACTIVITY (F-F4)      — card-not-inserted periods counted as work
* G1-VU-CALIBRATION-HEURISTIC (B-F8/XB-F2) — regex fallback calibrations unflagged

Assertions are independent of production internals: exact expected numeric
values, key presence, and status strings rather than snapshots.
"""
import os
import struct
import tempfile

from app.engine import TachoParser
from core.crypto.ef_signature import pair_ef_records, verify_ef_pairs
from core.decoders.card_ef import parse_card_gnss_places
from core.decoders.card_g22 import (
    parse_g22_border_crossings,
    parse_g22_load_unload_operations,
)
from core.decoders.common import _decode_gnss_coord
from core.decoders.vu_g1 import _parse_trep_05_technical
from core.utils.activity_stats import compute_activity_totals


# ── helpers ────────────────────────────────────────────────────────────────

def _coord(value):
    """Annex 1C GeoCoordinates: signed int24, +/-DD(D)MM.M x10."""
    return int(value).to_bytes(3, "big", signed=True)


def _stap(tag, dtype, data):
    return struct.pack(">HBH", tag, dtype, len(data)) + data


def _parse_card_file(data):
    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        return TachoParser(tmp.name).parse()
    finally:
        os.unlink(tmp.name)


def _gnss_place_auth(ts, lat=45041, lon=9125):
    """GNSSPlaceAuthRecord (12B): ts(4)+accuracy(1)+lat(3)+lon(3)+auth(1)."""
    return struct.pack(">I", ts) + bytes([7]) + _coord(lat) + _coord(lon) + bytes([1])


# ── CARD-COORD-BOUND (XA-F1) ───────────────────────────────────────────────

class TestCardCoordBound:
    def test_latitude_beyond_90_degrees_is_rejected(self):
        # 45 deg 31.2 min is a real latitude and must still decode.
        assert _decode_gnss_coord(_coord(45312), 0, 90) == 45.52
        # 91 deg (91000) can never be a latitude.
        assert _decode_gnss_coord(_coord(91000), 0, 90) is None
        # the reviewer's out-of-range example (raw 99999 -> 99 deg 99.9 min).
        assert _decode_gnss_coord(_coord(99999), 0, 90) is None

    def test_longitude_bounds_90_vs_180(self):
        # 91000 is a valid *longitude* (91 deg) but the latitude limit rejects it.
        assert _decode_gnss_coord(_coord(91000), 0, 90) is None
        assert _decode_gnss_coord(_coord(91000), 0, 180) == 91.0
        # the longitude limit itself: 180 deg is the edge, 181 deg is not.
        assert _decode_gnss_coord(_coord(180000), 0, 180) == 180.0
        assert _decode_gnss_coord(_coord(181000), 0, 180) is None

    def test_minutes_fraction_and_sentinel_rules(self):
        # A whole degree below the limit with a 60-minute fraction is corrupt.
        assert _decode_gnss_coord(_coord(45600), 0, 90) is None     # 45 deg 60.0 min
        # The exact maximum may carry no minutes at all.
        assert _decode_gnss_coord(_coord(90100), 0, 90) is None      # 90 deg 10.0 min
        # The unknown-position sentinel always stays None.
        assert _decode_gnss_coord(b"\x7f\xff\xff", 0, 180) is None

    def test_card_gnss_places_drops_out_of_range_coordinate(self):
        """The 0x0524 decoder must drop a record whose coordinate is impossible."""
        ts = struct.pack(">I", 1700000000)

        def records(lat):
            # 18-byte record: ts(4) + inner ts(4) + accuracy(1)
            # + lat(3) + lon(3) + odometer(3)
            chunk = (ts + ts + bytes([5])
                     + _coord(lat) + _coord(9125)
                     + (100000).to_bytes(3, "big"))
            return b"\x00\x00" + chunk

        good = {}
        parse_card_gnss_places(records(45312), good)
        assert len(good["gnss_ad_records"]) == 1
        assert good["gnss_ad_records"][0]["latitude"] == 45.52

        bad = {}
        parse_card_gnss_places(records(91000), bad)
        assert bad.get("gnss_ad_records", []) == []


# ── CARD-ODOMETER-SENTINEL (XA-F2) ─────────────────────────────────────────

class TestCardOdometerSentinel:
    def test_border_crossing_unknown_odometer_is_omitted(self):
        record = bytes([1, 2]) + _gnss_place_auth(1750000000) + b"\xff\xff\xff"
        results = {}
        parse_g22_border_crossings(b"\x00\x00" + record, results)
        crossing = results["border_crossings"][0]
        assert "vehicle_odometer_value" not in crossing
        assert crossing["latitude"] == 45.0683333
        assert crossing["record_index"] == 0

    def test_border_crossing_real_odometer_is_kept(self):
        record = bytes([1, 2]) + _gnss_place_auth(1750000000) + (89500).to_bytes(3, "big")
        results = {}
        parse_g22_border_crossings(b"\x00\x00" + record, results)
        assert results["border_crossings"][0]["vehicle_odometer_value"] == 89500

    def test_load_unload_unknown_odometer_is_omitted(self):
        record = (struct.pack(">I", 1750000000) + bytes([0x01])
                  + _gnss_place_auth(1750000000) + b"\xff\xff\xff")
        results = {}
        parse_g22_load_unload_operations(b"\x00\x00" + record, results)
        lu = results["load_unload_records"][0]
        assert "vehicle_odometer_value" not in lu
        assert lu["operation"] == "LOAD"


# ── CARD-EF-WHITELIST (D2-003) ─────────────────────────────────────────────

class TestCardEfWhitelist:
    def test_lone_signature_unknown_ef_is_reported_unsupported(self):
        # Only the signature half of a tag outside the whitelist is present.
        pairs = pair_ef_records([], [(0x0550, 0x01, b"s" * 128)])
        assert len(pairs) == 1
        assert pairs[0]["tag"] == 0x0550
        assert pairs[0]["status"] == "unsupported"

    def test_unsupported_ef_is_skipped_not_verified(self):
        pairs = pair_ef_records([], [(0x0550, 0x01, b"s" * 128)])
        report = verify_ef_pairs(pairs, None, None, "G1")
        assert report["verified"] == 0
        assert report["skipped"] == 1
        assert report["failed"] == 0

    def test_certificate_and_known_unsigned_signatures_stay_excluded(self):
        # A certificate block (0x0103 < 0x0500) carrying a signature-appendix
        # record is not a signed EF and must not be reported.
        assert pair_ef_records([], [(0x0103, 0x03, b"c" * 200)]) == []
        # 0x050E (Card_Download) is declared unsigned by the norm.
        assert pair_ef_records([], [(0x050E, 0x01, b"s" * 128)]) == []
        # A data-only record with no signature is not a signed EF either.
        assert pair_ef_records([(0x0550, 0x00, b"d" * 40)], []) == []


# ── CARD-GENERATION-FLIP (XD-F3) ───────────────────────────────────────────

class TestCardGenerationFlip:
    def test_stray_dtype02_record_does_not_flip_g1_to_g2(self):
        # The reviewer's trigger: a valid G1 card plus one dtype-0x02 record of
        # a non-marker tag must stay G1.
        data = _stap(0x0502, 0x02, b"\x00" * 40)
        assert _parse_card_file(data)["metadata"]["generation"] == "G1 (Digital)"
        assert _parse_card_file(_stap(0x9001, 0x02, b"X"))["metadata"]["generation"] \
            == "G1 (Digital)"

    def test_gen2_marker_tags_select_g2(self):
        assert _parse_card_file(_stap(0x0523, 0x02, b"\x00" * 40))["metadata"]["generation"] \
            == "G2 (Smart)"
        assert _parse_card_file(_stap(0x0501, 0x02, b"\x00" * 17))["metadata"]["generation"] \
            == "G2 (Smart)"

    def test_gen22_marker_tags_select_g22(self):
        data = _stap(0x0525, 0x02, b"\x00" * 10)
        assert _parse_card_file(data)["metadata"]["generation"] == "G2.2 (Smart V2)"


# ── CARD-UNKNOWN-ACTIVITY (F-F4) ───────────────────────────────────────────

class TestCardUnknownActivity:
    def test_card_not_inserted_single_crew_becomes_unknown(self):
        changes = [
            {"activity": "REST", "time": "00:00", "slot": "First",
             "crew": False, "card_inserted": False},
            {"activity": "DRIVE", "time": "01:00", "slot": "First",
             "crew": False, "card_inserted": True},
        ]
        totals = compute_activity_totals(changes)
        assert totals["UNKNOWN"] == 60
        assert totals["REST"] == 0

    def test_card_not_inserted_with_crew_keeps_activity(self):
        # 'c'=1 (crew) means the activity code is still meaningful.
        changes = [
            {"activity": "REST", "time": "00:00", "slot": "First",
             "crew": True, "card_inserted": False},
            {"activity": "DRIVE", "time": "01:00", "slot": "First"},
        ]
        totals = compute_activity_totals(changes)
        assert totals["REST"] == 60
        assert totals["UNKNOWN"] == 0

    def test_missing_flags_are_left_untouched(self):
        # A record without the p/c flags (e.g. a heuristic change) is unchanged.
        changes = [
            {"activity": "WORK", "time": "00:00", "slot": "First"},
            {"activity": "DRIVE", "time": "02:00", "slot": "First"},
        ]
        totals = compute_activity_totals(changes)
        assert totals["WORK"] == 120
        assert totals["UNKNOWN"] == 0


# ── G1-VU-CALIBRATION-HEURISTIC (B-F8 / XB-F2) ─────────────────────────────

def _trep05_regex_payload():
    """A payload whose deterministic TREP 05 structure does not fit, forcing the
    regex VIN-scan fallback to invent one calibration record."""
    data = bytearray(b"\x00" * 200)          # manufacturer field decodes empty
    data[100:117] = b"WVWZZZ1JZXW000001"     # VIN found by the fallback scan
    fixed = bytearray(40)
    fixed[0] = 0x01                           # nation
    fixed[1:15] = b"ABC123".ljust(14, b"\x00")
    fixed[15:17] = (100).to_bytes(2, "big")   # w constant
    fixed[17:19] = (1623).to_bytes(2, "big")  # k constant
    fixed[19:21] = (2000).to_bytes(2, "big")  # l constant
    data[117:157] = fixed
    data[96:100] = struct.pack(">I", 1600000000)   # timestamp before the VIN
    return bytes(data)


class TestG1VuCalibrationHeuristic:
    def test_regex_fallback_marks_calibrations_heuristic(self):
        results = {}
        _parse_trep_05_technical(_trep05_regex_payload(), results)
        assert len(results["calibrations"]) == 1
        # The inferred records must be flagged, like the TREP 02/03/06 fallbacks.
        assert results["metadata"]["heuristic_fields"] == {
            "vu_technical_TREP05": ["calibrations"],
        }

    def test_no_recovered_records_no_heuristic_flag(self):
        results = {}
        _parse_trep_05_technical(b"\x00" * 200, results)
        assert not results.get("calibrations")
        meta = results.get("metadata") or {}
        assert "heuristic_fields" not in meta
