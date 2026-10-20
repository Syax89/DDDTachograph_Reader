"""Low-level decoding helpers shared by all field decoders: nations, code-page strings, dates, activity values and cyclic activity buffers (Annex 1B/1C primitives)."""

import struct
from datetime import datetime, timezone

from core.utils.logger import get_logger

_log = get_logger(__name__)


def mark_heuristic(results, section, fields):
    """Record that *fields* in *section* were recovered by an emergency
    heuristic rather than the deterministic (spec-offset) path.

    Stored under ``metadata.heuristic_fields`` so the GUI/exports can flag
    these values as inferred (low confidence). Deterministic parsing is always
    the primary path; this list stays empty for clean, spec-compliant files.
    """
    if not fields:
        return
    # Every heuristic site records a structured reason next to the field list, so
    # a fallback can always be explained (see core.parser.fallback_reasons).
    from core.parser.fallback_reasons import record_fallback_reason
    record_fallback_reason(results, route=section, detail=",".join(sorted(fields)))
    meta = results.setdefault("metadata", {})
    bucket = meta.setdefault("heuristic_fields", {})
    existing = set(bucket.get(section, []))
    existing.update(fields)
    bucket[section] = sorted(existing)


_CODEPAGE_ENCODINGS = {
    0x01: 'latin-1', 0x02: 'iso-8859-2', 0x03: 'iso-8859-3',
    0x04: 'iso-8859-4', 0x05: 'iso-8859-5', 0x06: 'iso-8859-6',
    0x07: 'iso-8859-7', 0x08: 'iso-8859-8', 0x09: 'iso-8859-9',
    0x0A: 'iso-8859-10', 0x0B: 'iso-8859-11', 0x0D: 'iso-8859-13',
    0x0E: 'iso-8859-14', 0x0F: 'iso-8859-15', 0x10: 'iso-8859-16',
}

# NationNumeric → NationAlpha (Annex 1B §2.101 / Annex 1C §2.100). The set of
# defined values is a hard prefix (0x01..0x35) followed by the special codes
# 0xFD/0xFE/0xFF; everything in between (0x36..0xFC) is unassigned.
_NATIONS = {
    0x00: "No information available",
    0x01: "A", 0x02: "AL", 0x03: "AND", 0x04: "ARM", 0x05: "AZ", 0x06: "B", 0x07: "BG",
    0x08: "BIH", 0x09: "BY", 0x0A: "CH", 0x0B: "CY", 0x0C: "CZ", 0x0D: "D", 0x0E: "DK",
    0x0F: "E", 0x10: "EST", 0x11: "F", 0x12: "FIN", 0x13: "FL", 0x14: "FO", 0x15: "UK",
    0x16: "GE", 0x17: "GR", 0x18: "H", 0x19: "HR", 0x1A: "I", 0x1B: "IRL", 0x1C: "IS",
    0x1D: "KZ", 0x1E: "L", 0x1F: "LT", 0x20: "LV", 0x21: "M", 0x22: "MC", 0x23: "MD",
    0x24: "MK", 0x25: "N", 0x26: "NL", 0x27: "P", 0x28: "PL", 0x29: "RO", 0x2A: "RSM",
    0x2B: "RUS", 0x2C: "S", 0x2D: "SK", 0x2E: "SLO", 0x2F: "TM", 0x30: "TR", 0x31: "UA",
    0x32: "V", 0x33: "YU", 0x34: "MNE", 0x35: "SRB", 0xFD: "EC", 0xFE: "EUR", 0xFF: "WLD"
}


def get_nation(code):
    """Map numeric nation code to ISO/Common code (Annex 1B)."""
    return _NATIONS.get(code, f"Unknown({code:02X})")


def is_known_nation(code):
    """True when *code* is a defined NationNumeric value (Annex 1B §2.101).

    NationNumeric is a single byte; unassigned values (0x36..0xFC, excluding the
    special codes 0xFD/0xFE/0xFF) are not valid nations.
    """
    return code in _NATIONS


