"""Behavioural layout tests for the PDF report (cover, tables, appendix).

These tests drive the real ReportLab render and inspect what actually reached
the canvas: which pages carried content, which paragraph styles (and their
alignment) were used, and which table shapes were built. They never import a
private helper from :mod:`app.export` at module scope, so the tests describe
the approved *behaviour* (cover hierarchy, h:mm durations, wide-record cards,
technical appendix, visible row-cap warnings) instead of one implementation.

PyMuPDF is deliberately not used: it is not a project dependency.
"""
import os
import re
from copy import deepcopy
from unittest.mock import patch

import pytest

reportlab = pytest.importorskip("reportlab")

import reportlab.pdfgen.canvas as _canvas_module  # noqa: E402
import reportlab.platypus as _platypus  # noqa: E402
from reportlab.lib.enums import TA_RIGHT  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.platypus import Paragraph as _RealParagraph  # noqa: E402
from reportlab.platypus import Table as _RealTable  # noqa: E402

from app.export import ExportManager  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DDD_DIR = os.path.join(ROOT, "DDD")

_DURATION_RE = re.compile(r"^\d{2,}:\d{2}$")


# ── Render instrumentation ─────────────────────────────────────────────────


class PdfRender:
    """Capture what a real ReportLab build drew, page by page.

    * ``texts``  — every Paragraph text created
    * ``styled`` — ``(text, style_name, style_alignment)`` per Paragraph
    * ``tables`` — ``(ncols, [[cell text, ...], ...])`` per table built
    * ``drawn``  — page number → number of flowables drawn on it
    * ``drawn_items`` — page number → ``("paragraph", text)``/``("table", "")``
    * ``pages``  — total pages the canvas emitted
    * ``footer`` — ``(x, y, text)`` of every left-aligned canvas string
    * ``footer_right`` — ``(x, y, text)`` of every right-aligned canvas string
    * ``commands`` — TableStyle command lists of every table built
    """

    def __init__(self):
        self.texts = []
        self.styled = []
        self.tables = []
        self.drawn = {}
        self.drawn_items = {}
        self.pages = 0
        self.footer = []
        self.footer_right = []
        self.commands = []

    # -- helpers ---------------------------------------------------------
    def joined(self):
        return "\n".join(self.texts)

    def blank_pages(self):
        return [p for p in range(1, self.pages + 1) if not self.drawn.get(p)]

    def style_alignment(self, text):
        for captured, _name, alignment in self.styled:
            if captured == text:
                yield alignment

    def pairs(self):
        """Every adjacent label/value pair of every table, as one dict."""
        pairs = {}
        for _ncols, rows in self.tables:
            for row in rows:
                for index in range(0, len(row) - 1, 2):
                    pairs.setdefault(row[index], row[index + 1])
        return pairs

    def pages_showing(self, text):
        return [page for page, items in self.drawn_items.items()
                if ("paragraph", text) in items]

    def table_rows_with(self, cell_text):
        for _ncols, rows in self.tables:
            for row in rows:
                if cell_text in row:
                    yield row

    # -- patching --------------------------------------------------------
    def __enter__(self):
        spy = self
        real_paragraph = _RealParagraph
        real_table_init = _RealTable.__init__
        real_paragraph_draw = _RealParagraph.draw
        real_table_draw = _RealTable.draw
        real_set_style = _RealTable.setStyle
        real_show_page = _canvas_module.Canvas.showPage
        real_draw_string = _canvas_module.Canvas.drawString
        real_draw_right_string = _canvas_module.Canvas.drawRightString

        def paragraph_factory(text, style=None, *args, **kwargs):
            spy.texts.append(str(text))
            spy.styled.append((str(text), getattr(style, "name", ""),
                               getattr(style, "alignment", None)))
            return real_paragraph(text, style, *args, **kwargs)

        def table_init(table_self, data, *args, **kwargs):
            rows = []
            for row in data:
                cells = []
                if isinstance(row, (list, tuple)):
                    for cell in row:
                        cells.append(getattr(cell, "text", cell))
                else:
                    cells.append(row)
                rows.append([str(c) if not isinstance(c, str) else c for c in cells])
            spy.tables.append((max((len(r) for r in rows), default=0), rows))
            return real_table_init(table_self, data, *args, **kwargs)

        def counting_draw(original):
            def draw(flowable, *args, **kwargs):
                canvas = getattr(flowable, "canv", None)
                if canvas is not None:
                    page = canvas.getPageNumber()
                    spy.drawn[page] = spy.drawn.get(page, 0) + 1
                    if isinstance(flowable, real_paragraph):
                        item = ("paragraph", flowable.getPlainText())
                    else:
                        item = ("table", "")
                    spy.drawn_items.setdefault(page, []).append(item)
                return original(flowable, *args, **kwargs)
            return draw

        def recording_set_style(table_self, commands, *args, **kwargs):
            rows = [[getattr(cell, "text", cell) for cell in row]
                    for row in table_self._cellvalues]
            spy.commands.append((rows, list(getattr(commands, "_cmds", commands))))
            return real_set_style(table_self, commands, *args, **kwargs)

        def counting_show_page(canvas_self, *args, **kwargs):
            spy.pages = max(spy.pages, canvas_self.getPageNumber())
            return real_show_page(canvas_self, *args, **kwargs)

        def recording_draw_string(canvas_self, x, y, text, *args, **kwargs):
            spy.footer.append((x, y, text))
            return real_draw_string(canvas_self, x, y, text, *args, **kwargs)

        def recording_draw_right_string(canvas_self, x, y, text, *args, **kwargs):
            spy.footer_right.append((x, y, text))
            return real_draw_right_string(canvas_self, x, y, text, *args, **kwargs)

        self._patches = [
            patch.object(_platypus, "Paragraph", new=paragraph_factory),
            patch.object(_RealParagraph, "draw", new=counting_draw(real_paragraph_draw)),
            patch.object(_RealTable, "draw", new=counting_draw(real_table_draw)),
            patch.object(_RealTable, "__init__", new=table_init),
            patch.object(_RealTable, "setStyle", new=recording_set_style),
            patch.object(_canvas_module.Canvas, "showPage", new=counting_show_page),
            patch.object(_canvas_module.Canvas, "drawString", new=recording_draw_string),
            patch.object(_canvas_module.Canvas, "drawRightString",
                         new=recording_draw_right_string),
        ]
        for patcher in self._patches:
            patcher.start()
        return self

    def __exit__(self, *exc_info):
        for patcher in reversed(self._patches):
            patcher.stop()
        return False


