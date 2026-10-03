"""Batch 12 — GUI MEDIA families (widget logic only).

Families (``app/gui.py``):
  GUI-CARD-MARKER-SLOT      (G-F6)      card marker slot from ``cardSlot``
  GUI-CARD-PRESENT-GUESS    (G-F3/XG-F8) day-detail "Card present" estimate
  GUI-DASHBOARD-SLOT2-POPUP (G-F2/H-F4)  popup gets the full day's changes
  GUI-INVALID-IW-TIME       (H-F1)      non-string insertion_time must not crash
  GUI-NONE-CHANGES          (H-F3/XG-F7) ``changes=None`` must not crash
  GUI-SPEED-MARKER-CLIP     (G-F4)      overspeed marker stays inside the plot

Only the two families that genuinely need a Tk canvas/window (card-present
summary and the speed marker) touch tkinter; they skip cleanly when no display
is available. The rest exercise widget logic with ``object.__new__`` plus mocks.
"""
from unittest.mock import Mock

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app.gui import DayDetailWindow, DetailedSpeedChart, TachoExplorer


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


# ── shared helpers ─────────────────────────────────────────────────────

def _run_daily_populate(data, activity_list):
    """Run ``_populate_daily_activities`` with mocked tree/sections and return
    the ``slot_schedule``/``markers`` handed to ``_add_activity_day``."""
    app = object.__new__(TachoExplorer)
    app._payloads = {}
    app.tree = Mock()
    app.tree.insert.return_value = "node"
    app._add_section = Mock()
    app._day_vehicles_info = Mock(return_value=[])
    captured = {}

    def _capture(parent, day, is_vu, activities, day_km, changes_count,
                 driver_info, slot_schedule, markers, *args, **kwargs):
        captured["day"] = day
        captured["slot_schedule"] = slot_schedule
        captured["markers"] = markers
        return "daynode"

    app._add_activity_day = Mock(side_effect=_capture)
    app._populate_daily_activities("parent", data, activity_list)
    return captured


def _fast_dashboard(activities, data, slot_label="Slot 1"):
    """Run ``_show_daily_summary`` fast path with mocks; return captured args."""
    app = object.__new__(TachoExplorer)
    app._vu_slot_filter = slot_label
    app._show_empty = Mock()
    captured = []
    app._update_dashboard_in_place = Mock(side_effect=lambda *a: captured.append(a))
    app._show_daily_summary(activities, data, _fast_refresh=True)
    return app, captured


def _dashboard_double_click(activity_list, slot_label):
    """Drive ``_on_dashboard_double_click`` and capture what it passes to
    ``DayDetailWindow`` (both the change list and the keyword args).

    The constructor is swapped manually (and restored immediately) rather than
    with ``monkeypatch``: ``DayDetailWindow.__init__`` resolves its own name
    from the module global, so leaving the patch in place would break a real
    window constructed afterwards.
    """
    import app.gui as gui

    app = object.__new__(TachoExplorer)
    app._dashboard_is_vu = True
    app._vu_slot_filter = slot_label
    app.table = Mock()
    app.table.tv.identify_row.return_value = "row1"
    app.table.tv.item.return_value = ("01/05/2025",)
    app._day_vehicles_info = Mock(return_value=[])
    app._dashboard_activity_list = activity_list
    app._dashboard_data = {"metadata": {"is_vu": True}}

    captured = {}
    original = gui.DayDetailWindow

    def _stub(*args, **kwargs):
        captured["changes"] = args[2]
        captured["kwargs"] = kwargs

    gui.DayDetailWindow = _stub
    try:
        app._on_dashboard_double_click(Mock(y=10))
    finally:
        gui.DayDetailWindow = original
    return captured


def _open_detail(root, activities, data=None, is_vu=False):
    """Open a real DayDetailWindow and return its rendered body text."""
    window = DayDetailWindow(root, "01/05/2025", activities, 0, len(activities),
                             "", {}, [], [], [], data or {}, is_vu=is_vu)
    try:
        return window, window.text.get("1.0", tk.END)
    finally:
        DayDetailWindow._open_windows.clear()


# ── GUI-CARD-MARKER-SLOT (G-F6) ────────────────────────────────────────

_TWO_DRIVER_VU = {
    "metadata": {"is_vu": True},
    "card_iw_records": [
        {"holder_first_names": "MARIO", "holder_surname": "ROSSI",
         "card_slot": 0, "insertion_time": "2025-05-01T06:00:00+00:00",
         "withdrawal_time": "2025-05-01T10:00:00+00:00"},
        {"holder_first_names": "LUCA", "holder_surname": "BIANCHI",
         "card_slot": 1, "insertion_time": "2025-05-01T12:00:00+00:00",
         "withdrawal_time": "2025-05-01T18:00:00+00:00"},
    ],
}


