"""Shared human-readable formatting for report exports (Excel, CSV, PDF).

Centralises the value/record formatting used by every export so the output is
consistent: ISO timestamps become ``YYYY-MM-DD HH:MM``, nested tachograph
structures (card numbers, GNSS positions, vehicle registrations) are rendered
as compact text, internal bookkeeping keys are hidden, and column names are
humanised (``vehicle_plate`` → ``Vehicle Plate``).
"""
import re

# Tachograph "data not available" sentinels.
_NOT_AVAILABLE_INTS = {0xFFFFFF, 0xFFFFFFFF}
_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?")

# Internal bookkeeping keys never shown in exports.
HIDDEN_KEYS = {"source", "raw_tail_hex", "raw_hex", "payload_hex", "header_hex",
               "non_zero_regions", "name", "size", "confidence", "counters_raw"}
# Descriptive columns pushed to the table start / technical ones to the end.
LEADING_KEYS = ["description", "purpose", "control_type_label", "calibration_purpose_label", "timestamp", "date", "begin", "begin_time", "start"]
TRAILING_KEYS = ["record_type", "type_code"]

# Acronyms kept upper-case when humanising keys.
_ACRONYMS = {"vin", "gnss", "vu", "its", "id", "km", "kmh", "iw", "ic", "icc",
             "rsa", "ecdsa", "msca", "erca", "trep", "ad", "g1", "g2"}

# Section key → export label, in presentation order. Shared by Excel/CSV/PDF.
EXPORT_SECTIONS = [
    ("activities", "Daily Activities"),
    ("vehicle_sessions", "Vehicles Used"),
    ("vehicle_units", "Vehicle Units Used"),
    ("events", "Events"),
    ("faults", "Faults"),
    ("places", "Places"),
    ("specific_conditions", "Specific Conditions"),
    ("calibrations", "Calibrations"),
    ("control_activities", "Control Activities"),
    ("card_downloads", "Card Downloads"),
    ("gnss_ad_records", "GNSS Accumulated Driving"),
    ("gnss_places", "GNSS Places"),
    ("border_crossings", "Border Crossings"),
    ("load_unload_records", "Load / Unload"),
    ("load_sensor_data", "Load Sensor Data"),
    ("trailer_registrations", "Trailer Registrations"),
    ("overspeeding_events", "Overspeeding Events"),
    ("overspeeding_control", "Overspeeding Control"),
    ("power_interruptions", "Power Interruptions"),
    ("company_locks", "Company Locks"),
    ("vu_identifications", "VU Identifications"),
    ("sensor_pairings", "Sensor Pairings"),
    ("sensor_gnss_couplings", "Sensor GNSS Couplings"),
    ("card_iw_records", "Card Insertion / Withdrawal"),
    ("card_records", "Card Records"),
    ("time_adjustments", "Time Adjustments"),
    ("its_consents", "ITS Consents"),
    ("download_activities", "Download Activities"),
    ("speed_blocks", "Detailed Speed"),
    ("workshops", "Calibration Workshops"),
    ("inserted_drivers", "Inserted Drivers"),
    ("company_holders", "Company Holders"),
    ("signed_daily_records", "Signed Daily Records"),
    ("locations", "GPS Locations"),
    ("ef_signature_verification", "EF Card Data Signatures"),
    ("certificates", "Driver Card Certificates"),
    ("sensor_daily_records", "Sensor Daily Records"),
]

# Dict-style sections exposed as key/value sheets in Excel/CSV/PDF.
DICT_SECTIONS = [
    ("card_issuer", "Card Issuer"),
    ("card_application", "Card Application"),
    ("card_chip", "IC Chip"),
    ("card_icc", "ICC Identification"),
    ("vu_overview", "VU Overview"),
    ("vu_info", "VU Information"),
    ("company_info", "VU Company Info"),
    ("sensor_info", "Sensor Identification"),
]

