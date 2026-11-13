"""A driver card is one holder: moving the card to the other slot mid-day must
not split the day into two drivers.

The card's ActivityChangeInfo slot bit says which slot the card sat in. Read as
two timelines (the vehicle-unit reading, where each slot is a driver), the hours
before the move were counted twice, once as activity in slot 1 and once as the
UNKNOWN lead-in of slot 2, and a real day added up to 33 h 40.
"""
from core.analysis.period_report import build_period_report
from core.utils.activity_stats import (compute_activity_totals, day_segments,
                                       evaluate_driving_rules)
from core.utils.report_format import build_monthly_activity_report


def _ch(time, activity, slot, inserted=True):
    return {"time": time, "activity": activity, "slot": slot,
            "crew": False, "card_inserted": inserted}


#: Slot 1 until 16:48, then the card moves to slot 2 for the rest of the day.
MOVED = [_ch("00:00", "REST", "First"), _ch("06:00", "DRIVE", "First"),
         _ch("10:00", "REST", "First"), _ch("16:48", "REST", "First", inserted=False),
         _ch("16:48", "WORK", "Second"), _ch("17:48", "REST", "Second")]


def test_a_card_day_adds_up_to_24_hours():
    totals = compute_activity_totals(MOVED, one_driver=True)
    assert sum(totals.values()) == 24 * 60
    assert totals == {"DRIVE": 240, "WORK": 60, "REST": 1140, "AVAILABLE": 0,
                      "UNKNOWN": 0}


def test_the_vehicle_unit_reading_is_unchanged():
    # Two slots of a vehicle unit are two drivers: the default keeps them apart.
    split = day_segments(MOVED)
    assert set(split) == {"First", "Second"}
    assert set(day_segments(MOVED, one_driver=True)) == {"First"}


def test_rules_and_reports_take_the_card_reading():
    report = evaluate_driving_rules(MOVED, one_driver=True)
    assert report.drive_min == 240
    day = {"date": "04/07/2025", "changes": MOVED}
    headers, rows = build_monthly_activity_report([day], one_driver=True)
    assert rows[0][headers.index("Total (h)")] == "24:00"
    card = {"metadata": {"is_vu": False},
            "driver": {"card_number": "X1", "surname": "DOE", "firstname": "J"},
            "activities": [day]}
    row = build_period_report([("a.ddd", card)])[0]
    assert (row["drive_min"] + row["work_min"] + row["rest_min"]
            + row["available_min"] + row["unknown_min"]) == 24 * 60
