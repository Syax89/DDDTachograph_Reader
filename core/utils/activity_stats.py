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
- Rest/Available durations are kept at the **maximum** across slots because
  they share the same 24h day and cannot exceed it.
- The day ends at 86400 seconds (``24:00``).
- Non-dict entries and unparsable times are skipped.
"""

# Recognised activity kinds; order matches the GUI's ACTIVITY_COLORS keys.
ACTIVITY_KINDS = ("DRIVE", "WORK", "REST", "AVAILABLE")


def parse_time(time_str):
    """Parse an ``'HH:MM'`` time to seconds since midnight, or None.

    Same semantics as ``ActivityTimelineChart._parse_time`` in app/gui.py:
    exactly two colon-separated integer parts, otherwise None.
    """
    parts = str(time_str).split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60
    except ValueError:
        return None


def compute_activity_totals(changes):
    """Return dict {ACTIVITY: total_minutes} from a list of activity changes.

    Keys: DRIVE, WORK, REST, AVAILABLE.  See module docstring for the
    slot-grouping / sum-vs-max semantics.
    """
    ACCUM_BY_SUM = {"DRIVE", "WORK"}
    per_slot: dict[str, list] = {}
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        t = parse_time(ch.get("time", ""))
        act = str(ch.get("activity", "")).upper()
        if t is not None and act in ACTIVITY_KINDS:
            slot = str(ch.get("slot") or "First")
            per_slot.setdefault(slot, []).append((t, act))

    totals = {a: 0 for a in ACTIVITY_KINDS}
    for parsed in per_slot.values():
        parsed.sort(key=lambda item: item[0])
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