SECTION_DESCRIPTIONS = {
    "activities": "Daily activity breakdown (times in UTC). "
                  "Drive, Work, Rest, Available hours per day with monthly subtotals.",
    "vehicle_sessions": "Vehicles used by the driver: odometer range, first/last use dates, "
                        "registration plate and nation.",
    "vehicle_units": "Card Vehicle Units — serial numbers of VUs that have read the card.",
    "events": "Logged events (card insertion, power loss, security breach, motion conflicts, etc.).",
    "faults": "Logged faults (sensor, card, display, printer, internal VU failures).",
    "places": "Start and end locations recorded at the beginning and end of each daily work period.",
    "specific_conditions": "Specific driving conditions: ferry/train crossing, out-of-scope driving.",
    "calibrations": "Workshop calibration records with purpose, dates, workshop info, and VIN.",
    "control_activities": "Roadside control activity records (enforcement checks by authorities).",
    "card_downloads": "Timestamps of card data downloads performed by enforcement or company.",
    "gnss_ad_records": "GNSS accumulated driving records: position data with odometer heuristics.",
    "gnss_places": "GNSS-authenticated places visited (enhanced position with authentication status).",
    "border_crossings": "Border crossing records with country codes, timestamps, and GNSS position.",
    "load_unload_records": "Load and unload operation records with timestamps and odometer readings.",
    "load_sensor_data": "Axle load sensor data (weight per axle, if equipped).",
    "trailer_registrations": "Trailer coupling and decoupling registrations with plate numbers.",
    "overspeeding_events": "Overspeeding events with begin/end times, max speed, and average speed.",
    "overspeeding_control": "Last overspeeding control check timestamp and number of events since.",
    "power_interruptions": "Power supply interruption records (battery disconnections, power loss).",
    "company_locks": "Company lock-in and lock-out events (fleet operator access control).",
    "vu_identifications": "Vehicle Unit identification data: manufacturer, serial number, software version.",
    "sensor_pairings": "Motion sensor pairing records with the VU (sensor approval and serial numbers).",
    "sensor_gnss_couplings": "External GNSS sensor coupling records (satellite positioning sensor data).",
    "card_iw_records": "Driver card insertion and withdrawal events from VU memory.",
    "card_records": "Card record snapshots stored in the VU for each driver card seen.",
    "time_adjustments": "VU clock adjustment records (manual time changes by workshops or drivers).",
    "its_consents": "ITS (Intelligent Transport System) consent records for data transmission.",
    "download_activities": "VU download activity records (company or enforcement data extractions).",
    "speed_blocks": "Detailed speed data blocks: 60 speed samples per second, 1 block per second.",
    "workshops": "Calibration workshop records found in VU memory from previous calibrations.",
    "inserted_drivers": "Driver card information for each card inserted into the VU.",
    "company_holders": "Company card holder identification data.",
    "signed_daily_records": "Cryptographically signed daily activity records.",
    "locations": "GPS coordinates captured during driving activity.",
    "ef_signature_verification": "Card EF (Elementary File) digital signature verification results.",
    "previous_vehicle": "Previous vehicle used before the current vehicle assignment.",
    "calibration_vins": "VINs (Vehicle Identification Numbers) extracted from calibration records.",
    "card_numbers": "Card numbers observed by the VU from inserted driver and company cards.",
    "vu_record_arrays": "Raw VU RecordArray data: structural audit of all VU memory sections.",
    "sensor_daily_records": "Motion sensor daily speed records with min/max/average speeds.",
}


def fmt_iso(s):
    """ISO timestamp (2025-04-23T08:37:00+00:00) → '2025-04-23 08:37'."""
    m = _ISO_RE.match(s)
    return f"{m.group(1)} {m.group(2)}" if m else s


def humanize_key(key):
    """'vehicle_plate' → 'Vehicle Plate', 'gnss_accuracy' → 'GNSS Accuracy'."""
    words = str(key).split("_")
    out = []
    for w in words:
        if not w:
            continue
        out.append(w.upper() if w.lower() in _ACRONYMS else w.capitalize())
    return " ".join(out) if out else str(key)


