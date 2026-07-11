"""Formatting helpers remain usable without creating a Tk window."""
import pytest

pytest.importorskip("tkinter")

from app.gui import _columns_for, fmt_val


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