def render(tmp_path, data, name="report.pdf"):
    """Build a PDF through the production entry point under instrumentation."""
    path = str(tmp_path / name)
    with PdfRender() as spy:
        ExportManager.export_to_pdf(data, path)
    return path, spy


# ── Fixtures ───────────────────────────────────────────────────────────────

def minimal_data():
    return {"metadata": {"filename": "minimal.ddd", "generation": "G1 (Digital)",
                         "is_vu": False, "integrity_check": "Verified"}}


def normal_data():
    """A two-day driver card with operational + technical sections."""
    return {
        "metadata": {
            "filename": "normal.ddd",
            "parsed_at": "2026-06-08 19:00",
            "integrity_check": "VERIFIED (LOCAL CHAIN)",
            "generation": "G2 (Smart)",
            "file_size_bytes": 12345,
            "coverage_pct": 100.0,
            "is_vu": False,
            "decoder_failure_count": 0,
            "app_version": "2.7.1",
        },
        "coverage": {
            "byte_accounted_bytes": 12345,
            "byte_accounted_pct": 100.0,
            "unknown_bytes": 12,
            "unknown_pct": 0.1,
            "structurally_identified_bytes": 12333,
            "structurally_identified_pct": 99.9,
        },
        "driver": {"firstname": "Mario", "surname": "Rossi",
                   "card_number": "IT123456789", "issuing_nation": "I"},
        "vehicle": {"plate": "AA123BB", "vin": "VIN1234567890"},
        "activities": [
            {"date": "01/06/2026", "odometer_km": 150,
             "changes": [{"activity": "DRIVE", "time": "08:00"},
                         {"activity": "REST", "time": "12:00"}]},
            {"date": "02/06/2026", "odometer_km": 200,
             "changes": [{"activity": "DRIVE", "time": "09:00"},
                         {"activity": "REST", "time": "13:00"}]},
        ],
        "events": [{"description": "Over speeding",
                    "begin": "2026-06-01T10:30:00+00:00",
                    "end": "2026-06-01T10:35:00+00:00"}],
        "faults": [{"description": "Sensor fault",
                    "begin": "2026-06-02T11:00:00+00:00", "end": "N/A"}],
        "calibrations": [{"purpose": "Periodic inspection",
                          "workshop_name": "Workshop One",
                          "workshop_address": "Via Roma 1",
                          "workshop_card": "N/A", "vin": "VIN1234567890",
                          "workshop_card_expiry": "N/A",
                          "workshop_nation": "I", "workshop_plate": "B123CD",
                          "w_characteristic": 6200, "l_tyre_circumference": 8000,
                          "kc_constant": 2200, "speed_limit": 90,
                          "old_odometer": 50000, "new_odometer": 51000,
                          "old_time": 0, "new_time": 100,
                          "next_calibration": "01/07/2027"}],
        "ef_signature_verification": {"ef_results": [
            {"ef": "Identification", "status": "verified", "algorithm": "ECDSA"},
            {"ef": "Card_Download", "status": "verified", "algorithm": "ECDSA"},
        ]},
        "certificates": [{"format": "DER", "holder": "cardholder"}],
        "card_application": {"card_type": "driver", "card_version": 2},
    }