def _fmt_coords(lat, lon):
    if lat is None or lon is None:
        return ""
    return f"{lat:.5f}, {lon:.5f}"


def _fmt_dict(d):
    """Readable summary of known tachograph nested structures."""
    if d.get("present") is False:
        return "—"
    geo = d.get("geo") if isinstance(d.get("geo"), dict) else None
    if geo and ("latitude_deg" in geo or "longitude_deg" in geo):
        return _fmt_coords(geo.get("latitude_deg"), geo.get("longitude_deg"))
    if "latitude_deg" in d or "longitude_deg" in d:
        return _fmt_coords(d.get("latitude_deg"), d.get("longitude_deg"))
    if "card_number" in d:
        # FullCardNumber — an empty number means no card in the slot.
        return str(d["card_number"]).strip() or "—"
    if "plate" in d:
        plate = (d.get("plate") or "").strip()
        nation = (d.get("nation") or "").strip()
        if not plate or set(plate) <= {"?"}:
            return "—"
        return f"{nation} {plate}".strip() if "No information" not in nation else plate
    items = ", ".join(f"{humanize_key(k)}: {fmt_value(v)}"
                      for k, v in d.items()
                      if k not in HIDDEN_KEYS and not str(k).startswith("_"))
    return items if len(items) <= 120 else items[:120] + "…"


