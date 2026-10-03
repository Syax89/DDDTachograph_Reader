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
