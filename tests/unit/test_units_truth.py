"""The units, the flags and the rendered section must tell ONE truth.

Blind reviewer D found that the verdicts disagreed with the units, that the
'Decode units' section never rendered, and that the schema explanation never reached
the banner. These tests read the *rendered* output, not the registries.
"""
import struct

import pytest

from app.engine import TachoParser
from core.registry.registry import DecoderRegistry
from core.utils import report_format as rf
from tests.unit import vu_synthetic as S
from tests.unit.test_per_trep_units import _three_message_stream

TIME = S.BASE_TIME


def _parse(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


def _g1_stream():
    overview, events, technical = _three_message_stream()
    return overview + events + technical


def _g2_stream():
    return (S.section(0x31, S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
                      S.signature_record())
            + S.section(0x24, S.record_array(
                0x12, 64, [struct.pack(">I", TIME) + bytes(60)]),
                S.signature_record()))


# ── D-01: fill after the last message is padding, not a finding ──────────

@pytest.mark.parametrize("fill", [b"\x00", b"\xff"])
@pytest.mark.parametrize("length", [1, 4, 128])
def test_fill_after_the_last_message_is_declared_padding(tmp_path, fill, length):
    stream = _g1_stream() + fill * length
    result = _parse(tmp_path, "pad.ddd", stream)
    meta = result["metadata"]
    units = result.get("vu_units") or []
    assert units, "the units must be exposed at the top level"
    pad = units[-1]
    assert pad["path"] == "padding", pad
    assert pad["length"] == length
    # one verdict rules: padding is not damage
    assert (meta.get("trep_report") or {}).get("is_partial") is not True
    assert not meta.get("vu_integrity")
    assert result["metadata"]["vu_units_cover_file"] is True


@pytest.mark.parametrize("fill", [b"\xde\xad", b"\x99\x99", b"abc"])
def test_other_trailing_bytes_are_a_finding(tmp_path, fill):
    stream = _g1_stream() + fill
    result = _parse(tmp_path, "junk.ddd", stream)
    meta = result["metadata"]
    units = result.get("vu_units") or []
    assert units[-1]["path"] in ("heuristic", "unreadable"), units[-1]
    assert (meta.get("trep_report") or {}).get("is_partial") is True
    assert meta.get("vu_integrity"), "a non-fill tail must be a finding"


@pytest.mark.parametrize("length", [1, 4])
def test_generation_2_fill_is_padding_too(tmp_path, length):
    result = _parse(tmp_path, "g2pad.ddd", _g2_stream() + b"\xff" * length)
    units = result.get("vu_units") or []
    assert units[-1]["path"] == "padding", units[-1]
    # no *trailing-bytes* finding: the fill is padding (the synthetic sections may
    # still report their own, richer findings about the array list)
    assert not [f for f in (result["metadata"].get("vu_integrity") or [])
                if f.get("status") in ("trailing_bytes", "array_truncated")]


# ── D-02: the 'Decode units' section really renders ─────────────────────

def test_decode_units_section_renders_rows(tmp_path):
    # a junk tail creates a zone, so every column (reason included) is rendered
    result = _parse(tmp_path, "units.ddd", _g1_stream() + b"\xde\xad")
    assert result.get("vu_units"), "top-level units are what every surface reads"
    tables = {label: (desc, headers, rows)
              for label, desc, headers, rows, _t in rf.section_tables(result)}
    assert "Decode units" in tables, sorted(tables)
    _desc, headers, rows = tables["Decode units"]
    assert headers[:5] == ["TREP", "Offset", "Length", "Path", "Reason"], headers
    assert any(str(row[4]) for row in rows), "the reason column must carry text"
    assert len(rows) == len(result["vu_units"])
    first = rows[0]
    assert str(first[0]).startswith("0x")
    assert str(first[3]) == "normative"


def test_decode_units_reaches_excel_and_pdf(tmp_path):
    import zipfile
    from app.export import ExportManager
    result = _parse(tmp_path, "units2.ddd", _g1_stream())
    xlsx = tmp_path / "u.xlsx"
    pdf = tmp_path / "u.pdf"
    ExportManager.export_to_excel(result, str(xlsx))
    ExportManager.export_to_pdf(result, str(pdf))
    with zipfile.ZipFile(xlsx) as archive:
        sheet = "".join(archive.read(name).decode("utf-8", "ignore")
                        for name in archive.namelist() if name.endswith(".xml"))
    assert "Decode units" in sheet
    assert "normative" in sheet
    assert pdf.stat().st_size > 0


@pytest.mark.parametrize("key,label", [
    ("co_driver_activities", "Co-Driver Activities"),
    ("unmapped_record_types", "Manufacturer Extensions"),
    ("vu_units", "Decode units"),
])
def test_every_section_label_added_by_this_branch_renders(tmp_path, key, label):
    """A label in EXPORT_SECTIONS is not a section: read the rendered output."""
    stream = (S.section(0x32,
                        S.record_array(0x06, 4, [struct.pack(">I", TIME)]),
                        S.record_array(0x05, 3, [(1000).to_bytes(3, "big")]),
                        S.record_array(0x0D, 131, []),
                        S.record_array(0x01, 2, [struct.pack(">H", 0x10F3)]),
                        S.record_array(0x1C, 41, []),
                        S.record_array(0x16, 57, []),
                        S.record_array(0x09, 5, []),
                        S.record_array(0x22, 55, []),
                        S.record_array(0x23, 58, []),
                        S.record_array(0x29, 2, [struct.pack(">H", 0x10F4)]),
                        S.record_array(0x88, 6, [b"\x88" * 6]),
                        S.signature_record()))
    result = _parse(tmp_path, f"{key}.ddd", stream)
    assert result.get(key), f"{key} carries no data"
    labels = [label_ for label_, _d, _h, _r, _t in rf.section_tables(result)]
    assert label in labels, labels


# ── D-05: the recorded route says what actually ran ────────────────────

def test_a_one_byte_truncation_records_the_route_that_ran(tmp_path):
    data = _g1_stream()[:-1]
    result = _parse(tmp_path, "short.ddd", data)
    reasons = (result["metadata"].get("decode_paths") or {}).get(
        "fallback_reasons") or []
    assert reasons
    route = reasons[0]["route"]
    assert route in ("vu_walk_incomplete", "vu_fallback_scan"), reasons[0]
    # no scan recovered these units, so the route must not claim one
    if not result["metadata"].get("heuristic_fields"):
        assert route == "vu_walk_incomplete", reasons[0]
