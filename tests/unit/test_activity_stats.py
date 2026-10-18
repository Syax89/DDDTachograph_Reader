"""Tests for core.utils.activity_stats (shared slot-aware activity totals).

The naive per-event implementations in app/cli.py and app/export.py double
counted crew days because they interleaved both card slots; the shared
function groups per slot, sums DRIVE/WORK, keeps REST/AVAILABLE at the max.
"""
import pytest

from core.utils.activity_stats import (
    CONTINUOUS_DRIVE_LIMIT_MIN,
    DAILY_DRIVE_LIMIT_MIN,
    QUALIFYING_BREAK_MIN,
    RULE_CONTINUOUS_DRIVING,
    RULE_DAILY_DRIVING,
    DrivingRuleBreach,
    DrivingRuleReport,
    compute_activity_totals,
    evaluate_driving_rules,
    parse_time,
)


CREW_DAY = [
    # First slot:  DRIVE 00-08 (480) · REST 08-12 (240) · WORK 12-16 (240) · AVAILABLE 16-24 (480)
    {"activity": "DRIVE", "time": "00:00", "slot": "First"},
    # Second slot: REST 00-06 (360) · DRIVE 06-10 (240) · WORK 10-14 (240) · AVAILABLE 14-24 (600)
    {"activity": "REST", "time": "00:00", "slot": "Second"},
    {"activity": "DRIVE", "time": "06:00", "slot": "Second"},
    {"activity": "REST", "time": "08:00", "slot": "First"},
    {"activity": "WORK", "time": "10:00", "slot": "Second"},
    {"activity": "WORK", "time": "12:00", "slot": "First"},
    {"activity": "AVAILABLE", "time": "14:00", "slot": "Second"},
    {"activity": "AVAILABLE", "time": "16:00", "slot": "First"},
]

EXPECTED_CREW = {"DRIVE": 720, "WORK": 480, "REST": 360, "AVAILABLE": 600, "UNKNOWN": 0}


def test_crew_day_slots_are_grouped_then_summed_or_maxed():
    """Two interleaved slots: DRIVE/WORK summed, REST/AVAILABLE kept at max."""
    assert compute_activity_totals(CREW_DAY) == EXPECTED_CREW


def test_unsorted_input_is_order_independent():
    """Per-slot sort must make results identical regardless of input order."""
    forward = compute_activity_totals(CREW_DAY)
    shuffled = compute_activity_totals(list(reversed(CREW_DAY)))
    interleaved = compute_activity_totals(CREW_DAY[::2] + CREW_DAY[1::2])
    assert shuffled == EXPECTED_CREW
    assert interleaved == EXPECTED_CREW
    assert forward == shuffled == interleaved


def test_non_dict_entries_are_skipped_without_crash():
    """A stray non-dict element must not crash (regression for the CLI bug)."""
    polluted = [
        "junk",
        None,
        42,
        {"activity": "DRIVE", "time": "not-a-time"},  # unusable time -> skipped
    ] + CREW_DAY
    assert compute_activity_totals(polluted) == EXPECTED_CREW


def test_unrecognised_activity_is_bucketed_as_unknown_not_dropped():
    """An activity label outside the recognised kinds must not vanish.

    Its minutes are kept in an UNKNOWN bucket so a day whose activity code is
    unrecognised still totals its real span instead of silently shrinking.
    """
    day = [
        {"activity": "DRIVE", "time": "08:00"},
        {"activity": "MYSTERY", "time": "10:00"},
        {"activity": "REST", "time": "12:00"},
    ]
    # 00:00-08:00 carries no leading 00:00 status entry, so it is UNKNOWN (480);
    # the MYSTERY label adds 10:00-12:00 (120). Both stay in the day.
    assert compute_activity_totals(day) == {
        "DRIVE": 120, "WORK": 0, "REST": 720, "AVAILABLE": 0, "UNKNOWN": 600,
    }

    # UNKNOWN is a period: kept at the max across slots, not summed.
    crew = [
        {"activity": "MYSTERY", "time": "00:00", "slot": "First"},
        {"activity": "REST",    "time": "08:00", "slot": "First"},
        {"activity": "MYSTERY", "time": "00:00", "slot": "Second"},
        {"activity": "REST",    "time": "04:00", "slot": "Second"},
    ]
    assert compute_activity_totals(crew)["UNKNOWN"] == 480  # max(480, 240)


