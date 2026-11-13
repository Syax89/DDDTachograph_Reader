"""Record tables a person can read: technical columns behind a switch, codes in
words, one date format, columns as wide as their text, a record window.
"""
import pytest

pytest.importorskip("tkinter")

import tkinter as tk  # noqa: E402

from app.gui import DataTable, _rows_for, fmt_val  # noqa: E402
from app.gui_text import Columns, _columns_for, technical_columns  # noqa: E402

EVENT = {"description": "Driving without an appropriate card", "event_type_code": 4,
         "record_purpose": 1, "begin": "2025-03-07T17:46:00+00:00",
         "manufacturer_code": 162, "manufacturer": "Stoneridge"}
IW = {"holder_surname": "DOE", "card": "I100000168598002",
      "card_expiry": "2026-09-15T00:00:00+00:00",
      "insertion_time": "2025-07-07T03:49:00+00:00",
      "odometer_insertion_km": 111719, "odometer_insertion_raw": 111719,
      "card_slot": 0}
CALIBRATION = {"calibration_purpose": 3, "calibration_purpose_label": "Installation",
               "workshop_name": "WORKSHOP", "sensor_serial_hex": "018a922f",
               "sensor_serial": "25904308"}


# --- which columns are technical --------------------------------------------

def test_raw_hex_and_spelled_out_codes_are_technical():
    assert set(technical_columns(EVENT)) == {"event_type_code", "manufacturer_code"}
    assert set(technical_columns(IW)) == {"odometer_insertion_raw"}
    assert set(technical_columns(CALIBRATION)) == {"calibration_purpose",
                                                   "sensor_serial_hex"}


def test_a_code_with_no_words_beside_it_stays_visible():
    assert technical_columns({"type_code": 1, "nation": "I"}) == []


def test_technical_columns_go_last_and_keep_the_rest_in_place():
    cols = _columns_for([IW], None)
    assert cols[-1] == "odometer_insertion_raw"
    assert cols[:-1] == [c for c in IW if c != "odometer_insertion_raw"]


def test_rows_for_marks_technical_headers_and_renames_label_columns():
    headers, rows = _rows_for([CALIBRATION], None)
    assert isinstance(headers, Columns)
    assert headers[0] == "Calibration Purpose"           # not "... Label"
    assert headers.technical == {"Calibration Purpose Code"}   # the number, renamed
    assert len(rows[0]) == len(headers)


# --- values in words, one date format ---------------------------------------

def test_codes_read_as_words():
    assert fmt_val(1, key="record_purpose").startswith("Longest event")
    assert fmt_val(0, key="card_slot") == "Driver slot"
    assert fmt_val(1, key="card_slot") == "Co-driver slot"
    assert fmt_val(7, key="card_slot") == "7"


@pytest.mark.parametrize("value, key, shown", [
    ("2025-07-07T03:49:00+00:00", "insertion_time", "07/07/2025 03:49 UTC"),
    ("2026-09-15T00:00:00+00:00", "card_expiry", "15/09/2026"),
    ("2026-09-15T00:00:00+00:00", "begin", "15/09/2026 00:00 UTC"),
    ("2023-07-27", "last_date", "27/07/2023"),
    ("2025-07-07T03:49:00", "insertion_time", "07/07/2025 03:49"),
    ("GV692XZ", "plate", "GV692XZ"),
])
def test_dates_share_one_shape(value, key, shown):
    assert fmt_val(value, key=key) == shown


# --- the table ---------------------------------------------------------------

@pytest.fixture
def table():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.geometry("900x400")
    widget = DataTable(root)
    widget.pack(fill=tk.BOTH, expand=True)
    root.update()
    yield widget
    root.destroy()


def _shown(table):
    return [table.tv.item(iid, "values") for iid in table.tv.get_children()]


def test_technical_columns_are_hidden_until_switched_on(table):
    headers, rows = _rows_for([IW, dict(IW, insertion_time="2025-07-08T02:55:00+00:00")], None)
    table.show("Card IW", headers, rows)
    assert "Odometer Insertion Raw" not in table._cols
    assert table.technical_check.winfo_manager()           # the switch is offered
    assert len(_shown(table)[0]) == len(headers) - 1
    assert "Columns: 6" in table.count_lbl.cget("text")

    table.technical_var.set(True)
    table._toggle_technical()
    assert table._cols[-1] == "Odometer Insertion Raw"
    assert len(_shown(table)[0]) == len(headers)
    assert "Columns: 7" in table.count_lbl.cget("text")
    table.technical_var.set(False)
    table._toggle_technical()


def test_no_switch_without_technical_columns(table):
    table.show("Plain", ["A", "B"], [["1", "2"]])
    assert not table.technical_check.winfo_manager()
    assert _shown(table) == [("1", "2")]


def test_dates_with_time_sort_chronologically(table):
    rows = [["08/07/2025 02:55 UTC"], ["07/07/2025 15:50 UTC"], ["07/07/2025 03:49 UTC"]]
    table.show("Times", Columns(["When"]), rows)
    table._sort_by("When")
    assert [r[0] for r in _shown(table)] == [
        "07/07/2025 03:49 UTC", "07/07/2025 15:50 UTC", "08/07/2025 02:55 UTC"]


def test_columns_are_not_cut_below_their_text(table):
    long = "Driving without an appropriate card"
    headers = Columns([f"Column {i}" for i in range(8)])
    table.show("Wide", headers, [[long] * 8])
    table.update()
    table._fitted = False
    table._fit_columns()
    width = table.tv.column("Column 0", "width")
    assert width >= table._table_font().measure(long)


def test_record_window_lists_every_field_including_technical(table):
    headers, rows = _rows_for([IW], None)
    table.show("Card IW", headers, rows)
    first = table.tv.get_children()[0]
    table.tv.selection_set(first)
    assert table._open_detail() == "break"
    windows = [w for w in table.winfo_children() if isinstance(w, tk.Toplevel)]
    assert windows
    detail_tree = windows[-1].winfo_children()[0].winfo_children()[0]
    fields = [detail_tree.item(i, "values")[0] for i in detail_tree.get_children()]
    assert fields == list(headers)                         # technical included
    windows[-1].destroy()


def test_views_that_set_columns_themselves_are_not_projected(table):
    headers, rows = _rows_for([IW], None)
    table.show("Card IW", headers, rows)
    # what the summary panel and the dashboards do
    table._cols = ["Field", "Value"]
    table._all_rows = [("Name", "Value 1")]
    table._render(table._all_rows)
    assert _shown(table) == [("Name", "Value 1")]
    assert table._open_detail() is None
