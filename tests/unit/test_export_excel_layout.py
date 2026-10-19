"""Behavioural tests for the Excel workbook.

Every test reloads the workbook that was actually written to disk and inspects
what a spreadsheet reader sees: real date/duration/number cells instead of text
that only looks numeric, one filter range per table, a Summary that navigates
to the sheets and discloses the row limit, and monthly subtotal rows on their
own sheet. They describe behaviour, never a private helper's shape, so the
tests keep meaning if the exporter is reorganised.
"""
import datetime
import os
from copy import deepcopy
from unittest.mock import patch

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.export import ExportManager  # noqa: E402
from core.utils.report_format import (  # noqa: E402
    DICT_SECTIONS, EXPORT_SECTIONS, build_monthly_activity_report, summary_rows,
)

# A day whose status entries leave 00:00-08:00 unattributed: Drive 4 h,
# Rest 12 h, Unknown 8 h, total 24 h (see core.utils.activity_stats).
DAY_CHANGES = [
    {"activity": "DRIVE", "time": "08:00"},
    {"activity": "REST", "time": "12:00"},
]


def _day(date, odometer, changes=None):
    return {"date": date, "odometer_km": odometer, "changes": changes or DAY_CHANGES}


def _data():
    return {
        "metadata": {
            "filename": "workbook.ddd",
            "parsed_at": "2026-07-02 08:00",
            "integrity_check": "VERIFIED (LOCAL CHAIN)",
            "generation": "G2 (Smart)",
            "file_size_bytes": 4096,
            "coverage_pct": 100.0,
            "is_vu": False,
            "decoder_failure_count": 0,
        },
        "coverage": {
            "byte_accounted_bytes": 4096,
            "byte_accounted_pct": 100.0,
            "unknown_bytes": 0,
            "unknown_pct": 0.0,
            "structurally_identified_bytes": 4096,
            "structurally_identified_pct": 100.0,
        },
        "driver": {
            "firstname": "Mario",
            "surname": "Rossi",
            "card_number": "0000000123456789",
            "licence_number": "0000000000AB1234",
        },
        "vehicle": {"plate": "AA123BB", "vin": "YV2RTY0C9HB792078"},
        "activities": [
            _day("29/06/2026", 1500),
            _day("30/06/2026", 1600),
            _day("01/07/2026", 1700),
        ],
        "events": [
            {"description": "Over speeding", "begin": "2026-06-01T10:30:00+00:00",
             "end": "N/A"},
        ],
        "places": [
            {"timestamp": "2026-06-29T04:28:00+00:00", "entry_type": "START",
             "nation": "I", "region": 0, "odometer_km": 12345,
             "card_driver": "0000000000X1I003"},
            # 0xFFFFFF is the "not available" sentinel: it must stay the text
            # N/A and never become the number 0.
            {"timestamp": "2026-06-29T12:10:00+00:00", "entry_type": "END",
             "nation": "F", "region": 5, "odometer_km": 0xFFFFFF,
             "card_driver": "N/A"},
        ],
        "card_iw_records": [{
            "holder_surname": "Nitu",
            "card": "0000000000123456",
            "card_expiry": "27/08/2028",
            "insertion_time": "2024-11-25T09:16:00+00:00",
            "odometer_insertion_km": 1151186,
            "card_slot": 0,
            "withdrawal_time": "2024-12-03T14:04:00+00:00",
            "odometer_withdrawal_km": 1155623,
            "manual_input": True,
        }],
        "card_issuer": {"name": "Test Issuer", "nation": "I"},
        "signature_verification": {
            "treps": [{"trep": "0x01", "valid": True, "blocks": 3}],
        },
        "vu_certificates": [{"format": "CVC", "serial": "00FF"}],
    }


def _export(tmp_path, data=None, name="workbook.xlsx"):
    path = tmp_path / name
    ExportManager.export_to_excel(_data() if data is None else data, str(path))
    return path


def _load(tmp_path, data=None, name="workbook.xlsx"):
    return openpyxl.load_workbook(_export(tmp_path, data, name=name))


def _header_row(ws, first_header):
    """Row number of the table whose first header cell is *first_header*."""
    for row in ws.iter_rows():
        if row and row[0].value == first_header:
            return row[0].row
    raise AssertionError(f"header {first_header!r} not found on sheet {ws.title!r}")


