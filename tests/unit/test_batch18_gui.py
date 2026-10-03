"""Batch 18 — GUI LOW families (widget logic and render strings only).

Families (``app/gui.py``):
  GUI-BOGUS-DRIVER      (G-F8)  a driver section of all-"N/A" defaults is no
                                longer created / auto-selected
  GUI-DISTANCE-FALLBACK (XG-F9) the day-detail popup shows the day's distance,
                                never the absolute odometer; the one Italian UI
                                string became "Unknown"
  GUI-NAME-ORDER        (H-F8)  driver names render "First names Surname"
  GUI-SMOKE-LAUNCH      (H-F6)  a bare ``--smoke`` exits non-zero instead of
                                launching the GUI (which hangs a headless runner)
  GUI-SPEED-ROUNDING    (G-F5)  a sub-minute non-zero second count is not
                                truncated to "0 min"
  GUI-STALE-TABLE       (XG-F4) ``_parse_done`` refreshes the right-hand pane
                                in the same call, so the previous file's table
                                can never sit under the new filename

All are consumer-layer (``app/gui.py``) and exercise the widget logic with
mocks plus real Tk widgets. The Tk tests skip cleanly with no display
(``xvfb-run`` in the gate).
"""
import sys
from unittest.mock import Mock

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app.gui import (
    DayDetailWindow,
    DetailedSpeedChart,
    TachoExplorer,
    _fmt_seconds_duration,
)

DAY = "01/05/2025"
ISO = "2025-05-01"

_CARD_REC = {
    "holder_first_names": "MARIO",
    "holder_surname": "ROSSI",
    "card_number": "IT1234567890",
    "card_slot": 0,
    "insertion_time": "2025-05-01T06:00:00+00:00",
    "withdrawal_time": "2025-05-01T10:00:00+00:00",
}


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


# ── GUI-SPEED-ROUNDING (G-F5) ──────────────────────────────────────────

def test_fmt_seconds_duration_never_truncates_a_non_zero_value():
    """G-F5: a non-zero sub-minute count must not read "0 min"."""
    assert _fmt_seconds_duration(0) == "0 s"
    assert _fmt_seconds_duration(30) == "30 s"
    assert _fmt_seconds_duration(59) == "59 s"
    assert _fmt_seconds_duration(60) == "1 min"
    assert _fmt_seconds_duration(90) == "1 min 30 s"
    assert _fmt_seconds_duration(1800) == "30 min"


def test_speed_summary_shows_seconds_below_a_minute(root):
    """G-F5: 30 samples above the limit (and 30 moving) is 30 s, not "0 min"."""
    chart = DetailedSpeedChart(root)
    chart.pack(fill=tk.BOTH, expand=True)
    chart.show(DAY, [(second, 120) for second in range(30)])

    summary = chart.summary_lbl.cget("text")
    assert "30 s above 90 km/h" in summary
    assert "30 s moving" in summary
    assert "0 min" not in summary


def test_speed_summary_keeps_whole_minutes(root):
    """The fix must not disturb whole-minute values: 1800 s is still 30 min."""
    chart = DetailedSpeedChart(root)
    chart.pack(fill=tk.BOTH, expand=True)
    chart.show(DAY, [(second, 120) for second in range(1800)])

    summary = chart.summary_lbl.cget("text")
    assert "30 min above 90 km/h" in summary
    assert "30 min moving" in summary


def test_speed_summary_overspeed_column_is_not_zeroed(monkeypatch):
    """G-F5 sibling call-site: the Detailed Speed dashboard truncated its
    "Time >90 km/h" column/KPI to whole minutes too (0h 00m for 30 s)."""
    import app.gui as gui

    monkeypatch.setattr(gui, "detailed_speed_by_day",
                        lambda data: {"2025-05-01": [(0, 120)] * 30})
    app = object.__new__(TachoExplorer)
    captured = {}
    app._show_dashboard = Mock(
        side_effect=lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs))

    app._show_speed_summary([], {})

    title, _date_range, kpis, _columns, table_rows = captured["args"]
    assert title == "Detailed Speed"
    assert table_rows[0][4] == "30 s"
    assert ("Time >90 km/h", "30 s", "#d32f2f") in kpis


# ── GUI-SMOKE-LAUNCH (H-F6) ────────────────────────────────────────────

def test_bare_smoke_without_a_file_exits_nonzero(monkeypatch):
    """H-F6: ``--smoke`` alone used to fall through to ``TachoExplorer(...)
    .mainloop()`` and hang a headless runner. It must exit non-zero instead."""
    import app.gui as gui

    launched = Mock()
    monkeypatch.setattr(gui, "TachoExplorer", launched)
    monkeypatch.setattr(sys, "argv", ["gui.py", "--smoke"])

    with pytest.raises(SystemExit) as exc:
        gui.main()

    assert exc.value.code == 2
    launched.assert_not_called()


