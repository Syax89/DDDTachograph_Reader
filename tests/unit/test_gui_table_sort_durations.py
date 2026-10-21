"""Sorting an activity column must compare durations, not their text.

The dashboard prints a day's Drive/Work/Rest/Available as ``"Xh YYm"``
(``_fmt_duration_minutes``). ``DataTable._sort_by`` recognised dates and plain
numbers only, so a duration fell through to a string comparison: a 12 h day
sorted *before* a 5 h day, and 10 h days came before 8 h days, because "1" <
"5" and "1" < "8". Every duration column of the dashboard has this shape, so
the sort — the one interaction the dashboard's headers offer — put the days in
an order that matches neither time nor the numbers on screen.

Reproduced before the fix: ascending ``Drive`` over 5 h, 12 h, 9 h 30 m came
back as 12h, 5h, 9h30m.
"""
import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app.gui import TachoExplorer

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("DISPLAY"), reason="needs a display")

ROWS = [
    ["01/05/2025", "5h 00m", "12h 00m", "7h 00m"],
    ["02/05/2025", "12h 00m", "9h 30m", "2h 15m"],
    ["03/05/2025", "9h 30m", "0h 05m", "13h 40m"],
    ["04/05/2025", "0h 00m", "10h 00m", "3h 45m"],
]
COLUMNS = ["Date", "Drive", "Work", "Rest"]


@pytest.fixture
def explorer():
    try:
        app = TachoExplorer()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        yield app
    finally:
        try:
            for after_id in app.tk.call("after", "info"):
                app.tk.call("after", "cancel", after_id)
        except tk.TclError:
            pass
        try:
            app.destroy()
        except tk.TclError:
            pass


def _dates(app):
    return [list(app.table.tv.item(iid, "values"))[0]
            for iid in app.table.tv.get_children("")]


def _sorted_dates(app, column):
    app.table._sort_by(column)          # first click: ascending
    app.update()
    return _dates(app)


def test_a_duration_column_sorts_by_minutes(explorer):
    explorer.table.show("Days", COLUMNS, ROWS)
    assert _sorted_dates(explorer, "Drive") == [
        "04/05/2025",   # 0h 00m
        "01/05/2025",   # 5h 00m
        "03/05/2025",   # 9h 30m
        "02/05/2025",   # 12h 00m
    ]


def test_a_duration_column_sorts_by_minutes_descending(explorer):
    explorer.table.show("Days", COLUMNS, ROWS)
    assert _sorted_dates(explorer, "Drive") == [
        "04/05/2025", "01/05/2025", "03/05/2025", "02/05/2025"]
    assert _sorted_dates(explorer, "Drive") == [
        "02/05/2025", "03/05/2025", "01/05/2025", "04/05/2025"]


@pytest.mark.parametrize("column,worst", [
    ("Drive", "02/05/2025"),   # 12h 00m
    ("Work", "01/05/2025"),    # 12h 00m
    ("Rest", "03/05/2025"),    # 13h 40m
])
def test_the_longest_day_of_every_duration_column_sorts_last(explorer, column, worst):
    explorer.table.show("Days", COLUMNS, ROWS)
    ascending = _sorted_dates(explorer, column)
    assert ascending[-1] == worst


def test_a_marked_drive_cell_still_sorts_by_its_duration(explorer):
    """The infringement marker ("  !") trails the value: it must not defeat
    the comparison, and a marked day keeps its place by its minutes."""
    rows = [
        ["01/05/2025", "12h 15m  !"],
        ["02/05/2025", "4h 30m  !"],
        ["03/05/2025", "8h 00m"],
    ]
    explorer.table.show("Days", ["Date", "Drive"], rows)
    assert _sorted_dates(explorer, "Drive") == [
        "02/05/2025", "03/05/2025", "01/05/2025"]


def test_numbers_and_dates_keep_sorting_as_before(explorer):
    """The existing keys are untouched: only durations gained a numeric one."""
    rows = [
        ["01/05/2025", "1 100 km", "9"],
        ["02/05/2025", "999 km", "10"],
        ["03/05/2025", "2 000 km", "1"],
    ]
    explorer.table.show("Days", ["Date", "Km", "N"], rows)
    assert _sorted_dates(explorer, "Date") == [
        "01/05/2025", "02/05/2025", "03/05/2025"]
    assert _sorted_dates(explorer, "N") == [
        "03/05/2025", "01/05/2025", "02/05/2025"]
