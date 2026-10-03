"""Batch 10 MEDIA / PARSER (VU structure/normative) regression tests.

Two confirmed families from ``FIX-PLAN.md`` batch 10:

* VU-UNMAPPED-RECORDS (D2-005) — record types with no Annex 1C §2.120 name
  (RFU / manufacturer-specific, codes > 0x24) are flagged instead of being
  labelled with invented normative names; the norm-defined types 0x07
  (SensorPaired) and 0x1D (VuTimeAdjustmentGNSSRecord) are named and decoded.
* VU-UNSIGNED-BYTES (XE-F5) — bytes outside every signed section are surfaced in
  the VU signature report instead of a "fully valid" claim with no caveat.

Normative source: Reg. EU 2016/799 Annex 1C (consolidated 2023-08-21), §2.120
RecordType Value-assignment and Appendix 11 (download signatures). Assertions
use exact values/keys and are independent of production internals.

Red→green: on the pre-fix source, every assertion marked below raises
``KeyError``/``AssertionError`` (new symbol, new key, or wrong label).
"""
import struct

from core.crypto import vu_signature
from core.parser import vu_dispatcher
from core.parser.deterministic import DeterministicParser
from core.parser.vu_dispatcher import (
    RECORD_TYPES,
    _decode_record,
    walk_vu_record_arrays,
)

# 0x31 = Overview, 0x32 = Activities (Annex 1C TRTP table) → detected as G2.2.
_TREP_ACTIVITIES = b"\x76\x32"


def _array(record_type, record_size, records):
    return (bytes([record_type]) + struct.pack(">H", record_size)
            + struct.pack(">H", len(records)) + b"".join(records))


# ── VU-UNMAPPED-RECORDS (D2-005) ─────────────────────────────────────────────

class TestVuUnmappedRecords:
    def test_normative_set_is_the_annex_1c_enumeration(self):
        # Annex 1C §2.120 enumerates 36 record types occupying codes 0x01..0x24.
        assert vu_dispatcher.NORMATIVE_RECORD_TYPES == frozenset(range(0x01, 0x25))
        assert vu_dispatcher.is_normative_record_type(0x01) is True
        assert vu_dispatcher.is_normative_record_type(0x24) is True
        assert vu_dispatcher.is_normative_record_type(0x25) is False
        assert vu_dispatcher.is_normative_record_type(0x29) is False
        assert vu_dispatcher.is_normative_record_type(0x60) is False

    def test_norm_defined_types_are_named(self):
        # Value-assignment position 7 = SensorPaired (0x07), position 29 =
        # VuTimeAdjustmentGNSSRecord (0x1D).
        assert RECORD_TYPES[0x07] == ("SensorPaired", "low")
        assert RECORD_TYPES[0x1D] == ("VuTimeAdjustmentGNSSRecord", "high")

    def test_rfu_codes_are_not_given_normative_names(self):
        # 0x29/0x40/0x60 sit above the enumeration: no normative name exists.
        for rt in (0x29, 0x40, 0x60):
            assert RECORD_TYPES[rt][0].startswith("RFU_")

    def test_gnss_time_adjustment_record_is_decoded(self):
        out = _decode_record(0x1D, struct.pack(">II", 1600000000, 1600003600))
        assert out["name"] == "VuTimeAdjustmentGNSSRecord"
        assert out["size"] == 8
        assert out["old_time"] == "2020-09-13T12:26:40+00:00"
        assert out["new_time"] == "2020-09-13T13:26:40+00:00"
        assert "raw_hex" not in out

    def test_non_normative_record_is_flagged(self):
        out = _decode_record(0x29, struct.pack(">H", 0x1000))
        assert out["normative"] is False
        # a normative record carries no such flag (keeps the record shape stable)
        assert "normative" not in _decode_record(0x01, struct.pack(">H", 0x1000))

    def test_walker_surfaces_unmapped_record_types(self):
        stream = _TREP_ACTIVITIES + _array(0x29, 2, [struct.pack(">H", 0x1000)])
        results = {}
        walk_vu_record_arrays(stream, results)
        assert results["vu_unmapped_record_types"] == ["0x29"]

    def test_walker_keeps_normative_only_stream_clean(self):
        stream = _TREP_ACTIVITIES + _array(0x01, 2, [struct.pack(">H", 0x1000)])
        results = {}
        walk_vu_record_arrays(stream, results)
        assert "vu_unmapped_record_types" not in results

    def test_raw_tags_does_not_mark_unmapped_type_spec_verified(self):
        data = (_TREP_ACTIVITIES
                + _array(0x29, 2, [struct.pack(">H", 0x1000)])
                + _array(0x01, 2, [struct.pack(">H", 0x0800)]))
        raw_tags = DeterministicParser().parse(data, is_vu=True)["raw_tags"]
        key29 = next(k for k in raw_tags if "29_" in k)
        assert raw_tags[key29][0]["is_spec_verified"] is False
        key01 = next(k for k in raw_tags if "01_" in k)
        assert raw_tags[key01][0]["is_spec_verified"] is True