def fmt_value(v):
    """Format any decoded value as compact human-readable text."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s if s else "0"
    if isinstance(v, int):
        if v in _NOT_AVAILABLE_INTS:
            return "N/A"
        return f"{v:,}".replace(",", " ") if abs(v) >= 10000 else str(v)
    if isinstance(v, (bytes, bytearray)):
        h = v.hex()
        return h if len(h) <= 64 else h[:64] + "…"
    if isinstance(v, dict):
        return _fmt_dict(v)
    if isinstance(v, (list, tuple, set, frozenset)):
        v = sorted(v) if isinstance(v, (set, frozenset)) else list(v)
        if not v:
            return ""
        if all(not isinstance(x, (dict, list)) for x in v):
            text = ", ".join(fmt_value(x) for x in v)
            return text if len(text) <= 200 else text[:200] + "…"
        return f"[{len(v)} items]"
    if isinstance(v, str):
        return fmt_iso(v)
    return str(v)


def _visible_columns(records):
    """Ordered union of visible record keys: leading, natural, trailing."""
    natural = []
    present = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for k in rec:
            present.add(k)
            if (k in HIDDEN_KEYS or k in LEADING_KEYS or k in TRAILING_KEYS
                    or k in natural or str(k).startswith("_")):
                continue
            natural.append(k)
    cols = [k for k in LEADING_KEYS if k in present]
    cols += natural
    cols += [k for k in TRAILING_KEYS if k in present]
    return cols


def records_to_table(records):
    """Convert a list of record dicts to (header_labels, rows) of formatted
    strings, hiding internal keys and humanising the column names."""
    records = [r for r in records if isinstance(r, dict)]
    if not records:
        return [], []
    cols = _visible_columns(records)
    headers = [humanize_key(c) for c in cols]
    rows = [[fmt_value(rec.get(c)) for c in cols] for rec in records]
    return headers, rows


def _time_to_minutes(time_str):
    parts = time_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def _hours_str(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


ACTIVITY_COLS = ["Drive", "Work", "Rest", "Available", "Unknown"]
ACTIVITY_COL_KEYS = ["drive", "work", "rest", "available", "unknown"]


def _compute_day_hours(day):
    changes = day.get("changes") or []
    buckets = {"drive": 0, "work": 0, "rest": 0, "available": 0, "unknown": 0}
    key_map = {"DRIVE": "drive", "WORK": "work", "REST": "rest",
               "AVAIL": "available", "AVAILABLE": "available"}
    if not isinstance(changes, list) or len(changes) < 2:
        return buckets, 0
    for i in range(len(changes)):
        ch = changes[i]
        if not isinstance(ch, dict):
            continue
        act = str(ch.get("activity", "")).upper()
        bucket = key_map.get(act, "unknown")
        t1 = _time_to_minutes(str(ch.get("time", "00:00")))
        if i + 1 < len(changes):
            t2 = _time_to_minutes(str(changes[i + 1].get("time", "00:00")))
        else:
            t2 = 24 * 60
        if t2 < t1:
            t2 += 24 * 60
        buckets[bucket] += t2 - t1
    total = sum(buckets.values())
    return buckets, total


def build_monthly_activity_report(activities):
    months = {}
    for day in activities:
        if not isinstance(day, dict):
            continue
        date_str = str(day.get("date", ""))
        month_key = date_str[-7:] if len(date_str) >= 7 else date_str
        months.setdefault(month_key, []).append(day)

    headers = ["Date", "Odometer km", "Drive (h)", "Work (h)",
               "Rest (h)", "Available (h)", "Unknown (h)", "Total (h)"]
    rows = []
    for month_key in sorted(months.keys()):
        days = sorted(months[month_key], key=lambda d: str(d.get("date", "")))
        month_totals = {"drive": 0, "work": 0, "rest": 0, "available": 0, "unknown": 0}
        month_total = 0
        for day in days:
            date_str = str(day.get("date", ""))
            km = fmt_value(day.get("odometer_km", 0))
            buckets, total = _compute_day_hours(day)
            unknown_str = _hours_str(buckets["unknown"])
            if buckets["unknown"] > 0:
                unknown_str = "\u26a0 " + unknown_str
            rows.append([
                date_str, km,
                _hours_str(buckets["drive"]),
                _hours_str(buckets["work"]),
                _hours_str(buckets["rest"]),
                _hours_str(buckets["available"]),
                unknown_str,
                _hours_str(total),
            ])
            for k in month_totals:
                month_totals[k] += buckets[k]
            month_total += total
        rows.append([
            f"{month_key} TOTAL", "",
            _hours_str(month_totals["drive"]),
            _hours_str(month_totals["work"]),
            _hours_str(month_totals["rest"]),
            _hours_str(month_totals["available"]),
            _hours_str(month_totals["unknown"]),
            _hours_str(month_total),
        ])
    return headers, rows


def expand_activities(activities):
    """Flatten daily activity blocks into one row per activity change."""
    rows = []
    H = {k: k for k in ("Date", "Time", "Activity", "Odometer km",
                            "Slot", "Crew", "Card", "Driver")}
    for day in activities:
        if not isinstance(day, dict):
            continue
        date_str = fmt_value(day.get("date", day.get("timestamp", "N/A")))
        km = day.get("odometer_km", day.get("odometer_midnight", 0))
        driver = day.get("driver", "")
        changes = day.get("changes", [])
        if not isinstance(changes, list) or not changes:
            rows.append({H["Date"]: date_str, H["Time"]: "",
                         H["Activity"]: "(no event)",
                         H["Odometer km"]: fmt_value(km), H["Slot"]: "",
                         H["Crew"]: "", H["Card"]: "", H["Driver"]: driver})
            continue
        for ev in changes:
            if not isinstance(ev, dict):
                continue
            minute = ev.get("minute")
            time_str = ev.get("time", "")
            if not time_str and isinstance(minute, int):
                time_str = f"{minute // 60:02d}:{minute % 60:02d}"
            card = ev.get("card_inserted")
            rows.append({
                H["Date"]: date_str,
                H["Time"]: time_str,
                H["Activity"]: str(ev.get("activity", ev.get("type", ""))).capitalize(),
                H["Odometer km"]: fmt_value(km),
                H["Slot"]: fmt_value(ev.get("slot", "")),
                H["Crew"]: fmt_value(ev.get("crew", "")),
                H["Card"]: "" if card is None else ("Inserted" if card else "Not inserted"),
                H["Driver"]: driver,
            })
    return rows


def summary_rows(data):
    """(Field, Value) rows for the file/driver/vehicle summary."""
    meta = data.get("metadata", {})
    driver = data.get("driver", {})
    vehicle = data.get("vehicle", {})
    sv = data.get("signature_verification") or {}
    efv = data.get("ef_signature_verification") or {}

    rows = [
        ("File", meta.get("filename", "N/A")),
        ("Generation", meta.get("generation", "N/A")),
        ("Source", "Vehicle Unit (VU)" if meta.get("is_vu") else "Driver Card"),
        ("File size", f"{meta.get('file_size_bytes', 0):,} bytes".replace(",", " ")),
        ("Coverage", f"{meta.get('coverage_pct', 0)}%"),
        ("Integrity", meta.get("integrity_check", "N/A")),
        ("Parsed at", fmt_value(meta.get("parsed_at", ""))),
    ]
    if meta.get("app_version"):
        rows.append(("Reader version", meta["app_version"]))
    if sv.get("summary"):
        rows.append(("Signature verification", sv["summary"]))
    if efv.get("summary"):
        rows.append(("EF card data signatures", efv["summary"]))
    certs = data.get("certificates") or []
    if certs:
        rows.append(("Certificates", f"{len(certs)} decoded ({', '.join(sorted(set(c.get('format', '') for c in certs if c.get('format'))))})"))
    vu_certs = data.get("vu_certificates") or []
    if vu_certs:
        rows.append(("VU Certificates (CVC)", f"{len(vu_certs)} decoded"))

    if driver.get("surname", "N/A") != "N/A" or driver.get("card_number", "N/A") != "N/A":
        rows.append(("", ""))
        rows.append(("Driver", f"{driver.get('firstname', '')} {driver.get('surname', '')}".strip()))
        for key in ("card_number", "issuing_nation", "expiry_date", "birth_date",
                    "licence_number", "preferred_language"):
            val = driver.get(key, "N/A")
            if val and val != "N/A":
                rows.append((humanize_key(key), fmt_value(val)))

    if vehicle.get("plate", "N/A") != "N/A" or vehicle.get("vin", "N/A") != "N/A":
        rows.append(("", ""))
        for key in ("plate", "vin", "registration_nation"):
            val = vehicle.get(key, "N/A")
            if val and val != "N/A":
                rows.append((f"Vehicle {humanize_key(key)}", fmt_value(val)))
    return rows


def section_tables(data, max_rows=None):
    """Yield (label, headers, rows, truncated) for every populated export section."""
    for key, label in EXPORT_SECTIONS:
        items = data.get(key) or []
        if not items:
            continue
        if key == "activities":
            if not isinstance(items, list):
                items = [items]
            headers, rows = build_monthly_activity_report(items)
            if not rows:
                continue
        elif key == "ef_signature_verification" and isinstance(items, dict):
            ef_results = items.get("ef_results") or []
            if not ef_results:
                continue
            headers, rows = records_to_table(ef_results)
        else:
            if not isinstance(items, list):
                items = [items]
            if all(not isinstance(x, dict) for x in items):
                headers, rows = ["Value"], [[fmt_value(x)] for x in items]
            else:
                headers, rows = records_to_table(items)
        if not rows:
            continue
        # Insert section description as first data row
        desc = SECTION_DESCRIPTIONS.get(key, "")
        if desc:
            desc_row = [desc] + [""] * (len(headers) - 1)
            rows.insert(0, desc_row)
        truncated = False
        if max_rows is not None and len(rows) > max_rows:
            rows = rows[:max_rows]
            truncated = True
        yield label, headers, rows, truncated

    for key, label in DICT_SECTIONS:
        section = data.get(key) or {}
        if not isinstance(section, dict) or not section:
            continue
        rows = []
        for k, v in section.items():
            formatted = fmt_value(v)
            if formatted:
                rows.append([humanize_key(k), formatted])
        if not rows:
            continue
        desc = SECTION_DESCRIPTIONS.get(key, "")
        if desc:
            rows.insert(0, [desc, ""])
        yield label, ["Field", "Value"], rows, False
