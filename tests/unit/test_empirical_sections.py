"""Manufacturer/empirical data must be SHOWN, and explained as information.

The owner's rule: what lies outside the regulation is displayed like everything else
*and* the app says what it is — low confidence, layout not defined by the regulation,
raw bytes preserved — as information, never as an error.
"""
import struct

from app.engine import TachoParser
from core.registry.registry import DecoderRegistry
from core.utils import report_format as rf
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


def _parse(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


def _trep32(extra=(), co_driver=True):
    arrays = [S.record_array(0x06, 4, [struct.pack(">I", TIME)]),
              S.record_array(0x05, 3, [(1000).to_bytes(3, "big")]),
              S.record_array(0x0D, 131, []),
              S.record_array(0x01, 2, [struct.pack(">H", 0x10F3)]),
              S.record_array(0x1C, 41, []),
              S.record_array(0x16, 57, []),
              S.record_array(0x09, 5, []),
              S.record_array(0x22, 55, []),
              S.record_array(0x23, 58, [])]
    if co_driver:
        arrays.append(S.record_array(0x29, 2, [struct.pack(">H", 0x10F4)]))
    for rt, size, count in extra:
        arrays.append(S.record_array(rt, size, [bytes([rt]) * size] * count))
    arrays.append(S.signature_record())
    return S.section(0x32, *arrays)


# ── Item 1a: the observed co-driver array is a rendered section ───────────

def test_co_driver_activities_section_is_rendered(tmp_path):
    result = _parse(tmp_path, "co.ddd", _trep32())
    assert result.get("co_driver_activities"), "the records must be decoded"
    tables = {label: (desc, headers, rows)
              for label, desc, headers, rows, _t in rf.section_tables(result)}
    assert "Co-Driver Activities" in tables, sorted(tables)
    desc, headers, rows = tables["Co-Driver Activities"]
    assert rows, "the section must carry its rows"
    assert "Stoneridge" in desc and "0x29" in desc
    assert "manufacturer" in desc.lower() or "empirical" in desc.lower()
    keys = [key for key, _label in rf.EXPORT_SECTIONS]
    assert "co_driver_activities" in keys


def test_observed_section_is_not_a_defect(tmp_path):
    result = _parse(tmp_path, "co2.ddd", _trep32())
    assert not (meta := result["metadata"]).get("heuristic_fields")
    assert not (meta.get("decode_paths") or {}).get("fallback")
    # the *walk* is complete; mandatory-section completeness is a separate axis
    # (this synthetic stream has no Overview section)
    assert result["_vu_walk_complete"] is True


# ── Item 1b: unmapped manufacturer record types are shown ────────────────

def test_unmapped_record_type_section_is_rendered(tmp_path):
    result = _parse(tmp_path, "unmapped.ddd", _trep32(extra=[(0x88, 6, 2)]))
    assert "0x88" in (result.get("vu_unmapped_record_types") or [])
    assert "0x29" in (result.get("vu_unmapped_record_types") or [])
    rows = {row["record_type"]: row for row in result.get("unmapped_record_types") or []}
    assert "0x88" in rows, rows
    assert rows["0x88"]["record_count"] == 2
    assert rows["0x88"]["record_size"] == 6
    assert rows["0x88"]["raw_hex"]
    tables = {label: (desc, headers, rows)
              for label, desc, headers, rows, _t in rf.section_tables(result)}
    assert "Manufacturer Extensions" in tables, sorted(tables)
    _desc, headers, section_rows = tables["Manufacturer Extensions"]
    assert any("0x88" in str(cell) for row in section_rows for cell in row)


# ── Item 2: one informational note on every non-normative section ────────

def test_the_empirical_note_is_present_once_per_section_and_in_every_catalog():
    import glob
    import re
    note = rf.EMPIRICAL_NOTE
    assert note
    assert "manufacturer" in note.lower() and "low confidence" in note.lower()
    for key in ("co_driver_activities", "unmapped_record_types",
                "sensor_daily_records", "sensor_info"):
        assert note in rf.section_description(key), key
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        msgids = set(re.findall(r'^msgid "(.*)"$',
                                open(path, encoding="utf-8").read(), re.M))
        assert note in msgids, path


def test_sensor_payload_sections_keep_their_confidence_and_gain_the_note():
    assert "low confidence" in rf.section_description("sensor_daily_records").lower()
    assert rf.EMPIRICAL_NOTE in rf.section_description("sensor_daily_records")


# ── Coherence: the new labels exist and do not collide ───────────────────

def test_the_new_section_labels_are_translated(tmp_path):
    import glob
    import re
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        msgids = set(re.findall(r'^msgid "(.*)"$',
                                open(path, encoding="utf-8").read(), re.M))
        for label in ("Co-Driver Activities", "Manufacturer Extensions"):
            assert label in msgids, (path, label)


# ── Item 3: the new sections and the note survive the real exporters ─────

def test_the_empirical_sections_render_in_pdf_and_excel(tmp_path):
    """Render through the real exporters and read the text back (no clipping)."""
    import subprocess
    import zipfile
    from app.export import ExportManager

    result = _parse(tmp_path, "render.ddd", _trep32(extra=[(0x88, 6, 2)]))
    pdf = tmp_path / "render.pdf"
    xlsx = tmp_path / "render.xlsx"
    ExportManager.export_to_pdf(result, str(pdf))
    ExportManager.export_to_excel(result, str(xlsx))

    text = subprocess.run(["pdftotext", "-raw", str(pdf), "-"],
                          capture_output=True, text=True).stdout
    for needle in ("Co-Driver Activities", "Manufacturer Extensions", "0x88"):
        assert needle in text, needle
    # the note wraps across lines in the PDF, so assert its distinctive words
    for word in ("Manufacturer-specific", "empirical layout", "low confidence",
                 "raw bytes"):
        assert word in text, word
    # nothing is clipped: the section titles and the code survive whole
    assert "Co-Driver" in text and "Activities" in text
    assert "Manufacturer" in text and "Extensions" in text

    with zipfile.ZipFile(xlsx) as archive:
        sheet = "".join(archive.read(name).decode("utf-8", "ignore")
                        for name in archive.namelist() if name.endswith(".xml"))
    for needle in ("Co-Driver Activities", "Manufacturer Extensions", "0x88"):
        assert needle in sheet, needle


def test_the_manufacturer_extensions_table_row_count(tmp_path):
    """The probe stream's extension table has one row per unmapped record type."""
    result = _parse(tmp_path, "rows.ddd", _trep32(extra=[(0x88, 6, 2)]))
    tables = {label: rows for label, _d, _h, rows, _t in rf.section_tables(result)}
    rows = tables["Manufacturer Extensions"]
    # 0x29 (the observed co-driver array) and 0x88 (a manufacturer type)
    assert len(rows) == 2, [row[0] for row in rows]