def _table(ws, first_header):
    """``(headers, rows)`` of the first table on *ws*.

    Values are read exactly as openpyxl gives them back: a typed cell shows up
    as ``datetime``/``timedelta``/``int``, text stays ``str``.
    """
    header_row = _header_row(ws, first_header)
    headers = [cell.value for cell in ws[header_row]]
    while headers and headers[-1] is None:
        headers.pop()
    rows = [
        tuple(ws.cell(row=row, column=col).value for col in range(1, len(headers) + 1))
        for row in range(header_row + 1, ws.max_row + 1)
    ]
    return headers, rows


def _header_rows(ws):
    """Rows carrying the navy header band (the tables' own header rows)."""
    rows = []
    for row in ws.iter_rows():
        for cell in row:
            fill = cell.fill.fgColor.rgb if cell.fill is not None else None
            if isinstance(fill, str) and fill.endswith("1F4E79") and cell.font.bold:
                rows.append(cell.row)
                break
    return rows


def _sheet_text(ws):
    return "\n".join(str(cell.value) for row in ws.iter_rows() for cell in row
                     if cell.value is not None)


def _index_links(ws):
    """``[(sheet name, hyperlink)]`` of the Summary's sheet index."""
    header_row = _header_row(ws, "Sheet")
    links = []
    for row in range(header_row + 1, ws.max_row + 1):
        cell = ws.cell(row=row, column=1)
        if cell.value is None:
            continue
        links.append((cell.value, cell.hyperlink, ws.cell(row=row, column=3).value))
    return links


# ── typed cells ────────────────────────────────────────────────────────────


def test_daily_activities_are_typed_and_hold_only_day_rows(tmp_path):
    data = _data()
    wb = _load(tmp_path, data)
    ws = wb["Daily Activities"]

    headers, rows = _table(ws, "Date")
    assert headers[:8] == ["Date", "Odometer km", "Drive (h:mm)", "Work (h:mm)",
                           "Rest (h:mm)", "Available (h:mm)", "Unknown (h:mm)",
                           "Total (h:mm)"]
    assert len(rows) == 3, "the monthly subtotal rows belong to Monthly Activities"

    dates = [row[0] for row in rows]
    assert all(isinstance(day, datetime.datetime) for day in dates), dates
    assert [day.date() for day in dates] == [
        datetime.date(2026, 6, 29), datetime.date(2026, 6, 30), datetime.date(2026, 7, 1)]
    assert sorted(dates) == dates

    assert [row[1] for row in rows] == [1500, 1600, 1700]
    assert all(isinstance(row[1], int) for row in rows)

    # Durations are real numbers a reader can sum, formatted as elapsed hours.
    durations = [cell for row in rows for cell in row[2:8]]
    assert all(isinstance(value, datetime.timedelta) for value in durations), durations
    assert rows[0][2] == datetime.timedelta(hours=4)
    assert rows[0][4] == datetime.timedelta(hours=12)
    assert rows[0][7] == datetime.timedelta(hours=24)
    header_row = _header_row(ws, "Date")
    total_cell = ws.cell(row=header_row + 1, column=headers.index("Total (h:mm)") + 1)
    assert total_cell.number_format == "[h]:mm"

    # The typed cells carry exactly the shared report's facts (the activity
    # arithmetic is not reimplemented for Excel).
    _, report_rows = build_monthly_activity_report(data["activities"])
    for report_row, typed_row in zip(
            [row for row in report_rows if not str(row[0]).endswith(" TOTAL")],
            rows, strict=True):
        assert typed_row[0].date() == datetime.datetime.strptime(
            report_row[0], "%d/%m/%Y").date()
        assert typed_row[1] == int(report_row[1].replace(" ", ""))
        for column in range(2, 8):
            hours, minutes = report_row[column].lstrip("\u26a0 ").split(":")
            assert typed_row[column] == datetime.timedelta(
                hours=int(hours), minutes=int(minutes))


def test_unknown_time_marker_moves_out_of_the_numeric_cell(tmp_path):
    wb = _load(tmp_path)
    ws = wb["Daily Activities"]
    headers, rows = _table(ws, "Date")

    assert "Notes" in headers
    unknown = headers.index("Unknown (h:mm)")
    notes = headers.index("Notes")
    for row in rows:
        assert isinstance(row[unknown], datetime.timedelta)
        assert "\u26a0" not in str(row[unknown])
        assert "Unknown time" in row[notes]
    # The numeric value is the unattributed time the shared report states.
    assert rows[0][unknown] == datetime.timedelta(hours=8)
    assert not any(isinstance(value, str) and "\u26a0" in value
                   for row in rows for value in row)


