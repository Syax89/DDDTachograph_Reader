"""Indicative Regulation (EC) No 561/2006 analysis (core/analysis/regulation_561.py).

Every scenario is a synthetic driver-card timeline written as consecutive
``(activity, minutes)`` blocks from 00:00 UTC of a start date, turned into the
day records the parser produces (``{"date", "changes", "recorded_until"?}``).
``UNKNOWN`` blocks are written the way a card records them: a card-not-inserted
period (``card_inserted`` and ``crew`` both False), which the shared day
segmentation reads as UNKNOWN.
"""
import json
from datetime import date, timedelta

import pytest

from core.analysis import regulation_561 as r561
from core.analysis.regulation_561 import (
    FINDING_NOTICE, RULE_BREAK, RULE_DAILY_DRIVING, RULE_DAILY_EXTENSIONS, RULE_DAILY_REST,
    RULE_FORTNIGHTLY_DRIVING, RULE_REDUCED_REST_COUNT, RULE_WEEKLY_DRIVING, RULE_WEEKLY_REST_START,
    RULE_WEEKLY_REST_TWO_WEEKS, STATUS_INDETERMINATE, STATUS_INFRINGEMENT, analyse_days, analyse_result,
    build_timeline, format_report,
)

MONDAY = date(2024, 1, 1)          # a Monday: fixed weeks start here
SUNDAY_BEFORE = date(2023, 12, 31)


