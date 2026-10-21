"""Daily activity blocks are still de-duplicated *structurally*, newest first.

``_dedup_and_sort_activities`` used to build the recursive canonical form of every
day it saw, activity change by activity change — 7.15 ms of a 23.6 ms parse of a
real VU download (30 %). The cheap fingerprint that replaced it on the hot path is
only a bucket: a second day landing in the same bucket is still compared
canonically, so what counts as a duplicate is unchanged, the first occurrence still
wins and the order is unchanged. These tests pin the semantics.
"""
from app.engine import TachoParser


def _parser(*days):
    parser = TachoParser("no-such-file.ddd")
    parser.results = {"activities": list(days)}
    return parser


def _day(date, changes, odometer=1000):
    return {"date": date, "odometer_km": odometer,
            "changes": [{"minute": minute, "activity": "DRIVING"}
                        for minute in changes]}


def test_a_structurally_identical_day_is_dropped_and_the_first_wins():
    first = _day("02/01/2024", [0, 60], odometer=1000)
    duplicate = _day("02/01/2024", [0, 60], odometer=1000)
    other = _day("01/01/2024", [0, 60], odometer=999)
    parser = _parser(first, duplicate, other)
    parser._dedup_and_sort_activities()
    assert parser.results["activities"] == [first, other]     # newest first


def test_a_day_that_differs_in_one_change_is_kept():
    first = _day("02/01/2024", [0, 60])
    near_duplicate = _day("02/01/2024", [0, 61])
    parser = _parser(first, near_duplicate)
    parser._dedup_and_sort_activities()
    assert len(parser.results["activities"]) == 2


def test_a_day_that_differs_in_a_scalar_is_kept():
    first = _day("02/01/2024", [0, 60], odometer=1000)
    same_changes_other_odometer = _day("02/01/2024", [0, 60], odometer=1001)
    parser = _parser(first, same_changes_other_odometer)
    parser._dedup_and_sort_activities()
    assert len(parser.results["activities"]) == 2


def test_an_empty_change_list_still_deduplicates():
    first = _day("02/01/2024", [])
    duplicate = _day("02/01/2024", [])
    parser = _parser(first, duplicate)
    parser._dedup_and_sort_activities()
    assert parser.results["activities"] == [first]


def test_a_date_that_cannot_be_parsed_sorts_last():
    dated = _day("02/01/2024", [0])
    undated = {"date": "N/A", "odometer_km": None, "changes": []}
    parser = _parser(undated, dated)
    parser._dedup_and_sort_activities()
    assert parser.results["activities"] == [dated, undated]
