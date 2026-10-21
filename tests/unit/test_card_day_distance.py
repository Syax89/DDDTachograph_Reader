"""A driver-card activity day carries its own distance, never an odometer.

CARD-DAY-DISTANCE: CardActivityDailyRecord (Annex 1B §2.24, tag 0x0504 and the
VU's 0x0206 copy) stores ``ActivityDayDistance`` — the kilometres driven that
day. The decoder published it as ``odometer_km``, the key every other surface
reads as an absolute odometer reading, so

  * the day-detail popup always showed 0 km for a card day (the tree only ever
    derived a distance from VU odometer deltas), and
  * the Daily-Activities dashboard differenced one day's distance against the
    next (205 km on the 14th, 58 km on the 15th → "79 km" on the 14th).
"""

import struct

from core.decoders.common import parse_cyclic_buffer_activities
from core.utils.report_format import build_monthly_activity_report, expand_activities


def _day(prev_len, day_ts, presence, distance, change_values):
    body = b"".join(struct.pack(">H", v) for v in change_values)
    rec_len = 12 + len(body)
    return (struct.pack(">HHI", prev_len, rec_len, day_ts)
            + struct.pack(">HH", presence, distance) + body)


REST = 0x0000            # activity 0 (rest) at 00:00
DRIVE_0800 = (3 << 11) | 480   # activity 3 (drive) at 08:00


def _buffer():
    day1 = _day(0, 1_600_000_000, 10, 120, [REST, DRIVE_0800])
    day2 = _day(len(day1), 1_600_086_400, 11, 205, [REST, DRIVE_0800])
    # 2-byte header + newest-record pointer (offset of day2 from the base) + days
    return b"\x00\x00" + struct.pack(">H", len(day1)) + day1 + day2


def test_card_activity_day_exposes_day_distance_not_an_odometer():
    results = {"activities": []}
    parse_cyclic_buffer_activities(_buffer(), results)

    days = {day["date"]: day for day in results["activities"]}
    first = days["13/09/2020"]
    assert first["day_distance_km"] == 120
    assert "odometer_km" not in first
    assert days["14/09/2020"]["day_distance_km"] == 205


def test_exports_show_the_day_distance_of_a_card_day():
    day = {"date": "14/11/2023", "day_distance_km": 205,
           "changes": [{"time": "00:00", "activity": "REST",
                        "slot": "First", "crew": False, "card_inserted": True}]}
    rows = expand_activities([day])
    assert rows[0]["Odometer km"] == "205"

    headers, month_rows = build_monthly_activity_report([day])
    km_column = headers.index("Odometer km")
    assert month_rows[0][km_column] == "205"


def test_vu_days_keep_their_odometer_reading_in_exports():
    day = {"date": "14/11/2023", "odometer_km": 250_000,
           "changes": [{"time": "00:00", "activity": "REST",
                        "slot": "First", "crew": False, "card_inserted": True}]}
    assert expand_activities([day])[0]["Odometer km"] == "250 000"
    headers, month_rows = build_monthly_activity_report([day])
    assert month_rows[0][headers.index("Odometer km")] == "250 000"


def test_gui_day_distance_uses_the_card_distance_and_vu_deltas():
    pytest = __import__("pytest")
    pytest.importorskip("tkinter")
    from app.gui import _attach_day_distance

    card_days = [{"date": "14/11/2023", "day_distance_km": 205, "changes": []},
                 {"date": "15/11/2023", "day_distance_km": 58, "changes": []}]
    distances = _attach_day_distance(card_days, is_vu=False)
    assert [day["_day_km"] for day in card_days] == [205, 58]
    assert distances[id(card_days[0])] == 205

    vu_days = [{"date": "14/11/2023", "odometer_km": 250_000, "changes": []},
               {"date": "15/11/2023", "odometer_km": 250_320, "changes": []}]
    _attach_day_distance(vu_days, is_vu=True)
    assert [day["_day_km"] for day in vu_days] == [0, 320]


# ── The day's record table must label the figure it shows ──────────────────

def _day_table_columns(data, days):
    """Return the columns/rows ``_populate_daily_activities`` hands to the day
    section (tree + sections mocked; no real file, no personal data)."""
    import pytest
    pytest.importorskip("tkinter")
    from unittest.mock import Mock

    from app.gui import TachoExplorer

    app = object.__new__(TachoExplorer)
    app._payloads = {}
    app.tree = Mock()
    app.tree.insert.return_value = "node"
    app._day_vehicles_info = Mock(return_value=[])
    app._add_activity_day = Mock(return_value="daynode")
    captured = {}

    def _section(_node, _title, cols, rows):
        captured["cols"] = cols
        captured["rows"] = rows

    app._add_section = _section
    app._populate_daily_activities("parent", data, days)
    return captured["cols"], captured["rows"]


def _one_change():
    return [{"time": "00:00", "activity": "REST", "slot": "First",
             "crew": False, "card_inserted": True}]


def test_gui_card_day_table_labels_the_day_distance_not_an_odometer():
    """A card day has no odometer reading: its table must not say "Odometer".

    Annex 1B ``ActivityDayDistance`` is the day's driven kilometres; heading it
    "Odometer km" re-creates exactly the misreading the key split removed.
    """
    cols, rows = _day_table_columns(
        {"metadata": {"is_vu": False}, "driver": {"firstname": "A", "surname": "B"}},
        [{"date": "04/12/2020", "day_distance_km": 487, "changes": _one_change()}])

    assert cols[-1] == "Distance km"
    assert rows[0][-1] == "487"
    assert "Odometer km" not in cols


def test_gui_vu_day_table_keeps_the_odometer_header():
    """A VU day carries a real odometer reading; its header stays as it was."""
    cols, rows = _day_table_columns(
        {"metadata": {"is_vu": True}},
        [{"date": "04/12/2020", "odometer_km": 250_000, "changes": _one_change()}])

    assert cols[-1] == "Odometer km"
    assert rows[0][-1] == "250 000"