def test_monthly_totals_move_to_their_own_highlighted_sheet(tmp_path):
    wb = _load(tmp_path)
    assert "Monthly Activities" in wb.sheetnames
    ws = wb["Monthly Activities"]

    headers, rows = _table(ws, "Month")
    assert headers[0] == "Month"
    assert [row[0] for row in rows] == ["06/2026 TOTAL", "07/2026 TOTAL"]
    assert all(isinstance(row[2], datetime.timedelta) for row in rows)

    header_row = _header_row(ws, "Month")
    for offset in (1, 2):
        label = ws.cell(row=header_row + offset, column=1)
        assert label.font.bold
        assert label.fill.fgColor.rgb.endswith("D6E4F0")

    # Presentation moved; the per-bucket arithmetic did not.
    _, day_rows = _table(wb["Daily Activities"], "Date")
    for column in range(2, 8):
        assert (sum((row[column] for row in rows), datetime.timedelta())
                == sum((row[column] for row in day_rows), datetime.timedelta()))


def test_identifiers_sentinels_and_malformed_values_stay_text(tmp_path):
    data = deepcopy(_data())
    data["card_iw_records"][0]["card"] = "0000000000123456789012"  # >15 digits
    data["activities"].append(_day("not-a-date", 42))

    wb = _load(tmp_path, data)

    headers, rows = _table(wb["Card Insertion _ Withdrawal"], "Holder Surname")
    row = rows[0]
    assert row[headers.index("Card")] == "0000000000123456789012"
    assert isinstance(row[headers.index("Card")], str)
    assert row[headers.index("Card Expiry")] == datetime.datetime(2028, 8, 27)
    assert row[headers.index("Insertion Time")] == datetime.datetime(2024, 11, 25, 9, 16)
    assert row[headers.index("Odometer Insertion KM")] == 1151186
    assert row[headers.index("Card Slot")] == "0"       # a code, not a measure
    assert row[headers.index("Manual Input")] == "Yes"

    headers, rows = _table(wb["Places"], "Timestamp")
    assert rows[0][headers.index("Odometer KM")] == 12345
    assert rows[1][headers.index("Odometer KM")] == "N/A"
    assert rows[0][headers.index("Card Driver")] == "0000000000X1I003"
    assert rows[0][headers.index("Nation")] == "Italy"
    assert rows[1][headers.index("Card Driver")] == "N/A"

    _, day_rows = _table(wb["Daily Activities"], "Date")
    assert day_rows[-1][0] == "not-a-date"       # kept as text, never guessed
    assert isinstance(day_rows[-1][1], int)

    # A shown timestamp keeps its UTC marker in the cell format.
    meta_headers, event_rows = _table(wb["Events"], "Description")
    assert event_rows[0][meta_headers.index("Begin")] == datetime.datetime(2026, 6, 1, 10, 30)
    assert event_rows[0][meta_headers.index("End")] == "N/A"
    ws = wb["Events"]
    begin_cell = ws.cell(row=_header_row(ws, "Description") + 1,
                         column=meta_headers.index("Begin") + 1)
    assert begin_cell.number_format.endswith('"Z"')


# ── table shape, filter, print setup ───────────────────────────────────────


def test_tables_are_rectangular_with_filters_frozen_headers_and_print_titles(tmp_path):
    wb = _load(tmp_path)
    ws = wb["Events"]

    header_row = _header_row(ws, "Description")
    headers, rows = _table(ws, "Description")
    assert header_row == 2                       # row 1 is the section description
    assert ws.freeze_panes == f"A{header_row + 1}"
    assert ws.auto_filter.ref == f"A{header_row}:{openpyxl.utils.get_column_letter(len(headers))}{header_row + len(rows)}"
    assert ws.max_row == header_row + len(rows)  # no styling past the data
    assert ws.max_column == len(headers)

    assert ws.sheet_view.showGridLines is False
    assert ws.print_title_rows in (f"{header_row}:{header_row}",
                                   f"${header_row}:${header_row}")
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True

    # Header band: navy, white, bold, wrapped; description: italic + merged.
    for column in range(1, len(headers) + 1):
        cell = ws.cell(row=header_row, column=column)
        assert cell.font.bold and cell.font.color.rgb.endswith("FFFFFF")
        assert cell.fill.fgColor.rgb.endswith("1F4E79")
        assert cell.alignment.wrap_text is True
    assert str(ws.cell(row=1, column=1).value).startswith("Logged events")
    assert ws.cell(row=1, column=1).font.italic
    assert ws.merged_cells.ranges

    # A filter button needs room: the widest value plus padding, not its exact
    # width. Widths exist only for the columns the table actually has.
    widths = [ws.column_dimensions[openpyxl.utils.get_column_letter(column)].width
              for column in range(1, len(headers) + 1)]
    assert all(width and width >= 9 for width in widths), widths
    assert widths[headers.index("Description")] >= len("Over speeding") + 3


