"""Indicative driving- and rest-time analysis under Regulation (EC) No 561/2006.

What it does
------------
:func:`analyse_result` takes a parsed driver-card download and judges its
recorded activity against the driving-time, break and rest rules of
Regulation (EC) No 561/2006 (as amended by Regulation (EU) 2020/1054). Every
result is **indicative**: it reads only what the card recorded, it models a
subset of the Regulation, and it is never a legal determination about a driver.

The analysis is deterministic. It never reads the wall clock; every time is
UTC, the time base the tachograph records in.

Timeline
--------
The day records (``results["activities"]``) are concatenated into one
continuous UTC timeline. Each day is segmented by
:func:`core.utils.activity_stats.day_segments` — the same routine the totals
and the GUI chart use — after folding the card's two slot labels into one
timeline (a driver card belongs to one driver; the slot only says where the
card sat). A day missing between two recorded days is UNKNOWN, as is a
card-not-inserted period and anything after the ``recorded_until`` cut of the
last day. The data starts at 00:00 of the first recorded day and ends at that
cut (24:00 when there is none).

Readings of the Regulation
--------------------------
* **Break (art. 4(d), art. 7).** A break is "any period during which a driver
  may not carry out any driving or any other work and which is used
  exclusively for recuperation". Only REST counts. WORK is other work, and
  AVAILABLE (a period of availability) is not a break either: the driver must
  stay available to start work. A qualifying break is 45 min, or 15 min
  followed later by 30 min; a split's first part counts from the last
  qualifying break onward, even before driving resumes (the reading most
  favourable to the driver). Driving is cumulative between qualifying breaks;
  exactly 4 h 30 min is compliant.
* **Daily driving (art. 4(k), art. 6(1)).** Driving between the end of one
  daily (or weekly) rest and the start of the next, not per calendar day.
  9 h, extendable to 10 h at most twice per fixed week; an extension belongs to
  the week in which its daily driving period starts. A period above 10 h is an
  infringement on its own and is not also counted as an extension.
* **Weekly / fortnightly driving (art. 6(2), 6(3)).** Fixed weeks, Monday
  00:00 to Sunday 24:00 UTC; 56 h per week, 90 h per two consecutive weeks.
* **Daily rest (art. 4(g), art. 8(1), 8(2), 8(4)).** Within every 24 h after
  the end of the previous daily or weekly rest, the first REST period of which
  at least 9 h falls inside that window is the daily rest: regular when 11 h of
  it fall inside, or when a REST of at least 3 h lay entirely inside the window
  before it (the 3 h + 9 h split); otherwise reduced (art. 8(2): "the portion
  ... which falls within that 24-hour period"). The rule applies to a weekly
  rest that ends the window too. When no such rest exists, the window is an
  infringement and the walk resumes at the end of the next REST of at least
  9 h. At most three reduced daily rests between two weekly rests.
* **Weekly rest (art. 4(h), art. 8(6)).** Any REST of at least 24 h is a weekly
  rest; at least 45 h is regular. It must start no later than six 24-hour
  periods (144 h) after the end of the previous one, and any two consecutive
  fixed weeks need two weekly rests, at least one regular. A weekly rest that
  overlaps the two weeks counts for them (art. 8(6): "may be counted in either
  week"), the reading most favourable to the driver; a REST that spans a whole
  fixed week (leave) satisfies both weeks it belongs to.

Unrecorded time and the edges of the data
-----------------------------------------
Driving is never inferred from an unrecorded period. Whether an unrecorded
period was rest is not known either, so the whole analysis runs twice: once
reading every UNKNOWN period as rest (the reading most favourable to the
driver) and once reading it as not rest. A finding is an **infringement** only
when both readings produce it (the two findings overlap in time); a finding
only one reading produces is **indeterminate** — the record cannot decide it.

At the edges, a REST that touches the start or the end of the data has an
unknown length and is read as long enough for anything (a regular weekly
rest); the 24 h window still open at the end of the data is not judged; a
daily driving period cut by the start of the data is judged on the driving it
holds (a lower bound) but not counted as an extension, because the week it
started in is unknown; a fixed week the data does not fully cover is judged
only when its recorded driving already exceeds the limit.

Multi-manning (art. 8(5)'s 30 h window, and art. 7's break in a vehicle driven
by another driver) is not modelled: a break, daily-driving or daily-rest
infringement whose period overlaps time recorded in crew mode is reported as
indeterminate instead. :data:`NOT_MODELLED` lists every provision left out.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timezone
from typing import Iterable, NamedTuple

from core.utils.activity_stats import UNKNOWN_ACTIVITY, day_segments, parse_time, recorded_until_seconds

REGULATION = "Regulation (EC) No 561/2006"

DISCLAIMER = (
    "Indicative analysis of the recorded tachograph data only; not a legal "
    "determination. Several provisions of Regulation (EC) No 561/2006 are not "
    "modelled, and recording gaps can make a result indeterminate."
)

#: Appended to every finding's explanation.
FINDING_NOTICE = "Indicative only; not a legal determination."

_HOUR = 3600
_DAY = 86400
_WEEK = 7 * _DAY

DRIVE = "DRIVE"
WORK = "WORK"
AVAILABLE = "AVAILABLE"
REST = "REST"
UNKNOWN = UNKNOWN_ACTIVITY

# ── Limits (minutes) ─────────────────────────────────────────────────────────
#: Art. 7: driving allowed before a qualifying break.
BREAK_AFTER_DRIVING_MIN = 270
#: Art. 7: an uninterrupted break of at least 45 min ...
BREAK_FULL_MIN = 45
#: ... or a break of at least 15 min followed by one of at least 30 min.
BREAK_SPLIT_FIRST_MIN = 15
BREAK_SPLIT_SECOND_MIN = 30
#: Art. 6(1): daily driving time, and its twice-a-week extension.
DAILY_DRIVING_MIN = 540
DAILY_DRIVING_EXTENDED_MIN = 600
DAILY_EXTENSIONS_PER_WEEK = 2
#: Art. 6(2) / 6(3).
WEEKLY_DRIVING_MIN = 56 * 60
FORTNIGHTLY_DRIVING_MIN = 90 * 60
#: Art. 4(g) / 8: regular, reduced and split daily rest.
REGULAR_DAILY_REST_MIN = 11 * 60
REDUCED_DAILY_REST_MIN = 9 * 60
SPLIT_REST_FIRST_MIN = 3 * 60
#: Art. 8(4).
MAX_REDUCED_DAILY_RESTS = 3
#: Art. 4(h) / 8(6).
REGULAR_WEEKLY_REST_MIN = 45 * 60
REDUCED_WEEKLY_REST_MIN = 24 * 60
WEEKLY_REST_INTERVAL_MIN = 6 * 24 * 60
WEEKLY_RESTS_PER_TWO_WEEKS = 2

STATUS_INFRINGEMENT = "infringement"
STATUS_INDETERMINATE = "indeterminate"

# ── Rule identifiers ─────────────────────────────────────────────────────────
RULE_BREAK = "break_after_driving"
RULE_DAILY_DRIVING = "daily_driving"
RULE_DAILY_EXTENSIONS = "daily_driving_extensions"
RULE_WEEKLY_DRIVING = "weekly_driving"
RULE_FORTNIGHTLY_DRIVING = "fortnightly_driving"
RULE_DAILY_REST = "daily_rest"
RULE_REDUCED_REST_COUNT = "reduced_daily_rest_count"
RULE_WEEKLY_REST_START = "weekly_rest_interval"
RULE_WEEKLY_REST_TWO_WEEKS = "weekly_rests_two_weeks"

#: ``rule id -> (article, short title)``, in report order.
RULES = {
    RULE_BREAK: ("Art. 7", "Break after 4h30 of driving"),
    RULE_DAILY_DRIVING: ("Art. 6(1)", "Daily driving time"),
    RULE_DAILY_EXTENSIONS: ("Art. 6(1)", "Extended (10 h) driving days per week"),
    RULE_WEEKLY_DRIVING: ("Art. 6(2)", "Weekly driving time"),
    RULE_FORTNIGHTLY_DRIVING: ("Art. 6(3)", "Driving time in two consecutive weeks"),
    RULE_DAILY_REST: ("Art. 8(1)-(2)", "Daily rest within 24 hours"),
    RULE_REDUCED_REST_COUNT: ("Art. 8(4)", "Reduced daily rests between weekly rests"),
    RULE_WEEKLY_REST_START: ("Art. 8(6)", "Weekly rest within six 24-hour periods"),
    RULE_WEEKLY_REST_TWO_WEEKS: ("Art. 8(6)", "Weekly rests in two consecutive weeks"),
}

#: Rules whose verdict the multi-manning provisions can change.
_CREW_SENSITIVE = frozenset({RULE_BREAK, RULE_DAILY_DRIVING, RULE_DAILY_EXTENSIONS,
                             RULE_DAILY_REST, RULE_REDUCED_REST_COUNT})

#: Provisions of the Regulation this analysis does not model.
NOT_MODELLED = (
    "Art. 8(5) multi-manning daily rest (9 h within 30 h) and art. 7 breaks taken "
    "in a vehicle driven by another driver: crew-mode periods make the break, "
    "daily driving and daily rest results indeterminate.",
    "Art. 8(6)-(7) compensation of reduced weekly rests, and the art. 8(6) "
    "derogation allowing two consecutive reduced weekly rests in international "
    "transport of goods.",
    "Art. 8(6a) twelve-day derogation for occasional international passenger "
    "transport; art. 8(8)-(8a) where a rest is taken (vehicle, accommodation, "
    "return home).",
    "Art. 9 rest interrupted by a ferry or train journey; art. 12 departures to "
    "reach a suitable stopping place; national and art. 13-14 exemptions; "
    "out-of-scope (OUT) driving.",
    "Art. 6(2) limits on weekly working time (Directive 2002/15/EC) and art. "
    "6(5) recording of other work.",
    "Driving during unrecorded periods (card not inserted, missing days) is "
    "never inferred; such periods only make results indeterminate.",
    "Vehicle-unit downloads: the timeline there belongs to a vehicle and its "
    "card slots, not to one driver, so they are not analysed.",
)


class Timeline(NamedTuple):
    """A continuous UTC activity timeline built from day records.

    ``segments`` tile ``[start, end)`` with ``(start_s, end_s, kind)`` tuples
    (epoch seconds), adjacent segments of one kind merged. ``crew`` holds the
    ``(start_s, end_s)`` intervals recorded in crew (multi-manning) mode.
    """

    start: int
    end: int
    segments: tuple[tuple[int, int, str], ...]
    crew: tuple[tuple[int, int], ...]
    days: int
    missing_days: int


class _Run(NamedTuple):
    """A maximal REST run; ``open_*`` marks a run cut by an edge of the data."""

    start: int
    end: int
    open_start: bool
    open_end: bool

    @property
    def length(self):
        return self.end - self.start


class _Raw(NamedTuple):
    """A rule failure produced by one reading of the timeline."""

    rule: str
    start: int
    end: int
    measured: int
    limit: int
    unit: str
    detail: str


# ── Small helpers ────────────────────────────────────────────────────────────
_EPOCH_ORDINAL = date(1970, 1, 1).toordinal()


def _parse_date(text):
    """``'dd/mm/yyyy'`` → :class:`datetime.date`, or ``None``."""
    try:
        day, month, year = (int(part) for part in str(text).split("/"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def _day_start(day):
    return (day.toordinal() - _EPOCH_ORDINAL) * _DAY


def _week_start(t):
    """Monday 00:00 UTC of the fixed week holding epoch second ``t``."""
    days = t // _DAY
    weekday = (days + 3) % 7          # 1970-01-01 was a Thursday (weekday 3)
    return (days - weekday) * _DAY


def iso_utc(t):
    """Epoch seconds → ``'YYYY-MM-DDTHH:MMZ'``."""
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _date_text(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")


def format_minutes(minutes):
    """``271`` → ``'4h31'``."""
    minutes = int(minutes)
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60}h{minutes % 60:02d}"


def _merge(segments):
    out: list[tuple[int, int, str]] = []
    for start, end, kind in segments:
        if end <= start:
            continue
        if out and out[-1][2] == kind and out[-1][1] == start:
            out[-1] = (out[-1][0], end, kind)
        else:
            out.append((start, end, kind))
    return out


def _merge_intervals(intervals):
    out: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return out


def _overlap(a_start, a_end, b_start, b_end):
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _periods_meet(a, b):
    if (a.start, a.end) == (b.start, b.end):
        return True
    return a.start < b.end and b.start < a.end


# ── Timeline ─────────────────────────────────────────────────────────────────
def _changes(day):
    return [ch for ch in (day.get("changes") or []) if isinstance(ch, dict)]


def build_timeline(days: Iterable) -> Timeline | None:
    """Concatenate driver-card day records into one UTC timeline.

    Returns ``None`` when no day record carries a usable date or the data is
    empty. A date recorded twice keeps the record with more changes.
    """
    by_date: dict[date, dict] = {}
    for day in days or ():
        if not isinstance(day, dict):
            continue
        when = _parse_date(day.get("date"))
        if when is None:
            continue
        kept = by_date.get(when)
        if kept is None or len(_changes(day)) > len(_changes(kept)):
            by_date[when] = day
    if not by_date:
        return None

    ordered = sorted(by_date)
    t0 = _day_start(ordered[0])
    segments: list[tuple[int, int, str]] = []
    crew: list[tuple[int, int]] = []
    missing = 0
    previous_end = t0
    t1 = t0
    for when in ordered:
        day = by_date[when]
        base = _day_start(when)
        if base > previous_end:
            missing += (base - previous_end) // _DAY
            segments.append((previous_end, base, UNKNOWN))
        # One driver, one timeline: the slot only says where the card sat.
        changes = [dict(ch, slot="First") for ch in _changes(day)]
        cut = recorded_until_seconds(day)
        per_day = day_segments(changes, cut).get("First") or [(0, _DAY, UNKNOWN)]
        # ``day_segments`` sorts stably, so of two changes at one time the
        # later one owns the segment; the dict keeps the later one too.
        timed = [(parse_time(ch.get("time", "")), ch.get("crew") is True) for ch in changes]
        crew_at = dict(sorted(((t, c) for t, c in timed if t is not None), key=lambda item: item[0]))
        for start, end, kind in per_day:
            segments.append((base + start, base + end, kind))
            if kind != UNKNOWN and crew_at.get(start):
                crew.append((base + start, base + end))
        previous_end = base + _DAY
        t1 = base + (cut if cut is not None else _DAY)

    segments = [(s, min(e, t1), k) for s, e, k in segments if s < t1]
    if t1 <= t0:
        return None
    return Timeline(start=t0, end=t1, segments=tuple(_merge(segments)),
                    crew=tuple(_merge_intervals((s, min(e, t1)) for s, e in crew if s < t1)),
                    days=len(ordered), missing_days=missing)


def _interpret(timeline, unknown_as_rest):
    """The timeline with UNKNOWN read as REST, or left as non-rest UNKNOWN."""
    if not unknown_as_rest:
        return list(timeline.segments)
    return _merge((s, e, REST if k == UNKNOWN else k) for s, e, k in timeline.segments)


class _DriveIndex:
    """Driving seconds inside any interval, by binary search."""

    def __init__(self, segments):
        self._starts: list[int] = []
        self._ends: list[int] = []
        self._cum = [0]
        for start, end, kind in segments:
            if kind == DRIVE:
                self._starts.append(start)
                self._ends.append(end)
                self._cum.append(self._cum[-1] + end - start)

    def _before(self, t):
        i = bisect_right(self._starts, t)
        if i == 0:
            return 0
        return self._cum[i - 1] + min(t, self._ends[i - 1]) - self._starts[i - 1]

    def between(self, a, b):
        return self._before(b) - self._before(a) if b > a else 0


# ── One reading of the timeline ──────────────────────────────────────────────
def _breaks(segments):
    """Art. 7: driving accumulated between qualifying breaks."""
    found: list[_Raw] = []
    assessed = 0
    acc = 0
    stretch_start = None
    last_drive_end = 0
    split_started = False

    def close():
        nonlocal assessed
        if stretch_start is None:
            return
        assessed += 1
        minutes = acc // 60
        if minutes > BREAK_AFTER_DRIVING_MIN:
            found.append(_Raw(
                RULE_BREAK, stretch_start, last_drive_end, minutes, BREAK_AFTER_DRIVING_MIN, "minutes",
                f"{format_minutes(minutes)} of driving without a qualifying break (45 min, or 15 min "
                f"then 30 min); limit {format_minutes(BREAK_AFTER_DRIVING_MIN)}."))

    for start, end, kind in segments:
        length_min = (end - start) // 60
        if kind == DRIVE:
            if stretch_start is None:
                stretch_start = start
            acc += end - start
            last_drive_end = end
        elif kind == REST:
            if length_min >= BREAK_FULL_MIN or (split_started and length_min >= BREAK_SPLIT_SECOND_MIN):
                close()
                acc = 0
                stretch_start = None
                split_started = False
            elif length_min >= BREAK_SPLIT_FIRST_MIN:
                split_started = True
    close()
    return found, {RULE_BREAK: assessed}


class _Period(NamedTuple):
    """A daily driving period: from the end of one rest to the next rest."""

    start: int
    end: int
    open_start: bool


def _daily(runs, t0, t1):
    """Art. 8(1)-(4): daily rests, and the daily driving periods between them."""
    found: list[_Raw] = []
    periods: list[_Period] = []
    assessed_rest = 0
    assessed_reduced = 0
    ref, ref_open, i, reduced = t0, True, 0, 0
    if runs and runs[0].open_start:
        # The data opens inside a rest of unknown length: read it as a weekly rest.
        if runs[0].open_end:
            return found, periods, {RULE_DAILY_REST: 0, RULE_REDUCED_REST_COUNT: 0}
        ref, ref_open, i = runs[0].end, False, 1

    while ref < t1:
        window_end = ref + _DAY
        chosen = None
        split = False
        longest = 0
        j = i
        while j < len(runs) and runs[j].start < window_end:
            run = runs[j]
            inside = min(run.end, window_end) - run.start
            longest = max(longest, inside)
            if inside >= REDUCED_DAILY_REST_MIN * 60:
                chosen = j
                break
            if inside >= SPLIT_REST_FIRST_MIN * 60 and run.end <= window_end:
                split = True
            j += 1
        late = False
        if chosen is None:
            if window_end > t1:
                periods.append(_Period(ref, t1, ref_open))     # window still open at the end
                break
            assessed_rest += 1
            found.append(_Raw(
                RULE_DAILY_REST, ref, window_end, longest // 60, REDUCED_DAILY_REST_MIN, "minutes",
                f"No daily rest of at least 9h within the 24 hours after the previous rest ended; "
                f"the longest rest inside that window is {format_minutes(longest // 60)}."))
            j = i
            while j < len(runs) and not (runs[j].length >= REDUCED_DAILY_REST_MIN * 60 or runs[j].open_end):
                j += 1
            if j == len(runs):
                periods.append(_Period(ref, t1, ref_open))
                break
            chosen, late = j, True
        else:
            assessed_rest += 1
        run = runs[chosen]
        periods.append(_Period(ref, run.start, ref_open))
        inside = min(run.end, window_end) - run.start
        if run.length >= REDUCED_WEEKLY_REST_MIN * 60 or run.open_end:
            reduced = 0
        elif not late and not ref_open and inside < REGULAR_DAILY_REST_MIN * 60 and not split:
            reduced += 1
            assessed_reduced += 1
            if reduced > MAX_REDUCED_DAILY_RESTS:
                found.append(_Raw(
                    RULE_REDUCED_REST_COUNT, run.start, run.end, reduced, MAX_REDUCED_DAILY_RESTS, "count",
                    f"Reduced daily rest ({format_minutes(inside // 60)} inside its 24-hour window) is "
                    f"number {reduced} since the last weekly rest; at most "
                    f"{MAX_REDUCED_DAILY_RESTS} are allowed."))
        ref, ref_open, i = run.end, False, chosen + 1
        if run.open_end:
            break
    return found, periods, {RULE_DAILY_REST: assessed_rest, RULE_REDUCED_REST_COUNT: assessed_reduced}


def _daily_driving(periods, drive):
    """Art. 6(1): 9 h per daily driving period, 10 h at most twice a week."""
    found: list[_Raw] = []
    extensions: dict[int, int] = {}
    for period in periods:
        minutes = drive.between(period.start, period.end) // 60
        if minutes > DAILY_DRIVING_EXTENDED_MIN:
            found.append(_Raw(
                RULE_DAILY_DRIVING, period.start, period.end, minutes, DAILY_DRIVING_EXTENDED_MIN, "minutes",
                f"{format_minutes(minutes)} of driving between two daily rests; limit 10h00 "
                f"(9h00, extendable to 10h00 twice a week)."))
        elif minutes > DAILY_DRIVING_MIN and not period.open_start:
            week = _week_start(period.start)
            extensions[week] = extensions.get(week, 0) + 1
            if extensions[week] > DAILY_EXTENSIONS_PER_WEEK:
                found.append(_Raw(
                    RULE_DAILY_EXTENSIONS, period.start, period.end, extensions[week],
                    DAILY_EXTENSIONS_PER_WEEK, "count",
                    f"Daily driving of {format_minutes(minutes)} is extended day number "
                    f"{extensions[week]} above 9h00 in the week starting {_date_text(week)}; at most "
                    f"{DAILY_EXTENSIONS_PER_WEEK} are allowed."))
    weeks = {_week_start(p.start) for p in periods if not p.open_start}
    return found, {RULE_DAILY_DRIVING: len(periods), RULE_DAILY_EXTENSIONS: len(weeks)}


def _weeks(t0, t1):
    week = _week_start(t0)
    out = []
    while week < t1:
        out.append(week)
        week += _WEEK
    return out


def _weekly_driving(t0, t1, drive):
    """Art. 6(2)-(3): 56 h per fixed week, 90 h per two consecutive weeks."""
    found: list[_Raw] = []
    weeks = _weeks(t0, t1)
    totals = [drive.between(w, w + _WEEK) // 60 for w in weeks]
    full = [w >= t0 and w + _WEEK <= t1 for w in weeks]
    for week, minutes in zip(weeks, totals, strict=True):
        if minutes > WEEKLY_DRIVING_MIN:
            found.append(_Raw(
                RULE_WEEKLY_DRIVING, week, week + _WEEK, minutes, WEEKLY_DRIVING_MIN, "minutes",
                f"{format_minutes(minutes)} of driving in the fixed week starting {_date_text(week)}; "
                f"limit {format_minutes(WEEKLY_DRIVING_MIN)}."))
    pairs = 0
    for k in range(len(weeks) - 1):
        minutes = totals[k] + totals[k + 1]
        pairs += full[k] and full[k + 1]
        if minutes > FORTNIGHTLY_DRIVING_MIN:
            found.append(_Raw(
                RULE_FORTNIGHTLY_DRIVING, weeks[k], weeks[k] + 2 * _WEEK, minutes, FORTNIGHTLY_DRIVING_MIN,
                "minutes",
                f"{format_minutes(minutes)} of driving in the two consecutive weeks starting "
                f"{_date_text(weeks[k])}; limit {format_minutes(FORTNIGHTLY_DRIVING_MIN)}."))
    return found, {RULE_WEEKLY_DRIVING: sum(full), RULE_FORTNIGHTLY_DRIVING: pairs}


def _weekly_rest(runs, t0, t1):
    """Art. 8(6): weekly rest interval and the two-week requirement."""
    found: list[_Raw] = []
    weekly = [r for r in runs if r.length >= REDUCED_WEEKLY_REST_MIN * 60 or r.open_start or r.open_end]
    interval = WEEKLY_REST_INTERVAL_MIN * 60
    assessed = 0
    previous_end = None
    for run in weekly:
        if previous_end is None and run.open_start:
            previous_end = run.end
            continue
        ref = t0 if previous_end is None else previous_end
        assessed += 1
        if run.start - ref > interval:
            minutes = (run.start - ref) // 60
            since = ("the start of the data" if previous_end is None
                     else "the end of the previous weekly rest")
            found.append(_Raw(
                RULE_WEEKLY_REST_START, ref, run.start, minutes, WEEKLY_REST_INTERVAL_MIN, "minutes",
                f"Weekly rest started {format_minutes(minutes)} after {since}; it must start within "
                f"six 24-hour periods ({format_minutes(WEEKLY_REST_INTERVAL_MIN)})."))
        previous_end = run.end
    ref = t0 if previous_end is None else previous_end
    if t1 - ref > interval:
        assessed += 1
        minutes = (t1 - ref) // 60
        found.append(_Raw(
            RULE_WEEKLY_REST_START, ref, t1, minutes, WEEKLY_REST_INTERVAL_MIN, "minutes",
            f"No weekly rest started within six 24-hour periods ({format_minutes(WEEKLY_REST_INTERVAL_MIN)}); "
            f"{format_minutes(minutes)} recorded without one."))

    weeks = _weeks(t0, t1)
    pairs = 0
    for k in range(len(weeks) - 1):
        start, end = weeks[k], weeks[k] + 2 * _WEEK
        if start < t0 or end > t1:
            continue
        pairs += 1
        inside = [r for r in weekly if r.start < end and r.end > start]
        regular = [r for r in inside if r.length >= REGULAR_WEEKLY_REST_MIN * 60 or r.open_start or r.open_end]
        # A rest spanning a whole fixed week (leave, a long stop) is more than
        # any weekly-rest requirement asks of those two weeks.
        whole_week = any(r.start <= w and r.end >= w + _WEEK for r in inside for w in (start, start + _WEEK))
        if not whole_week and (len(inside) < WEEKLY_RESTS_PER_TWO_WEEKS or not regular):
            found.append(_Raw(
                RULE_WEEKLY_REST_TWO_WEEKS, start, end, len(inside), WEEKLY_RESTS_PER_TWO_WEEKS, "count",
                f"{len(inside)} weekly rest(s), {len(regular)} of them regular (45h), in the two weeks "
                f"starting {_date_text(start)}; at least two are required, one of them regular."))
    return found, {RULE_WEEKLY_REST_START: assessed, RULE_WEEKLY_REST_TWO_WEEKS: pairs}


def _evaluate(timeline, unknown_as_rest):
    """Every rule failure of one reading, and how many units each rule judged."""
    segments = _interpret(timeline, unknown_as_rest)
    t0, t1 = timeline.start, timeline.end
    runs = [_Run(s, e, s == t0, e == t1) for s, e, k in segments if k == REST]
    drive = _DriveIndex(segments)
    found: list[_Raw] = []
    assessed: dict[str, int] = {}
    for part, counts in (
            _breaks(segments),
            _weekly_driving(t0, t1, drive),
            _weekly_rest(runs, t0, t1)):
        found.extend(part)
        assessed.update(counts)
    daily_found, periods, counts = _daily(runs, t0, t1)
    found.extend(daily_found)
    assessed.update(counts)
    part, counts = _daily_driving(periods, drive)
    found.extend(part)
    assessed.update(counts)
    return found, assessed


# ── The two readings combined ────────────────────────────────────────────────
_WHY_UNRECORDED = (
    "Reached only when the unrecorded periods (card not inserted, missing days) are read as not "
    "rest; the record cannot tell, so no infringement is claimed.")
_WHY_FAVOURABLE_ONLY = (
    "Reached only when the unrecorded periods are read as rest; read as not rest, the periods line "
    "up differently and this result is not reproduced, so it is left undecided.")
_WHY_CREW = (
    "Crew (multi-manning) driving was recorded in this period, and the multi-manning provisions "
    "(art. 7 second paragraph, art. 8(5)) are not modelled.")


def _finding(raw, status, why, timeline):
    article, title = RULES[raw.rule]
    unknown_s = sum(_overlap(s, e, raw.start, raw.end) for s, e, k in timeline.segments if k == UNKNOWN)
    explanation = raw.detail if not why else f"{raw.detail} {why}"
    return {
        "rule": raw.rule,
        "article": article,
        "title": title,
        "status": status,
        "start": iso_utc(raw.start),
        "end": iso_utc(raw.end),
        "measured": raw.measured,
        "limit": raw.limit,
        "unit": raw.unit,
        "unrecorded_min": unknown_s // 60,
        "explanation": f"{explanation} {FINDING_NOTICE}",
        "indicative": True,
    }


def _combine(timeline, favourable, unfavourable):
    matched: set[int] = set()
    combined: list[tuple[_Raw, str, str]] = []
    for raw in favourable:
        hits = [k for k, other in enumerate(unfavourable)
                if other.rule == raw.rule and _periods_meet(raw, other)]
        matched.update(hits)
        if hits:
            combined.append((raw, STATUS_INFRINGEMENT, ""))
        else:
            combined.append((raw, STATUS_INDETERMINATE, _WHY_FAVOURABLE_ONLY))
    for k, raw in enumerate(unfavourable):
        if k not in matched:
            combined.append((raw, STATUS_INDETERMINATE, _WHY_UNRECORDED))
    out = []
    for raw, status, why in combined:
        if status == STATUS_INFRINGEMENT and raw.rule in _CREW_SENSITIVE and any(
                _overlap(s, e, raw.start, raw.end) for s, e in timeline.crew):
            status, why = STATUS_INDETERMINATE, _WHY_CREW
        out.append(_finding(raw, status, why, timeline))
    order = list(RULES)
    out.sort(key=lambda f: (f["start"], order.index(f["rule"]), f["end"]))
    return out


# ── Public API ───────────────────────────────────────────────────────────────
def _report(status, message, **extra):
    report = {
        "regulation": REGULATION,
        "status": status,
        "message": message,
        "disclaimer": DISCLAIMER,
        "not_modelled": list(NOT_MODELLED),
    }
    report.update(extra)
    return report


def analyse_days(days) -> dict:
    """Analyse one driver's day records (``results["activities"]`` of a card).

    ``summary["by_rule"][rule]["assessed"]`` counts what the favourable reading
    judged: driving stretches (art. 7), daily driving periods, weeks holding a
    daily driving period (extensions), fully covered weeks / pairs of weeks,
    24-hour rest windows, reduced daily rests found, and weekly-rest intervals.
    """
    timeline = build_timeline(days)
    if timeline is None:
        return _report("no_data", "No dated activity record to analyse.", findings=[], summary={
            "infringements": 0, "indeterminate": 0, "by_rule": {}})
    favourable, assessed = _evaluate(timeline, unknown_as_rest=True)
    unfavourable, _ = _evaluate(timeline, unknown_as_rest=False)
    findings = _combine(timeline, favourable, unfavourable)
    by_rule = {}
    for rule, (article, title) in RULES.items():
        by_rule[rule] = {
            "article": article,
            "title": title,
            "assessed": assessed.get(rule, 0),
            "infringement": sum(1 for f in findings if f["rule"] == rule and f["status"] == STATUS_INFRINGEMENT),
            "indeterminate": sum(1 for f in findings if f["rule"] == rule and f["status"] == STATUS_INDETERMINATE),
        }
    unknown_min = sum(e - s for s, e, k in timeline.segments if k == UNKNOWN) // 60
    summary = {
        "infringements": sum(1 for f in findings if f["status"] == STATUS_INFRINGEMENT),
        "indeterminate": sum(1 for f in findings if f["status"] == STATUS_INDETERMINATE),
        "by_rule": by_rule,
    }
    return _report(
        "analysed", "Driver card activity analysed as one driver's continuous UTC timeline.",
        period={"start": iso_utc(timeline.start), "end": iso_utc(timeline.end),
                "days_recorded": timeline.days, "days_missing": timeline.missing_days,
                "unrecorded_min": unknown_min},
        summary=summary, findings=findings)


def analyse_result(result) -> dict:
    """Analyse a parsed download (the dict :class:`app.engine.TachoParser` returns).

    Vehicle-unit downloads are not analysed (status ``not_applicable``): their
    activity is recorded per vehicle and card slot, and a slot can hold several
    drivers' cards in turn, so it is not one driver's timeline.
    """
    meta = (result or {}).get("metadata") or {}
    if meta.get("is_vu"):
        return _report(
            "not_applicable",
            "Vehicle-unit download: activity is recorded per vehicle and card slot, not per driver, "
            "so no driving/rest-time analysis is made. Analyse the driver card download instead.",
            findings=[], summary={"infringements": 0, "indeterminate": 0, "by_rule": {}})
    return analyse_days((result or {}).get("activities") or [])


def format_report(report) -> list[str]:
    """Plain-text lines for a report from :func:`analyse_result`."""
    lines = ["=" * 60, "DRIVING AND REST TIMES - " + REGULATION.upper(), "=" * 60, report["disclaimer"]]
    if report["status"] != "analysed":
        lines += ["", report["message"], "=" * 60]
        return lines
    period = report["period"]
    summary = report["summary"]
    lines += [
        "",
        f"Period (UTC): {period['start']} to {period['end']} "
        f"({period['days_recorded']} days recorded, {period['days_missing']} missing, "
        f"{format_minutes(period['unrecorded_min'])} unrecorded)",
        f"Infringements: {summary['infringements']}   Indeterminate: {summary['indeterminate']}",
        "",
        f"{'Rule':<56}{'Assessed':>9}{'Infr.':>7}{'Indet.':>8}",
    ]
    for item in summary["by_rule"].values():
        name = f"{item['article']} {item['title']}"
        lines.append(f"{name:<56}{item['assessed']:>9}{item['infringement']:>7}{item['indeterminate']:>8}")
    if report["findings"]:
        lines.append("")
    for finding in report["findings"]:
        lines.append(f"[{finding['status'].upper()}] {finding['article']} {finding['start']} -> {finding['end']}")
        lines.append(f"    {finding['explanation']}")
    lines += ["", "Not modelled:"]
    lines += [f"  - {item}" for item in report["not_modelled"]]
    lines.append("=" * 60)
    return lines