def test_smoke_with_a_file_still_self_checks(monkeypatch):
    """The two-argument form must keep routing to ``_smoke_check``."""
    import app.gui as gui

    check = Mock(return_value=0)
    monkeypatch.setattr(gui, "_smoke_check", check)
    monkeypatch.setattr(sys, "argv", ["gui.py", "--smoke", "x.ddd"])

    with pytest.raises(SystemExit) as exc:
        gui.main()

    assert exc.value.code == 0
    check.assert_called_once_with("x.ddd")


def test_smoke_entrypoint_does_not_hang_without_a_file():
    """End-to-end: ``python -m app.gui --smoke`` must terminate, not open a
    window. A hang here would blow the subprocess timeout."""
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "app.gui", "--smoke"],
        cwd=repo, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    assert "usage" in proc.stdout.lower()


# ── GUI-BOGUS-DRIVER (G-F8) ────────────────────────────────────────────

_NOW_DRIVER = {
    "card_number": "N/A",
    "surname": "N/A",
    "firstname": "N/A",
    "birth_date": "N/A",
    "expiry_date": "N/A",
    "issuing_nation": "N/A",
}


def _populate_tree_sections(data):
    """Run the real ``_populate_tree`` with a mocked tree; return the app and
    the labels of every section it created."""
    app = object.__new__(TachoExplorer)
    app.tree = Mock()
    app.tree.get_children.return_value = []
    app.tree.insert.return_value = "section"
    app.current_file = "sample.ddd"
    app._payloads = {}
    app._integrity_label = Mock(return_value="OK")
    app._populate_unparsed = Mock()
    app._populate_security = Mock()
    app._add_section = Mock(return_value="section")
    app._populate_tree(data)
    return app, [call.args[1] for call in app._add_section.call_args_list]


def test_all_na_driver_section_is_not_created():
    """G-F8: an untouched ``TachoResult.driver`` is every field "N/A" — a
    truthy string, so ``any(drv.values())`` created and auto-selected a
    phantom "Driver / Cardholder" panel full of "N/A"."""
    app, labels = _populate_tree_sections(
        {"metadata": {"is_vu": False}, "driver": dict(_NOW_DRIVER)})

    assert not any("Driver / Cardholder" in label for label in labels)
    assert app.__dict__.get("_auto_select_iid") is None


def test_driver_section_is_still_created_for_real_data():
    """The guard must still fire for a driver with a usable value."""
    data = {"metadata": {"is_vu": False},
            "driver": {**_NOW_DRIVER, "firstname": "MARIO",
                       "surname": "ROSSI", "card_number": "IT1234567890"}}
    app, labels = _populate_tree_sections(data)

    assert any("Driver / Cardholder" in label for label in labels)
    assert app.__dict__.get("_auto_select_iid") == "section"


# ── GUI-STALE-TABLE (XG-F4) ────────────────────────────────────────────

def _parse_done_app():
    app = object.__new__(TachoExplorer)
    app._finish_parse = Mock()
    app._populate_tree = Mock()
    app._update_top_bar = Mock()
    app._check_integrity = Mock()
    app._show_empty = Mock()
    app.btn_export = Mock()
    app.status = Mock()
    app.tree = Mock()
    app.after_idle = Mock()
    return app


def test_parse_done_replaces_the_stale_table_synchronously():
    """XG-F4: between the filename update and the deferred <<TreeviewSelect>>
    render, the pane still showed the PREVIOUS file's rows under the NEW
    filename. ``_parse_done`` must replace the pane synchronously (a neutral
    placeholder, never the old file's data) and then render the node on idle."""
    app = _parse_done_app()
    app.tree.get_children.return_value = ["node1"]
    app._auto_select_iid = "node1"
    app._on_tree_select = Mock()

    app._parse_done({"metadata": {}}, "file2.ddd")

    # Stale pane replaced in-call; the new node renders on the idle cycle.
    app._show_empty.assert_called_once()
    app.after_idle.assert_called_once()
    app._on_tree_select.assert_not_called()


def test_parse_done_clears_the_table_when_there_are_no_nodes():
    """With no selectable node the stale pane must still be cleared."""
    app = _parse_done_app()
    app.tree.get_children.return_value = []
    app._auto_select_iid = None
    app._on_tree_select = Mock()

    app._parse_done({"metadata": {}}, "file2.ddd")

    app._show_empty.assert_called_once()
    app._on_tree_select.assert_not_called()
    app.after_idle.assert_not_called()