def signature_only_data():
    """A VU download whose only exported content is its signature material."""
    return {
        "metadata": {"filename": "vu.ddd", "generation": "G2 (Smart)",
                     "is_vu": True, "integrity_check": "Verified",
                     "parsed_at": "2026-06-08 19:00"},
        "signature_verification": {
            "all_treps_valid": True, "msca_to_vu": True, "root_anchored": True,
            "summary": "All TREPs valid (root anchored)",
            "treps": [
                {"trep": "0x21", "status": "valid", "length": 64},
                {"trep": "0x22", "status": "valid", "length": 96},
            ],
        },
        "vu_certificates": [{"car": "IT", "chr": "VU-001", "format": "CVC"}],
    }


def month_end_data():
    """Two months of activity, the document ending on a monthly subtotal."""
    return {
        "metadata": {"filename": "months.ddd", "generation": "G2 (Smart)",
                     "is_vu": False, "integrity_check": "Verified"},
        "activities": [
            {"date": "31/01/2025", "changes": [{"activity": "REST", "time": "00:00"}]},
            {"date": "01/02/2025", "changes": [{"activity": "DRIVE", "time": "00:00"},
                                               {"activity": "REST", "time": "08:00"}]},
            {"date": "28/02/2025", "changes": [{"activity": "REST", "time": "00:00"}]},
        ],
    }


# ── 1. No blank pages ──────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", [minimal_data, normal_data,
                                     signature_only_data, month_end_data])
def test_no_page_is_blank_for_minimal_normal_signature_or_month_end(tmp_path, fixture):
    path, spy = render(tmp_path, fixture())
    body = open(path, "rb").read()
    assert body.startswith(b"%PDF-")
    assert body.strip().endswith(b"%%EOF")
    assert spy.pages >= 1
    assert spy.blank_pages() == [], "pages with nothing drawn on them"


def test_every_section_heading_carries_data_on_its_page(tmp_path):
    """A heading must not be stranded at the foot of a page with no data."""
    data = month_end_data()
    data["events"] = [{"description": f"Event {i}",
                       "begin": "2025-01-01T10:00:00+00:00"} for i in range(60)]
    data["faults"] = [{"description": f"Fault {i}"} for i in range(40)]
    data["calibrations"] = [{"purpose": f"Calibration {i}"} for i in range(30)]
    _path, spy = render(tmp_path, data)

    headings = ("Daily Activities", "Events", "Faults", "Technical Appendix",
                "Calibrations")
    checked = 0
    for heading in headings:
        for page in spy.pages_showing(heading):
            assert ("table", "") in spy.drawn_items[page], (
                f"heading {heading!r} is alone on page {page}")
            checked += 1
    assert checked >= len(headings)


# ── 2. Cover hierarchy ─────────────────────────────────────────────────────

def test_driver_name_is_printed_once_and_na_na_is_never_rendered(tmp_path):
    _path, spy = render(tmp_path, normal_data())
    named = [t for t in spy.texts if "Mario Rossi" in t]
    assert len(named) == 1, named

    # A VU file has no driver identity of its own: the old cover printed the
    # placeholder pair as "N/A N/A".
    _path, vu_spy = render(tmp_path, signature_only_data(), "vu.pdf")
    assert not any("N/A N/A" in t for t in vu_spy.texts)


def test_cover_identity_survives_when_the_driver_fields_are_placeholders(tmp_path):
    data = signature_only_data()
    data["driver"] = {"firstname": "N/A", "surname": "N/A", "card_number": "N/A"}
    _path, spy = render(tmp_path, data, "vu_na.pdf")
    assert not any("N/A N/A" in t for t in spy.texts)