def test_empty_changes_return_all_zero_totals():
    assert compute_activity_totals([]) == {
        "DRIVE": 0, "WORK": 0, "REST": 0, "AVAILABLE": 0, "UNKNOWN": 0,
    }


def test_single_slot_day_spans_the_whole_day():
    """One slot only: every hour of the day is attributed, none vanishes.

    The first recorded change is at 08:00 with no leading 00:00 status entry
    (Annex 1C §2.170 requires one), so 00:00-08:00 is UNKNOWN; the rest follows
    the recorded changes. The day spans a full 24h instead of silently
    shrinking to 16h (REPORT-OVERNIGHT-GAP / XF-F2).
    """
    single = [
        {"activity": "DRIVE", "time": "08:00"},
        {"activity": "WORK", "time": "12:00"},
        {"activity": "REST", "time": "14:00"},
    ]
    assert compute_activity_totals(single) == {
        "DRIVE": 240, "WORK": 120, "REST": 600, "AVAILABLE": 0, "UNKNOWN": 480,
    }


@pytest.mark.parametrize("time_str,expected", [
    ("00:00", 0),
    ("08:00", 28800),
    ("23:59", 86340),
    ("24:00", 86400),
])
def test_parse_time_valid(time_str, expected):
    assert parse_time(time_str) == expected


@pytest.mark.parametrize("bad", ["abc", "", "8:00:00", "08", None, 123,
                                  "25:00", "08:75", "24:01", "-1:00", "12:-5"])
def test_parse_time_invalid_returns_none(bad):
    assert parse_time(bad) is None


# ── Driving-time rules, Reg. (EC) 561/2006 art. 6(1) and art. 7 ────────────
#
# Only two rules are modelled: daily driving above 9 h (art. 6(1)) and more
# than 4 h 30 min of continuous driving without a qualifying break (art. 7).
# These tests pin the boundary of each limit, the 45-minute break model, the
# slot semantics (both limits are per driver) and the UNKNOWN-period choice
# documented in ``evaluate_driving_rules``.


def _day(*segments, slot="First"):
    """Build one day's ``changes`` from ``(activity, "HH:MM")`` segment starts."""
    return [{"activity": activity, "time": start, "slot": slot}
            for activity, start in segments]


def _rules_of(*segments, slot="First"):
    return evaluate_driving_rules(_day(*segments, slot=slot))


def test_limits_are_the_regulation_numbers():
    """Art. 6(1) nine hours; art. 7 four and a half hours / a 45 min break."""
    assert DAILY_DRIVE_LIMIT_MIN == 9 * 60
    assert CONTINUOUS_DRIVE_LIMIT_MIN == 4 * 60 + 30
    assert QUALIFYING_BREAK_MIN == 45


def test_clean_day_is_not_flagged():
    """A day well inside both limits: 8 h of driving in two 4 h stretches."""
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:00"),
                       ("DRIVE", "05:00"), ("WORK", "09:00"))
    assert report.drive_min == 480
    assert report.longest_stretch_min == 240
    assert report.breaches == ()
    assert report.flagged is False


def test_exactly_the_daily_limit_is_not_a_breach():
    """Art. 6(1) forbids *more than* nine hours: 9 h 00 min is legal."""
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:30"),
                       ("DRIVE", "05:15"), ("REST", "09:45"))
    assert report.drive_min == DAILY_DRIVE_LIMIT_MIN == 540
    assert report.longest_stretch_min == 270
    assert report.breaches == ()