def test_speed_summary_overspeed_column_is_not_zeroed(monkeypatch):
    """Drive ``_on_dashboard_double_click`` and capture the args handed to
    ``DayDetailWindow``. The constructor is swapped manually and restored
    immediately (it resolves its own name from the module global)."""
    import app.gui as gui

    app = object.__new__(TachoExplorer)
    app._dashboard_is_vu = is_vu
    app._vu_slot_filter = "Slot 1"
    app.table = Mock()
    app.table.tv.identify_row.return_value = "row1"
    app.table.tv.item.return_value = (DAY,)
    app._day_vehicles_info = Mock(return_value=[])
    app._dashboard_activity_list = activity_list
    app._dashboard_data = data
    app._dashboard_card_day_km = card_day_km or {}

    captured = {}
    original = gui.DayDetailWindow

    def _stub(*args, **kwargs):
        captured["changes"] = args[2]
        captured["day_km"] = args[3]
        captured["driver_name"] = args[5]
        captured["slot_schedule"] = args[6]
        captured["markers"] = args[7]

    gui.DayDetailWindow = _stub
    try:
        app._on_dashboard_double_click(Mock(y=10))
    finally:
        gui.DayDetailWindow = original
    return captured


def test_dashboard_markers_use_firstname_surname_order():
    """H-F8: the popup markers/schedule showed "SURNAME FIRSTNAME" while the
    rest of the app shows "First names Surname"."""
    day = {"date": DAY, "changes": []}
    data = {"metadata": {"is_vu": False},
            "card_iw_records": [dict(_CARD_REC)]}

    captured = _dashboard_double_click(data, [day])

    names = {marker[2] for marker in captured["markers"]}
    assert names == {"MARIO ROSSI"}
    schedule_names = {entry[2]
                      for entries in captured["slot_schedule"].values()
                      for entry in entries}
    assert schedule_names == {"MARIO ROSSI"}


def test_driver_presence_uses_firstname_surname_order():
    win = object.__new__(DayDetailWindow)
    win._data = {"card_iw_records": [dict(_CARD_REC)]}
    win._iso_date = ISO

    ranges = win._driver_presence()

    names = [name for entries in ranges.values() for (_s, _e, name) in entries]
    assert names == ["MARIO ROSSI"]


def test_shared_timeline_uses_firstname_surname_order():
    win = object.__new__(DayDetailWindow)
    win._data = {"card_iw_records": [dict(_CARD_REC)]}
    win._iso_date = ISO
    win._slot_schedule = {}
    win._oos_events = []

    entries = win._build_shared_timeline()

    card_in = [entry for entry in entries if entry[2] == "CARD_IN"]
    assert card_in
    assert "MARIO ROSSI" in card_in[0][5]
    assert "ROSSI MARIO" not in card_in[0][5]


# ── GUI-DISTANCE-FALLBACK (XG-F9) ──────────────────────────────────────

def test_popup_uses_the_day_delta_not_the_absolute_odometer():
    """XG-F9: for a card file ``_day_km`` is 0, so the popup used to fall back
    to the absolute ``odometer_km`` as the day's "Distance". It must reuse the
    odometer-delta the dashboard shows for the same day."""
    day = {"date": DAY, "changes": [], "odometer_km": 123456}
    data = {"metadata": {"is_vu": False}, "card_iw_records": []}

    captured = _dashboard_double_click(data, [day],
                                       card_day_km={id(day): 42})

    assert captured["day_km"] == 42
    assert captured["day_km"] != day["odometer_km"]


def test_popup_shows_zero_when_no_day_distance_is_known():
    """With no dashboard delta available the popup must show 0, never the
    absolute odometer."""
    day = {"date": DAY, "changes": [], "odometer_km": 123456}
    data = {"metadata": {"is_vu": False}, "card_iw_records": []}

    captured = _dashboard_double_click(data, [day])

    assert captured["day_km"] == 0


def test_missing_driver_name_falls_back_to_english_unknown():
    """XG-F9: the only Italian string in the UI ("Sconosciuto") became the
    English "Unknown", matching every other fallback."""
    nameless = {
        "holder_first_names": "", "holder_surname": "", "card_number": "",
        "card_slot": 0,
        "insertion_time": "2025-05-01T06:00:00+00:00",
        "withdrawal_time": "2025-05-01T08:00:00+00:00",
    }
    day = {"date": DAY, "changes": []}
    data = {"metadata": {"is_vu": False},
            "card_iw_records": [nameless]}

    captured = _dashboard_double_click(data, [day])

    assert {marker[2] for marker in captured["markers"]} == {"Unknown"}