def test_activity_period_is_chronological_and_scoped(tmp_path):
    data = minimal_data()
    data["activities"] = [
        {"date": "05/01/2025", "changes": [{"activity": "REST", "time": "00:00"}]},
        {"date": "31/12/2024", "changes": [{"activity": "REST", "time": "00:00"}]},
        {"date": "not-a-date", "changes": [{"activity": "REST", "time": "00:00"}]},
        {"date": "01/12/2024", "changes": []},
    ]
    _path, spy = render(tmp_path, data)
    text = spy.joined()

    assert "01/12/2024 \u2013 05/01/2025" in text
    period_line = next(t for t in spy.texts if "01/12/2024" in t)
    assert "UTC" in period_line
    # The scope is explicit: this is the file's own day coverage, nothing more.
    assert "not the file's full retention or download period" in text
    # The malformed day date is never used to state the period (the shared
    # monthly table still lists the record under its own key, as Excel/CSV do).
    assert "not-a-date" not in period_line


def test_activity_period_of_an_undated_file_does_not_invent_dates(tmp_path):
    data = minimal_data()
    data["activities"] = [{"date": "", "changes": []}, {"changes": []}]
    _path, spy = render(tmp_path, data)
    assert any("no dated activity" in t.lower() for t in spy.texts)


def test_cover_carries_every_summary_row_warning(tmp_path):
    data = minimal_data()
    data["metadata"].update({
        "trep_report": {
            "is_partial": True, "mandatory_ok": 3, "mandatory_total": 7,
            "completeness_pct": 42.9, "complete_walk": False,
            "mandatory_missing": [{"name": "Overview", "trep": "0x01"}],
            "decoded_suspect": [{"name": "Events", "trep": "0x15"}],
        },
        "salvage_recovered": ["events", "faults"],
        "parse_warnings": [{"phase": "ef_walk", "message": "boom"}],
        "decoder_failure_count": 2,
        "origin_note": "VU-wrapped card image detected",
    })
    data["coverage"] = {"byte_accounted_bytes": 100, "byte_accounted_pct": 97.5,
                        "unknown_bytes": 3, "unknown_pct": 2.5}
    data["signature_verification"] = {"summary": "All TREPs valid"}
    data["faults"] = [{"description": "Sensor fault"}]

    from core.utils.report_format import summary_rows

    _path, spy = render(tmp_path, data)
    text = spy.joined()
    # File/Generation/Source/Parsed-at are stated by the cover's title block, so
    # they are shown there by value rather than as a repeated label.
    title_block = {"File", "Generation", "Source", "Parsed at"}
    found = 0
    for field, value in summary_rows(data):
        if not field or not value:
            continue
        if field not in title_block:
            assert str(field) in text, field
        assert str(value) in text, (field, value)
        found += 1
    assert found >= 12


def test_cover_totals_match_the_monthly_table_for_all_five_buckets(tmp_path):
    _path, spy = render(tmp_path, normal_data())

    assert ("Drive", "08:00") in [(r[0], r[1]) for r in spy.table_rows_with("Drive")]
    stats = spy.pairs()
    assert stats["Drive"] == "08:00"
    assert stats["Work"] == "00:00"
    assert stats["Rest"] == "23:00"
    assert stats["Available"] == "00:00"
    assert stats["Unknown"] == "17:00"
    assert stats["Total"] == "48:00"
    assert stats["Days with activity"] == "2"
    assert stats["Events"] == "1"
    assert stats["Faults"] == "1"

    # The monthly table's own subtotal reports the same numbers.
    subtotal = next(row for row in spy.table_rows_with("06/2026 TOTAL"))
    assert subtotal[2] == "08:00"
    assert subtotal[4] == "23:00"
    assert subtotal[6].lstrip("! ").strip() == "17:00"
    assert subtotal[7] == "48:00"