# ── Builders ─────────────────────────────────────────────────────────────────
def make_days(blocks, start=MONDAY, *, pad="REST", recorded_until=None):
    """Day records for consecutive ``(kind, minutes[, crew])`` blocks.

    The last day is filled up to 24:00 with ``pad`` unless ``recorded_until``
    ("HH:MM", on the last day) ends the recording first.
    """
    events = []
    t = 0
    for block in blocks:
        kind, minutes = block[0], block[1]
        crew = block[2] if len(block) > 2 else False
        events.append((t, kind, crew))
        t += minutes
    n_days = max(1, -(-t // 1440))
    if t < n_days * 1440 and recorded_until is None:
        events.append((t, pad, False))

    def change(minute_of_day, kind, crew):
        unknown = kind == "UNKNOWN"
        return {
            "time": f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}",
            "activity": "REST" if unknown else kind,
            "slot": "First",
            "crew": False if unknown else crew,
            "card_inserted": not unknown,
        }

    days = []
    for d in range(n_days):
        lo, hi = d * 1440, (d + 1) * 1440
        ongoing = [e for e in events if e[0] <= lo][-1]
        changes = [change(0, ongoing[1], ongoing[2])]
        changes += [change(e[0] - lo, e[1], e[2]) for e in events if lo < e[0] < hi]
        record = {"date": (start + timedelta(days=d)).strftime("%d/%m/%Y"), "changes": changes}
        days.append(record)
    if recorded_until is not None:
        days[-1]["recorded_until"] = recorded_until
    return days


def duty(drive_min, extra_work=0):
    """A duty: driving in 4h30 chunks with 45 min breaks, then optional WORK."""
    blocks = []
    left = drive_min
    while left > 0:
        chunk = min(270, left)
        blocks.append(("DRIVE", chunk))
        left -= chunk
        if left > 0:
            blocks.append(("REST", 45))
    if extra_work:
        blocks.append(("WORK", extra_work))
    return blocks


def length(blocks):
    return sum(b[1] for b in blocks)


def cycle(drive_min, rest_min, extra_work=0):
    """A duty followed by a rest."""
    return duty(drive_min, extra_work) + [("REST", rest_min)]


def day_cycle(drive_min, extra_work=0):
    """A duty plus the rest that completes 24 h (start to start)."""
    work = duty(drive_min, extra_work)
    return work + [("REST", 1440 - length(work))]


def findings(report, rule=None, status=None):
    return [f for f in report["findings"]
            if (rule is None or f["rule"] == rule) and (status is None or f["status"] == status)]


def statuses(report, rule):
    return [f["status"] for f in findings(report, rule)]


#: Data opens at 00:00 inside a rest, so the first daily period starts at 06:00.
LEAD = [("REST", 360)]


# ── Timeline ─────────────────────────────────────────────────────────────────
class TestTimeline:
    def test_days_are_concatenated_in_date_order(self):
        days = make_days(LEAD + [("DRIVE", 1440)])          # crosses midnight
        timeline = build_timeline(list(reversed(days)))
        assert timeline.start == r561._day_start(MONDAY)
        assert timeline.end == timeline.start + 2 * 86400
        drive = [(s, e) for s, e, k in timeline.segments if k == "DRIVE"]
        assert drive == [(timeline.start + 6 * 3600, timeline.start + 30 * 3600)]

    def test_missing_day_is_unknown(self):
        days = make_days(LEAD + day_cycle(540) * 3)
        del days[1]
        timeline = build_timeline(days)
        assert timeline.missing_days == 1
        base = r561._day_start(MONDAY) + 86400
        assert (base, base + 86400, "UNKNOWN") in timeline.segments

    def test_recorded_until_ends_the_data(self):
        days = make_days(LEAD + [("DRIVE", 240)], recorded_until="10:00")
        timeline = build_timeline(days)
        assert timeline.end == r561._day_start(MONDAY) + 10 * 3600
        assert timeline.segments[-1][2] == "DRIVE"

    def test_card_slots_fold_into_one_timeline(self):
        day = {"date": "01/01/2024", "changes": [
            {"time": "00:00", "activity": "REST", "slot": "First", "crew": False, "card_inserted": True},
            {"time": "06:00", "activity": "DRIVE", "slot": "Second", "crew": False, "card_inserted": True},
            {"time": "10:31", "activity": "REST", "slot": "First", "crew": False, "card_inserted": True},
        ]}
        report = analyse_days([day])
        assert [(f["status"], f["measured"]) for f in findings(report, RULE_BREAK)] == \
            [(STATUS_INFRINGEMENT, 271)]

    def test_crew_intervals_are_kept(self):
        timeline = build_timeline(make_days(LEAD + [("DRIVE", 120, True)]))
        start = r561._day_start(MONDAY)
        assert timeline.crew == ((start + 6 * 3600, start + 8 * 3600),)

    def test_no_dated_records_is_no_data(self):
        assert analyse_days([])["status"] == "no_data"
        assert analyse_days([{"date": "garbage", "changes": []}])["status"] == "no_data"


# ── Art. 7: breaks ───────────────────────────────────────────────────────────
class TestBreaks:
    def test_exactly_four_and_a_half_hours_is_compliant(self):
        report = analyse_days(make_days(LEAD + [("DRIVE", 270)]))
        assert findings(report, RULE_BREAK) == []
        assert report["summary"]["by_rule"][RULE_BREAK]["assessed"] == 1

    def test_one_minute_more_is_an_infringement(self):
        report = analyse_days(make_days(LEAD + [("DRIVE", 271)]))
        (finding,) = findings(report, RULE_BREAK)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"], finding["unit"]) == (271, 270, "minutes")
        assert finding["article"] == "Art. 7"
        assert (finding["start"], finding["end"]) == ("2024-01-01T06:00Z", "2024-01-01T10:31Z")

    def test_45_minute_break_resets(self):
        report = analyse_days(make_days(LEAD + [("DRIVE", 135), ("REST", 45), ("DRIVE", 270)]))
        assert findings(report, RULE_BREAK) == []

    def test_44_minute_break_does_not_reset(self):
        report = analyse_days(make_days(LEAD + [("DRIVE", 135), ("REST", 44), ("DRIVE", 136)]))
        assert [f["measured"] for f in findings(report, RULE_BREAK, STATUS_INFRINGEMENT)] == [271]

    def test_split_15_then_30_resets(self):
        blocks = LEAD + [("DRIVE", 120), ("REST", 15), ("DRIVE", 150), ("REST", 30), ("DRIVE", 270)]
        assert findings(analyse_days(make_days(blocks)), RULE_BREAK) == []

    def test_split_30_then_15_does_not_reset(self):
        blocks = LEAD + [("DRIVE", 120), ("REST", 30), ("DRIVE", 120), ("REST", 15), ("DRIVE", 31)]
        report = analyse_days(make_days(blocks))
        assert [f["measured"] for f in findings(report, RULE_BREAK, STATUS_INFRINGEMENT)] == [271]

    def test_split_first_part_below_15_minutes_does_not_count(self):
        blocks = LEAD + [("DRIVE", 120), ("REST", 14), ("DRIVE", 120), ("REST", 30), ("DRIVE", 31)]
        report = analyse_days(make_days(blocks))
        assert [f["measured"] for f in findings(report, RULE_BREAK, STATUS_INFRINGEMENT)] == [271]

    @pytest.mark.parametrize("kind", ["WORK", "AVAILABLE"])
    def test_work_or_availability_is_not_a_break(self, kind):
        report = analyse_days(make_days(LEAD + [("DRIVE", 135), (kind, 60), ("DRIVE", 136)]))
        assert [f["measured"] for f in findings(report, RULE_BREAK, STATUS_INFRINGEMENT)] == [271]

    def test_unknown_gap_makes_it_indeterminate(self):
        report = analyse_days(make_days(LEAD + [("DRIVE", 135), ("UNKNOWN", 60), ("DRIVE", 136)]))
        (finding,) = findings(report, RULE_BREAK)
        assert finding["status"] == STATUS_INDETERMINATE
        assert finding["unrecorded_min"] == 60
        assert report["summary"]["infringements"] == 0

    def test_driving_over_midnight_accumulates(self):
        blocks = [("REST", 22 * 60), ("DRIVE", 271)]          # 22:00 → 02:31
        report = analyse_days(make_days(blocks))
        (finding,) = findings(report, RULE_BREAK, STATUS_INFRINGEMENT)
        assert (finding["start"], finding["end"]) == ("2024-01-01T22:00Z", "2024-01-02T02:31Z")

    def test_crew_period_makes_it_indeterminate(self):
        report = analyse_days(make_days(LEAD + [("DRIVE", 300, True)]))
        (finding,) = findings(report, RULE_BREAK)
        assert finding["status"] == STATUS_INDETERMINATE
        assert "multi-manning" in finding["explanation"]


# ── Art. 6: driving times ────────────────────────────────────────────────────
class TestDailyDriving:
    def test_nine_hour_days_are_compliant(self):
        report = analyse_days(make_days(LEAD + day_cycle(540) * 5))
        assert findings(report, RULE_DAILY_DRIVING) == []
        assert findings(report, RULE_DAILY_EXTENSIONS) == []
        assert report["summary"]["by_rule"][RULE_DAILY_DRIVING]["assessed"] >= 5

    def test_two_ten_hour_days_a_week_are_compliant(self):
        blocks = LEAD + day_cycle(600) * 2 + day_cycle(540) * 3
        report = analyse_days(make_days(blocks))
        assert findings(report, RULE_DAILY_DRIVING) == []
        assert findings(report, RULE_DAILY_EXTENSIONS) == []

    def test_third_ten_hour_day_is_an_infringement(self):
        blocks = LEAD + day_cycle(600) * 3 + day_cycle(540) * 2
        report = analyse_days(make_days(blocks))
        (finding,) = findings(report, RULE_DAILY_EXTENSIONS)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"], finding["unit"]) == (3, 2, "count")
        assert finding["start"] == "2024-01-03T06:00Z"

    def test_extensions_count_per_fixed_week(self):
        # Fri + Sat in one week, Mon of the next: never three in one week.
        blocks = [("REST", 4 * 1440 + 360)] + day_cycle(600) * 2 + [("REST", 2 * 1440)] + day_cycle(600)
        report = analyse_days(make_days(blocks))
        assert findings(report, RULE_DAILY_EXTENSIONS) == []

    def test_more_than_ten_hours_is_an_infringement(self):
        report = analyse_days(make_days(LEAD + day_cycle(601)))
        (finding,) = findings(report, RULE_DAILY_DRIVING)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"]) == (601, 600)

    def test_exactly_ten_hours_is_not(self):
        assert findings(analyse_days(make_days(LEAD + day_cycle(600))), RULE_DAILY_DRIVING) == []

    def test_daily_driving_runs_rest_to_rest_across_midnight(self):
        # 20:00 → 07:15 next day: 4h00 on the first calendar day, 6h30 on the second.
        blocks = [("REST", 20 * 60)] + duty(630) + [("REST", 900)]
        report = analyse_days(make_days(blocks))
        (finding,) = findings(report, RULE_DAILY_DRIVING)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert finding["measured"] == 630
        assert finding["start"] == "2024-01-01T20:00Z"


class TestWeeklyDriving:
    # Mon–Sat: 2 × 10 h + 4 × 9 h = 56 h, then a long rest.
    WEEK_56 = day_cycle(600) * 2 + day_cycle(540) * 4

    def test_56_hours_is_compliant(self):
        report = analyse_days(make_days(LEAD + self.WEEK_56 + [("REST", 3000)]))
        assert findings(report, RULE_WEEKLY_DRIVING) == []

    def test_56_hours_and_a_minute_is_an_infringement(self):
        week = day_cycle(600) * 2 + day_cycle(540) * 3 + day_cycle(541)
        report = analyse_days(make_days(LEAD + week + [("REST", 3000)]))
        (finding,) = findings(report, RULE_WEEKLY_DRIVING)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"]) == (3361, 3360)
        assert (finding["start"], finding["end"]) == ("2024-01-01T00:00Z", "2024-01-08T00:00Z")

    def _fortnight(self, last_day_drive):
        week2 = day_cycle(540) * 3 + day_cycle(last_day_drive)
        # Week 1 ends Sun 06:00; one more day of rest reaches Mon 06:00.
        return LEAD + self.WEEK_56 + [("REST", 1440)] + week2 + [("REST", 3000)]

    def test_90_hours_in_two_weeks_is_compliant(self):
        report = analyse_days(make_days(self._fortnight(420)))      # 56 h + 34 h
        assert findings(report, RULE_FORTNIGHTLY_DRIVING) == []

    def test_90_hours_and_a_minute_is_an_infringement(self):
        report = analyse_days(make_days(self._fortnight(421)))
        (finding,) = findings(report, RULE_FORTNIGHTLY_DRIVING)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"]) == (5401, 5400)

    def test_partial_week_is_not_assessed(self):
        report = analyse_days(make_days(LEAD + day_cycle(540) * 2))
        assert report["summary"]["by_rule"][RULE_WEEKLY_DRIVING]["assessed"] == 0


# ── Art. 8: daily rest ───────────────────────────────────────────────────────
def _rest_report(rest_blocks, drive=540):
    """One duty from 06:00, the given rest blocks, another duty, a long rest."""
    blocks = LEAD + duty(drive) + rest_blocks + duty(drive) + [("REST", 3000)]
    return analyse_days(make_days(blocks))


def _reduced(report):
    return report["summary"]["by_rule"][RULE_REDUCED_REST_COUNT]["assessed"]


class TestDailyRest:
    def test_eleven_hours_is_regular(self):
        report = _rest_report([("REST", 660)])
        assert findings(report, RULE_DAILY_REST) == []
        assert _reduced(report) == 0

    def test_nine_hours_is_reduced(self):
        report = _rest_report([("REST", 540)])
        assert findings(report, RULE_DAILY_REST) == []
        assert _reduced(report) == 1

    def test_under_nine_hours_is_an_infringement(self):
        report = _rest_report([("REST", 539)])
        (finding,) = findings(report, RULE_DAILY_REST)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"]) == (539, 540)
        assert (finding["start"], finding["end"]) == ("2024-01-01T06:00Z", "2024-01-02T06:00Z")

    def test_split_three_plus_nine_is_regular(self):
        blocks = LEAD + duty(240) + [("REST", 180)] + duty(240) + [("REST", 540)] + duty(240) \
            + [("REST", 3000)]
        report = analyse_days(make_days(blocks))
        assert findings(report, RULE_DAILY_REST) == []
        assert _reduced(report) == 0

    def test_split_with_a_first_part_under_three_hours_is_reduced(self):
        blocks = LEAD + duty(240) + [("REST", 179)] + duty(240) + [("REST", 540)] + duty(240) \
            + [("REST", 3000)]
        assert _reduced(analyse_days(make_days(blocks))) == 1

    def test_only_the_portion_inside_24_hours_counts(self):
        # Duty 06:00 → 20:30, then 11 h of rest of which 9h30 fall before 06:00.
        blocks = LEAD + duty(540, extra_work=240) + [("REST", 660)] + duty(240) + [("REST", 3000)]
        report = analyse_days(make_days(blocks))
        assert findings(report, RULE_DAILY_REST) == []
        assert _reduced(report) == 1

    def test_three_reduced_rests_are_allowed(self):
        blocks = LEAD + cycle(540, 540) * 3 + duty(240) + [("REST", 3000)]
        report = analyse_days(make_days(blocks))
        assert _reduced(report) == 3
        assert findings(report, RULE_REDUCED_REST_COUNT) == []

    def test_fourth_reduced_rest_is_an_infringement(self):
        blocks = LEAD + cycle(540, 540) * 4 + duty(240) + [("REST", 3000)]
        report = analyse_days(make_days(blocks))
        (finding,) = findings(report, RULE_REDUCED_REST_COUNT)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"], finding["unit"]) == (4, 3, "count")

    def test_weekly_rest_resets_the_reduced_count(self):
        blocks = LEAD + cycle(540, 540) * 2 + cycle(540, 24 * 60) + cycle(540, 540) * 2 \
            + duty(240) + [("REST", 3000)]
        report = analyse_days(make_days(blocks))
        assert _reduced(report) == 4
        assert findings(report, RULE_REDUCED_REST_COUNT) == []

    def test_unknown_gap_instead_of_rest_is_indeterminate(self):
        report = _rest_report([("REST", 300), ("UNKNOWN", 360)])
        assert statuses(report, RULE_DAILY_REST) == [STATUS_INDETERMINATE]
        assert report["summary"]["infringements"] == 0

    def test_missing_day_is_indeterminate_never_an_infringement(self):
        days = make_days(LEAD + day_cycle(540) * 4 + [("REST", 3000)])
        del days[2]
        report = analyse_days(days)
        assert report["summary"]["infringements"] == 0
        assert STATUS_INDETERMINATE in statuses(report, RULE_DAILY_REST)

    def test_open_window_at_the_end_of_the_data_is_not_judged(self):
        report = analyse_days(make_days(LEAD + duty(540), recorded_until="15:45"))
        assert report["findings"] == []

    def test_window_without_rest_judged_when_data_covers_it(self):
        report = analyse_days(make_days(LEAD + duty(540, extra_work=24 * 60) + [("REST", 3000)]))
        assert statuses(report, RULE_DAILY_REST) == [STATUS_INFRINGEMENT]


# ── Art. 8(6): weekly rest ───────────────────────────────────────────────────
class TestWeeklyRest:
    def _interval(self, extra_work):
        # Weekly rest ends Mon 06:00 (the lead). Five 24 h days, then a 24 h
        # duty that ends exactly 144 h later, then a 45 h weekly rest.
        last = duty(540)
        last = last + [("WORK", 1440 - length(last) + extra_work)]
        return analyse_days(make_days(LEAD + day_cycle(540) * 5 + last + [("REST", 45 * 60), ("WORK", 60)]))

    def test_weekly_rest_starting_after_exactly_144_hours_is_compliant(self):
        assert findings(self._interval(0), RULE_WEEKLY_REST_START) == []

    def test_weekly_rest_starting_later_is_an_infringement(self):
        (finding,) = findings(self._interval(1), RULE_WEEKLY_REST_START)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["measured"], finding["limit"]) == (8641, 8640)

    def test_no_weekly_rest_at_all_is_an_infringement(self):
        report = analyse_days(make_days(LEAD + day_cycle(480) * 8, pad="WORK"))
        assert STATUS_INFRINGEMENT in statuses(report, RULE_WEEKLY_REST_START)

    def _fortnight(self, first, second):
        # Data from Sun 31 Dec: weeks of 1 and 8 January are fully covered.
        blocks = day_cycle(540) * 5 + duty(540) + [("REST", first)] \
            + day_cycle(540) * 5 + duty(540) + [("REST", second)] \
            + day_cycle(540) * 3 + duty(240)
        return analyse_days(make_days(blocks, start=SUNDAY_BEFORE, pad="WORK"))

    def test_regular_and_reduced_weekly_rest_is_compliant(self):
        report = self._fortnight(45 * 60, 24 * 60)
        assert findings(report, RULE_WEEKLY_REST_TWO_WEEKS) == []
        assert report["summary"]["by_rule"][RULE_WEEKLY_REST_TWO_WEEKS]["assessed"] == 1

    def test_two_reduced_weekly_rests_is_an_infringement(self):
        report = self._fortnight(24 * 60, 24 * 60)
        (finding,) = findings(report, RULE_WEEKLY_REST_TWO_WEEKS)
        assert finding["status"] == STATUS_INFRINGEMENT
        assert (finding["start"], finding["end"]) == ("2024-01-01T00:00Z", "2024-01-15T00:00Z")

    def test_a_rest_under_24_hours_is_no_weekly_rest(self):
        report = self._fortnight(45 * 60, 24 * 60 - 1)
        (finding,) = findings(report, RULE_WEEKLY_REST_TWO_WEEKS)
        assert finding["measured"] == 1

    def test_a_rest_spanning_a_whole_week_satisfies_the_two_weeks(self):
        # Leave from Fri 5 to Mon 15 January: one rest, but no week to fill.
        blocks = day_cycle(540) * 5 + duty(540) + [("REST", 10 * 1440)] + day_cycle(540) * 2 + duty(240)
        report = analyse_days(make_days(blocks, start=SUNDAY_BEFORE, pad="WORK"))
        assert report["summary"]["by_rule"][RULE_WEEKLY_REST_TWO_WEEKS]["assessed"] == 1
        assert findings(report, RULE_WEEKLY_REST_TWO_WEEKS) == []

    def test_unknown_weekend_is_indeterminate(self):
        blocks = day_cycle(540) * 5 + duty(540) + [("REST", 45 * 60)] \
            + day_cycle(540) * 5 + duty(540) + [("UNKNOWN", 30 * 60)] \
            + day_cycle(540) * 3 + duty(240)
        report = analyse_days(make_days(blocks, start=SUNDAY_BEFORE, pad="WORK"))
        assert statuses(report, RULE_WEEKLY_REST_TWO_WEEKS) == [STATUS_INDETERMINATE]
        assert STATUS_INFRINGEMENT not in statuses(report, RULE_WEEKLY_REST_START)
        # Read as not rest, the gap also leaves a day without rest; never claimed.
        # (Driving totals are the exception: recorded driving is never inferred,
        # so the 90 h this scenario drives does not depend on the gap.)
        assert all(f["status"] == STATUS_INDETERMINATE for f in report["findings"]
                   if f["unrecorded_min"] and f["rule"] != RULE_FORTNIGHTLY_DRIVING)