def test_daily_sheet_description_points_at_the_monthly_sheet(tmp_path):
    wb = _load(tmp_path)
    description = str(wb["Daily Activities"].cell(row=1, column=1).value)
    assert "Monthly Activities" in description


# ── row limit disclosure ───────────────────────────────────────────────────


def test_row_limit_is_disclosed_on_the_sheet_and_in_the_summary(tmp_path):
    data = _data()
    data["events"] = [{"description": f"Event {index}",
                       "begin": "2026-06-01T10:30:00+00:00"} for index in range(7)]
    with patch("app.export._EXCEL_MAX_ROWS", 3):
        wb = _load(tmp_path, data)

    ws = wb["Events"]
    description = str(ws.cell(row=1, column=1).value)
    assert "3 of 7" in description and "row limit" in description.lower()
    _, rows = _table(ws, "Description")
    assert len(rows) == 3

    summary = _sheet_text(wb["Summary"])
    assert "3 of 7" in summary
    assert "JSON" in summary


def test_activity_split_respects_the_row_limit_including_subtotal_rows(tmp_path):
    """The cap still counts day rows *and* subtotal rows, as before.

    With a 4-row cap the second month's subtotal (row 5) is cut: the day rows
    that survived stay on Daily Activities, June's retained subtotal stays on
    Monthly Activities, and no 07/2026 total is invented.
    """
    data = _data()
    with patch("app.export._EXCEL_MAX_ROWS", 4):
        wb = _load(tmp_path, data)

    _, day_rows = _table(wb["Daily Activities"], "Date")
    assert len(day_rows) == 3
    description = str(wb["Daily Activities"].cell(row=1, column=1).value)
    assert "4 of 5" in description

    _, month_rows = _table(wb["Monthly Activities"], "Month")
    assert [row[0] for row in month_rows] == ["06/2026 TOTAL"]


def test_row_limit_is_disclosed_when_no_data_row_survives(tmp_path):
    data = _data()
    with patch("app.export._EXCEL_MAX_ROWS", 0):
        wb = _load(tmp_path, data)

    assert "Daily Activities" in wb.sheetnames
    ws = wb["Daily Activities"]
    headers, _ = _table(ws, "Date")
    assert headers
    assert ws.max_row == _header_row(ws, "Date")     # header kept, no data rows
    assert "row limit" in str(ws.cell(row=1, column=1).value).lower()
    # No retained subtotal row means no Monthly Activities sheet at all.
    assert "Monthly Activities" not in wb.sheetnames
    assert "row limit" in _sheet_text(wb["Summary"]).lower()


def test_row_limit_is_disclosed_when_the_retained_rows_are_all_blank(tmp_path):
    """A capped section whose retained rows carry no value still says so."""
    data = _data()
    data["events"] = [{"begin": ""}, {"begin": ""}]
    data["faults"] = [{"source": "internal", "confidence": "low"}]
    with patch("app.export._EXCEL_MAX_ROWS", 1):
        wb = _load(tmp_path, data)

    ws = wb["Events"]
    assert "1 of 2" in str(ws.cell(row=1, column=1).value)
    _, rows = _table(ws, "Begin")
    assert rows == [(None,)]   # the retained row is blank, as in the report
    # A section with no visible column at all is stated, not silently dropped.
    assert "Faults" not in wb.sheetnames
    assert "No visible columns — Faults" in _sheet_text(wb["Summary"])


# ── Summary navigation ─────────────────────────────────────────────────────


