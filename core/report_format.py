"""Shared human-readable formatting for report exports (Excel, CSV, PDF).

Centralises the value/record formatting used by every export so the output is
consistent: ISO timestamps become ``YYYY-MM-DD HH:MM``, nested tachograph
structures (card numbers, GNSS positions, vehicle registrations) are rendered
as compact text, internal bookkeeping keys are hidden, and column names are
humanised (``vehicle_plate`` → ``Vehicle Plate``).
"""
import re

from core.i18n import tr

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
]


def fmt_iso(s):
    """ISO timestamp (2025-04-23T08:37:00+00:00) → '2025-04-23 08:37'."""
    m = _ISO_RE.match(s)
    return f"{m.group(1)} {m.group(2)}" if m else s


def humanize_key(key):
    """'vehicle_plate' → 'Vehicle Plate', 'gnss_accuracy' → 'GNSS Accuracy'.
    The result goes through the i18n layer (see :mod:`core.i18n`)."""
    words = str(key).split("_")
    out = []
    for w in words:
        if not w:
            continue
        out.append(w.upper() if w.lower() in _ACRONYMS else w.capitalize())
    return tr(" ".join(out)) if out else str(key)


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


def expand_activities(activities):
    """Flatten daily activity blocks into one row per activity change."""
    rows = []
    H = {k: tr(k) for k in ("Date", "Time", "Activity", "Odometer km",
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
                         H["Activity"]: tr("(no event)"),
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
                H["Card"]: "" if card is None else tr("Inserted" if card else "Not inserted"),
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
        (tr("File"), meta.get("filename", "N/A")),
        (tr("Generation"), meta.get("generation", "N/A")),
        (tr("Source"), tr("Vehicle Unit (VU)") if meta.get("is_vu") else tr("Driver Card")),
        (tr("File size"), f"{meta.get('file_size_bytes', 0):,} bytes".replace(",", " ")),
        (tr("Coverage"), f"{meta.get('coverage_pct', 0)}%"),
        (tr("Integrity"), meta.get("integrity_check", "N/A")),
        (tr("Parsed at"), fmt_value(meta.get("parsed_at", ""))),
    ]
    if meta.get("app_version"):
        rows.append((tr("Reader version"), meta["app_version"]))
    if sv.get("summary"):
        rows.append((tr("Signature verification"), sv["summary"]))
    if efv.get("summary"):
        rows.append((tr("EF card data signatures"), efv["summary"]))

    if driver.get("surname", "N/A") != "N/A" or driver.get("card_number", "N/A") != "N/A":
        rows.append(("", ""))
        rows.append((tr("Driver"), f"{driver.get('firstname', '')} {driver.get('surname', '')}".strip()))
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
                rows.append((tr(f"Vehicle {humanize_key(key)}"), fmt_value(val)))
    return rows


def section_tables(data, max_rows=None):
    """Yield (label, headers, rows) for every populated export section."""
    for key, label in EXPORT_SECTIONS:
        items = data.get(key) or []
        if not items:
            continue
        if key == "activities":
            if not isinstance(items, list):
                items = [items]
            recs = expand_activities(items)
            if not recs:
                continue
            headers = list(recs[0].keys())
            rows = [[r.get(h, "") for h in headers] for r in recs]
        elif key == "ef_signature_verification" and isinstance(items, dict):
            ef_results = items.get("ef_results") or []
            if not ef_results:
                continue
            headers, rows = records_to_table(ef_results)
        else:
            if not isinstance(items, list):
                items = [items]
            if all(not isinstance(x, dict) for x in items):
                headers, rows = [tr("Value")], [[fmt_value(x)] for x in items]
            else:
                headers, rows = records_to_table(items)
        if not rows:
            continue
        truncated = False
        if max_rows is not None and len(rows) > max_rows:
            rows = rows[:max_rows]
            truncated = True
        yield tr(label), headers, rows, truncated
