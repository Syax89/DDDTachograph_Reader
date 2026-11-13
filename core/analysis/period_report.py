"""Monthly activity report per driver (card downloads) and per vehicle (VU downloads).

Several downloads of the same driver or vehicle usually overlap: a card
downloaded every 28 days repeats the days already in the previous file, and its
first and last days are partial. The report therefore merges the *days* of all
inputs per entity before adding anything up: each calendar day is counted once,
taken from the download that holds it most completely (a day without a
``recorded_until`` cut beats a cut one, a later cut beats an earlier one).

Per entity and month it gives the recorded days, the days with driving, the
Drive/Work/Rest/Available/Unknown minutes (the same slot-aware arithmetic as
every other view, :func:`core.utils.activity_stats.compute_activity_totals`),
the distance and — for drivers — the indicative Regulation (EC) No 561/2006
findings of :mod:`core.analysis.regulation_561`, counted in the month their
period starts. The 561 analysis runs once over the driver's merged timeline, so
a period that spans two downloads is judged as one.

Distance: a driver-card day carries its own ActivityDayDistance; a VU day
carries an odometer reading, so its distance is the increase from the previous
recorded day (0 when the previous day is not the calendar day before, so a gap
in the data never lands on one day). This mirrors the GUI's
``_attach_day_distance``.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta

from core.utils.activity_stats import compute_activity_totals, recorded_until_seconds

COLUMNS = (
    ("entity_type", "Type"),
    ("entity_id", "Card / vehicle"),
    ("entity_name", "Name / VIN"),
    ("month", "Month"),
    ("days_recorded", "Days recorded"),
    ("days_driving", "Days with driving"),
    ("drive_min", "Drive (min)"),
    ("work_min", "Work (min)"),
    ("rest_min", "Rest (min)"),
    ("available_min", "Available (min)"),
    ("unknown_min", "Unknown (min)"),
    ("distance_km", "Distance (km)"),
    ("infringements_561", "561 infringements (indicative)"),
    ("indeterminate_561", "561 indeterminate"),
    ("sources", "Source files"),
)

_TOTAL_KEYS = {"DRIVE": "drive_min", "WORK": "work_min", "REST": "rest_min",
               "AVAILABLE": "available_min", "UNKNOWN": "unknown_min"}


def _day_date(value) -> date | None:
    try:
        return datetime.strptime(str(value), "%d/%m/%Y").date()
    except ValueError:
        return None


def _entity(result: dict) -> tuple[str, str, str] | None:
    """``(type, id, name)`` of a download, or ``None`` when it cannot be told."""
    meta = result.get("metadata") or {}
    if meta.get("is_vu"):
        vehicle = result.get("vehicle") or {}
        plate = str(vehicle.get("plate") or "").strip()
        vin = str(vehicle.get("vin") or "").strip()
        if not plate and not vin:
            return None
        return "vehicle", plate or vin, vin
    driver = result.get("driver") or {}
    card = str(driver.get("card_number") or "").strip()
    if not card:
        return None
    name = " ".join(part for part in (str(driver.get("surname") or "").strip(),
                                      str(driver.get("firstname") or "").strip()) if part)
    return "driver", card, name


def _completeness(day: dict) -> tuple[bool, int]:
    cut = recorded_until_seconds(day)
    return (cut is None, cut or 0)


def merge_days(results: list[tuple[str, dict]]) -> dict:
    """``{(type, id): {"name", "sources", "days": {date: day_record}}}`` over all inputs."""
    entities: dict = {}
    for source, result in results:
        entity = _entity(result or {})
        if entity is None:
            continue
        kind, ident, name = entity
        slot = entities.setdefault((kind, ident), {"name": name, "sources": [], "days": {}})
        if name and not slot["name"]:
            slot["name"] = name
        slot["sources"].append(source)
        for day in result.get("activities") or []:
            if not isinstance(day, dict):
                continue
            when = _day_date(day.get("date"))
            if when is None:
                continue
            held = slot["days"].get(when)
            if held is None or _completeness(day) > _completeness(held):
                slot["days"][when] = day
    return entities


def _distances(kind: str, days: dict) -> dict:
    out = {}
    previous_date, previous_odo = None, None
    for when in sorted(days):
        day = days[when]
        km = 0
        odo = day.get("odometer_km")
        if kind == "vehicle":
            if (isinstance(odo, (int, float)) and previous_odo
                    and previous_date == when - timedelta(days=1) and odo > previous_odo):
                km = int(odo - previous_odo)
        if not km:
            raw = day.get("day_distance_km")
            km = int(raw) if isinstance(raw, (int, float)) and raw > 0 else 0
        if isinstance(odo, (int, float)) and odo:
            previous_date, previous_odo = when, odo
        out[when] = km
    return out


def build_period_report(results: list[tuple[str, dict]]) -> list[dict]:
    """One row per entity and month, sorted by type, entity and month.

    ``results`` is ``[(source_name, parsed_result), ...]``. Inputs whose driver
    card number or vehicle plate/VIN is unknown are left out.
    """
    rows: list[dict] = []
    for (kind, ident), slot in sorted(merge_days(results).items()):
        days = slot["days"]
        distances = _distances(kind, days)
        months: dict = {}
        for when in sorted(days):
            day = days[when]
            row = months.setdefault(f"{when:%Y-%m}", {
                "entity_type": kind, "entity_id": ident,
                "entity_name": slot["name"], "month": f"{when:%Y-%m}",
                "days_recorded": 0, "days_driving": 0,
                **{key: 0 for key in _TOTAL_KEYS.values()},
                "distance_km": 0, "infringements_561": "", "indeterminate_561": "",
                "sources": ", ".join(sorted(set(slot["sources"]))),
            })
            totals = compute_activity_totals(day.get("changes") or [],
                                             recorded_until_seconds(day),
                                             one_driver=kind == "driver")
            row["days_recorded"] += 1
            if totals["DRIVE"]:
                row["days_driving"] += 1
            for activity, key in _TOTAL_KEYS.items():
                row[key] += totals[activity]
            row["distance_km"] += distances[when]
        if kind == "driver" and days:
            _add_561_counts(months, [days[when] for when in sorted(days)])
        rows.extend(months[month] for month in sorted(months))
    return rows


def _add_561_counts(months: dict, days: list[dict]) -> None:
    from core.analysis.regulation_561 import analyse_days
    report = analyse_days(days)
    for row in months.values():
        row["infringements_561"] = 0
        row["indeterminate_561"] = 0
    for finding in report.get("findings") or []:
        month = str(finding.get("start") or "")[:7]
        row = months.get(month)
        if row is None:
            continue
        if finding.get("status") == "infringement":
            row["infringements_561"] += 1
        elif finding.get("status") == "indeterminate":
            row["indeterminate_561"] += 1


def _hm(minutes) -> str:
    return f"{int(minutes) // 60}:{int(minutes) % 60:02d}"


def format_table(rows: list[dict]) -> list[str]:
    """Plain-text table for the terminal (durations as h:mm)."""
    header = ("Type", "Card / vehicle", "Month", "Days", "Drv days", "Drive", "Work",
              "Rest", "Avail", "Unknown", "km", "561 inf.", "561 ind.")
    lines = [" | ".join(header)]
    for r in rows:
        lines.append(" | ".join(str(v) for v in (
            r["entity_type"], r["entity_id"], r["month"], r["days_recorded"],
            r["days_driving"], _hm(r["drive_min"]), _hm(r["work_min"]),
            _hm(r["rest_min"]), _hm(r["available_min"]), _hm(r["unknown_min"]),
            r["distance_km"], r["infringements_561"], r["indeterminate_561"])))
    if not rows:
        lines.append("(no driver card or vehicle unit with a known identity)")
    lines.append("561 counts are indicative only, not a legal determination.")
    return lines


def write_period_report(rows: list[dict], path: str) -> None:
    """Write ``rows`` as ``.csv`` (semicolon, UTF-8 with BOM) or ``.xlsx``."""
    if path.lower().endswith(".xlsx"):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = "Period report"
        sheet.append([label for _key, label in COLUMNS])
        for r in rows:
            sheet.append([r[key] for key, _label in COLUMNS])
        sheet.freeze_panes = "A2"
        book.save(path)
        return
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([label for _key, label in COLUMNS])
        for r in rows:
            writer.writerow([_csv_safe(r[key]) for key, _label in COLUMNS])


def _csv_safe(value):
    # Same guard as the other CSV exports: a cell must never start a formula.
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else value
