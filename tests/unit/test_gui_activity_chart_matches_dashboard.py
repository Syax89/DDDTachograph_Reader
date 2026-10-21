"""The Daily-Activities timeline must report the same minutes as the dashboard.

``ActivityTimelineChart._build_blocks`` re-implemented the day segmentation on
its own instead of using the shared one in
:mod:`core.utils.activity_stats` — the routine behind the Daily-Activities
dashboard, the CLI summary and the PDF report.  The three consequences were all
visible on screen:

* a card-not-inserted period (``card_inserted`` false + ``crew`` false, Annex
  1C §2.1 note 2) was painted as *Rest*, so a day the driver spent without a
  card showed 23 h of rest in the chart and the dashboard showed 5 min;
* a missing leading 00:00 status entry (Annex 1C §2.170) left the first hours
  of the day unaccounted instead of UNKNOWN;
* an unrecognised activity label was dropped, shrinking the day's total.

Measured on the tracked samples before the fix: 471 of 1750 single-slot days
and 956 of 1307 vehicle-unit days whose chart minutes disagreed with
``compute_activity_totals``.
"""
import pytest

from core.utils.activity_stats import compute_activity_totals

pytest.importorskip("tkinter")

from app.gui import ActivityTimelineChart


def minutes(blocks):
    """``{activity: minutes}`` for one slot's block list."""
    totals = {}
    for start, end, activity in blocks:
        totals[activity] = totals.get(activity, 0) + (end - start) // 60
    return totals


def test_a_card_not_inserted_period_is_unknown_not_rest():
    """Annex 1C §2.1 note 2: with no card and one crew member the recorded
    activity code is 'not relevant' — the chart must not call it Rest."""
    changes = [
        {"activity": "REST", "time": "00:00", "slot": "First",
         "card_inserted": False, "crew": False},
        {"activity": "DRIVE", "time": "14:00", "slot": "First",
         "card_inserted": True, "crew": False},
    ]
    chart = minutes(ActivityTimelineChart._build_blocks(changes, is_vu=False)["Cardholder"])
    assert chart.get("REST", 0) == 0, "card-absent minutes painted as Rest"
    assert chart == {"UNKNOWN": 840, "DRIVE": 600}


def test_the_chart_and_the_dashboard_report_the_same_day():
    """One day, four activities, one card slot: every minute must agree."""
    changes = [
        {"activity": "REST", "time": "00:00", "slot": "First",
         "card_inserted": False, "crew": False},
        {"activity": "DRIVE", "time": "04:30", "slot": "First",
         "card_inserted": True, "crew": False},
        {"activity": "WORK", "time": "08:00", "slot": "First",
         "card_inserted": True, "crew": False},
        {"activity": "XYZ", "time": "09:15", "slot": "First",
         "card_inserted": True, "crew": False},
        {"activity": "REST", "time": "18:00", "slot": "First",
         "card_inserted": True, "crew": False},
    ]
    chart = minutes(ActivityTimelineChart._build_blocks(changes, is_vu=False)["Cardholder"])
    dashboard = compute_activity_totals(changes)
    assert chart == {kind: mins for kind, mins in dashboard.items() if mins}


def test_a_missing_leading_status_entry_is_unknown_not_an_empty_gap():
    """Annex 1C §2.170: the day always has a status at 00:00. When the decoder
    did not emit it, the hours before the first change are UNKNOWN."""
    changes = [{"activity": "WORK", "time": "06:00", "slot": "First"}]
    blocks = ActivityTimelineChart._build_blocks(changes, is_vu=False)["Cardholder"]
    assert blocks == [(0, 21600, "UNKNOWN"), (21600, 86400, "WORK")]


def test_an_unrecognised_activity_label_keeps_its_minutes():
    """A label outside the four kinds is UNKNOWN, not a hole in the day."""
    changes = [{"activity": "XYZ", "time": "03:00", "slot": "First"}]
    blocks = ActivityTimelineChart._build_blocks(changes, is_vu=False)["Cardholder"]
    assert minutes(blocks) == {"UNKNOWN": 1440}
    assert sum(end - start for start, end, _a in blocks) == 86400


def test_a_vehicle_unit_day_keeps_its_two_slots_apart():
    """Slot labels and per-slot totals stay exactly as they were shown."""
    changes = [
        {"activity": "DRIVE", "time": "00:00", "slot": "First"},
        {"activity": "REST", "time": "12:00", "slot": "First"},
        {"activity": "REST", "time": "00:00", "slot": "Second"},
        {"activity": "DRIVE", "time": "10:00", "slot": "Second"},
    ]
    blocks = ActivityTimelineChart._build_blocks(changes, is_vu=True)
    assert set(blocks) == {"Slot 1", "Slot 2"}
    assert minutes(blocks["Slot 1"]) == {"DRIVE": 720, "REST": 720}
    assert minutes(blocks["Slot 2"]) == {"REST": 600, "DRIVE": 840}


def test_a_vehicle_unit_day_matches_the_dashboard_slot_by_slot():
    changes = [
        {"activity": "REST", "time": "00:00", "slot": "First",
         "card_inserted": False, "crew": False},
        {"activity": "DRIVE", "time": "05:00", "slot": "First",
         "card_inserted": True, "crew": False},
        {"activity": "REST", "time": "00:00", "slot": "Second",
         "card_inserted": False, "crew": False},
        {"activity": "AVAILABLE", "time": "07:00", "slot": "Second",
         "card_inserted": True, "crew": False},
    ]
    blocks = ActivityTimelineChart._build_blocks(changes, is_vu=True)
    assert minutes(blocks["Slot 1"]) == {"UNKNOWN": 300, "DRIVE": 1140}
    assert minutes(blocks["Slot 2"]) == {"UNKNOWN": 420, "AVAILABLE": 1020}
