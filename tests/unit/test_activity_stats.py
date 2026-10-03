"""Tests for core.utils.activity_stats (shared slot-aware activity totals).

The naive per-event implementations in app/cli.py and app/export.py double
counted crew days because they interleaved both card slots; the shared
function groups per slot, sums DRIVE/WORK, keeps REST/AVAILABLE at the max.
"""
import pytest

from core.utils.activity_stats import compute_activity_totals, parse_time


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
