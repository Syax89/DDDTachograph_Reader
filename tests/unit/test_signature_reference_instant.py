"""Certificate dates are judged at the latest instant the file records.

VuDownloadActivityData ``downloading_time`` and EF Card_Download hold the
*previous* download (seen on real files), so ``_signature_timestamp`` used to
judge certificates days or months before the data was actually recorded. The
reference is now the latest recorded instant: the last activity day's cut, the
VU's ``max_downloadable_time``, with the download-time fields as a lower bound.
"""
from datetime import datetime, timezone

from app.engine import TachoParser


def _parser(results, is_vu=False):
    parser = TachoParser("/nonexistent/reference-instant.ddd")
    parser.results = results
    parser.is_vu = is_vu
    return parser


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _day(date, *times, recorded_until=None):
    day = {"date": date, "changes": [{"time": t, "activity": "DRIVE"} for t in times]}
    if recorded_until:
        day["recorded_until"] = recorded_until
    return day


def test_latest_activity_day_beats_the_previous_download_time():
    parser = _parser({
        "card_downloads": [{"download_time": "2025-03-06T11:39:10Z"}],
        "activities": [_day("15/07/2025", "00:00", "15:59"), _day("14/07/2025", "08:00")],
    })
    assert parser._signature_timestamp() == _utc(2025, 7, 15, 15, 59)


def test_recorded_until_is_preferred_over_the_last_change():
    parser = _parser({"activities": [_day("15/07/2025", "10:00", recorded_until="18:49")]})
    assert parser._signature_timestamp() == _utc(2025, 7, 15, 18, 49)


def test_vu_max_downloadable_time_counts():
    parser = _parser({
        "download_activities": [{"downloading_time": "2025-06-29T18:24:07Z"}],
        "downloadable_periods": [{"max_downloadable_time": "2025-07-02T18:23:00Z"}],
        "activities": [_day("01/07/2025", "09:00")],
    }, is_vu=True)
    assert parser._signature_timestamp() == _utc(2025, 7, 2, 18, 23)


def test_download_time_stays_a_lower_bound():
    parser = _parser({
        "download_activities": [{"downloading_time": "2025-08-01T10:00:00Z"}],
        "activities": [_day("15/07/2025", "10:00")],
    }, is_vu=True)
    assert parser._signature_timestamp() == _utc(2025, 8, 1, 10, 0)


def test_future_corrupt_dates_are_ignored():
    parser = _parser({
        "card_downloads": [{"download_time": "2025-03-06T11:39:10Z"}],
        "activities": [_day("01/01/2099", "10:00")],
    })
    assert parser._signature_timestamp() == _utc(2025, 3, 6, 11, 39, 10)


def test_undated_file_is_still_not_judged():
    parser = _parser({"activities": [{"date": "garbage"}], "card_downloads": [{}]})
    assert parser._signature_timestamp() is None
    assert _parser({})._signature_timestamp() is None