def test_one_minute_over_the_daily_limit_is_a_breach():
    """9 h 01 min of driving, in stretches short enough to keep art. 7 happy."""
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:00"),
                       ("DRIVE", "04:45"), ("REST", "08:45"),
                       ("DRIVE", "09:30"), ("REST", "10:31"))
    assert report.drive_min == 541
    assert report.longest_stretch_min == 240
    assert report.breaches == (DrivingRuleBreach(
        rule=RULE_DAILY_DRIVING, slot="First",
        measured_min=541, limit_min=DAILY_DRIVE_LIMIT_MIN),)


def test_continuous_drive_just_under_the_limit_is_clean():
    """Art. 7 is also "more than": 4 h 29 min without a break is legal."""
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:29"))
    assert report.longest_stretch_min == 269
    assert report.breaches == ()


def test_continuous_drive_over_the_limit_flags_continuous_driving():
    """4 h 31 min in one stretch: only art. 7 is broken (4 h 31 min < 9 h)."""
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:31"))
    assert report.drive_min == 271
    assert report.longest_stretch_min == 271
    assert report.breaches == (DrivingRuleBreach(
        rule=RULE_CONTINUOUS_DRIVING, slot="First",
        measured_min=271, limit_min=CONTINUOUS_DRIVE_LIMIT_MIN),)


def test_a_45_minute_break_resets_the_stretch():
    """Art. 7: 45 min of non-driving ends the continuous period."""
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:00"),
                       ("DRIVE", "04:45"), ("REST", "08:45"))
    assert report.drive_min == 480
    assert report.longest_stretch_min == 240
    assert report.breaches == ()


def test_a_44_minute_break_does_not_reset_the_stretch():
    """One minute short of art. 7's break: the stretch keeps accumulating."""
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:00"),
                       ("DRIVE", "04:44"), ("REST", "09:00"))
    assert report.drive_min == 240 + 256
    assert report.longest_stretch_min == 240 + 256
    assert [b.rule for b in report.breaches] == [RULE_CONTINUOUS_DRIVING]


def test_work_and_availability_also_count_towards_the_break():
    """Art. 7 accepts "a break" *or* other work, so any non-DRIVE run counts.

    A rest of 20 min followed by 25 min of work is 45 uninterrupted
    non-driving minutes even though no single segment reaches 45.
    """
    report = _rules_of(("DRIVE", "00:00"), ("REST", "04:00"),
                       ("WORK", "04:20"), ("DRIVE", "04:45"),
                       ("AVAILABLE", "08:45"))
    assert report.longest_stretch_min == 240
    assert report.breaches == ()


def test_a_day_without_any_drive_is_clean():
    """Rest only (and an empty day): nothing to flag, nothing to measure."""
    rest_only = _rules_of(("REST", "00:00"), ("WORK", "12:00"))
    assert rest_only == DrivingRuleReport(drive_min=0, longest_stretch_min=0,
                                          breaches=())
    assert evaluate_driving_rules([]) == DrivingRuleReport(
        drive_min=0, longest_stretch_min=0, breaches=())


def test_card_not_inserted_is_neither_driving_nor_a_break():
    """The documented UNKNOWN choice: no driving time, no stretch reset.

    Driving 00:00→04:00, card out 04:00→05:00, driving 05:00→05:31. Treated as
    a break, the unknown hour would reset the stretch counter and hide the
    4 h 31 min, so the counter carries on across the gap instead (it does
    interrupt a break run — see test_unknown_time_cannot_complete_a_break).
    Annex 1C §2.1 note (2) only says the activity code is "not relevant", so
    the time is unmeasured, neither driving nor a break.
    """
    day = [
        {"activity": "DRIVE", "time": "00:00", "card_inserted": True},
        {"activity": "DRIVE", "time": "04:00", "card_inserted": False, "crew": False},
        {"activity": "DRIVE", "time": "05:00", "card_inserted": True},
        {"activity": "REST", "time": "05:31", "card_inserted": True},
    ]
    report = evaluate_driving_rules(day)
    assert report.drive_min == 271, "the unknown hour is not driving time"
    assert report.longest_stretch_min == 271
    assert [b.rule for b in report.breaches] == [RULE_CONTINUOUS_DRIVING]


