"""Data preparation behind the GUI views: activity days, distances, totals,
detailed-speed blocks, driver names per date, calibration and driving-rule text.

Pure functions (no Tk), moved out of ``app/gui.py`` unchanged; ``app.gui``
re-exports every name, so callers and tests that use ``app.gui.<name>`` are
unaffected.
"""

from app.gui_day_detail import _activity_to_iso
from app.i18n import _
from core.utils.activity_stats import QUALIFYING_BREAK_MIN, RULE_CONTINUOUS_DRIVING, RULE_DAILY_DRIVING
from datetime import datetime, timedelta, timezone


def _activity_days(activities):
    """Return one file's activity days as ``[(sort_key, display_text), ...]``.

    The sort key is the ISO form :func:`_activity_to_iso` derives, because the
    decoders emit ``dd/mm/yyyy`` (which sorts lexicographically wrong); the
    display text is the day exactly as the file recorded it, like the Date
    column of the Daily-Activities dashboard. A day recorded twice (two
    download sections, or both card slots) is counted once.
    """
    days = {}
    for record in activities if isinstance(activities, list) else []:
        if not isinstance(record, dict):
            continue
        raw = record.get("date")
        if raw in (None, ""):
            continue
        days.setdefault(_activity_to_iso(str(raw)), str(raw))
    return sorted(days.items())


def _utc_speed_block(block):
    """Return a block's UTC start and raw samples, or ``None`` if invalid."""
    if not isinstance(block, dict):
        return None
    timestamp = block.get("timestamp") or block.get("begin")
    samples = block.get("_chart_speeds_kmh", block.get("speeds_kmh"))
    if not isinstance(timestamp, str) or not isinstance(samples, list):
        return None
    try:
        start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (start.replace(tzinfo=timezone.utc) if start.tzinfo is None
            else start.astimezone(timezone.utc)), samples


def _attach_day_distance(days, is_vu):
    """Store each day's distance as ``_day_km`` and return ``{id(day): km}``.

    *days* must be in chronological order. A VU activity block carries an
    odometer reading, so its distance is the delta from the previous day. A
    driver-card activity record carries no odometer at all — only
    ActivityDayDistance (Annex 1B §2.24), the kilometres driven that day — so
    the day's distance is used as-is. Differencing it against the previous day,
    as the card route used to, produced a number with no meaning (and left the
    day at 0 km in the tree, which only ever looked at VU days).
    """
    distances = {}
    prev_odo = 0
    for day in days:
        odo = day.get("odometer_km", 0) or 0
        km = 0
        if is_vu and prev_odo and odo and odo > prev_odo:
            km = odo - prev_odo
        if not km:
            km = int(day.get("day_distance_km") or 0)
        if odo:
            prev_odo = odo
        day["_day_km"] = km
        distances[id(day)] = km
    return distances


def _compute_activity_totals(changes, recorded_until=None):
    """Return dict {ACTIVITY: total_minutes} from a list of activity changes.

    Changes are grouped per card slot (driver) first, so crew days (two
    drivers recording simultaneously in slots ``First``/``Second``) keep
    their timelines independent.

    Drive/Work durations are summed across slots (each driver accumulates
    independently).  Rest/Available durations are kept at the **maximum**
    across slots because they share the same 24h day and cannot exceed it.
    """
    from core.utils.activity_stats import compute_activity_totals as _shared
    return _shared(changes, recorded_until)


def _driver_names_by_date(activity_list, iw_records, slot_name):
    """Return ``{date_iso: {driver name}}`` for one VU slot view.

    Each card insertion/withdrawal record (VuCardIWRecord) is walked day by
    day and a driver is attached to a day when that day's ``card_inserted``
    activity changes put the card in *slot_name*. Only days that carry such a
    change can ever match, so the walk is clipped to the range of those days:
    the decoders accept a withdrawal time up to 2100, and one corrupt record
    used to cost ~36 000 iterations (each re-scanning every change) on the Tk
    thread, freezing the GUI. For sane data the result is unchanged.
    """
    # (date_iso, minute_of_day) -> slot, from the unfiltered activity changes
    slot_by_minute: dict[tuple[str, int], str] = {}
    for day_data in activity_list:
        if not isinstance(day_data, dict):
            continue
        date_iso = _activity_to_iso(str(day_data.get("date", "")))
        for ch in day_data.get("changes") or []:
            if not isinstance(ch, dict) or not ch.get("card_inserted"):
                continue
            t = ch.get("time", "")
            if isinstance(t, str) and ":" in t:
                try:
                    h, m = t.split(":")[:2]
                    minute = int(h) * 60 + int(m)
                except ValueError:
                    continue
                slot = str(ch.get("slot") or "")
                if slot:
                    slot_by_minute[(date_iso, minute)] = slot
    # First slot seen per day: the "any time on this day" fallback.
    first_slot_by_day: dict[str, str] = {}
    for (d, _m), s in slot_by_minute.items():
        first_slot_by_day.setdefault(d, s)
    known_days = []
    for d in first_slot_by_day:
        try:
            known_days.append(datetime.strptime(d, "%Y-%m-%d").date())
        except ValueError:
            pass
    iw_by_date: dict[str, set] = {}
    if not known_days:
        return iw_by_date
    first_day, last_day = min(known_days), max(known_days)

    for iw in iw_records:
        if not isinstance(iw, dict):
            continue
        name = f"{iw.get('holder_first_names','')} {iw.get('holder_surname','')}".strip()
        if not name or name == "N/A N/A":
            continue
        ins_str = iw.get("insertion_time", "")
        ins_dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                ins_dt = datetime.strptime(ins_str[:19], fmt)
            except (ValueError, IndexError, TypeError):
                pass
        if ins_dt is None:
            continue
        wit_str = iw.get("withdrawal_time", "")
        wit_dt = None
        if isinstance(wit_str, str) and wit_str:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    wit_dt = datetime.strptime(wit_str[:19], fmt)
                except (ValueError, IndexError):
                    pass
        if wit_dt is None:
            wit_dt = ins_dt
        current = max(ins_dt.date(), first_day)
        end = min(wit_dt.date(), last_day)
        while current <= end:
            day_iso = current.isoformat()
            iw_slot = ""
            # Look for a card_inserted event within 2 minutes on the insertion day
            if current == ins_dt.date():
                ins_minute = ins_dt.hour * 60 + ins_dt.minute
                for offset in range(-2, 3):
                    check_min = ins_minute + offset
                    if 0 <= check_min < 1440:
                        iw_slot = slot_by_minute.get((day_iso, check_min), "")
                        if iw_slot:
                            break
            if not iw_slot:
                # Fallback: use card_inserted from any time on this day
                iw_slot = first_slot_by_day.get(day_iso, "")
            if iw_slot in ("First", "Second") and iw_slot == slot_name:
                iw_by_date.setdefault(day_iso, set()).add(name)
            current += timedelta(days=1)
    return iw_by_date


