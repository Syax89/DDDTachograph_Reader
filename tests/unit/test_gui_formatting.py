"""Formatting helpers remain usable without creating a Tk window."""
from unittest.mock import Mock

import pytest

pytest.importorskip("tkinter")

from app.gui import TachoExplorer, _columns_for, fmt_val


def test_gui_scalar_formatting_matches_existing_display_output():
    assert fmt_val("2026-06-01T10:30:00+00:00") == "2026-06-01 10:30"
    assert fmt_val("I", key="nation") == "Italy"
    assert fmt_val(0x21, key="trep") == "33  (TREP 21)"
    assert fmt_val({"card_number": ""}) == "—"
    assert fmt_val([1, 2]) == "1, 2"


def test_gui_column_order_and_filtering_are_unchanged():
    records = [{
        "description": "Event",
        "purpose": "Control",
        "value": 1,
        "source": "internal",
        "record_type": 2,
        "_key": "dedupe",
    }]

    assert _columns_for(records, None) == ["purpose", "description", "value", "record_type"]
    assert _columns_for(["scalar"], None) == ["Value"]


def test_dashboard_slot_view_keeps_slotless_changes():
    """G-F7 / XG-F6: heuristic G1 TREP 02 changes carry no ``slot``.

    Filtering strictly on ``slot`` dropped them from every slot view and the
    Daily-Activities dashboard reported 0h for each activity of the day, while
    the same rows stayed visible in the day tree. A change with no slot must
    still be counted (as unassigned), never silently zeroed.
    """
    app = object.__new__(TachoExplorer)
    app._vu_slot_filter = "Slot 2"
    app._show_empty = Mock()
    captured = []
    app._update_dashboard_in_place = Mock(side_effect=lambda *a: captured.append(a))

    activities = [{
        "date": "01/05/2025",
        "changes": [
            {"activity": "DRIVE", "time": "08:00"},   # no slot
            {"activity": "WORK", "time": "12:00"},    # no slot
        ],
    }]

    app._show_daily_summary(activities, {"metadata": {"is_vu": True}},
                            _fast_refresh=True)

    assert not app._show_empty.called, "slotless day must not be treated as empty"
    _date_range, kpis, table_rows = captured[0][:3]
    assert ("Drive", "4h 00m", "#1565c0") in kpis
    day_row = next(r for r in table_rows if r and r[0] == "01/05/2025")
    assert day_row[5] == "4h 00m"      # Drive column (0h before the fix)
    assert day_row[6] == "12h 00m"     # Work column


def _slot_view(activities, slot_label):
    app = object.__new__(TachoExplorer)
    app._vu_slot_filter = slot_label
    app._show_empty = Mock()
    captured = []
    app._update_dashboard_in_place = Mock(side_effect=lambda *a: captured.append(a))
    app._show_daily_summary(activities, {"metadata": {"is_vu": True}},
                            _fast_refresh=True)
    return captured[0][2]  # table_rows


def test_dashboard_slot_view_does_not_leak_the_other_slot():
    """Direction B of G-F7/XG-F6: keeping slot-less changes must not also leak
    a real change from the *other* card slot into the wrong slot view."""
    activities = [{
        "date": "01/05/2025",
        "changes": [
            {"activity": "DRIVE", "time": "00:00", "slot": "First"},
            {"activity": "REST",  "time": "08:00", "slot": "First"},
            {"activity": "WORK",  "time": "00:00", "slot": "Second"},
            {"activity": "DRIVE", "time": "10:00", "slot": "Second"},
        ],
    }]

    row1 = next(r for r in _slot_view(activities, "Slot 1")
                if r and r[0] == "01/05/2025")
    assert row1[5] == "8h 00m"    # Drive  = First 00:00-08:00
    assert row1[6] == "0h 00m"    # Work   = none (Second's must NOT leak in)

    row2 = next(r for r in _slot_view(activities, "Slot 2")
                if r and r[0] == "01/05/2025")
    assert row2[6] == "10h 00m"   # Work   = Second 00:00-10:00
    assert row2[5] == "14h 00m"   # Drive  = Second 10:00-24:00


def test_day_detail_uses_the_same_slot_filter_as_the_summary(monkeypatch):
    """The day-detail path had the identical ``== slot_name`` predicate as the
    summary, so a slot-less day opened an EMPTY detail. Both must filter through
    the shared ``_changes_for_slot`` helper."""
    app = object.__new__(TachoExplorer)
    app._dashboard_is_vu = True
    app._vu_slot_filter = "Slot 1"
    app.table = Mock()
    app.table.tv.identify_row.return_value = "row1"
    app.table.tv.item.return_value = ("01/05/2025",)
    app._day_vehicles_info = Mock(return_value=[])
    app._dashboard_activity_list = [{"date": "01/05/2025", "changes": [
        {"activity": "DRIVE", "time": "08:00"},                    # no slot -> kept
        {"activity": "WORK",  "time": "12:00", "slot": "First"},   # kept
        {"activity": "REST",  "time": "16:00", "slot": "Second"},  # other slot -> dropped
    ]}]
    app._dashboard_data = {"metadata": {"is_vu": True}}

    captured = {}
    monkeypatch.setattr("app.gui.DayDetailWindow",
                        lambda *a, **k: captured.setdefault("changes", a[2]))
    app._on_dashboard_double_click(Mock(y=10))

    assert [c["activity"] for c in captured["changes"]] == ["DRIVE", "WORK"]
