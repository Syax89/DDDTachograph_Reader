"""Shared activity-totals computation (no tkinter dependency).

Extracted verbatim from ``app/gui.py`` (``_compute_activity_totals`` and
``ActivityTimelineChart._parse_time``) so the CLI summary and the PDF export
use exactly the same slot-aware semantics as the GUI timeline.

Semantics:
- Changes are grouped per card slot (``First``/``Second``) first, so crew
  days (two drivers recording simultaneously) keep their timelines
  independent.
- Drive/Work durations are summed across slots (each driver accumulates
  independently).
- Rest/Available/Unknown durations are kept at the **maximum** across slots
  because they share the same 24h day and cannot exceed it (they are periods,
  not additive).
- An activity label that is not one of the four recognised kinds is bucketed
  as ``UNKNOWN`` rather than silently dropped, so no recorded hour disappears
  from the totals.
- The day ends at 86400 seconds (``24:00``).
- Non-dict entries and unusable (out-of-range / unparsable) times are skipped.
"""

# Recognised activity kinds; order matches the GUI's ACTIVITY_COLORS keys.
ACTIVITY_KINDS = ("DRIVE", "WORK", "REST", "AVAILABLE")
# Bucket for any activity label outside ACTIVITY_KINDS (see app/gui.py:1704).
UNKNOWN_ACTIVITY = "UNKNOWN"


def parse_time(time_str):
    """Parse an ``'HH:MM'`` time to seconds since midnight, or ``None``.

    Only exactly two colon-separated integer parts inside a real clock range
    are accepted: ``0 <= hours <= 24``, ``0 <= minutes < 60``, with ``24:00``
    the only valid 24-hour value. Out-of-range values (``'25:00'``,
    ``'08:75'``, ``'24:01'``) and negative values are rejected as unusable
    (``None``). This is the range guard the report's former ``_time_to_minutes``
    applied; every consumer (report tables, PDF cover, CLI summary and the GUI
    timeline) now routes through this single function.
    """
    parts = str(time_str).split(":")
    if len(parts) != 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except (ValueError, TypeError):
        return None
    if not 0 <= hours <= 24 or not 0 <= minutes < 60 or (hours == 24 and minutes):
        return None
    return hours * 3600 + minutes * 60


def compute_activity_totals(changes):
    """Return dict {ACTIVITY: total_minutes} from a list of activity changes.

    Keys: DRIVE, WORK, REST, AVAILABLE, UNKNOWN. Any activity label outside the
    recognised kinds is accumulated as UNKNOWN so its hours stay in the totals
    instead of vanishing. A card-not-inserted period ('p'=1, 'c'=0 — the record
    carries ``card_inserted`` False and ``crew`` False) is likewise bucketed as
    UNKNOWN: Annex 1C §2.1 declares its activity code "not relevant". See the
    module docstring for the slot-grouping / sum-vs-max semantics (UNKNOWN uses
    max, like REST/AVAILABLE).
    """
    ACCUM_BY_SUM = {"DRIVE", "WORK"}
    per_slot: dict[str, list] = {}
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        t = parse_time(ch.get("time", ""))
        if t is None:
            continue
        act = str(ch.get("activity", "")).upper()
        if act not in ACTIVITY_KINDS:
            act = UNKNOWN_ACTIVITY
        elif ch.get("card_inserted") is False and ch.get("crew") is False:
            # Annex 1C §2.1 note (2): during a card-not-inserted period
            # ('p'=1) with a single crew member ('c'=0) the recorded activity
            # code `aa` is "not relevant"; the period is UNKNOWN, not a real
            # REST/WORK/etc. Declassify it so card-absent minutes cannot
            # inflate the activity totals (F-F4). Both bits must be explicitly
            # present and false: records without the flags are left untouched.
            act = UNKNOWN_ACTIVITY
        slot = str(ch.get("slot") or "First")
        per_slot.setdefault(slot, []).append((t, act))

    totals = {a: 0 for a in ACTIVITY_KINDS + (UNKNOWN_ACTIVITY,)}
    for parsed in per_slot.values():
        parsed.sort(key=lambda item: item[0])
        # Annex 1C §2.170 (VuActivityDailyData): a daily record "always
        # includes two ActivityChangeInfo words giving the status of the two
        # slots at 00:00". When that leading entry is absent — dropped by a
        # decoder, or the day starts with the card not yet inserted — the
        # interval [00:00, first recorded change) was attributed to no activity
        # at all and silently vanished (a day of 06:00→24:00 totalled 18h, not
        # 24h). Bucket it as UNKNOWN, matching §2.1 note (2) ("UNKNOWN periods
        # correspond to periods where the driver card was not inserted"), so no
        # recorded hour disappears from the day.
        if parsed[0][0] > 0:
            parsed.insert(0, (0, UNKNOWN_ACTIVITY))
        slot_tot: dict[str, int] = {}
        for i, (start, act) in enumerate(parsed):
            end = parsed[i + 1][0] if i + 1 < len(parsed) else 86400
            slot_tot[act] = slot_tot.get(act, 0) + (end - start) // 60
        for act, mins in slot_tot.items():
            if act in ACCUM_BY_SUM:
                totals[act] += mins
            else:
                if mins > totals[act]:
                    totals[act] = mins
    return totals