def _calibration_days_left(next_date, now=None):
    """Whole days from ``now`` to the next calibration date, or ``None``.

    Accepts a ``datetime`` or the two string shapes the decoders produce: ISO
    8601 (G2, ``2025-01-21T09:04:31+00:00``, sometimes with ``Z`` or without
    an offset) and the G1 ``DD/MM/YYYY[ HH:MM]`` form. A value without a time
    zone is read as UTC: comparing a naive date with an aware ``now`` used to
    raise ``TypeError``, which the caller swallowed, so the "calibration
    expired / due soon" flag silently disappeared.
    """
    from datetime import datetime, timezone
    if now is None:
        now = datetime.now(timezone.utc)
    nd = None
    if isinstance(next_date, datetime):
        nd = next_date
    elif isinstance(next_date, str) and next_date.strip():
        text = next_date.strip()
        try:
            nd = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                nd = datetime.strptime(text[:10], "%d/%m/%Y")
            except ValueError:
                return None
    if nd is None:
        return None
    if nd.tzinfo is None:
        nd = nd.replace(tzinfo=timezone.utc)
    return (nd - now).days


def _fmt_duration_minutes(mins):
    """Render a minute count as 'Xh Ym'."""
    return f"{mins // 60}h {mins % 60:02d}m"


def _driving_rule_explanation(breaches):
    """One tooltip line per broken driving-time rule, with the measured value.

    The rules come from Regulation (EC) 561/2006 — art. 6(1) (daily driving)
    and art. 7 (continuous driving) — see
    :func:`core.utils.activity_stats.evaluate_driving_rules`. Each line states
    what was measured and against which limit, in the same duration format the
    Drive column uses, so the flag can be checked against the numbers on
    screen instead of being taken on trust.
    """
    lines = []
    for breach in breaches:
        if breach.rule == RULE_DAILY_DRIVING:
            lines.append(_("Daily driving {driven} \u2014 limit {limit}").format(
                driven=_fmt_duration_minutes(breach.measured_min),
                limit=_fmt_duration_minutes(breach.limit_min)))
        elif breach.rule == RULE_CONTINUOUS_DRIVING:
            lines.append(_("Continuous driving {driven} without a {pause} min "
                           "break \u2014 limit {limit}").format(
                driven=_fmt_duration_minutes(breach.measured_min),
                pause=QUALIFYING_BREAK_MIN,
                limit=_fmt_duration_minutes(breach.limit_min)))
    return "\n".join(lines)


def detailed_speed_by_day(data, on_progress=None):
    """Return UTC detailed-speed samples grouped by ISO date.

    *on_progress* is called once per speed block. The GUI passes its event-loop
    pump there (see ``TachoExplorer._pump_render``): one block holds thousands
    of one-second samples, so a file's worth of them is long enough to freeze
    the busy bar if the loop is never given a turn.
    """
    grouped = {}
    blocks = list(data.get("speed_blocks") or [])
    for block in blocks:
        if on_progress is not None:
            on_progress()
        decoded = _utc_speed_block(block)
        if decoded is None:
            continue
        start, samples = decoded
        for offset, speed in enumerate(samples):
            if not isinstance(speed, int) or speed == 0xFF:
                continue
            moment = start + timedelta(seconds=offset)
            day = moment.date().isoformat()
            grouped.setdefault(day, {})[moment.hour * 3600 + moment.minute * 60 + moment.second] = speed
    return {day: sorted(samples.items()) for day, samples in grouped.items()}


def detailed_speed_blocks_by_day(blocks, on_progress=None):
    """Group raw records by every UTC day for which they contain a sample.

    *on_progress* behaves as in :func:`detailed_speed_by_day`.
    """
    grouped = {}
    for block in blocks if isinstance(blocks, list) else []:
        if on_progress is not None:
            on_progress()
        decoded = _utc_speed_block(block)
        if decoded is None:
            continue
        start, samples = decoded
        days = set()
        for offset, speed in enumerate(samples):
            if isinstance(speed, int) and speed != 0xFF:
                days.add((start + timedelta(seconds=offset)).date().isoformat())
        for day in days:
            grouped.setdefault(day, []).append(block)
    return grouped
