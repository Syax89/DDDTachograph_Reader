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

def get_nation(code):
    """Map numeric nation code to ISO/Common code (Annex 1B)."""
    nations = {
        0x00: "No information available",
        0x01: "A", 0x02: "AL", 0x03: "AND", 0x04: "ARM", 0x05: "AZ", 0x06: "B", 0x07: "BG",
        0x08: "BIH", 0x09: "BY", 0x0A: "CH", 0x0B: "CY", 0x0C: "CZ", 0x0D: "D", 0x0E: "DK",
        0x0F: "E", 0x10: "EST", 0x11: "F", 0x12: "FIN", 0x13: "FL", 0x14: "FR", 0x15: "UK",
        0x16: "GE", 0x17: "GR", 0x18: "H", 0x19: "HR", 0x1A: "I", 0x1B: "IRL", 0x1C: "IS",
        0x1D: "KZ", 0x1E: "L", 0x1F: "LT", 0x20: "LV", 0x21: "M", 0x22: "MC", 0x23: "MD",
        0x24: "MK", 0x25: "N", 0x26: "NL", 0x27: "P", 0x28: "PL", 0x29: "RO", 0x2A: "RSM",
        0x2B: "RUS", 0x2C: "S", 0x2D: "SK", 0x2E: "SLO", 0x2F: "TM", 0x30: "TR", 0x31: "UA",
        0x32: "V", 0x33: "YU", 0x34: "MNE", 0x35: "SRB", 0xFD: "EC", 0xFE: "EUR", 0xFF: "WLD"
    }
    return nations.get(code, f"Unknown({code:02X})")

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
        if ts != 0 and ts != 0xFFFFFFFF and 0 < ts <= 4102444800:
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
            record_valid = not (rec_len < 14 or rec_len > 2048 or ts == 0 or ts == 0xFFFFFFFF)

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

def _decode_gnss_coord(data, offset):
    """Decode GeoCoordinates — Annex 1C §2.76: signed int24, ±DDMM.M ×10.
    
    Latitude:  ±DDMM.M × 10  (e.g. 45°31.2'N → +45312)
    Longitude: ±DDDMM.M × 10 (e.g. 009°12.5'E → +9125)
    Unknown position = 0x7FFFFF (3 bytes).
    Returns decimal degrees, or None on no-fix / out of bounds.
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
    return round(sign * (deg + minutes / 60.0), 7)
