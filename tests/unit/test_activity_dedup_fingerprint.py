"""Daily activity blocks are still de-duplicated *structurally*, newest first.

``_dedup_and_sort_activities`` used to build the recursive canonical form of every
day it saw, activity change by activity change — 7.15 ms of a 23.6 ms parse of a
real VU download (30 %). The cheap fingerprint that replaced it on the hot path is
only a bucket: a second day landing in the same bucket is still compared
canonically, so what counts as a duplicate is unchanged, the first occurrence still
wins and the order is unchanged.

These tests pin the *semantics* the dedup had before the optimisation as well as
after it, so most of them cannot fail if the optimisation alone is reverted (a
pure perf change keeps the behaviour by definition — the corpus diff is its real
guard). The last group is different: it hands the dedup two days that share a
fingerprint bucket but differ only inside a nested change, which only the
canonical comparison can tell apart, so a fingerprint-only dedup fails them.
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


# ── The canonical form must stay type-preserving ─────────────────────────────
#
# ``json.dumps`` alone is not: it renders a tuple and a list identically and
# folds an int dict key onto its string form. Two days that differ only in that
# way were called the same day and one of them was dropped — a duplicate test
# that silently loses a record.

def _day_with(date, changes):
    return {"date": date, "changes": changes}


def test_a_tuple_and_a_list_inside_a_day_are_different_days():
    as_tuple = _day_with("02/01/2024", [("DRIVE", 60)])
    as_list = _day_with("02/01/2024", [["DRIVE", 60]])
    parser = _parser(as_tuple, as_list)
    parser._dedup_and_sort_activities()
    assert len(parser.results["activities"]) == 2


def test_an_integer_and_a_string_key_are_different_days():
    int_keyed = _day_with("02/01/2024", [{1: "DRIVE"}])
    str_keyed = _day_with("02/01/2024", [{"1": "DRIVE"}])
    parser = _parser(int_keyed, str_keyed)
    parser._dedup_and_sort_activities()
    assert len(parser.results["activities"]) == 2


def test_an_integer_and_its_decimal_string_are_different_days():
    as_int = _day_with("02/01/2024", [{"odometer": 1000}])
    as_text = _day_with("02/01/2024", [{"odometer": "1000"}])
    parser = _parser(as_int, as_text)
    parser._dedup_and_sort_activities()
    assert len(parser.results["activities"]) == 2


def test_key_order_still_does_not_make_a_duplicate():
    """The canonical form stays key-order independent (it sorted keys before)."""
    first = {"date": "02/01/2024", "changes": [{"a": 1, "b": 2}]}
    second = {"changes": [{"b": 2, "a": 1}], "date": "02/01/2024"}
    parser = _parser(first, second)
    parser._dedup_and_sort_activities()
    assert parser.results["activities"] == [first]


def test_an_identical_day_stays_a_duplicate_through_the_type_shape():
    """Same types, same values, different object: still one day."""
    first = _day_with("02/01/2024", [("DRIVE", 60)])
    duplicate = _day_with("02/01/2024", [("DRIVE", 60)])
    parser = _parser(first, duplicate)
    parser._dedup_and_sort_activities()
    assert parser.results["activities"] == [first]


# ── Inside one fingerprint bucket ────────────────────────────────────────────
#
# The bucket key is the record's scalar fields plus the *lengths* of its
# containers, so two days with the same date and the same number of activity
# changes always land in the same bucket whatever those changes say. Only the
# canonical comparison can tell them apart — a dedup that trusted the
# fingerprint alone would drop the second day and lose a record.

def _two_change_day(date, second_activity):
    return {"date": date,
            "changes": [{"minute": 0, "activity": "DRIVING"},
                        {"minute": 60, "activity": second_activity}]}


def test_two_days_in_one_bucket_that_differ_nested_are_both_kept():
    first = _two_change_day("02/01/2024", "REST")
    # Same scalars (the date), same container lengths (two changes): the
    # fingerprint is identical, the nested change is not.
    same_bucket_other_change = _two_change_day("02/01/2024", "BREAK")
    parser = _parser(first, same_bucket_other_change)
    parser._dedup_and_sort_activities()
    assert len(parser.results["activities"]) == 2
    assert parser.results["activities"][0] is first
    assert parser.results["activities"][1] is same_bucket_other_change


def test_a_duplicate_in_the_same_bucket_is_still_dropped():
    """The bucket alone never decides: a canonical twin inside it is dropped."""
    first = _two_change_day("02/01/2024", "REST")
    duplicate = _two_change_day("02/01/2024", "REST")
    third = _two_change_day("02/01/2024", "BREAK")
    parser = _parser(first, duplicate, third)
    parser._dedup_and_sort_activities()
    assert parser.results["activities"] == [first, third]


def test_a_nested_tuple_and_list_inside_one_bucket_are_both_kept():
    """The same bucket rule under the type-shape distinction."""
    as_tuple = {"date": "02/01/2024", "changes": [("DRIVE", 60), ("REST", 30)]}
    as_list = {"date": "02/01/2024", "changes": [["DRIVE", 60], ("REST", 30)]}
    parser = _parser(as_tuple, as_list)
    parser._dedup_and_sort_activities()
    assert len(parser.results["activities"]) == 2
