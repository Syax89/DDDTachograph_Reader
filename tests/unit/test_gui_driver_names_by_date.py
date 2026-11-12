"""Per-day driver names of the VU Daily-Activities dashboard.

The insertion→withdrawal walk is clipped to the days that carry activity
changes: the decoders accept withdrawal times up to 2100, and one corrupt
VuCardIWRecord used to make ~36 000 day iterations on the Tk thread.
"""
import time

import pytest

pytest.importorskip("tkinter")

from app.gui import _driver_names_by_date  # noqa: E402


def _day(date, *changes):
    return {"date": date, "changes": [
        {"time": t, "slot": slot, "card_inserted": True, "activity": "WORK"}
        for t, slot in changes]}


ACTIVITIES = [
    _day("10/07/2025", ("06:01", "First"), ("06:05", "Second")),
    _day("11/07/2025", ("00:00", "First")),
    _day("12/07/2025", ("00:00", "Second")),
]


def _iw(first, surname, ins, wit):
    return {"holder_first_names": first, "holder_surname": surname,
            "insertion_time": ins, "withdrawal_time": wit}


def test_drivers_are_attached_to_the_days_of_their_slot():
    iw = [_iw("A", "One", "2025-07-10T06:00:00", "2025-07-11T18:00:00"),
          _iw("B", "Two", "2025-07-10T06:05:00", "2025-07-12T18:00:00")]
    first = _driver_names_by_date(ACTIVITIES, iw, "First")
    second = _driver_names_by_date(ACTIVITIES, iw, "Second")
    assert first == {"2025-07-10": {"A One"}, "2025-07-11": {"A One", "B Two"}}
    assert second == {"2025-07-10": {"B Two"}, "2025-07-12": {"B Two"}}


def test_missing_withdrawal_covers_the_insertion_day_only():
    iw = [_iw("A", "One", "2025-07-10T06:00:00", "")]
    assert _driver_names_by_date(ACTIVITIES, iw, "First") == {"2025-07-10": {"A One"}}


def test_corrupt_far_future_withdrawal_does_not_freeze():
    iw = [_iw("A", "One", "1990-01-01T00:00:00", "2100-12-31T23:59:59")] * 50
    started = time.perf_counter()
    result = _driver_names_by_date(ACTIVITIES, iw, "First")
    assert time.perf_counter() - started < 1.0
    assert set(result) == {"2025-07-10", "2025-07-11"}


def test_no_card_insertions_means_no_names():
    iw = [_iw("A", "One", "2025-07-10T06:00:00", "2100-01-01T00:00:00")]
    assert _driver_names_by_date([{"date": "10/07/2025", "changes": []}], iw, "First") == {}
