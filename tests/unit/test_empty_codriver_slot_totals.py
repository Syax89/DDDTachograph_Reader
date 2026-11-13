"""An empty co-driver slot must not turn every VU day into "Unknown 24:00".

A single-manned vehicle unit records the second slot all day with no card
inserted. Its 24h of card-absent UNKNOWN won the max-across-slots rule, so every
day read Unknown 24:00 and totalled up to 36h+ although one driver was on board.
"""
from core.utils.activity_stats import compute_activity_totals


def _ch(time, activity, slot, inserted):
    return {"time": time, "activity": activity, "slot": slot,
            "crew": False, "card_inserted": inserted}


def _single_driver_vu_day():
    return [
        _ch("00:00", "REST", "First", False),      # card not inserted yet
        _ch("06:00", "WORK", "First", True),
        _ch("06:30", "DRIVE", "First", True),
        _ch("14:30", "REST", "First", True),
        _ch("16:00", "REST", "First", False),      # card withdrawn
        _ch("00:00", "REST", "Second", False),     # empty co-driver slot
        _ch("06:30", "AVAILABLE", "Second", False),
    ]


def test_empty_codriver_slot_is_left_out():
    totals = compute_activity_totals(_single_driver_vu_day())
    assert totals == {"DRIVE": 480, "WORK": 30, "REST": 90,
                      "AVAILABLE": 0, "UNKNOWN": 840}
    assert sum(totals.values()) == 24 * 60


def test_a_day_with_no_card_in_any_slot_stays_unknown():
    changes = [_ch("00:00", "REST", "First", False),
               _ch("00:00", "REST", "Second", False)]
    assert compute_activity_totals(changes)["UNKNOWN"] == 24 * 60


def test_crew_day_still_counts_both_slots():
    changes = [
        _ch("00:00", "DRIVE", "First", True), _ch("04:00", "REST", "First", True),
        _ch("00:00", "REST", "Second", True), _ch("04:00", "DRIVE", "Second", True),
        _ch("08:00", "REST", "Second", True),
    ]
    totals = compute_activity_totals(changes)
    assert totals["DRIVE"] == 480   # 4h + 4h, one per driver


def test_records_without_card_flags_are_unchanged():
    # Driver-card downloads carry no card_inserted flag: one slot, as before.
    changes = [{"time": "00:00", "activity": "REST"},
               {"time": "08:00", "activity": "DRIVE"},
               {"time": "12:00", "activity": "REST"}]
    totals = compute_activity_totals(changes)
    assert totals["DRIVE"] == 240 and totals["REST"] == 1200