def test_cover_totals_follow_the_shared_two_slot_engine(tmp_path):
    """A crew day is summed per slot exactly as the monthly table does it."""
    from core.utils.activity_stats import compute_activity_totals

    crew_day = {"date": "01/06/2026", "changes": [
        {"activity": "DRIVE", "time": "00:00", "slot": "First"},
        {"activity": "REST", "time": "12:00", "slot": "First"},
        {"activity": "DRIVE", "time": "00:00", "slot": "Second"},
        {"activity": "REST", "time": "10:00", "slot": "Second"},
    ]}
    expected = compute_activity_totals(crew_day["changes"])
    data = minimal_data()
    data["activities"] = [crew_day]

    _path, spy = render(tmp_path, data)
    stats = spy.pairs()

    def _h_mm(minutes):
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    assert stats["Drive"] == _h_mm(expected["DRIVE"])
    assert stats["Work"] == _h_mm(expected["WORK"])
    assert stats["Rest"] == _h_mm(expected["REST"])
    assert stats["Available"] == _h_mm(expected["AVAILABLE"])
    assert stats["Unknown"] == _h_mm(expected["UNKNOWN"])
    assert stats["Total"] == _h_mm(sum(expected.values()))
    # Drive accumulates across the two slots while Rest is kept at the maximum,
    # so the disclosed crew-day total legitimately passes 24:00.
    assert expected["DRIVE"] + expected["REST"] > 24 * 60
    assert int(stats["Total"].split(":")[0]) > 24


def test_unknown_duration_is_explained_not_implied_to_be_corruption(tmp_path):
    _path, spy = render(tmp_path, normal_data())
    explanation = next(t for t in spy.texts if t.startswith("Unknown time"))
    assert "not" in explanation and "corrupt" in explanation.lower()


def test_cover_does_not_print_a_trust_badge(tmp_path):
    _path, spy = render(tmp_path, normal_data())
    text = spy.joined().lower()
    for invented in ("trusted file", "trust badge", "certified report"):
        assert invented not in text


# ── 3. Activity table: durations, alignment, totals ────────────────────────

def test_activity_durations_and_numeric_cells_are_right_aligned_paragraphs(tmp_path):
    _path, spy = render(tmp_path, normal_data())

    headers = [r[0] for r in spy.table_rows_with("Drive (h:mm)")]
    assert headers, "the PDF-local activity header must state (h:mm)"
    rendered_headers = next(row for row in spy.table_rows_with("Drive (h:mm)"))
    assert rendered_headers[-1] == "Total (h:mm)"

    duration_paragraphs = [text for text in spy.texts if _DURATION_RE.match(text)]
    assert duration_paragraphs, "no h:mm duration reached a paragraph"
    for text in duration_paragraphs:
        alignments = list(spy.style_alignment(text))
        assert alignments and all(a == TA_RIGHT for a in alignments), (text, alignments)


def test_activity_table_totals_are_bold_and_shaded(tmp_path):
    """The subtotal row is bold *and* picks up its own shaded background."""
    _path, spy = render(tmp_path, month_end_data())

    total_style_names = {name for text, name, _a in spy.styled
                         if text in {"08:00", "16:00"} and "Total" in name}
    assert total_style_names, "no bold total paragraph style was used"

    def _last_background(commands, row_index):
        color = None
        for command in commands:
            if command[0] != "BACKGROUND":
                continue
            _name, start, stop = command[0], command[1], command[2]
            first_row, last_row = start[1], stop[1]
            if first_row <= row_index <= last_row:
                color = command[3]
        return color

    shaded_somewhere = False
    for rows, commands in spy.commands:
        for index, row in enumerate(rows):
            if not row or not row[0].endswith(" TOTAL"):
                continue
            own = _last_background(commands, index)
            previous = _last_background(commands, index - 1)
            assert own is not None
            assert own != previous, "the subtotal row is not shaded differently"
            shaded_somewhere = True
    assert shaded_somewhere


def test_a_full_month_stays_on_one_page_including_the_first(tmp_path):
    """A normal 31-day month must not be split, even under the section intro."""
    data = minimal_data()
    data["activities"] = [
        {"date": f"{day:02d}/12/2025",
         "changes": [{"activity": "REST", "time": "00:00"},
                     {"activity": "DRIVE", "time": "06:00"}]}
        for day in range(1, 32)
    ]
    _path, spy = render(tmp_path, data)

    heading_pages = spy.pages_showing("Daily Activities \u2014 12/2025 (31 days)")
    subtotal_pages = spy.pages_showing("12/2025 TOTAL")
    assert heading_pages, [t for t in spy.texts if "Daily Activities" in t]
    assert heading_pages == subtotal_pages, (heading_pages, subtotal_pages)

    # The next section, if any, must not share that page either.
    for index in (1, 2, 4, 6):
        assert spy.pages_showing(f"{index:02d}/12/2025") == heading_pages