# Short ISO/Common nation code → full English country name (Annex 1B).
_NATION_FULL_NAMES = {
    "A": "Austria", "AL": "Albania", "AND": "Andorra", "ARM": "Armenia",
    "AZ": "Azerbaijan", "B": "Belgium", "BG": "Bulgaria",
    "BIH": "Bosnia and Herzegovina", "BY": "Belarus", "CH": "Switzerland",
    "CY": "Cyprus", "CZ": "Czech Republic", "D": "Germany", "DK": "Denmark",
    "E": "Spain", "EST": "Estonia", "F": "France", "FIN": "Finland",
    "FL": "Liechtenstein", "FO": "Faroe Islands", "UK": "United Kingdom",
    "GE": "Georgia", "GR": "Greece", "H": "Hungary", "HR": "Croatia",
    "I": "Italy", "IRL": "Ireland", "IS": "Iceland", "KZ": "Kazakhstan",
    "L": "Luxembourg", "LT": "Lithuania", "LV": "Latvia", "M": "Malta",
    "MC": "Monaco", "MD": "Moldova", "MK": "North Macedonia", "N": "Norway",
    "NL": "Netherlands", "P": "Portugal", "PL": "Poland", "RO": "Romania",
    "RSM": "San Marino", "RUS": "Russia", "S": "Sweden", "SK": "Slovakia",
    "SLO": "Slovenia", "TM": "Turkmenistan", "TR": "Turkey", "UA": "Ukraine",
    "V": "Vatican City", "YU": "Yugoslavia", "MNE": "Montenegro",
    "SRB": "Serbia", "EC": "European Community", "EUR": "Europe",
    "WLD": "World",
}


def nation_full_name(value):
    """Return the full English country name for a nation value.

    Accepts either a numeric NationNumeric code or a short ISO/Common code
    string (as returned by :func:`get_nation`). Falls back to the input value
    when it is unknown, empty or a non-country placeholder.
    """
    if value is None:
        return ""
    short = get_nation(value) if isinstance(value, int) else str(value).strip()
    if not short or short in ("N/A", "No information available"):
        return short
    return _NATION_FULL_NAMES.get(short, short)


def decode_string(data, is_id=False):
    """Decode binary string handling CodePage byte (Annex 1B/1C)."""
    if not data:
        return ""
    try:
        data = data.rstrip(b'\x00\xff')
        if not data:
            return ""

        if data[0] < 0x20:
            enc = _CODEPAGE_ENCODINGS.get(data[0], 'latin-1')
            payload = data[1:]
        else:
            enc = 'latin-1'
            payload = data
        
        decoded = payload.decode(enc, errors='ignore').strip()
        if is_id:
            return "".join(c for c in decoded if (c.isalnum() or c == ' ') and ord(c) < 128).strip().upper()
        return "".join(c for c in decoded if c.isprintable()).strip()
    except (UnicodeDecodeError, IndexError, LookupError) as exc:
        _log.debug("String decode failed (len=%d): %s", len(data), exc)
        return ""

def decode_coded_text(data):
    """Decode a ``codePage``-prefixed string, keeping non-ASCII characters.

    ``codePage`` is the ISO/IEC 8859 part number that applies to the characters
    (Annex 1B §2.114 VehicleRegistrationNumber, Annex 1C §2.167): the first byte
    is the code page, the rest is the text. An unknown code page falls back to
    latin-1, exactly like :func:`decode_string`.

    Unlike ``decode_string(..., is_id=True)`` — which keeps only ASCII
    alphanumerics — this preserves accented letters, which are legal in a
    VehicleRegistrationNumber. Trailing ``00``/``FF`` padding is stripped first
    so a short VRN does not decode into control characters.
    """
    if not data:
        return ""
    raw = bytes(data).rstrip(b"\x00\xff")
    if not raw:
        return ""
    enc = _CODEPAGE_ENCODINGS.get(raw[0], "latin-1")
    try:
        decoded = raw[1:].decode(enc, errors="ignore")
    except LookupError:                                  # unknown code page name
        decoded = raw[1:].decode("latin-1", errors="ignore")
    return "".join(ch for ch in decoded if ch.isprintable()).strip()


#: ``EntryTypeDailyWorkPeriod`` (Annex 1B §2.51) — the assignment generation 2
#: keeps ("Value assignment: according to ISO/IEC8824-1" in Annex 1C §2.66,
#: whose enumeration is a figure in the accessible editions, so the shared
#: generation-1 text is the citable one). Six values are assigned:
#:
#:   (0) Begin, related time = card insertion time or time of entry
#:   (1) End,   related time = card withdrawal time or time of entry
#:   (2) Begin, related time manually entered (start time)
#:   (3) End,   related time manually entered (end of work period)
#:   (4) Begin, related time assumed by VU
#:   (5) End,   related time assumed by VU
ENTRY_TYPE_DAILY_WORK_PERIOD: dict[int, tuple[str, str]] = {
    0x00: ("BEGIN", "Begin (card insertion time)"),
    0x01: ("END", "End (card withdrawal time)"),
    0x02: ("BEGIN", "Begin manually entered"),
    0x03: ("END", "End manually entered"),
    0x04: ("BEGIN", "Begin assumed by VU"),
    0x05: ("END", "End assumed by VU"),
}

