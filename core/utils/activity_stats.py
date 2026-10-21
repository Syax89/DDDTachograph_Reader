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

Both public functions share one segmentation routine (:func:`day_segments`),
so the totals and the driving-rule verdicts of a day can never disagree about
which minutes were DRIVE. The GUI's activity timeline draws from the same
routine (see ``ActivityTimelineChart``), so the chart and the dashboard can
never paint different hours for the same day either.
"""

from typing import NamedTuple

# Recognised activity kinds; order matches the GUI's ACTIVITY_COLORS keys.
ACTIVITY_KINDS = ("DRIVE", "WORK", "REST", "AVAILABLE")
# Bucket for any activity label outside ACTIVITY_KINDS (see app/gui.py:1704).
UNKNOWN_ACTIVITY = "UNKNOWN"

#: End of the tachograph day, in seconds since midnight (``24:00``).
DAY_END_SECONDS = 86400

#: Kinds summed across slots; every other kind is a period kept at the maximum.
#: Drive/Work accumulate per driver, Rest/Available/Unknown cannot exceed a 24h
#: day (see the module docstring).
_SUM_ACROSS_SLOTS = frozenset({"DRIVE", "WORK"})


# ── Driving-time rules, Regulation (EC) No 561/2006 ────────────────────────
# Only the two rules below are modelled; neither the "10 h twice a week"
# extension of art. 6(1) nor the reduced-daily/weekly-rest rules are.
#: Art. 6(1): "The daily driving time shall not exceed nine hours."
DAILY_DRIVE_LIMIT_MIN = 540
#: Art. 7: after a continuous driving period of 4 h 30 min the driver must take
#: a break of at least 45 min, i.e. driving time since the last qualifying
#: break may not exceed 4 h 30 min.
CONTINUOUS_DRIVE_LIMIT_MIN = 270
#: Art. 7: length of the break that ends a continuous driving period.
QUALIFYING_BREAK_MIN = 45

#: Breach identifiers returned by :func:`evaluate_driving_rules`.
RULE_DAILY_DRIVING = "daily_driving"
RULE_CONTINUOUS_DRIVING = "continuous_driving"


class DrivingRuleBreach(NamedTuple):
    """One broken driving-time rule.

    ``slot`` is the card slot (``First``/``Second``) whose timeline breached
    the rule: both limits are *per driver*, so a crew day is judged slot by
    slot, never on the two drivers' summed driving time.
    """

    rule: str
    slot: str
    measured_min: int
    limit_min: int


class DrivingRuleReport(NamedTuple):
    """The driving-time verdict for one day.

    ``drive_min`` is the day's DRIVE time with the same slot semantics as
    :func:`compute_activity_totals` (summed across slots), i.e. the number the
    Daily-Activities dashboard shows in its Drive column. ``longest_stretch_min``
    is the longest stretch driven without a qualifying break, taken over the
    slots (the worst driver). ``breaches`` lists every broken rule.
    """

    drive_min: int
    longest_stretch_min: int
    breaches: tuple[DrivingRuleBreach, ...]

    @property
    def flagged(self):
        """True when the day breaks at least one driving-time rule."""
        return bool(self.breaches)


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


def _activity_segments(changes):
    """Return ``{slot: [(start_second, end_second, kind), ...]}`` for one day.

    The one place where a day's changes become a timeline. Changes are grouped
    per card slot, sorted, a missing leading 00:00 status entry is filled with
    UNKNOWN, unrecognised activity labels and card-not-inserted periods are
    declassified to UNKNOWN, and unusable times are skipped. The segments of a
    slot tile the whole 24h day, so no recorded minute can be counted twice or
    lost, and :func:`compute_activity_totals` and
    :func:`evaluate_driving_rules` always agree about which minutes were DRIVE.
    """
    per_slot: dict[str, list[tuple[int, str]]] = {}
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

    segments: dict[str, list[tuple[int, int, str]]] = {}
    for slot, parsed in per_slot.items():
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
        segments[slot] = [
            (start, parsed[i + 1][0] if i + 1 < len(parsed) else DAY_END_SECONDS, act)
            for i, (start, act) in enumerate(parsed)
        ]
    return segments


def day_segments(changes):
    """Public name of the shared day segmentation (see :func:`_activity_segments`).

    Consumers that draw a day rather than total it — the GUI activity timeline
    — call this instead of re-deriving the segmentation, so a chart and the
    dashboard can never disagree about which minutes were DRIVE, REST or an
    unrecorded (UNKNOWN) period.
    """
    return _activity_segments(changes)


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
    totals = {a: 0 for a in ACTIVITY_KINDS + (UNKNOWN_ACTIVITY,)}
    for segments in _activity_segments(changes).values():
        slot_tot: dict[str, int] = {}
        for start, end, act in segments:
            slot_tot[act] = slot_tot.get(act, 0) + (end - start) // 60
        for act, mins in slot_tot.items():
            if act in _SUM_ACROSS_SLOTS:
                totals[act] += mins
            else:
                if mins > totals[act]:
                    totals[act] = mins
    return totals


def evaluate_driving_rules(changes) -> DrivingRuleReport:
    """Return the driving-time rules broken by one day of changes.

    Only two rules are judged — Regulation (EC) No 561/2006 art. 6(1) (daily
    driving time above 9 h) and art. 7 (more than 4 h 30 min of continuous
    driving) — at the limits held by :data:`DAILY_DRIVE_LIMIT_MIN` and
    :data:`CONTINUOUS_DRIVE_LIMIT_MIN`. Nothing beyond them: no 10 h extension
    of art. 6(1), no weekly/fortnightly totals, no rest rules.

    Break model — a deliberate simplification, **not** a legal reading: a
    continuous driving period ends after **45 uninterrupted minutes of any
    non-DRIVE activity**, i.e. rest, availability and work are all treated
    alike, and UNKNOWN is excluded. That is the simplified proxy this flagging
    was asked to implement; it is not the Regulation's formal definition of a
    qualifying break, and nothing here is a legal determination about a driver
    or a day. The 15+30 split the article permits is not modelled at all (see
    the shortcut comment below), so the model is deliberately coarser than the
    rule in both directions.

    Slot semantics: both limits are per driver, so each card slot is judged on
    its own timeline. A crew day whose two drivers each drove 8 h in two 4 h
    stretches is clean even though the day's summed DRIVE is 16 h, while one
    driver's 10 h day is flagged on that driver's own figures. ``drive_min`` in
    the returned report stays the summed value — exactly what the
    Daily-Activities dashboard prints in its Drive column
    (``compute_activity_totals(changes)["DRIVE"]``) — while the breaches and
    ``longest_stretch_min`` come from the worst single slot.

    UNKNOWN periods (a card-not-inserted period, Annex 1C §2.1 note (2), or an
    unrecorded leading gap) are deliberately **excluded** from the break proxy:
    the Regulation accepts a break or other work, and an unrecorded period is
    demonstrably neither. The consequences, both conservative:

    * they add no driving time, and the accumulating stretch **carries on**
      across them, so the driving on both sides of a card-out gap adds up
      instead of the gap silently resetting the counter;
    * they **interrupt** a break run, so 30 min of rest, a card-out gap and
      20 min of work are *not* the 45 uninterrupted minutes art. 7 wants.

    A day with a card-not-inserted gap is therefore flagged only when the
    driving itself exceeds a limit.

    Args:
        changes: One day's activity changes, the same shape
            :func:`compute_activity_totals` takes.

    Returns:
        DrivingRuleReport: the day's DRIVE minutes, the longest stretch driven
        without a qualifying break, and the list of breaches (each with the
        measured value, the limit it broke and the slot it belongs to).
    """
    segments = _activity_segments(changes)
    drive_min = 0
    longest_stretch = 0
    breaches: list[DrivingRuleBreach] = []
    for slot in sorted(segments):
        slot_drive = 0
        stretch = 0
        slot_longest = 0
        non_drive = 0
        for start, end, act in segments[slot]:
            minutes = (end - start) // 60
            if act == "DRIVE":
                slot_drive += minutes
                stretch += minutes
                non_drive = 0
                if stretch > slot_longest:
                    slot_longest = stretch
                continue
            if act == UNKNOWN_ACTIVITY:
                # Neither driving nor a break (see the docstring): no driving
                # time is added, the stretch carries on across the gap, and the
                # break run is interrupted because unknown time cannot be a
                # qualifying break.
                non_drive = 0
                continue
            non_drive += minutes
            if non_drive >= QUALIFYING_BREAK_MIN:
                # shortcut: 15+30 split not modelled, add when a user reports a missed case
                stretch = 0
                non_drive = 0
        drive_min += slot_drive
        if slot_longest > longest_stretch:
            longest_stretch = slot_longest
        if slot_drive > DAILY_DRIVE_LIMIT_MIN:
            breaches.append(DrivingRuleBreach(
                RULE_DAILY_DRIVING, slot, slot_drive, DAILY_DRIVE_LIMIT_MIN))
        if slot_longest > CONTINUOUS_DRIVE_LIMIT_MIN:
            breaches.append(DrivingRuleBreach(
                RULE_CONTINUOUS_DRIVING, slot, slot_longest, CONTINUOUS_DRIVE_LIMIT_MIN))
    return DrivingRuleReport(drive_min=drive_min,
                             longest_stretch_min=longest_stretch,
                             breaches=tuple(breaches))
