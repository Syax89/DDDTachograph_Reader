"""Batch 13 — GUI MEDIA families (widget logic only).

Families (``app/gui.py``):
  GUI-STALE-DAY-POPUP   (G-F1/XG-F5) day-detail popup keyed by file + day
  GUI-VEHICLES-PER-DAY  (H-F9)       day detail lists vehicles on every
                                     day a session spans (dashboard parity)

Both families are consumer-layer (``app/gui.py``) and exercise the widget
logic with mocks plus a real ``DayDetailWindow``. The tests skip cleanly when
no display is available (``xvfb-run`` in the gate).
"""
from unittest.mock import Mock

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app.gui import DayDetailWindow, TachoExplorer

DAY = "01/05/2025"


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    window.geometry("900x420")
    try:
        yield window
    finally:
        window.destroy()


@pytest.fixture(autouse=True)
def _clean_open_windows():
    """The open-window registry is class-level; never leak between tests."""
    DayDetailWindow._open_windows.clear()
    yield
    DayDetailWindow._open_windows.clear()


def _open(root, day, activities, file_name):
    """Open a real ``DayDetailWindow`` for ``file_name`` and return it.

    ``parent`` must carry ``current_file`` (the loader sets it), so the reuse
    key can tell two files apart even when they share a day label.
    """
    root.current_file = file_name
    return DayDetailWindow(root, day, activities, 0, len(activities),
                           "", {}, [], [], [], {})


# ── GUI-STALE-DAY-POPUP (G-F1 / XG-F5) ─────────────────────────────────

def test_same_day_in_a_new_file_opens_a_new_window(root):
    """G-F1/XG-F5: ``_open_windows`` was keyed by the day string only, so
    opening a day from a second file that shares the ``dd/mm/yyyy`` label
    lifted the FIRST file's window (its data still on screen) and the new
    file's data never appeared. Loading two different files must create two
    windows, the second showing the second file's data."""
    _open(root, DAY, [{"activity": "DRIVE", "time": "06:00"}], "file1.ddd")
    _open(root, DAY, [{"activity": "REST", "time": "07:00"}], "file2.ddd")

    assert len(DayDetailWindow._open_windows) == 2
    win2 = DayDetailWindow._open_windows[("file2.ddd", DAY)]
    body = win2.text.get("1.0", tk.END)
    assert "07:00  Rest" in body
    assert "06:00  Drive" not in body


def test_same_file_same_day_reuses_the_window(root):
    """The fix must not break the original reuse: the SAME file's same day
    lifts the already-open window instead of stacking duplicates."""
    win1 = _open(root, DAY, [{"activity": "DRIVE", "time": "06:00"}], "a.ddd")
    _open(root, DAY, [{"activity": "DRIVE", "time": "06:00"}], "a.ddd")

    assert len(DayDetailWindow._open_windows) == 1
    assert DayDetailWindow._open_windows[("a.ddd", DAY)] is win1


def test_same_file_different_days_stay_distinct(root):
    """The key still carries the day: two days of one file are two windows
    (a key of file-identity alone would wrongly collapse them)."""
    win1 = _open(root, "01/05/2025", [{"activity": "DRIVE", "time": "06:00"}], "a.ddd")
    win2 = _open(root, "02/05/2025", [{"activity": "REST", "time": "07:00"}], "a.ddd")

    assert win1 is not win2
    assert len(DayDetailWindow._open_windows) == 2


def test_closing_a_window_releases_its_own_key(root):
    """XG-F5: closing must drop the entry under the full (file, day) key, not
    the bare day, or the stale entry stays and blocks the real one."""
    win1 = _open(root, DAY, [{"activity": "DRIVE", "time": "06:00"}], "a.ddd")
    win1._on_close()

    assert ("a.ddd", DAY) not in DayDetailWindow._open_windows


# ── GUI-VEHICLES-PER-DAY (H-F9) ────────────────────────────────────────

_SPAN = {
    "vehicle_plate": "AB123",
    "vehicle_nation": "I",
    "start": "2025-05-01T08:00:00+00:00",
    "end": "2025-05-03T18:00:00+00:00",
}
_SPAN_DATA = {"metadata": {"is_vu": False}, "vehicle_sessions": [_SPAN]}