def test_summary_index_links_every_sheet_with_a_safe_internal_target(tmp_path):
    wb = _load(tmp_path)
    summary = wb["Summary"]
    links = _index_links(summary)

    assert {name for name, _link, _count in links} == set(wb.sheetnames) - {"Summary"}
    for name, link, count in links:
        assert link is not None
        assert link.target is None                                  # internal only
        assert link.location == "'" + name.replace("'", "''") + "'!A1"
        assert wb[name].title == name
        assert count is not None

    _, rows = _table(wb["Events"], "Description")
    counts = {name: count for name, _link, count in links}
    assert counts["Events"] == len(rows)


def test_sheet_names_stay_legal_unique_and_linkable(tmp_path, monkeypatch):
    import core.utils.report_format as report_format

    monkeypatch.setattr(report_format, "EXPORT_SECTIONS", [
        ("long_section", "Driver's Very Long Section Name Over The Limit"),
        ("dup_a", "Load / Unload"),
        ("dup_b", "Load ? Unload"),
    ])
    data = {"long_section": [{"value": "a"}],
            "dup_a": [{"value": "b"}],
            "dup_b": [{"value": "c"}]}
    wb = _load(tmp_path, data)

    names = [name for name in wb.sheetnames if name != "Summary"]
    assert len(names) == 3
    assert len(set(names)) == 3
    for name in names:
        assert len(name) <= 31
        assert not set(name) & set("[]*?:/\\")
        assert name == name.strip("'")
    assert "Load _ Unload" in names                       # existing disambiguation
    linked = {name for name, _link, _count in _index_links(wb["Summary"])}
    assert linked == set(names)
    for name, link, _count in _index_links(wb["Summary"]):
        assert link.location == "'" + name.replace("'", "''") + "'!A1"


# ── preserved sections and untrusted text ──────────────────────────────────


def test_dictionary_and_signature_sheets_are_kept_and_uncapped(tmp_path):
    with patch("app.export._EXCEL_MAX_ROWS", 1):
        wb = _load(tmp_path)

    assert {"Card Issuer", "TREP Signatures", "VU Certificates"} <= set(wb.sheetnames)
    headers, rows = _table(wb["Card Issuer"], "Field")
    assert headers == ["Field", "Value"]
    assert ("Name", "Test Issuer") in rows
    # Dictionary sections keep the shared key/value text as it is (no nation
    # expansion there today: that is the record-table path only).
    assert ("Nation", "I") in rows
    _, trep_rows = _table(wb["TREP Signatures"], "TREP")
    assert trep_rows and trep_rows[0][0] == "0x01"
    _, cert_rows = _table(wb["VU Certificates"], "Format")
    assert cert_rows[0][0] == "CVC"


def test_spreadsheet_text_protection_still_covers_every_excel_path(tmp_path):
    data = _data()
    data["metadata"]["filename"] = "=cmd|' /C calc'!A0"
    data["events"] = [{"description": "=SUM(1,1)",
                       "begin": "2026-06-01T10:30:00+00:00",
                       "=untrusted_header": "@payload"}]
    data["activities"] = [_day("=SUM(1,1)", 1500)]
    wb = _load(tmp_path, data)

    events = wb["Events"]
    headers, rows = _table(events, "Description")
    assert headers[0] == "'=untrusted Header" or "'=untrusted Header" in headers
    assert rows[0][headers.index("Description")] == "'=SUM(1,1)"
    assert "'@payload" in [value for row in rows for value in row]
    assert "'=cmd|' /C calc'!A0" in _sheet_text(wb["Summary"])

    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                assert cell.data_type != "f", f"formula written to {sheet.title}!{cell.coordinate}"
                if isinstance(cell.value, str):
                    assert not cell.value.startswith(("=", "+", "@"))


def test_summary_keeps_every_shared_fact_including_zero_and_false(tmp_path):
    data = _data()
    wb = _load(tmp_path, data)
    ws = wb["Summary"]
    labels = {ws.cell(row=row, column=1).value for row in range(1, ws.max_row + 1)}
    for field, value in summary_rows(data):
        if field and value not in (None, ""):
            assert field in labels

    with patch("app.export.summary_rows",
               return_value=[("Zero metric", 0), ("False flag", False),
                             ("", ""), ("File", "workbook.ddd")]):
        wb = _load(tmp_path, data, )
    ws = wb["Summary"]
    values = {(ws.cell(row=row, column=1).value, ws.cell(row=row, column=2).value)
              for row in range(1, ws.max_row + 1)}
    assert ("Zero metric", 0) in values
    assert ("False flag", False) in values