def test_slot_aggregation_is_explained_once_near_the_activity_table(tmp_path):
    _path, spy = render(tmp_path, normal_data())
    explanations = [t for t in spy.texts
                    if "summed across the two card slots" in t]
    assert len(explanations) == 1
    assert "24:00" in explanations[0]


# ── 4. Wide technical records become field/value cards ─────────────────────

def _wide_record(n_fields=14):
    record = {}
    for i in range(1, n_fields + 1):
        record[f"field_{i:02d}"] = f"SENTINEL{i:02d}"
    return record


def test_wide_records_are_field_value_cards_with_every_field_preserved(tmp_path):
    first = _wide_record()
    second = _wide_record()
    for key in second:
        second[key] = second[key] + "-B"
    data = minimal_data()
    data["vu_identifications"] = [first, second]
    data["vu_identifications"][0]["zero_reading"] = 0
    data["vu_identifications"][0]["flag_reading"] = False

    _path, spy = render(tmp_path, data)
    text = spy.joined()

    for i in range(1, 15):
        assert f"SENTINEL{i:02d}" in text
        assert f"SENTINEL{i:02d}-B" in text
    # Zero and False are values, not blanks.
    assert "Zero Reading" in text and "\n0\n" in f"\n{text}\n"
    assert "\nNo\n" in f"\n{text}\n"

    # Explicit record numbering, and no squeezed 14-column table survived.
    assert "Record 1 of 2" in text and "Record 2 of 2" in text
    assert max(ncols for ncols, _rows in spy.tables) <= 8


def test_wide_record_cards_repeat_value_and_false_as_text(tmp_path):
    record = _wide_record(12)
    record["available"] = False
    record["count"] = 0
    data = minimal_data()
    data["overspeeding_events"] = [record]

    _path, spy = render(tmp_path, data)
    rows = list(spy.table_rows_with("Available"))
    assert rows, "the False field must be rendered, not dropped"
    assert any("No" in row for row in rows)
    assert any("Count" in row for row in rows)


def test_constant_record_type_note_is_kept_in_the_section_description(tmp_path):
    record = _wide_record(12)
    record["record_type"] = "0x0C"
    data = minimal_data()
    data["overspeeding_events"] = [record, dict(record)]

    _path, spy = render(tmp_path, data)
    text = spy.joined()
    assert "Record type: 0x0C" in text
    assert "VuCalibrationRecord" in text


# ── 5. Technical appendix ordering ─────────────────────────────────────────

def test_technical_appendix_follows_the_operational_sections(tmp_path):
    data = normal_data()
    data["signature_verification"] = {
        "summary": "All TREPs valid",
        "treps": [{"trep": "0x21", "status": "valid"}],
    }
    data["vu_certificates"] = [{"car": "IT", "chr": "VU-001"}]

    _path, spy = render(tmp_path, data)
    text = spy.joined()
    order = ["Events", "Faults", "Technical Appendix", "Signature Verification"]
    positions = [text.index(name) for name in order]
    assert positions == sorted(positions), positions
    # Technical sections are inside the appendix, not before it.
    for technical in ("Calibrations", "EF Card Data Signatures",
                      "Driver Card Certificates", "Card Application",
                      "VU Certificates (CVC)",
                      # the label is escaped, as every report string is
                      "File &amp; Parse Details"):
        assert text.index(technical) > text.index("Technical Appendix"), technical


def test_appendix_lists_are_each_rendered_once(tmp_path):
    data = normal_data()
    data["signature_verification"] = {"treps": [{"trep": "0x21"}]}
    _path, spy = render(tmp_path, data)
    assert spy.texts.count("Technical Appendix") == 1


def test_sections_without_visible_columns_do_not_leave_an_empty_heading(tmp_path):
    data = minimal_data()
    data["events"] = [{"source": "internal", "confidence": "low"}]
    data["faults"] = [{"description": "Sensor fault"}]

    _path, spy = render(tmp_path, data)
    assert "Events" not in spy.texts
    assert "Faults" in spy.texts
    assert spy.blank_pages() == []


def test_a_section_whose_values_are_all_blank_is_not_printed_as_an_empty_grid(tmp_path):
    data = minimal_data()
    data["places"] = [{"description": "", "timestamp": ""}]
    data["faults"] = [{"description": "Sensor fault"}]

    _path, spy = render(tmp_path, data)
    assert "Places" not in spy.texts
    assert "Faults" in spy.texts


# ── 6. Row-cap warnings ────────────────────────────────────────────────────