# ── VU-UNSIGNED-BYTES (XE-F5) ────────────────────────────────────────────────

def _stub_verifier(monkeypatch, sections):
    """Stub the crypto primitives so only the coverage logic is exercised."""
    monkeypatch.setattr(vu_signature, "iter_vu_sections", lambda _data: iter(sections))
    monkeypatch.setattr(vu_signature, "parse_cvc", lambda _raw: {"car": "ca"})
    monkeypatch.setattr(vu_signature, "cvc_public_key", lambda _cvc: (object(), object()))
    monkeypatch.setattr(vu_signature, "cvc_temporal_status", lambda *_a: {})
    monkeypatch.setattr(vu_signature, "verify_cvc_chain_link", lambda *_a: True)
    monkeypatch.setattr(vu_signature, "_verify_ecdsa", lambda *_a: True)


# One Overview section (certs 0x04/0x0F + signature 0x08) whose records end at
# offset 83. The certificate payloads the verifier reads live at pos+5.
_OVERVIEW = {
    "marker": 0,
    "trep": 0x21,
    "records": [(2, 0x04, 1, 1, 8), (8, 0x0F, 1, 1, 14), (14, 0x08, 64, 1, 83)],
}


class TestVuUnsignedBytes:
    def test_trailing_bytes_outside_every_section_are_flagged(self, monkeypatch):
        _stub_verifier(monkeypatch, [_OVERVIEW])
        data = bytearray(88)
        data[7] = 0x04
        data[13] = 0x0F
        report = vu_signature.verify_vu_download(bytes(data))
        assert report["unsigned_bytes"] == 5
        assert report["unsigned_ranges"] == [[83, 88]]
        assert "5 unsigned byte(s) outside signed sections" in report["summary"]

    def test_bytes_before_the_first_section_are_flagged(self, monkeypatch):
        section = {
            "marker": 10,
            "trep": 0x21,
            "records": [(12, 0x04, 1, 1, 18), (18, 0x0F, 1, 1, 24), (24, 0x08, 64, 1, 93)],
        }
        _stub_verifier(monkeypatch, [section])
        data = bytearray(93)
        data[17] = 0x04
        data[23] = 0x0F
        report = vu_signature.verify_vu_download(bytes(data))
        assert report["unsigned_bytes"] == 10
        assert report["unsigned_ranges"] == [[0, 10]]

    def test_download_trailer_is_not_counted_as_unsigned(self, monkeypatch):
        # A short 0x76 0x00 trailer at EOF is a recognised non-normative
        # download artefact, not unsigned payload riding along.
        _stub_verifier(monkeypatch, [_OVERVIEW])
        data = bytearray(87)
        data[7] = 0x04
        data[13] = 0x0F
        data[83:87] = b"\x76\x00\x01\x01"
        report = vu_signature.verify_vu_download(bytes(data))
        assert "unsigned_bytes" not in report
        assert "unsigned" not in report["summary"]

    def test_all_bytes_covered_reports_no_warning(self, monkeypatch):
        section = {
            "marker": 0,
            "trep": 0x21,
            "records": [(2, 0x04, 1, 1, 8), (8, 0x0F, 1, 1, 14), (14, 0x08, 64, 1, 88)],
        }
        _stub_verifier(monkeypatch, [section])
        data = bytearray(88)
        data[7] = 0x04
        data[13] = 0x0F
        report = vu_signature.verify_vu_download(bytes(data))
        assert "unsigned_bytes" not in report
        assert "unsigned" not in report["summary"]