def _day_vehicles(day, data):
    """Drive ``_on_dashboard_double_click`` for a card file and capture the
    ``vehicle_info`` list handed to ``DayDetailWindow`` (positional arg 9)."""
    import app.gui as gui

    app = object.__new__(TachoExplorer)
    app._dashboard_is_vu = False
    app.table = Mock()
    app.table.tv.identify_row.return_value = "row1"
    app.table.tv.item.return_value = (day,)
    app._dashboard_activity_list = [{"date": day, "changes": []}]
    app._dashboard_data = data

    captured = {}
    original = gui.DayDetailWindow

    def _stub(*args, **kwargs):
        captured["vehicles"] = args[9]

    gui.DayDetailWindow = _stub
    try:
        app._on_dashboard_double_click(Mock(y=10))
    finally:
        gui.DayDetailWindow = original
    return captured


def test_multi_day_session_shows_on_the_intermediate_day():
    """H-F9: a 01/05→03/05 session was counted on 02/05 by the dashboard
    (which fills every spanned day) yet the day detail for 02/05 listed no
    vehicle. The popup must include a session whose interval covers the day."""
    captured = _day_vehicles("02/05/2025", _SPAN_DATA)
    assert [v["plate"] for v in captured["vehicles"]] == ["AB123"]


def test_multi_day_session_shows_on_the_end_day():
    """H-F9: 03/05 is the session's END; the old code anchored on the START
    only, so the end day (and any middle day) showed no vehicle."""
    captured = _day_vehicles("03/05/2025", _SPAN_DATA)
    assert [v["plate"] for v in captured["vehicles"]] == ["AB123"]


def test_multi_day_session_still_shows_on_the_start_day():
    """Control: the start day is inside the interval and was already correct."""
    captured = _day_vehicles("01/05/2025", _SPAN_DATA)
    assert [v["plate"] for v in captured["vehicles"]] == ["AB123"]


def test_day_before_the_session_has_no_vehicle():
    """A 01/05→03/05 session must not leak onto 30/04 (before the start)."""
    captured = _day_vehicles("30/04/2025", _SPAN_DATA)
    assert captured["vehicles"] == []


def test_day_after_the_session_has_no_vehicle():
    """A 01/05→03/05 session must not leak onto 04/05 (after the end)."""
    captured = _day_vehicles("04/05/2025", _SPAN_DATA)
    assert captured["vehicles"] == []


def _tree_day_vehicles(data):
    """Run the tree route (``_populate_daily_activities``) with the real
    ``_day_vehicles_info`` and capture the vehicles attached to each day node.

    The tree day nodes feed the SAME day-detail popup as the dashboard, so a
    multi-day session must land on every spanned day here too.
    """
    app = object.__new__(TachoExplorer)
    app._payloads = {}
    app.tree = Mock()
    app.tree.insert.return_value = "node"
    app._add_section = Mock()
    captured = []

    def _capture(parent, day, is_vu, activities, day_km, changes_count,
                 driver_info, slot_schedule, markers, oos_events, vehicle_info):
        captured.append((day, [v["plate"] for v in vehicle_info]))
        return "daynode"

    app._add_activity_day = Mock(side_effect=_capture)
    activity_list = [{"date": d, "changes": []} for d in
                     ("01/05/2025", "02/05/2025", "03/05/2025", "04/05/2025")]
    app._populate_daily_activities("parent", data, activity_list)
    return dict(captured)


def test_tree_day_nodes_span_a_multi_day_session():
    """H-F9 sibling: the tree's "Daily Activities" day nodes are another route
    into the same day-detail popup. They must list the vehicle on every day the
    session spans (not only the anchor day), matching the dashboard."""
    by_day = _tree_day_vehicles(_SPAN_DATA)
    assert by_day["01/05/2025"] == ["AB123"]
    assert by_day["02/05/2025"] == ["AB123"]
    assert by_day["03/05/2025"] == ["AB123"]
    assert by_day["04/05/2025"] == []