def test_csv_export_still_lists_monthly_subtotals_inline(tmp_path):
    path = os.path.join(tmp_path, "keep.csv")
    data = _data()
    ExportManager.export_to_csv(data, path)
    with open(path, encoding="utf-8-sig") as handle:
        text = handle.read()
    assert "=== DAILY ACTIVITIES ===" in text
    assert "06/2026 TOTAL" in text and "07/2026 TOTAL" in text


# ── malformed containers (the summary tint is decoration only) ─────────────
#
# The workbook must export every top-level shape the previous exporter
# exported. Colouring a summary row is presentation: a container the shared
# classifier cannot read means "no tint", never an exception and never a
# trust claim.

#: Containers named in the review where the *base* exporter succeeded.
_MALFORMED_SUMMARY_SHAPES = [
    {"metadata": "invalid shape", "events": [{"description": "hello"}]},
    {"metadata": ["invalid shape"], "events": [{"description": "hello"}]},
    {"metadata": {"integrity_check": "Verified"},
     "ef_signature_verification": "invalid shape"},
    {"metadata": {"integrity_check": "Verified"},
     "ef_signature_verification": {"verified": None}},
    {"coverage": "x", "metadata": None},
    {"metadata": None, "coverage": None},
]

#: Every top-level key ``export_to_excel`` reads, and the malformed shapes a
#: truncated/partial parse result can carry in it.
_MALFORMED_VALUES: list = [None, "invalid shape", 7, ["invalid shape"], [None], [1], {}]
_FUZZ_KEYS = (
    ["metadata", "coverage", "driver", "vehicle", "signature_verification",
     "ef_signature_verification", "vu_certificates", "certificates"]
    + [key for key, _label in EXPORT_SECTIONS]
    + [key for key, _label in DICT_SECTIONS]
)

#: Combinations that already fail on the shared/base exporter too (an integer
#: ``vu_certificates`` is iterated there as well: ``TypeError: 'int' object is
#: not iterable``). Kept, and stated, so a real regression cannot hide.
_PRE_EXISTING_CRASHES = (("vu_certificates", 7),)


def _summary_pairs(ws):
    """``{label: value}`` of the Summary's field/value rows."""
    pairs = {}
    for row in range(1, ws.max_row + 1):
        label = ws.cell(row=row, column=1).value
        if label is not None:
            pairs[label] = ws.cell(row=row, column=2).value
    return pairs


@pytest.mark.parametrize("extra", _MALFORMED_SUMMARY_SHAPES)
def test_malformed_containers_still_export_every_summary_fact(tmp_path, extra):
    data = {"events": [{"description": "hello"}], **extra}
    wb = _load(tmp_path, data)
    ws = wb["Summary"]

    # Every fact the shared summary derives from these containers is written.
    pairs = _summary_pairs(ws)
    for field, value in summary_rows(data):
        if field and value not in (None, ""):
            assert field in pairs, f"missing summary fact {field!r}"
    assert "Events" in wb.sheetnames

    # ... and a shape the classifier cannot read is not tinted at all: no
    # "corrupt" claim and no "trusted" styling is invented from it.
    integrity_row = next(row for row in range(1, ws.max_row + 1)
                         if ws.cell(row=row, column=1).value == "Integrity")
    value_cell = ws.cell(row=integrity_row, column=2)
    assert not (value_cell.fill.fgColor.rgb or "").endswith("F8D7DA")


def test_unreadable_integrity_still_tints_a_real_corrupt_verdict(tmp_path):
    """The tint that *is* meant to show keeps working when it can be read."""
    data = _data()
    data["metadata"]["parse_error"] = "truncated download"
    wb = _load(tmp_path, data)
    ws = wb["Summary"]
    row = next(row for row in range(1, ws.max_row + 1)
               if ws.cell(row=row, column=1).value == "Integrity")
    assert (ws.cell(row=row, column=2).fill.fgColor.rgb or "").endswith("F8D7DA")


def _fuzz_seed():
    """A result whose integrity path is walkable, so every branch is reached."""
    data = deepcopy(_data())
    data["metadata"]["integrity_check"] = "Verified (test)"
    data["ef_signature_verification"] = {"verified": 3, "failed": 0, "skipped": 0}
    return data