def test_card_markers_use_the_record_card_slot():
    """With no ``inserted_drivers``/name mapping at all, the co-driver's
    insertion/withdrawal markers must still land in Slot 2, driven by the
    record's authoritative ``card_slot`` (0=driver, 1=co-driver)."""
    captured = _run_daily_populate(_TWO_DRIVER_VU,
                                   [{"date": "01/05/2025", "changes": []}])

    assert [(m[1], m[2], m[3]) for m in captured["markers"]] == [
        ("Slot 1", "MARIO ROSSI", True),
        ("Slot 1", "MARIO ROSSI", False),
        ("Slot 2", "LUCA BIANCHI", True),
        ("Slot 2", "LUCA BIANCHI", False),
    ]
    assert set(captured["slot_schedule"]) == {"Slot 1", "Slot 2"}


def test_card_marker_slot_beats_the_time_name_heuristic():
    """G-F6: a co-driver whose insertion coincides (within 2 min) with a
    ``card_inserted`` change stamped ``First`` used to be mislabelled Slot 1.
    The authoritative ``card_slot`` must win over the time/name inference."""
    data = {
        "metadata": {"is_vu": True},
        "card_iw_records": [
            {"holder_first_names": "ANNA", "holder_surname": "VERDI",
             "card_slot": 1, "insertion_time": "2025-05-01T06:00:00+00:00",
             "withdrawal_time": "2025-05-01T09:00:00+00:00"},
        ],
    }
    activities = [{"date": "01/05/2025", "changes": [
        {"activity": "DRIVE", "time": "06:00", "slot": "First",
         "card_inserted": True},
    ]}]

    captured = _run_daily_populate(data, activities)
    insertion_markers = [m for m in captured["markers"] if m[3]]
    assert len(insertion_markers) == 1
    assert insertion_markers[0][1] == "Slot 2"


# ── GUI-CARD-PRESENT-GUESS (G-F3 / XG-F8) ──────────────────────────────

def test_card_present_guess_uses_the_end_of_the_last_activity(root):
    """G-F3: with no CARD_IN markers the summary estimated the withdrawal from
    the *start* of the last activity (14:00 for a REST running to 24:00). The
    window must end at the last activity's END."""
    window, body = _open_detail(root, [
        {"activity": "DRIVE", "time": "06:00"},
        {"activity": "REST",  "time": "14:00"},
    ])
    try:
        assert "Card present: 06:00 \u2013 24:00" in body
    finally:
        window.destroy()


def test_card_present_not_invented_when_the_card_is_absent(root):
    """XG-F8: an activity with ``card_inserted=False`` produces an explicit
    "Card not inserted" line; the summary must not simultaneously claim the
    card was present."""
    window, body = _open_detail(root, [
        {"activity": "DRIVE", "time": "06:00", "card_inserted": False},
    ])
    try:
        assert "Card not inserted" in body
        assert "Card present" not in body
    finally:
        window.destroy()


# ── GUI-DASHBOARD-SLOT2-POPUP (G-F2 / H-F4) ────────────────────────────

_SLOT_DAY = [{"date": "01/05/2025", "changes": [
    {"activity": "DRIVE", "time": "00:00", "slot": "First"},
    {"activity": "WORK",  "time": "08:00", "slot": "Second"},
]}]


def test_dashboard_double_click_hands_the_popup_the_whole_day():
    """G-F2/H-F4: opening the popup from a Slot-2 dashboard used to pass only
    the Slot-2 changes, so the popup's Slot-1 tab was always empty. The popup
    must receive the day's full change set and re-split it itself."""
    captured = _dashboard_double_click(_SLOT_DAY, "Slot 2")
    assert [c["activity"] for c in captured["changes"]] == ["DRIVE", "WORK"]


def test_dashboard_slot2_popup_opens_on_the_dashboard_slot(root):
    """G-F2/H-F4: the popup also defaulted to ``_current_slot = 1``, so opening
    it from a Slot-2 dashboard showed the (empty) Slot-1 tab immediately. It
    must open on the dashboard's selected slot."""
    captured = _dashboard_double_click(_SLOT_DAY, "Slot 2")
    assert captured["kwargs"]["initial_slot"] == 2

    window = DayDetailWindow(root, "01/05/2025", captured["changes"], 0, 0,
                             "", {}, [], [], [], {}, is_vu=True,
                             initial_slot=captured["kwargs"]["initial_slot"])
    try:
        assert window._current_slot == 2
        body = window.text.get("1.0", tk.END)
        assert "No data for this day." not in body
        assert "Work" in body
    finally:
        DayDetailWindow._open_windows.clear()
        window.destroy()


