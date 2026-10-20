"""The three bookkeeping defects a blind refutation review found.

* a normative-walker **exception** must stay `normative_decoder_exception` /
  `decoder_defect_suspected` (it used to be overwritten with `file_truncated`);
* a section whose Appendix-7 schema is `incomplete` must reach the download-level
  verdict (it did not: 9 missing arrays and `is_partial` stayed False);
* a lone dangling `0x76` byte at EOF is a truncated marker, not padding.
"""
import os
import struct

import pytest

from app.engine import TachoParser
from core.parser import g1_walker
from core.registry.registry import DecoderRegistry
from tests.unit import vu_synthetic as S
from tests.unit.real_data import real_ddd_files, require_real_file

TIME = S.BASE_TIME


def _parse_bytes(tmp_path, name, data):
    path = os.path.join(str(tmp_path), name)
    with open(path, "wb") as handle:
        handle.write(data)
    DecoderRegistry.reset_instance()
    return TachoParser(path).parse(), path


def _reasons(result):
    return (result["metadata"].get("decode_paths") or {}).get("fallback_reasons") or []


def _is_partial(result):
    return (result["metadata"].get("trep_report") or {}).get("is_partial")


# ── Item 1: an exception is our defect, not a damaged file ────────────────

def test_g1_walker_exception_keeps_its_honest_cause(tmp_path, monkeypatch):
    path = require_real_file("*_3B330594AC.ddd")          # a real G1 VU download
    with open(path, "rb") as handle:
        data = handle.read()

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic walker defect")

    monkeypatch.setattr(g1_walker, "walk_g1_vu", boom)
    result, _path = _parse_bytes(tmp_path, "boom.ddd", data)
    reasons = _reasons(result)
    assert reasons, "the fallback must still be declared"
    first = reasons[0]
    assert first["cause"] == "normative_decoder_exception", first
    assert first["classification"] == "decoder_defect_suspected", first
    assert "RuntimeError" in (first.get("detail") or "")
    assert "synthetic walker defect" in (first.get("detail") or "")
    assert (result["metadata"].get("decode_paths") or {}).get("fallback")


def test_gen2_walker_exception_keeps_its_honest_cause(tmp_path, monkeypatch):
    from core.parser import vu_dispatcher
    data = S.section(0x31,
                     S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
                     S.signature_record())

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic dispatcher defect")

    # the RecordArray walker is what the engine calls for a Gen2 download
    monkeypatch.setattr(vu_dispatcher, "walk_vu_record_arrays", boom)
    result, _path = _parse_bytes(tmp_path, "boom2.ddd", data)
    first = (_reasons(result) or [{}])[0]
    assert first.get("cause") == "normative_decoder_exception", first
    assert first.get("classification") == "decoder_defect_suspected", first
    assert "RuntimeError" in (first.get("detail") or "")


def test_a_truncated_g1_file_still_reports_a_damaged_file(tmp_path):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        data = handle.read()
    result, _path = _parse_bytes(tmp_path, "cut.ddd", data[:len(data) // 2])
    reasons = _reasons(result)
    assert reasons
    assert reasons[0]["cause"] in ("file_truncated", "count_exceeds_eof"), reasons[0]
    assert reasons[0]["classification"] == "file_damaged", reasons[0]


# ── Item 2: an incomplete Appendix-7 schema reaches the verdict ────────────

def test_incomplete_schema_makes_the_download_partial(tmp_path):
    data = (b"\x76\x31" + bytes([0x0A]) + struct.pack(">HH", 17, 1)
            + S.VIN.encode("ascii")
            + bytes([0x08]) + struct.pack(">HH", 64, 1) + bytes(64))
    result, _path = _parse_bytes(tmp_path, "schema.ddd", data)
    meta = result["metadata"]
    schema = (meta.get("vu_section_schema") or [{}])[0]
    assert schema["status"] == "incomplete"
    assert schema["missing_arrays"], schema
    assert _is_partial(result) is True
    findings = meta.get("vu_integrity") or []
    assert [f for f in findings if f["status"] == "schema_violation"], findings
    assert result["_vu_walk_complete"] is False
    # records are still emitted: only the verdict changed
    assert result["vehicle"]["vin"] == S.VIN


def test_unexpected_array_makes_the_download_partial(tmp_path):
    data = S.section(0x23,
                     S.record_array(0x18, 8, [bytes(8)]),
                     S.record_array(0x22, 55, [bytes(55)]),
                     S.record_array(0x15, 8, [bytes(8)]),
                     S.signature_record())
    result, _path = _parse_bytes(tmp_path, "unexpected.ddd", data)
    schema = (result["metadata"].get("vu_section_schema") or [{}])[0]
    assert schema["unexpected_arrays"] == ["0x22"], schema
    assert _is_partial(result) is True
    assert any(f["status"] == "schema_violation"
               for f in (result["metadata"].get("vu_integrity") or []))


def test_the_intact_corpus_stays_complete_and_not_partial():
    files = real_ddd_files()
    if not files:
        pytest.skip("no private corpus available")
    for path in files:
        DecoderRegistry.reset_instance()
        result = TachoParser(path).parse()
        meta = result["metadata"]
        for schema in meta.get("vu_section_schema") or []:
            # TREP 00 has no Appendix-7 array list; every other section must be
            # complete on an intact file.
            assert schema["status"] in ("complete",
                                        "not applicable (no RecordArray list in Appendix 7)"), (
                os.path.basename(path), schema)
        assert not _is_partial(result), os.path.basename(path)
        assert not meta.get("heuristic_fields"), os.path.basename(path)


# ── Item 3: a lone dangling 0x76 is a truncated marker, not padding ───────

def test_dangling_marker_byte_makes_the_walk_incomplete(tmp_path):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        data = handle.read()
    ends = sorted({message["end"] for message in g1_walker.iter_g1_vu_messages(data)})
    cut = next((end + 1 for end in ends if end < len(data) and data[end] == 0x76), None)
    assert cut, "no message boundary followed by a marker byte"
    result, _path = _parse_bytes(tmp_path, "dangling.ddd", data[:cut])
    assert _is_partial(result) is True
    findings = result["metadata"].get("vu_integrity") or []
    assert [f for f in findings if f["status"] == "trailing_bytes"
            and f["trailing_bytes"] == 1], findings
    assert (result["metadata"].get("trep_report") or {}).get("complete_walk") is False
    assert result["_g1_walk_decoded_all"] is True


@pytest.mark.parametrize("fill", [b"\x00", b"\xff", b"\x00\x00", b"\xff\xff\xff"])
def test_zero_or_ff_fill_after_the_last_message_is_padding(tmp_path, fill):
    from tests.unit.test_vu_schema_and_mixed06 import _g1_technical_body
    stream = b"\x76\x05" + _g1_technical_body() + b"\x00" * 128 + fill
    results = {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                          "registration_nation": "N/A"}}
    _messages, complete = g1_walker.walk_g1_vu(stream, results)
    assert complete is True
    assert results["_g1_walk_decoded_all"] is True