#: Generation 1 assigns exactly the six values above (Annex 1B §2.51 enumerates
#: 0..5 in text: card time, manually entered, "assumed by VU").
ENTRY_TYPE_G1_MAX = 0x05

#: Generation 2 adds the two GNSS-based values (Reg. (EU) 2016/799 Appendix 1
#: §2.66, "Generation 2" block: *Begin/End, related time based on GNSS data*
#: (6)/(7)). Reg. (EU) 2021/1228 replaces that block's text with "Value
#: assignment: according to ISO/IEC8824-1" and prints an ASN.1 figure that lists
#: 0..3 only, so the 2016 wording is the readable assignment for 6/7 — they are
#: *not* newly authorised by the 2021 act, and nothing above 7 is assigned by any
#: readable text.
ENTRY_TYPE_DAILY_WORK_PERIOD_G2: dict[int, tuple[str, str]] = {
    **ENTRY_TYPE_DAILY_WORK_PERIOD,
    0x06: ("BEGIN", "Begin, related time based on GNSS data"),
    0x07: ("END", "End, related time based on GNSS data"),
}

ENTRY_TYPE_STATUS_ASSIGNED = "assigned"
ENTRY_TYPE_STATUS_UNKNOWN = "unknown (not assigned by the readable generation-2 text)"
#: Status quoted for the two GNSS-based generation-2 values (see above).
ENTRY_TYPE_STATUS_ASSIGNED_GNSS = (
    "assigned (Reg. 2016/799 sec. 2.66; 2021/1228 ASN.1 figure lists 0..3 only)")


def entry_type_daily_work_period(code, generation="G2"):
    """``(short, meaning)`` for one EntryTypeDailyWorkPeriod byte.

    Generation 1 assigns 0..5; generation 2 assigns 0..7 (the last two are the
    GNSS-based begin/end). A code the readable text does not assign keeps its
    numeric value as the short form — nothing is invented, and no code is
    dropped: :func:`entry_type_daily_work_period_status` says how it is assigned.
    """
    try:
        value = int(code)
    except (TypeError, ValueError):
        return ("Unknown", "unknown")
    if generation == "G1":
        if value in ENTRY_TYPE_DAILY_WORK_PERIOD:
            return ENTRY_TYPE_DAILY_WORK_PERIOD[value]
        return (f"0x{value:02X}", f"not assigned (0x{value:02X})")
    if value in ENTRY_TYPE_DAILY_WORK_PERIOD_G2:
        return ENTRY_TYPE_DAILY_WORK_PERIOD_G2[value]
    return (f"0x{value:02X}", f"unknown (0x{value:02X})")


def entry_type_daily_work_period_status(code, generation="G2"):
    """How the readable text assigns a code: assigned / not assigned / unknown."""
    try:
        value = int(code)
    except (TypeError, ValueError):
        return ENTRY_TYPE_STATUS_UNKNOWN
    if generation == "G1":
        return (ENTRY_TYPE_STATUS_ASSIGNED
                if value in ENTRY_TYPE_DAILY_WORK_PERIOD else "not assigned")
    if value in ENTRY_TYPE_DAILY_WORK_PERIOD:
        return ENTRY_TYPE_STATUS_ASSIGNED
    if value in ENTRY_TYPE_DAILY_WORK_PERIOD_G2:
        return ENTRY_TYPE_STATUS_ASSIGNED_GNSS
    return ENTRY_TYPE_STATUS_UNKNOWN