@pytest.mark.parametrize("key", _FUZZ_KEYS)
def test_malformed_section_values_never_break_the_workbook(tmp_path, key):
    for index, value in enumerate(_MALFORMED_VALUES):
        if any(key == crash_key and value == crash_value
               for crash_key, crash_value in _PRE_EXISTING_CRASHES):
            continue
        data = _fuzz_seed()
        data[key] = deepcopy(value)
        _load(tmp_path, data, name=f"malformed-{key}-{index}.xlsx")


# ── identifier columns are never dates ─────────────────────────────────────


def test_card_identifier_columns_are_never_time_typed(tmp_path):
    data = {
        "events": [
            {"description": "A", "begin": "2026-06-01T10:30:00+00:00",
             "card_driver_begin": "2026-03-04"},
            {"description": "B", "begin": "2026-06-01T11:30:00+00:00",
             "card_driver_begin": "04/03/2026"},
        ],
        "faults": [
            {"description": "F1", "begin": "2026-06-01T10:30:00+00:00",
             "card_driver_begin": "I100000021247001",
             "card_driver_end": "2026-03-04",
             "card_codriver_begin": "04/03/2026",
             "card_codriver_end": "2026-03-04"},
        ],
    }
    wb = _load(tmp_path, data)
    ws = wb["Events"]
    headers, rows = _table(ws, "Description")
    column = headers.index("Card Driver Begin")
    assert [row[column] for row in rows] == ["2026-03-04", "04/03/2026"]

    # The real timestamp column beside it keeps its typed cell.
    assert isinstance(rows[0][headers.index("Begin")], datetime.datetime)

    # No identifier column anywhere in the workbook is a date cell.
    checked = 0
    for sheet in wb.worksheets:
        for header_row in _header_rows(sheet):
            identifiers = [
                cell.column for cell in sheet[header_row]
                if isinstance(cell.value, str)
                and str(cell.value).startswith("Card ")
                and str(cell.value).split()[-1] in ("Begin", "End")
            ]
            for row in sheet.iter_rows(min_row=header_row + 1):
                for cell in row:
                    if cell.column in identifiers and cell.value is not None:
                        checked += 1
                        assert not isinstance(
                            cell.value, (datetime.date, datetime.datetime)), (
                            f"{sheet.title}!{cell.coordinate} = {cell.value!r} is a date")
    assert checked, "the fixture must produce identifier columns"


# ── Summary index ──────────────────────────────────────────────────────────


def _contents_column_width(ws):
    return ws.column_dimensions["B"].width


