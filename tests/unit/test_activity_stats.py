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

EXPECTED_CREW = {"DRIVE": 720, "WORK": 480, "REST": 360, "AVAILABLE": 600}


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
        {"activity": "DRIVE", "time": "not-a-time"},  # unparsable -> skipped
        {"activity": "UNKNOWN", "time": "10:00"},     # unknown activity -> skipped
    ] + CREW_DAY
    assert compute_activity_totals(polluted) == EXPECTED_CREW


def test_empty_changes_return_all_zero_totals():
    assert compute_activity_totals([]) == {
        "DRIVE": 0, "WORK": 0, "REST": 0, "AVAILABLE": 0,
    }


def test_single_slot_day_matches_naive_expectation():
    """One slot only: same result a correct single-crew computation gives."""
    single = [
        {"activity": "DRIVE", "time": "08:00"},
        {"activity": "WORK", "time": "12:00"},
        {"activity": "REST", "time": "14:00"},
    ]
    assert compute_activity_totals(single) == {
        "DRIVE": 240, "WORK": 120, "REST": 600, "AVAILABLE": 0,
    }


@pytest.mark.parametrize("time_str,expected", [
    ("00:00", 0),
    ("08:00", 28800),
    ("23:59", 86340),
    ("24:00", 86400),
])
def test_parse_time_valid(time_str, expected):
    assert parse_time(time_str) == expected


@pytest.mark.parametrize("bad", ["abc", "", "8:00:00", "08", None, 123])
def test_parse_time_invalid_returns_none(bad):
    assert parse_time(bad) is None