# ── ExtendedSerialNumber display helpers (Annex 1B §2.56) ──────────────────
# A decoded serial is one compact scalar for the panels and tables; the
# structured dict stays in the JSON. A leaf module so both the generation-1
# decoders and the RecordArray dispatcher share one implementation.
def decode_extended_serial_number(data, off):
    """Decode one ExtendedSerialNumber (Annex 1B §2.56 / Annex 1C §2.56)."""
    from core.utils.manufacturer_codes import (
        MANUFACTURER_STATUS_NOT_REGISTERED, MANUFACTURER_STATUS_REGISTERED,
        manufacturer_name)
    if not isinstance(off, int) or off < 0 or off + 8 > len(data):
        return None
    raw = bytes(data[off:off + 8])
    month = _bcd_octet(raw[4])
    year_suffix = _bcd_octet(raw[5])
    out = {
        "serial_number": int.from_bytes(raw[0:4], "big"),
        "month_year_bcd": raw[4:6].hex(),
        "month": month,
        "year_suffix": year_suffix,
        "equipment_type": raw[6],
        "equipment_type_status": ("reserved (0xFF)" if raw[6] == 0xFF
                                 else "manufacturer specific"),
        "manufacturer_code": raw[7],
        "manufacturer": manufacturer_name(raw[7]),
        "manufacturer_status": (MANUFACTURER_STATUS_REGISTERED
                                if manufacturer_name(raw[7]) is not None
                                else MANUFACTURER_STATUS_NOT_REGISTERED),
    }
    if month is None or year_suffix is None:
        out["month_year_status"] = "invalid BCD / month"
    elif not 1 <= month <= 12:
        out["month_year_status"] = "invalid month"
    else:
        out["month_year_status"] = "valid"
    return out


def _bcd_octet(value):
    """One BCD octet as a decimal int, or None when a nibble exceeds 9."""
    high, low = value >> 4, value & 0x0F
    if high > 9 or low > 9:
        return None
    return high * 10 + low


def with_serial_text(hex_text, data, off):
    """``<hex> · <compact decoded serial>`` — hex kept, decoded form appended."""
    text = serial_text(decode_extended_serial_number(data, off))
    return f"{hex_text} \u00b7 {text}" if text else hex_text


def manufacturer_short_name(code):
    """Short registry name for a compact cell."""
    from core.utils.manufacturer_codes import manufacturer_name
    """A compact form of the registry name, for a table cell.

    The registry publishes full legal names ('Stoneridge Electronics AB'); a
    Field/Value panel of compact scalars cannot carry those. The short form keeps
    the first two words (and any acronym) and drops the legal suffix, which is what
    neighbouring rows do with long strings. Registry identity, not a guess: the
    bytes come from the official code table.
    """
    name = manufacturer_name(code)
    if not name:
        return None
    words = str(name).replace(",", " ").split()
    keep = []
    for word in words[:2]:
        keep.append(word)
    short = " ".join(keep)
    return short.rstrip(".").strip() or None


def serial_text(info):
    """One compact cell for an ExtendedSerialNumber (§2.56).

    ``<decimal serial> · <MM/YY> · <manufacturer short name>`` — the same density as
    the neighbouring rows. The monthYear is a BCD pair: when it is not a valid
    BCD month the two raw bytes are printed instead of a fabricated date, and the
    year stays the two digits the field carries (the century is not part of it).
    """
    if not isinstance(info, dict):
        return None
    serial = info.get("serial_number")
    if serial is None:
        return None
    month, year = info.get("month"), info.get("year_suffix")
    if month is None or year is None:
        stamp = str(info.get("month_year_bcd") or "").upper()
    else:
        stamp = f"{month:02d}/{year:02d}"
    parts = [str(serial)]
    if stamp:
        parts.append(stamp)
    maker = manufacturer_short_name(info.get("manufacturer_code"))
    if maker:
        parts.append(maker)
    return " \u00b7 ".join(parts)

#: ManualInputFlag (Annex 1B §2.66 / Annex 1C §2.93) enumerates exactly two
#: values. It is *not* a boolean: a driver who made no manual entries records
#: ``noEntry`` (0), one who did records ``manualEntries`` (1), and anything else
#: is RFU/undefined — never to be reported as «manual entries».
MANUAL_INPUT_FLAG_MEANINGS = {0: "noEntry", 1: "manualEntries"}

#: Meaning reported for a ManualInputFlag value the regulation does not define.
MANUAL_INPUT_FLAG_UNDEFINED = "undefined (not a ManualInputFlag value)"


def describe_manual_input_flag(value):
    """English meaning of one raw ManualInputFlag byte (0/1 defined, rest RFU)."""
    try:
        code = int(value)
    except (TypeError, ValueError):
        return MANUAL_INPUT_FLAG_UNDEFINED
    return MANUAL_INPUT_FLAG_MEANINGS.get(code, MANUAL_INPUT_FLAG_UNDEFINED)