def test_row_cap_warning_is_visible_for_activities_and_ordinary_sections(tmp_path):
    data = minimal_data()
    data["activities"] = [
        {"date": f"{day:02d}/05/2025",
         "changes": [{"activity": "REST", "time": "00:00"}]}
        for day in range(1, 29)
    ] * 60  # 1680 rows, past the 1500-row PDF cap
    data["events"] = [{"description": f"Event {i}",
                       "begin": "2025-05-01T10:00:00+00:00"} for i in range(1600)]

    _path, spy = render(tmp_path, data)
    warnings = [t for t in spy.texts if "1 500-row report limit" in t]
    assert len(warnings) >= 2, warnings
    assert any("JSON" in w for w in warnings)
    assert any("Excel" in w for w in warnings)
    assert all("1 500" in w or "1500" in w for w in warnings)


def test_a_month_sliced_before_its_subtotal_says_so(tmp_path):
    data = minimal_data()
    data["activities"] = [
        {"date": f"{(day % 28) + 1:02d}/05/2025",
         "changes": [{"activity": "REST", "time": "00:00"}]}
        for day in range(1600)
    ]

    _path, spy = render(tmp_path, data)
    partial = [t for t in spy.texts if "Daily Activities" in t and "partial" in t]
    assert partial, [t for t in spy.texts if "Daily Activities" in t]
    assert not any(t.endswith("()") for t in spy.texts)


# ── 7. Footer survives long file names ─────────────────────────────────────

def test_footer_strings_never_overlap_for_a_long_file_name(tmp_path):
    data = normal_data()
    data["metadata"]["filename"] = "A" * 160 + ".ddd"

    _path, spy = render(tmp_path, data)
    page_w = 297 * 72 / 25.4
    left = [(x, text) for x, _y, text in spy.footer]
    right = [(x, text) for x, _y, text in spy.footer_right if text.startswith("Page ")]
    assert left and right
    for x, text in left:
        left_edge = x + pdfmetrics.stringWidth(text, "Helvetica", 7)
        for right_x, _right_text in right:
            assert left_edge + 6 < right_x, (text, left_edge, right_x)
        assert left_edge < page_w
    # A file name too long for the footer is shortened, not run into the page
    # number.
    from core.utils.version import __version__
    assert left[0][1].endswith(f"\u2026  ·  TachoReader v{__version__}")


# ── 9. Correction leg: disclosure, labels, pagination, placeholders ────────

def _minutes(duration):
    hours, _sep, mins = duration.partition(":")
    return int(hours) * 60 + int(mins)


def test_row_cap_warning_survives_a_preview_with_no_displayable_values(tmp_path):
    """A capped section must disclose the cut even when no row shows a value."""
    data = minimal_data()
    data["events"] = [{"source": "internal"}] * 1500 + [{"description": "FINAL-EVENT"}]

    _path, spy = render(tmp_path, data)
    text = spy.joined()
    assert "FINAL-EVENT" not in text, "the preview really carries no visible value"

    warnings = [entry for entry in spy.texts if "row limit" in entry]
    assert warnings, "the row cap must stay disclosed"
    assert any("1 500" in entry for entry in warnings)
    assert any("JSON" in entry for entry in warnings)
    # And it must not pretend that 1 500 blank rows were printed.
    assert not any("Showing the first" in entry for entry in warnings)
    assert any("no table is printed" in entry for entry in warnings)


def test_uncapped_section_without_displayable_values_is_still_skipped(tmp_path):
    data = minimal_data()
    data["events"] = [{"source": "internal"}] * 3
    data["faults"] = [{"description": "Sensor fault"}]

    _path, spy = render(tmp_path, data)
    assert "Events" not in spy.texts
    assert "Faults" in spy.texts


def test_cover_period_counts_dated_days_not_days_with_recorded_activity(tmp_path):
    """The period states the dated span; the grid keeps the active-day count."""
    data = minimal_data()
    data["activities"] = [
        {"date": "01/06/2025", "changes": []},
        {"date": "02/06/2025", "changes": [{"activity": "REST", "time": "00:00"}]},
    ]

    _path, spy = render(tmp_path, data)
    period = next(t for t in spy.texts if "01/06/2025" in t and "02/06/2025" in t)
    assert "2 dated days" in period
    assert "with activity" not in period

    stats = spy.pairs()
    assert stats["Days with activity"] == "1"     # established count, unchanged
    assert stats["Rest"] == "24:00"               # duration math unchanged