# ── Report shape ─────────────────────────────────────────────────────────────
class TestReport:
    BLOCKS = LEAD + [("DRIVE", 300)] + [("REST", 60)] + day_cycle(601) + [("UNKNOWN", 600)] + duty(300)

    def test_every_finding_is_marked_indicative(self):
        report = analyse_days(make_days(self.BLOCKS))
        assert report["findings"]
        for finding in report["findings"]:
            assert finding["indicative"] is True
            assert finding["explanation"].endswith(FINDING_NOTICE)
            assert set(finding) >= {"rule", "article", "status", "start", "end", "measured", "limit",
                                    "unit", "explanation"}
        assert "not a legal determination" in report["disclaimer"]
        assert report["not_modelled"]

    def test_summary_counts_match_the_findings(self):
        report = analyse_days(make_days(self.BLOCKS))
        summary = report["summary"]
        assert summary["infringements"] == len(findings(report, status=STATUS_INFRINGEMENT))
        assert summary["indeterminate"] == len(findings(report, status=STATUS_INDETERMINATE))
        assert sum(item["infringement"] + item["indeterminate"] for item in summary["by_rule"].values()) \
            == len(report["findings"])

    def test_deterministic_and_json_serialisable(self):
        days = make_days(self.BLOCKS)
        first = analyse_days(days)
        assert first == analyse_days(json.loads(json.dumps(days)))
        json.dumps(first)

    def test_vehicle_unit_is_not_analysed(self):
        report = analyse_result({"metadata": {"is_vu": True}, "activities": make_days(self.BLOCKS)})
        assert report["status"] == "not_applicable"
        assert report["findings"] == []

    def test_card_result_is_analysed(self):
        report = analyse_result({"metadata": {"is_vu": False}, "activities": make_days(self.BLOCKS)})
        assert report["status"] == "analysed"

    def test_text_report(self):
        lines = format_report(analyse_days(make_days(self.BLOCKS)))
        text = "\n".join(lines)
        assert "561/2006" in text and "[INFRINGEMENT]" in text and "Not modelled:" in text
        vu = "\n".join(format_report(analyse_result({"metadata": {"is_vu": True}})))
        assert "Vehicle-unit download" in vu