#: PreviousVehicleInfo = vehicleRegistrationIdentification(15) +
#: cardWithdrawalTime(4); generation 2 appends vuGeneration(1).
#: Annex 1B §2.85 (19 bytes) / Annex 1C §2.118 (20 bytes).
PREVIOUS_VEHICLE_INFO_G1_SIZE = 19
PREVIOUS_VEHICLE_INFO_G2_SIZE = 20


def decode_previous_vehicle_info(data, offset, with_vu_generation=False):
    """Decode one PreviousVehicleInfo at *offset* (Annex 1B §2.85 / 1C §2.118).

    Layout, generation independent::

        vehicleRegistrationIdentification (15)
            vehicleRegistrationNation   NationNumeric (1)
            vehicleRegistrationNumber   codePage(1) + 13 chars (14)
        cardWithdrawalTime              TimeReal (4)
        vuGeneration                    INTEGER (1)  — generation 2 only

    This is the previous vehicle a driver used, stored *inside* one
    VuCardIWRecord: each record keeps its own copy, so it must never be merged
    into the file-level current vehicle.

    Returns ``None`` when *data* is too short to hold the whole structure — a
    partial structure is not decoded by guesswork.
    """
    size = (PREVIOUS_VEHICLE_INFO_G2_SIZE if with_vu_generation
            else PREVIOUS_VEHICLE_INFO_G1_SIZE)
    if offset < 0 or offset + size > len(data):
        return None
    block = data[offset:offset + size]
    nation_code = block[0]
    withdrawal_ts = struct.unpack(">I", block[15:19])[0]
    out = {
        "registration_nation": get_nation(nation_code),
        "registration_nation_code": nation_code,
        "registration_code_page": block[1],
        "registration_plate": decode_coded_text(block[1:15]),
        "card_withdrawal_time": (
            datetime.fromtimestamp(withdrawal_ts, tz=timezone.utc).isoformat()
            if 946684800 <= withdrawal_ts <= 4102444800 else None),
        "card_withdrawal_timestamp": withdrawal_ts,
    }
    if with_vu_generation:
        out["vu_generation"] = block[19]
    return out


def decode_date(data, prefer_datef=False):
    """Decode TimeReal (4 bytes) or Datef (4 bytes).

    When ``prefer_datef`` is True, BCD decoding is attempted first and preferred
    if it yields a valid date. Useful for fields like CardHolderBirthDate that
    use the Datef format (Annex 1B §2.26) rather than TimeReal.
    """
    if len(data) < 4:
        return "N/A"

    datef_result = decode_datef(data[:4])
    datef_valid = datef_result != "N/A"

    ts = None
    ts_valid = False
    try:
        ts = struct.unpack(">I", data[:4])[0]
        if 946684800 <= ts <= 4102444800:
            ts_valid = True
    except (struct.error, ValueError, OverflowError):
        pass

    if prefer_datef and datef_valid:
        return datef_result

    if ts_valid:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%d/%m/%Y')

    if datef_valid:
        return datef_result

    return "N/A"

def decode_datef(data):
    """Decode Datef (4-byte BCD: YY YY MM DD per Annex 1B §2.26)."""
    if len(data) < 4:
        return "N/A"
    try:
        yh = (data[0] >> 4) * 10 + (data[0] & 0x0F)
        yl = (data[1] >> 4) * 10 + (data[1] & 0x0F)
        m  = (data[2] >> 4) * 10 + (data[2] & 0x0F)
        d  = (data[3] >> 4) * 10 + (data[3] & 0x0F)
        year = yh * 100 + yl
        if 1900 <= year <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            # The BCD range check alone accepts impossible calendar dates
            # (e.g. 31/02). Reject them explicitly.
            datetime(year, m, d)
            return f"{d:02d}/{m:02d}/{year}"
    except (IndexError, ValueError) as exc:
        _log.debug("Datef BCD decode failed (len=%d): %s", len(data), exc)
    return "N/A"

def decode_activity_val(val):
    """Decode 2-byte ActivityChangeInfo (Annex 1B §2.1): 'scpaattttttttttt' —
    s=slot, c=crew status, p=card status (1 = card not inserted), aa=activity,
    t=minutes since midnight. Returns None for an invalid minute value."""
    slot = (val >> 15) & 1
    driving_status = (val >> 14) & 1 # 0=Single, 1=Crew
    card_not_inserted = (val >> 13) & 1
    act_code = (val >> 11) & 3
    mins = val & 0x07FF
    if mins > 1439:
        return None
    acts = {0: "REST", 1: "AVAILABLE", 2: "WORK", 3: "DRIVE"}
    return {
        "activity": acts.get(act_code, "UNKNOWN"),
        "time": f"{mins // 60:02d}:{mins % 60:02d}",
        "slot": "Second" if slot else "First",
        "crew": bool(driving_status),
        "card_inserted": not card_not_inserted,
    }

