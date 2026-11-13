"""The calibration due-date check must not vanish on an offset-less date.

``datetime.fromisoformat("2025-01-21")`` is naive; subtracting it from an aware
``now`` raised ``TypeError``, which the overview swallowed, so the "calibration
expired / due soon" marker silently disappeared.
"""
from datetime import datetime, timezone

import pytest

pytest.importorskip("tkinter")

from app.gui import _calibration_days_left  # noqa: E402

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("value, expected", [
    ("2026-01-11T00:00:00+00:00", 10),
    ("2026-01-11T00:00:00Z", 10),
    ("2026-01-11", 10),                      # naive ISO: used to raise TypeError
    ("2026-01-11T00:00:00", 10),
    ("11/01/2026", 10),                       # G1 form
    ("11/01/2026 09:04", 10),
    ("2025-12-22", -10),
    (datetime(2026, 1, 11), 10),              # naive datetime object
    (datetime(2026, 1, 11, tzinfo=timezone.utc), 10),
])
def test_days_left(value, expected):
    assert _calibration_days_left(value, now=NOW) == expected


@pytest.mark.parametrize("value", [None, "", "not a date", 12345, {"x": 1}])
def test_unreadable_dates_return_none(value):
    assert _calibration_days_left(value, now=NOW) is None