def test_cover_totals_are_complete_while_the_table_is_capped(tmp_path):
    """1 501 full days: the totals cover all of them, the tables cannot."""
    from datetime import date, timedelta

    start = date(2020, 1, 1)
    data = minimal_data()
    data["activities"] = [
        {"date": (start + timedelta(days=offset)).strftime("%d/%m/%Y"),
         "changes": [{"activity": "REST", "time": "00:00"}]}
        for offset in range(1501)
    ]

    _path, spy = render(tmp_path, data)
    stats = spy.pairs()
    assert stats["Rest"] == "36024:00"
    assert stats["Total"] == "36024:00"

    # Monthly subtotal rows consume the same 1 500-row cap, so the printed
    # tables are a strict subset of the input.
    printed = sum(
        _minutes(row[-1])
        for _ncols, rows in spy.tables
        for row in rows
        if row and isinstance(row[0], str) and row[0].endswith(" TOTAL")
    )
    assert 0 < printed < 1501 * 24 * 60
    assert any("row limit" in entry for entry in spy.texts)

    # The cover says exactly that, instead of promising agreement.
    note = next(t for t in spy.texts if "every daily record" in t)
    assert "subset" in note and "row limit" in note


def test_section_intro_stays_with_the_first_card_of_a_tall_record(tmp_path):
    data = minimal_data()
    data["events"] = [{"description": f"Event description {index}"}
                      for index in range(14)]
    tall = {"field_00": "longvalue " * 240}
    for index in range(1, 12):
        tall[f"field_{index:02d}"] = f"VALUE-{index}"
    data["vu_identifications"] = [tall]

    _path, spy = render(tmp_path, data)
    heading_pages = spy.pages_showing("VU Identifications")
    assert heading_pages
    for page in heading_pages:
        assert ("table", "") in spy.drawn_items[page], (
            f"the section intro is stranded on page {page}")

    record_pages = spy.pages_showing("Record 1 of 1")
    assert record_pages and record_pages[0] == heading_pages[0]
    assert spy.blank_pages() == []


def test_placeholder_driver_name_is_dropped_even_with_a_real_card_number(tmp_path):
    data = minimal_data()
    data["driver"] = {"firstname": "N/A", "surname": "N/A",
                      "card_number": "I100000168598002"}

    _path, spy = render(tmp_path, data)
    assert not any("N/A N/A" in entry for entry in spy.texts)
    assert "Driver" not in spy.texts                # the name row says nothing
    assert spy.pairs()["Card Number"] == "I100000168598002"


def test_one_over_page_card_value_is_split_not_dropped(tmp_path):
    data = minimal_data()
    record = {"field_00": "longvalue " * 900}
    for index in range(1, 12):
        record[f"field_{index:02d}"] = f"VALUE-{index}"
    data["vu_identifications"] = [record]

    _path, spy = render(tmp_path, data)
    text = spy.joined()
    # Every word of the value is drawn (across the split parts), and the fields
    # after it are not swallowed by the fragment.
    assert sum(entry.count("longvalue") for entry in spy.texts) >= 890
    assert text.count("longvalue") <= 910
    assert "VALUE-1" in text and "VALUE-11" in text
    # The record identity repeats on every page the card continues onto.
    assert len(spy.pages_showing("Record 1 of 1")) >= 2
    assert spy.blank_pages() == []


def test_subtitle_keeps_the_shared_source_text(tmp_path):
    _path, spy = render(tmp_path, signature_only_data())
    assert any("Vehicle Unit (VU)" in entry for entry in spy.texts)

    _path, card_spy = render(tmp_path, minimal_data(), "card.pdf")
    assert any(entry.endswith("\u00b7  Driver Card") for entry in card_spy.texts)


# ── 8. Real sample files render ────────────────────────────────────────────

@pytest.mark.skipif(not os.path.isdir(DDD_DIR),
                    reason="private DDD samples absent (DDD/ is git-ignored)")
def test_every_private_sample_file_renders_without_blank_pages(tmp_path):
    from app.engine import TachoParser

    samples = sorted(name for name in os.listdir(DDD_DIR)
                     if name.lower().endswith(".ddd"))
    assert samples, "DDD/ present but empty"
    for name in samples:
        data = deepcopy(TachoParser(os.path.join(DDD_DIR, name)).parse())
        path, spy = render(tmp_path, data, name + ".pdf")
        body = open(path, "rb").read()
        assert body.startswith(b"%PDF-")
        assert spy.blank_pages() == [], name