def get_cyclic_data(data, start, length, base_offset=4):
    """Read data from a cyclic buffer handling wrap-around."""
    buf_size = len(data) - base_offset
    if buf_size <= 0:
        return b'\x00' * length
    
    start_rel = (start - base_offset) % buf_size
    end_rel = start_rel + length
    
    if end_rel <= buf_size:
        return data[base_offset + start_rel : base_offset + end_rel]
    else:
        part1 = data[base_offset + start_rel : base_offset + buf_size]
        part2 = data[base_offset : base_offset + (end_rel - buf_size)]
        return part1 + part2

def parse_cyclic_buffer_activities(val, results):
    if len(val) < 16:
        return
    try:
        buf_size = len(val) - 4
        newest_ptr = struct.unpack(">H", val[2:4])[0]
        ptr = 4 + newest_ptr
        seen_dates = set()
        
        for _ in range(366):
            header_data = get_cyclic_data(val, ptr, 8)
            if len(header_data) < 8:
                break
            
            prev_len, rec_len, ts = struct.unpack(">HHI", header_data)

            # An invalid header skips this record's body, but the walk continues
            # via prev_len (a bare `continue` here would re-read the same header
            # until the iteration budget runs out, without ever advancing).
            record_valid = not (rec_len < 14 or rec_len > 2048) and (946684800 <= ts <= 4102444800)

            if record_valid:
                try:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    date_str = dt.strftime('%d/%m/%Y')
                except (OSError, ValueError, OverflowError):
                    date_str = "Invalid"

                if date_str not in seen_dates:
                    seen_dates.add(date_str)
                    counters_data = get_cyclic_data(val, ptr+8, 4)
                    pres, dist = struct.unpack(">HH", counters_data)

                    daily = {"date": date_str, "odometer_km": int(dist), "changes": []}

                    act_len = rec_len - 12
                    if act_len > 0:
                        act_data = get_cyclic_data(val, ptr+12, act_len)
                        for i in range(0, len(act_data), 2):
                            if i + 2 > len(act_data):
                                break
                            ev_val = struct.unpack(">H", act_data[i:i+2])[0]
                            if ev_val != 0xFFFF: # Fix Midnight Bug (allow 0)
                                activity = decode_activity_val(ev_val)
                                if activity is not None:
                                    daily["changes"].append(activity)

                    if daily["changes"]:
                        results["activities"].append(daily)

            if prev_len == 0 or prev_len > buf_size:
                break
            
            curr_offset = max(0, ptr - 4)
            prev_offset = (curr_offset - prev_len) % buf_size
            ptr = 4 + prev_offset
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Cyclic buffer activity parse failed: %s", exc)

def _decode_gnss_coord(data, offset, maximum_degrees=180):
    """Decode GeoCoordinates — Annex 1C §2.76: signed int24, ±DD(D)MM.M ×10.

    Latitude:  ±DDMM.M × 10  (e.g. 45°31.2'N → +45312), |DD| = 0..90
    Longitude: ±DDDMM.M × 10 (e.g. 009°12.5'E → +9125), |DDD| = 0..180
    Unknown position = 0x7FFFFF (3 bytes).

    A latitude/longitude is bounded on the globe: |degrees| ≤ 90 for a
    latitude, ≤ 180 for a longitude, and the minutes must be a real
    60-minute fraction (< 60). Values outside those bounds are corrupt bytes
    (e.g. an out-of-range EF Places/GNSS payload), not a position, so they
    return ``None`` exactly like the unknown-position sentinel — the same
    bound ``core.decoders.card_g22._coord`` already enforces. *maximum_degrees*
    selects the latitude (90) or longitude (180) limit.
    """
    if len(data) < offset + 3:
        return None
    raw = int.from_bytes(data[offset:offset + 3], 'big', signed=True)
    if raw == 0x7FFFFF:
        return None
    sign = -1 if raw < 0 else 1
    v = abs(raw) / 10.0          # DDMM.M
    deg = int(v // 100)
    minutes = v - deg * 100
    if deg > maximum_degrees or minutes >= 60.0:
        return None
    if deg == maximum_degrees and minutes != 0.0:
        return None
    return round(sign * (deg + minutes / 60.0), 7)