def _estimated_lines(text, width):
    per_line = max(int(width) - 2, 10)
    return max(-(-len(str(text)) // per_line), 1)


def test_summary_index_never_blank_never_clipped(tmp_path):
    data = _data()
    data["certificates"] = [{"format": "ERCA", "serial": "01", "subject": "MSCA"}]
    data["card_application"] = {"application_id": "Tachograph", "generation": "G2"}
    wb = _load(tmp_path, data)

    # A section with no shared description is still indexed (Driver Card
    # Certificates and the card application tables have none today).
    assert {"Driver Card Certificates", "Card Application"} <= set(wb.sheetnames)
    summary = wb["Summary"]
    width = _contents_column_width(summary)
    header_row = _header_row(summary, "Sheet")

    for row in range(header_row + 1, summary.max_row + 1):
        cell = summary.cell(row=row, column=2)
        text = str(cell.value or "")
        assert text.strip(), f"blank Contents cell for {summary.cell(row=row, column=1).value!r}"
        assert not text.endswith("\u2026"), f"clipped Contents entry: {text!r}"
        assert cell.alignment.wrap_text is True
        height = summary.row_dimensions[row].height or 15
        assert height >= 15 * _estimated_lines(text, width), (
            f"row {row} too short for {text!r} at width {width}")
    indexed = {summary.cell(row=row, column=1).value
               for row in range(header_row + 1, summary.max_row + 1)}
    assert indexed == set(wb.sheetnames) - {"Summary"}


def test_summary_index_fallback_is_derived_and_deterministic(tmp_path):
    data = _data()
    data["certificates"] = [{"format": "ERCA", "serial": "01"}]
    data["card_application"] = {"application_id": "Tachograph"}
    first = _load(tmp_path, data, name="index-a.xlsx")
    second = _load(tmp_path, data, name="index-b.xlsx")

    def entries(wb):
        ws = wb["Summary"]
        header_row = _header_row(ws, "Sheet")
        return {ws.cell(row=row, column=1).value: ws.cell(row=row, column=2).value
                for row in range(header_row + 1, ws.max_row + 1)}

    one, two = entries(first), entries(second)
    assert one == two
    # The fallback says what the sheet *is* — it does not invent content.
    assert "record" in str(one["Driver Card Certificates"]).lower()
    assert "key" in str(one["Card Application"]).lower()


# ── row-limit warning visibility ───────────────────────────────────────────


def _merged_note(ws):
    """``(text, total merged width, row height)`` of the note row."""
    cell = ws.cell(row=1, column=1)
    span = max((rng.max_col - rng.min_col + 1 for rng in ws.merged_cells.ranges),
               default=1)
    width = sum(ws.column_dimensions[openpyxl.utils.get_column_letter(column)].width
                for column in range(1, span + 1))
    return str(cell.value), width, (ws.row_dimensions[1].height or 15)


def test_row_limit_warning_is_readable_in_a_one_column_table(tmp_path):
    data = {"events": [{"description": f"Event {index}"} for index in range(7)]}
    with patch("app.export._EXCEL_MAX_ROWS", 3):
        wb = _load(tmp_path, data)

    ws = wb["Events"]
    headers, rows = _table(ws, "Description")
    assert headers == ["Description"]                       # the narrow case
    assert len(rows) == 3

    text, width, height = _merged_note(ws)
    assert "3 of 7" in text and "JSON" in text
    assert width >= 60, f"merged note width {width} is too narrow to read"
    lines = _estimated_lines(text, width)
    assert height >= 15 * lines
    assert height <= 409.5                                  # Excel's hard cap
    # Only the note row (and the wrapped header band) wrap: data rows never do.
    for row in ws.iter_rows(min_row=_header_row(ws, "Description") + 1):
        for cell in row:
            assert not cell.alignment.wrap_text


def test_row_limit_warning_is_readable_in_an_ordinary_table(tmp_path):
    data = _data()
    data["events"] = [{"description": f"Event {index}",
                       "begin": "2026-06-01T10:30:00+00:00"} for index in range(7)]
    with patch("app.export._EXCEL_MAX_ROWS", 3):
        wb = _load(tmp_path, data)
    text, width, height = _merged_note(wb["Events"])
    assert "3 of 7" in text
    assert width >= 60
    assert height >= 15 * _estimated_lines(text, width)
    assert height <= 409.5


# ── date display shape ─────────────────────────────────────────────────────


def test_date_only_cells_display_the_source_shape(tmp_path):
    data = _data()
    data["sensor_daily_records"] = [
        {"date": "2024-03-20", "max_speed": 90, "average_speed": 40},
    ]
    wb = _load(tmp_path, data)

    # dd/mm/yyyy source → dd/mm/yyyy display (the report's own shape).
    ws = wb["Daily Activities"]
    header_row = _header_row(ws, "Date")
    cell = ws.cell(row=header_row + 1, column=1)
    assert cell.value.date() == datetime.date(2026, 6, 29)
    assert cell.number_format == "dd/mm/yyyy"

    # ISO source → ISO display.
    ws = wb["Sensor Daily Records"]
    headers, rows = _table(ws, "Date")
    column = headers.index("Date")
    sensor_cell = ws.cell(row=_header_row(ws, "Date") + 1, column=column + 1)
    assert sensor_cell.value.date() == datetime.date(2024, 3, 20)
    assert rows[0][column].date() == datetime.date(2024, 3, 20)
    assert sensor_cell.number_format == "yyyy-mm-dd"


def test_over_long_section_note_keeps_its_row_limit_disclosure(tmp_path, monkeypatch):
    """Past Excel's 409.5pt row limit the note is elided, never the disclosure."""
    import core.utils.report_format as report_format

    monkeypatch.setitem(report_format.SECTION_DESCRIPTIONS, "events",
                       "A description that is far too long to fit in one row. " * 40)
    data = {"events": [{"description": f"Event {index}",
                        "begin": "2026-06-01T10:30:00+00:00"} for index in range(7)]}
    with patch("app.export._EXCEL_MAX_ROWS", 3):
        wb = _load(tmp_path, data)

    text, width, height = _merged_note(wb["Events"])
    assert "3 of 7" in text and "JSON" in text       # the disclosure survived
    assert text.startswith("\u2026")                  # and the cut is visible
    assert height <= 409.5                            # Excel's hard cap
    assert height >= 15 * _estimated_lines(text, width)   # what is left fits