def test_crew_day_is_judged_per_driver_not_on_the_sum():
    """Both limits are per driver: two 8 h drivers are clean, 15 h is not."""
    clean_crew = (_day(("DRIVE", "00:00"), ("REST", "04:00"),
                       ("DRIVE", "04:45"), ("REST", "08:45"), slot="First")
                  + _day(("DRIVE", "00:00"), ("REST", "04:00"),
                         ("DRIVE", "04:45"), ("REST", "08:45"), slot="Second"))
    report = evaluate_driving_rules(clean_crew)
    assert report.drive_min == 960, "the day's DRIVE stays the summed value"
    assert report.drive_min == compute_activity_totals(clean_crew)["DRIVE"]
    assert report.longest_stretch_min == 240
    assert report.breaches == (), "no single driver exceeded any limit"

    breaking_crew = (_day(("DRIVE", "00:00"), ("REST", "04:00"), slot="First")
                     + _day(("DRIVE", "00:00"), ("REST", "10:00"), slot="Second"))
    report = evaluate_driving_rules(breaking_crew)
    assert report.drive_min == 840
    assert report.longest_stretch_min == 600
    assert {(b.rule, b.slot) for b in report.breaches} == {
        (RULE_DAILY_DRIVING, "Second"), (RULE_CONTINUOUS_DRIVING, "Second")}
    assert all(b.slot == "Second" for b in report.breaches)


@pytest.mark.parametrize("segments", [
    (("DRIVE", "00:00"), ("REST", "04:00"), ("DRIVE", "05:00"), ("WORK", "09:00")),
    (("DRIVE", "00:00"), ("REST", "04:31")),
    (("REST", "00:00"), ("DRIVE", "06:00"), ("REST", "12:00")),
])
def test_drive_minutes_agree_with_the_dashboard_totals(segments):
    """One segmentation routine: the flag can never contradict the Drive cell."""
    day = _day(*segments)
    assert (evaluate_driving_rules(day).drive_min
            == compute_activity_totals(day)["DRIVE"])


def test_unusable_changes_are_skipped_without_crash():
    """Same guard as the totals: junk entries and bad times are ignored."""
    polluted = ["junk", None, {"activity": "DRIVE", "time": "bad"}] + _day(
        ("DRIVE", "00:00"), ("REST", "04:31"))
    report = evaluate_driving_rules(polluted)
    assert report.drive_min == 271
    assert report.flagged is True


def test_unknown_time_cannot_complete_a_break():
    """A card-out gap interrupts the break run instead of joining its halves.

    Driving, 30 min rest, an hour with the card out, 20 min work: 30 + 20 min
    of *known* non-driving is not the 45 uninterrupted minutes art. 7 wants, so
    the stretch keeps running and the extra driving is flagged.
    """
    day = [
        {"activity": "DRIVE", "time": "00:00", "card_inserted": True},
        {"activity": "REST", "time": "04:00", "card_inserted": True},
        {"activity": "REST", "time": "04:30", "card_inserted": False, "crew": False},
        {"activity": "WORK", "time": "05:30", "card_inserted": True},
        {"activity": "DRIVE", "time": "05:50", "card_inserted": True},
        {"activity": "REST", "time": "06:31", "card_inserted": True},
    ]
    report = evaluate_driving_rules(day)
    assert report.drive_min == 240 + 41
    assert report.longest_stretch_min == 240 + 41
    assert [b.rule for b in report.breaches] == [RULE_CONTINUOUS_DRIVING]
