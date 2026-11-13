"""The most recent day of a download ends where its recording ends.

Its last status entry says what was going on at that instant, not how long it
lasted; stretching it to 24:00 invented hours. Seen on real downloads: a driver
card downloaded at 18:49 whose last entry was "DRIVE at 15:59" reported 15:23 of
driving instead of 7:22, and G1 cards showed 17 h of WORK on their download day.
The file carries no reliable download time (VuDownloadActivityData and EF
Card_Download hold the *previous* download), so the cut is the last recorded
instant and the tail of the day is UNKNOWN.
"""
import os
import tempfile

from app.engine import TachoParser
from core.utils.activity_stats import (
    compute_activity_totals,
    day_segments,
    evaluate_driving_rules,
    recorded_until_seconds,
)


def _ch(time, activity, slot="First"):
    return {"time": time, "activity": activity, "slot": slot}


DAY = [_ch("00:00", "REST"), _ch("06:00", "DRIVE"), _ch("10:00", "REST"),
       _ch("11:00", "DRIVE")]


def test_without_a_cut_the_day_runs_to_midnight():
    assert compute_activity_totals(DAY)["DRIVE"] == 4 * 60 + 13 * 60


def test_the_tail_after_the_cut_is_unknown():
    totals = compute_activity_totals(DAY, recorded_until=11 * 3600)
    assert totals == {"DRIVE": 240, "WORK": 0, "REST": 360 + 60,
                      "AVAILABLE": 0, "UNKNOWN": 13 * 60}
    assert sum(totals.values()) == 24 * 60


def test_a_cut_inside_a_segment_splits_it():
    totals = compute_activity_totals(DAY, recorded_until=12 * 3600)
    assert totals["DRIVE"] == 240 + 60 and totals["UNKNOWN"] == 12 * 60


def test_segments_and_rules_follow_the_cut():
    segments = day_segments(DAY, 11 * 3600)["First"]
    assert segments[-1] == (11 * 3600, 86400, "UNKNOWN")
    report = evaluate_driving_rules(DAY, 11 * 3600)
    assert report.drive_min == 240
    assert not report.flagged          # 17 h of driving without the cut


def test_recorded_until_seconds_reads_the_day_record():
    assert recorded_until_seconds({"recorded_until": "15:59"}) == 15 * 3600 + 59 * 60
    assert recorded_until_seconds({"date": "15/07/2025"}) is None
    assert recorded_until_seconds(None) is None


# --- the parser marks only the most recent day --------------------------------

def _parser(is_vu, activities, periods=None):
    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    tmp.write(b"\x00")
    tmp.close()
    parser = TachoParser(tmp.name)
    os.unlink(tmp.name)
    parser.is_vu = is_vu
    parser.results = {"activities": activities}
    if periods is not None:
        parser.results["downloadable_periods"] = periods
    return parser


def _days():
    return [{"date": "14/07/2025", "changes": [_ch("00:00", "REST"), _ch("22:00", "DRIVE")]},
            {"date": "15/07/2025", "changes": [_ch("00:00", "REST"), _ch("15:59", "DRIVE")]}]


def test_card_download_day_is_cut_at_its_last_change():
    days = _days()
    _parser(False, days)._mark_last_recorded_day()
    assert days[1]["recorded_until"] == "15:59"
    assert "recorded_until" not in days[0]


def test_vu_uses_the_latest_downloadable_time_on_that_day():
    days = _days()
    _parser(True, days, [{"max_downloadable_time": "2025-07-15T16:30:00+00:00"}]
            )._mark_last_recorded_day()
    assert days[1]["recorded_until"] == "16:30"


def test_vu_that_recorded_past_the_last_day_leaves_it_complete():
    # The requested period ended before the unit's latest data: the day is whole.
    days = _days()
    _parser(True, days, [{"max_downloadable_time": "2025-07-16T09:00:00+00:00"}]
            )._mark_last_recorded_day()
    assert all("recorded_until" not in d for d in days)