def test_dashboard_slot2_popup_renders_both_slots(root):
    """End-to-end (within the test): the popup built from the changes the
    dashboard actually passed must show data in *both* slot tabs, never
    "No data for this day." for the first slot."""
    changes = _dashboard_double_click(_SLOT_DAY, "Slot 2")["changes"]
    window = DayDetailWindow(root, "01/05/2025", changes, 0, 0,
                             "", {}, [], [], [], {}, is_vu=True)
    try:
        assert "No data for this day." not in window.text.get("1.0", tk.END)
        window._toggle_slot()
        slot2_body = window.text.get("1.0", tk.END)
        assert "No data for this day." not in slot2_body
        assert "Work" in slot2_body
    finally:
        DayDetailWindow._open_windows.clear()
        window.destroy()


# ── GUI-INVALID-IW-TIME (H-F1) ─────────────────────────────────────────

def test_dashboard_survives_int_insertion_time():
    """H-F1: an out-of-range/raw integer TimeReal made ``ins_str[:19]`` raise
    ``TypeError`` (not covered by ``except (ValueError, IndexError)``) and
    crashed the whole Daily-Activities dashboard."""
    data = {"metadata": {"is_vu": True}, "card_iw_records": [
        {"holder_first_names": "A", "holder_surname": "B",
         "insertion_time": 4294967295}]}
    _, captured = _fast_dashboard(
        [{"date": "01/05/2025", "changes": [
            {"activity": "DRIVE", "time": "08:00", "slot": "First"}]}], data)
    assert captured, "dashboard must still render with a non-string TimeReal"


def test_dashboard_survives_none_insertion_time():
    """H-F1 (second shape): a ``None`` insertion_time is the other non-string
    value the decoder can emit; it must be skipped, not crash the render."""
    data = {"metadata": {"is_vu": True}, "card_iw_records": [
        {"holder_first_names": "A", "holder_surname": "B",
         "insertion_time": None}]}
    _, captured = _fast_dashboard(
        [{"date": "01/05/2025", "changes": [
            {"activity": "DRIVE", "time": "08:00", "slot": "First"}]}], data)
    assert captured


# ── GUI-NONE-CHANGES (H-F3 / XG-F7) ────────────────────────────────────

def test_daily_tree_populate_survives_none_changes():
    """H-F3/XG-F7 call site 1: ``_populate_daily_activities`` (day tree render)."""
    captured = _run_daily_populate({"metadata": {"is_vu": False}},
                                   [{"date": "01/05/2025", "changes": None}])
    assert captured["day"] == "01/05/2025"


def test_dashboard_summary_survives_none_changes():
    """H-F3/XG-F7 call sites in ``_show_daily_summary`` (card file path)."""
    _, captured = _fast_dashboard([{"date": "01/05/2025", "changes": None}],
                                  {"metadata": {"is_vu": False}})
    assert captured


def test_dashboard_summary_survives_none_changes_for_vu():
    """H-F3/XG-F7 slot-filter call site of ``_show_daily_summary`` (VU path)."""
    _, captured = _fast_dashboard([{"date": "01/05/2025", "changes": None}],
                                  {"metadata": {"is_vu": True}})
    assert captured


def test_driver_summary_survives_none_changes():
    """H-F3/XG-F7 call site in ``_build_driver_summary`` (statistics rows)."""
    app = object.__new__(TachoExplorer)
    _, rows = app._build_driver_summary(
        {"driver": {}, "activities": [{"changes": None}]})
    assert ("  Activity changes", "0", False) in rows


# ── GUI-SPEED-MARKER-CLIP (G-F4) ───────────────────────────────────────

def _drawn_chart(root, samples, events):
    chart = DetailedSpeedChart(root)
    chart.pack(fill=tk.BOTH, expand=True)
    root.update()
    chart.show("01/05/2025", samples, overspeeding_events=events)
    root.update_idletasks()
    chart._draw()
    return chart


def test_overspeed_marker_stays_within_the_plot(root):
    """G-F4: an event whose max speed exceeds every sampled speed of the day
    was drawn above the plot (off-canvas → invisible and unhoverable). The
    y-ceiling must include the event's max speed."""
    chart = _drawn_chart(root, [(3600, 100), (7200, 120)],
                         [{"begin": "2025-05-01T08:00:00+00:00",
                           "max_speed_kmh": 250}])
    assert chart._oes_dots, "the overspeed marker must be drawn"
    _x, y, _evt = chart._oes_dots[0]
    _left, _right, top, bottom = chart._plot[:4]
    assert top <= y <= bottom
    assert chart._y_scale[1] >= 250


def test_overspeed_marker_without_speed_does_not_crash(root):
    """G-F4 companion: an event lacking ``max_speed_kmh`` must not raise inside
    ``y_for`` (``"" * height / ceiling``)."""
    chart = _drawn_chart(root, [(3600, 100)],
                         [{"begin": "2025-05-01T08:00:00+00:00"}])
    assert chart._oes_dots
    _x, y, _evt = chart._oes_dots[0]
    _left, _right, top, bottom = chart._plot[:4]
    assert top <= y <= bottom
