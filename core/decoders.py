"""Field-level decoders for DDD tachograph card and vehicle unit data. Supports G1 (Annex 1B), G2 (Annex 1C), and G2.2 (Annex 1C update) formats across driver cards and VU downloads."""
import struct
from datetime import datetime, timezone

from core.logger import get_logger
from core.constants import MAX_ODO_DISTANCE_KM
from core.event_fault_codes import describe_event, describe_fault

_log = get_logger(__name__)

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
    """Decode 2-byte activityChangeInfo."""
    slot = (val >> 15) & 1
    driving_status = (val >> 14) & 1 # 0=Single, 1=Crew
    act_code = (val >> 11) & 3
    mins = val & 0x07FF
    acts = {0: "REST", 1: "AVAILABLE", 2: "WORK", 3: "DRIVE"}
    return {
        "tipo": acts.get(act_code, "UNKNOWN"),
        "activity": acts.get(act_code, "UNKNOWN"),
        "ora": f"{mins // 60:02d}:{mins % 60:02d}",
        "slot": "Second" if slot else "First",
        "team": bool(driving_status),
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

                    daily = {"data": date_str, "km": int(dist), "eventi": []}

                    act_len = rec_len - 12
                    if act_len > 0:
                        act_data = get_cyclic_data(val, ptr+12, act_len)
                        for i in range(0, len(act_data), 2):
                            if i + 2 > len(act_data):
                                break
                            ev_val = struct.unpack(">H", act_data[i:i+2])[0]
                            if ev_val != 0xFFFF: # Fix Midnight Bug (allow 0)
                                daily["eventi"].append(decode_activity_val(ev_val))

                    if daily["eventi"]:
                        results["activities"].append(daily)

            if prev_len == 0 or prev_len > buf_size:
                break
            
            curr_offset = max(0, ptr - 4)
            prev_offset = (curr_offset - prev_len) % buf_size
            ptr = 4 + prev_offset
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Cyclic buffer activity parse failed: %s", exc)


def parse_g2_vu_record(val, results, tag):
    """Dispatch G2/G2.2 VU records to appropriate decoders.

    Handles tags 0x0509-0x0512 (G2 VU records) and 0x052B-0x0533 (G2.2 VU records).
    The raw value may be a RecordArray or a single record.
    """
    # Lazy imports to break circular dependency (g2_decoders -> decoders -> g2_decoders)
    from . import g2_decoders as _g2
    from .record_array import RecordArrayParser as _RAP

    try:
        decoders_map = _g2.G2_VU_RECORD_DECODERS
        if tag not in decoders_map:
            return

        name, decode_fn, default_size = decoders_map[tag]

        hdr = _RAP.parse_header(val, 0)
        if hdr and hdr["record_size"] > 0 and hdr["no_of_records"] > 0:
            records = []
            for idx, rec, _ in _RAP.iter_records(val, 0):
                decoded = decode_fn(rec, 0)
                if decoded:
                    records.append(decoded)
            if records:
                key_map = {
                    0x0509: "card_records",
                    0x050A: "card_iw_records",
                    0x050B: "downloadable_periods",
                    0x050D: "time_adjustments",
                    0x050F: "company_locks",
                    0x0510: "sensor_paired",
                    0x0511: "sensor_gnss_coupled",
                    0x0512: "its_consents",
                    0x052B: "vu_controller",
                    0x052C: "detailed_speed",
                    0x052D: "overspeeding_events",
                    0x052E: "overspeeding_control",
                    0x052F: "time_adj_gnss",
                    0x0530: "power_interruptions",
                    0x0531: "sensor_faults",
                    0x0532: "sensor_gnss_coupled_g22",
                    0x0533: "sensor_paired_g22",
                }
                result_key = key_map.get(tag, f"g2_{tag:04X}")
                results.setdefault(result_key, []).extend(records)
        else:
            decoded = decode_fn(val, 0)
            if decoded:
                result_key = f"g2_{tag:04X}"
                results.setdefault(result_key, []).append(decoded)
    except (struct.error, IndexError, ValueError, KeyError, AttributeError) as exc:
        _log.debug("G2 VU record parse failed for tag 0x%04X: %s", tag, exc)

def parse_g1_identification(val, results):
    if len(val) < 65:
        return
    off = 0
    # CardIdentification (65 bytes)
    results["driver"]["issuing_nation"] = get_nation(val[off])
    off += 1
    results["driver"]["card_number"] = decode_string(val[off:off+16], is_id=True)
    off += 16
    off += 36 # cardIssuingAuthorityName
    off += 4 + 4 # cardIssueDate, cardValidityBegin
    results["driver"]["expiry_date"] = decode_date(val[off:off+4])
    off += 4
    
    # DriverCardHolderIdentification (78 bytes)
    if len(val) >= off + 78:
        results["driver"]["surname"] = decode_string(val[off:off+36])
        off += 36
        results["driver"]["firstname"] = decode_string(val[off:off+36])
        off += 36
        results["driver"]["birth_date"] = decode_date(val[off:off+4], prefer_datef=True)
        off += 4
        results["driver"]["preferred_language"] = decode_string(val[off:off+2])
        off += 2
    elif len(val) >= off + 36: # Partial (e.g. G2 internal)
        results["driver"]["surname"] = decode_string(val[off:off+36])
        off += 36

def parse_g1_driving_licence(val, results):
    if len(val) < 53:
        return
    results["driver"]["licence_issuing_nation"] = get_nation(val[36])
    results["driver"]["licence_number"] = decode_string(val[37:53], is_id=True)

def parse_g1_vehicles_used(val, results):
    """
    EF_Vehicles_Used (0x0505). 
    In G1: Fixed 31-byte records.
    In G2: Fixed 35-byte records (Annex 1C).
    """
    if len(val) < 4:
        return
    
    # Determine record size: 31 (G1) or 35 (G2)
    # The first 2 bytes are an index/pointer
    rec_data = val[2:]
    divisible_31 = len(rec_data) % 31 == 0
    divisible_35 = len(rec_data) % 35 == 0
    rec_size = 31
    if divisible_35 and not divisible_31:
        rec_size = 35
    elif divisible_35 and divisible_31:
        # Both sizes fit — try to validate the first record with G2 size first,
        # fall back to G1 if the timestamp is out of range
        if len(rec_data) >= 35:
            candidate = struct.unpack(">I", rec_data[8:12])[0]
            if 946684800 <= candidate <= 2000000000:
                rec_size = 35
    
    consecutive_garbage = 0
    for i in range(len(rec_data) // rec_size):
        chunk = rec_data[i*rec_size:(i+1)*rec_size]
        if len(chunk) < rec_size:
            break

        try:
            if rec_size == 31:
                # Annex 1B (G1) - Correct field order: odo_begin(3), odo_end(3), first_use(4), last_use(4), nation(1), plate(14)
                odo_begin = int.from_bytes(chunk[0:3], byteorder='big')
                odo_end = int.from_bytes(chunk[3:6], byteorder='big')
                first_use_ts = struct.unpack(">I", chunk[6:10])[0]
                last_use_ts = struct.unpack(">I", chunk[10:14])[0]
                nation_code = chunk[14]
                plate = decode_string(chunk[15:29], is_id=True)
            else:
                # Annex 1C (G2) - Correct field order: odo_begin(4), odo_end(4), first_use(4), last_use(4), nation(1), plate(14)
                odo_begin = struct.unpack(">I", chunk[0:4])[0]
                odo_end = struct.unpack(">I", chunk[4:8])[0]
                first_use_ts = struct.unpack(">I", chunk[8:12])[0]
                last_use_ts = struct.unpack(">I", chunk[12:16])[0]
                nation_code = chunk[16]
                plate = decode_string(chunk[17:31], is_id=True)

            # Strict plate validation: reject records with garbage plates.
            stripped = plate.strip().rstrip('\x00')
            if not stripped or len(stripped) < 2:
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue
            if not all(0x20 <= ord(c) < 0x7F for c in stripped):
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue
            alpha_ratio = sum(1 for c in stripped if c.isalnum()) / len(stripped) if stripped else 0
            if alpha_ratio < 0.5:
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue

            # Reject VIN-length strings (14+ chars) — real plates are shorter
            if len(stripped) >= 14:
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue

            if nation_code > 0x50:
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue

            if odo_begin is not None and odo_begin > MAX_ODO_DISTANCE_KM * 100:
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue
            if odo_end is not None and odo_end > MAX_ODO_DISTANCE_KM * 100:
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue

            # Sanitization
            if first_use_ts < 946684800 or first_use_ts > 2000000000:
                consecutive_garbage += 1
                if consecutive_garbage >= 3:
                    break
                continue

            if odo_begin == 0xFFFFFF or odo_begin == 0xFFFFFFFF:
                odo_begin = None
            if odo_end == 0xFFFFFF or odo_end == 0xFFFFFFFF:
                odo_end = None

            start_date = datetime.fromtimestamp(first_use_ts, tz=timezone.utc).isoformat()
            end_date = "Open Session"
            if last_use_ts != 0xFFFFFFFF and last_use_ts > 946684800:
                 try:
                     end_date = datetime.fromtimestamp(last_use_ts, tz=timezone.utc).isoformat()
                 except (OSError, ValueError, OverflowError):
                     pass

            distance = (odo_end - odo_begin) if (odo_begin is not None and odo_end is not None) else 0
            if distance is not None and (distance < 0 or distance > 1000000):
                distance = None  # odo reset or anomaly, don't report

            results["vehicle_sessions"].append({
                "vehicle_plate": plate,
                "vehicle_nation": get_nation(nation_code),
                "start": start_date,
                "end": end_date,
                "odometer_begin": odo_begin,
                "odometer_end": odo_end,
                "distance": distance
            })
            consecutive_garbage = 0
        except (struct.error, IndexError, ValueError, KeyError) as exc:
            _log.debug("Vehicle used record parse failed: %s", exc)
            continue

def parse_g1_current_usage(val, results):
    if len(val) < 19:
        return
    try:
        ts = struct.unpack(">I", val[0:4])[0]
        if ts == 0 or ts == 0xFFFFFFFF or ts > 4102444800:
            return
        results["vehicle"]["plate"] = decode_string(val[5:19], is_id=True)
        results["vehicle"]["registration_nation"] = get_nation(val[4])
    except (struct.error, IndexError, ValueError):
        pass

def parse_card_identification(val, results):
    """Parse CardIdentification (tag 0x0102) — Annex 1B §2.15, 65 bytes.

    Structure:
      CardIssuingMemberState    1  NationNumeric
      CardNumber               16  CardNumber(16)
      CardIssuingAuthorityName 36  Name (CodePage + 35 chars)
      CardIssueDate             4  TimeReal
      CardValidityBegin         4  TimeReal
      CardExpiryDate            4  TimeReal
    Total: 65 bytes
    """
    if len(val) < 65:
        return
    results["driver"]["issuing_nation"] = get_nation(val[0])
    results["driver"]["card_number"] = decode_string(val[1:17], is_id=True)
    results["driver"]["issuing_authority"] = decode_string(val[17:53])
    results["driver"]["issue_date"] = decode_date(val[53:57])
    results["driver"]["validity_begin"] = decode_date(val[57:61])
    results["driver"]["expiry_date"] = decode_date(val[61:65])

def parse_driver_card_holder_identification(val, results):
    if len(val) < 78:
        return
    results["driver"]["surname"] = decode_string(val[0:36])
    results["driver"]["firstname"] = decode_string(val[36:72])
    results["driver"]["birth_date"] = decode_date(val[72:76], prefer_datef=True)
    results["driver"]["preferred_language"] = decode_string(val[76:78])

def parse_calibration_data(val, results):
    """Parse CalibrationData (tag 0x050C) — Annex 1B §2.118, 167 bytes per record.

    Record structure (Annex 1B §2.118 VuCalibrationRecord):
      CalibrationPurpose              1  UInt8
      WorkshopName                   36  Name (CodePage + 35 chars)
      WorkshopAddress                36  Address (CodePage + 35 chars)
      WorkshopCardNumber             18  FullCardNumber
      WorkshopCardExpiryDate          4  TimeReal
      VehicleIdentificationNumber    17  SimpleString
      VehicleRegistrationNation       1  NationNumeric
      VehicleRegistrationNumber      14  InternationalString(13)
      VehicleCharacteristicConstant   2  UInt16 (W)
      ConstantOfRecordingEquipment    2  UInt16 (K)
      TyreCircumference               2  UInt16 (L)
      TyreSize                       15  SimpleString
      AuthorisedSpeed                 1  UInt8
      OldOdometerValue                3  UInt24
      NewOdometerValue                3  UInt24
      OldTimeValue                    4  TimeReal
      NewTimeValue                    4  TimeReal
      NextCalibrationDate             4  TimeReal
    Total: 167 bytes
    """
    if len(val) < 105:
        return
    try:
        data = val[2:]  # skip 2-byte header pointer

        # Annex 1B §2.118 VuCalibrationRecord = 167 bytes.
        # Some G2 files contain 105-byte non-standard records (likely a
        # reduced layout without workshop fields). Prefer 167, fall back to 105.
        if len(data) % 167 == 0:
            rec_size = 167
        elif len(data) % 105 == 0:
            rec_size = 105
            _log.debug("Calibration: non-standard 105-byte records")
        else:
            return

        for i in range(0, len(data) - rec_size + 1, rec_size):
            chunk = data[i:i + rec_size]
            purpose = chunk[0]

            if rec_size >= 167:
                workshop_name = decode_string(chunk[1:37])
                workshop_address = decode_string(chunk[37:73])
                # FullCardNumber (§2.73): cardType(1) + nation(1) + cardNumber(16)
                ws_card_nation = get_nation(chunk[74])
                ws_card_number = decode_string(chunk[75:91], is_id=True)
                ws_card_expiry = decode_date(chunk[91:95])
            else:
                workshop_name = ""
                workshop_address = ""
                ws_card_nation = "N/A"
                ws_card_number = "N/A"
                ws_card_expiry = "N/A"

            vin_off = 95 if rec_size >= 167 else 1
            nation_off = 112 if rec_size >= 167 else 18
            plate_off = 113 if rec_size >= 167 else 19
            w_off = 127 if rec_size >= 167 else 33
            k_off = 129 if rec_size >= 167 else 35
            l_off = 131 if rec_size >= 167 else 37
            tyre_off = 133 if rec_size >= 167 else 39
            speed_off = 148 if rec_size >= 167 else 54
            odo_off = 149 if rec_size >= 167 else 55

            vin = decode_string(chunk[vin_off:vin_off + 17], is_id=True)
            nation = get_nation(chunk[nation_off])
            # VehicleRegistrationNumber = codePage(1) + 13 chars
            plate = decode_string(chunk[plate_off + 1:plate_off + 14], is_id=True)
            w_const = struct.unpack(">H", chunk[w_off:w_off + 2])[0]
            k_const = struct.unpack(">H", chunk[k_off:k_off + 2])[0]
            l_const = struct.unpack(">H", chunk[l_off:l_off + 2])[0]
            tyre = decode_string(chunk[tyre_off:tyre_off + 15])
            speed = chunk[speed_off]
            old_odo = int.from_bytes(chunk[odo_off:odo_off + 3], 'big')
            if old_odo == 0xFFFFFF:
                old_odo = None
            new_odo = int.from_bytes(chunk[odo_off + 3:odo_off + 6], 'big') if rec_size >= 167 else None
            if new_odo == 0xFFFFFF:
                new_odo = None
            old_time = decode_date(chunk[odo_off + 6:odo_off + 10]) if rec_size >= 167 else "N/A"
            new_time = decode_date(chunk[odo_off + 10:odo_off + 14]) if rec_size >= 167 else "N/A"
            next_cal = decode_date(chunk[odo_off + 14:odo_off + 18]) if rec_size >= 167 else "N/A"

            results["calibrations"].append({
                "purpose_code": purpose,
                "workshop_name": workshop_name,
                "workshop_address": workshop_address,
                "workshop_card": f"{ws_card_nation}{ws_card_number}" if rec_size >= 167 else "N/A",
                "workshop_card_expiry": ws_card_expiry,
                "vin_at_calibration": vin,
                "nation_at_calibration": nation,
                "plate_at_calibration": plate,
                "w_characteristic_constant": w_const,
                "k_constant": k_const,
                "l_tyre_circumference": l_const,
                "tyre_size": tyre,
                "speed_limit": speed,
                "old_odometer": old_odo,
                "new_odometer": new_odo,
                "old_time": old_time,
                "new_time": new_time,
                "next_calibration_date": next_cal,
            })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Calibration data parse failed: %s", exc)

# ─── Gen 2.2 (Smart Tachograph V2) Decoders ─── Reg. EU 2023/980 ───

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

def parse_g22_gnss_accumulated_driving(val, results):
    """Parse GNSSAccumulatedDrivingRecord — Annex 1C §2.79 (11 bytes per record).

    Structure (Annex 1C §2.79, amended Reg. 2021/1228):
      timeStamp        4  TimeReal
      gnssAccuracy     1  UInt8 (metres)
      geoCoordinates   6  latitude(3, signed int24) + longitude(3, signed int24) — §2.76
    Total: 11 bytes
    """
    if len(val) < 11:
        return
    try:
        rec_size = 11
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            gnss_accuracy = chunk[4]
            lat = _decode_gnss_coord(chunk, 5)
            lon = _decode_gnss_coord(chunk, 8)
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                results.setdefault("gnss_ad_records", []).append({
                    "timestamp": dt,
                    "gnss_accuracy": gnss_accuracy,
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("GNSS accumulated driving parse failed: %s", exc)

def parse_g22_load_unload_operations(val, results):
    """Parse VuLoadUnloadRecord — ASN.1 (tachograph.asn:379-384), 11 bytes per record.

    Structure (all fields required):
      timestamp       4  TimeReal
      operationType   1  UInt8 (0x01=LOAD, 0x02=UNLOAD, 0x03=SIMULTANEOUS)
      latitude        3  Int24 (signed, ±DDMM.M ×10)
      longitude       3  Int24 (signed, ±DDDMM.M ×10)
    Total: 11 bytes
    """
    if len(val) < 11:
        return
    try:
        rec_size = 11
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            op_type = chunk[4]
            lat = _decode_gnss_coord(chunk, 5)
            lon = _decode_gnss_coord(chunk, 8)
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                op_map = {0x01: "LOAD", 0x02: "UNLOAD", 0x03: "SIMULTANEOUS"}
                results.setdefault("load_unload_records", []).append({
                    "timestamp": dt,
                    "operation": op_map.get(op_type, f"0x{op_type:02X}"),
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Load/unload operations parse failed: %s", exc)

def parse_g22_trailer_registrations(val, results):
    """Parse VehicleRegistrationIdentificationRecord — ASN.1 (tachograph.asn:386-391), 20 bytes.

    Structure (ASN.1):
      timestamp              4  TimeReal
      trailerNation          1  NationNumeric
      trailerPlate          14  InternationalString{13} (codePage 1 + chars 13)
      couplingStatus         1  UInt8 (0=COUPLED, 1=UNCOUPLED)
    Total: 20 bytes
    """
    if len(val) < 20:
        return
    try:
        rec_size = 20
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            nation = get_nation(chunk[4])
            plate = decode_string(chunk[5:19], is_id=True)
            coupling = chunk[19]
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            results.setdefault("trailer_registrations", []).append({
                "timestamp": dt,
                "nation": nation,
                "trailer_plate": plate,
                "event": "COUPLED" if coupling == 0 else "UNCOUPLED"
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Trailer registrations parse failed: %s", exc)

def parse_g22_gnss_enhanced_places(val, results):
    """Parse GNSSPlaceAuthRecord — Annex 1C §2.79c (12 bytes per record).

    Structure (Annex 1C §2.79c + §2.76):
      timeStamp             4  TimeReal
      gnssAccuracy          1  UInt8 (metres)
      geoCoordinates        6  latitude(3, int24) + longitude(3, int24)
      authenticationStatus  1  UInt8 (0=not authenticated, 1=authenticated)
    Total: 12 bytes
    """
    if len(val) < 12:
        return
    try:
        rec_size = 12
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            gnss_accuracy = chunk[4]
            lat = _decode_gnss_coord(chunk, 5)
            lon = _decode_gnss_coord(chunk, 8)
            auth_status = chunk[11]
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                results.setdefault("gnss_places", []).append({
                    "timestamp": dt,
                    "gnss_accuracy": gnss_accuracy,
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                    "authentication_status": auth_status,
                    "authenticated": auth_status == 1,
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("GNSS enhanced places parse failed: %s", exc)

def parse_g22_load_sensor_data(val, results):
    """Parse load sensor (weight) data (Gen 2.2)."""
    if len(val) < 8:
        return
    try:
        # timestamp(4) + axle_weight(2) per axle + total(2)
        ts = struct.unpack(">I", val[0:4])[0]
        if ts == 0 or ts == 0xFFFFFFFF:
            return
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        weights = []
        for j in range(4, len(val) - 1, 2):
            w = struct.unpack(">H", val[j:j+2])[0]
            if w != 0xFFFF:
                weights.append(w)
        results.setdefault("load_sensor_data", []).append({
            "timestamp": dt,
            "weights_kg": weights
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Load sensor data parse failed: %s", exc)

def parse_g22_border_crossings(val, results):
    """Parse VuBorderCrossingRecord — ASN.1 (tachograph.asn:393-399), 12 bytes.

    Structure (all fields required, Annex 1C §2.76 for geo):
      timestamp      4  TimeReal
      nationFrom     1  NationNumeric
      nationTo       1  NationNumeric
      latitude       3  Int24 (signed, ±DDMM.M ×10)
      longitude      3  Int24 (signed, ±DDDMM.M ×10)
    Total: 12 bytes
    """
    if len(val) < 12:
        return
    try:
        rec_size = 12
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            lat = _decode_gnss_coord(chunk, 6)
            lon = _decode_gnss_coord(chunk, 9)
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                results.setdefault("border_crossings", []).append({
                    "timestamp": dt,
                    "nation_from": get_nation(chunk[4]),
                    "nation_to": get_nation(chunk[5]),
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Border crossings parse failed: %s", exc)

def parse_g1_app_identification(val, results):
    """Parse DriverCardApplicationIdentification (tag 0x0501).

    G1 (Annex 1B §2.61, 10 bytes): type(1) + version(2) + noOfEventsPerType(1)
    + noOfFaultsPerType(1) + activityStructureLength(2) + noOfCardVehicleRecords(2)
    + noOfCardPlaceRecords(1).
    G2 (Annex 1C §2.61, 17 bytes): noOfCardPlaceRecords becomes 2 bytes, followed
    by noOfGNSSADRecords(2) + noOfSpecificConditionRecords(2) +
    noOfCardVehicleUnitRecords(2).
    """
    if len(val) < 10:
        return
    try:
        app_type = val[0]
        version = struct.unpack(">H", val[1:3])[0]
        no_events = val[3]
        no_faults = val[4]
        activity_len = struct.unpack(">H", val[5:7])[0]
        no_vehicles = struct.unpack(">H", val[7:9])[0]
        info = {
            "type": app_type,
            "version": version,
            "no_events_per_type": no_events,
            "no_faults_per_type": no_faults,
            "activity_structure_length": activity_len,
            "no_vehicle_records": no_vehicles,
        }
        if len(val) >= 17:
            info["no_place_records"] = struct.unpack(">H", val[9:11])[0]
            info["no_gnss_ad_records"] = struct.unpack(">H", val[11:13])[0]
            info["no_specific_condition_records"] = struct.unpack(">H", val[13:15])[0]
            info["no_card_vehicle_unit_records"] = struct.unpack(">H", val[15:17])[0]
        else:
            info["no_place_records"] = val[9]
        results.setdefault("card_application", {}).update(info)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("App identification parse failed: %s", exc)

def parse_g1_events_data(val, results):
    """Parse CardEventData (tag 0x0502) — CardEventRecords of 24 bytes.

    Record (Annex 1B §2.19): eventType(1, EventFaultType) + eventBeginTime(4) +
    eventEndTime(4) + eventVehicleRegistration(15: nation + plate).
    Records are deduplicated across the G1/G2 EF copies."""
    if len(val) < 24:
        return
    try:
        off = 0
        rec_size = 24
        seen = {(e.get("event_type_code"), e.get("begin"), e.get("end"))
                for e in results["events"] if isinstance(e, dict)}
        while off + rec_size <= len(val):
            ev_type = val[off]
            if ev_type == 0xFF:
                off += rec_size
                continue
            begin_ts = struct.unpack(">I", val[off+1:off+5])[0]
            end_ts = struct.unpack(">I", val[off+5:off+9])[0]
            if begin_ts == 0 or begin_ts == 0xFFFFFFFF:
                off += rec_size
                continue
            nation = get_nation(val[off+9])
            plate = decode_string(val[off+10:off+24], is_id=True)
            begin = datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat()
            end = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat() if end_ts != 0xFFFFFFFF else "N/A"
            if (ev_type, begin, end) in seen:
                off += rec_size
                continue
            seen.add((ev_type, begin, end))
            results["events"].append({
                "descrizione": describe_event(ev_type),
                "event_type_code": ev_type,
                "begin": begin,
                "end": end,
                "vehicle_nation": nation,
                "vehicle_plate": plate
            })
            off += rec_size
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Events data parse failed: %s", exc)

def parse_g1_faults_data(val, results):
    """Parse CardFaultData (tag 0x0503) — CardFaultRecords of 24 bytes.

    Record (Annex 1B §2.21): faultType(1, EventFaultType 0x30-0x4F) +
    faultBeginTime(4) + faultEndTime(4) + faultVehicleRegistration(15).
    Records are deduplicated across the G1/G2 EF copies."""
    if len(val) < 24:
        return
    try:
        off = 0
        rec_size = 24
        seen = {(f.get("fault_type_code"), f.get("begin"), f.get("end"))
                for f in results["faults"] if isinstance(f, dict)}
        while off + rec_size <= len(val):
            fault_type = val[off]
            if fault_type == 0xFF:
                off += rec_size
                continue
            begin_ts = struct.unpack(">I", val[off+1:off+5])[0]
            end_ts = struct.unpack(">I", val[off+5:off+9])[0]
            if begin_ts == 0 or begin_ts == 0xFFFFFFFF:
                off += rec_size
                continue
            nation = get_nation(val[off+9])
            plate = decode_string(val[off+10:off+24], is_id=True)
            begin = datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat()
            end = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat() if end_ts != 0xFFFFFFFF else "N/A"
            if (fault_type, begin, end) in seen:
                off += rec_size
                continue
            seen.add((fault_type, begin, end))
            results["faults"].append({
                "descrizione": describe_fault(fault_type),
                "fault_type_code": fault_type,
                "begin": begin,
                "end": end,
                "vehicle_nation": nation,
                "vehicle_plate": plate
            })
            off += rec_size
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Faults data parse failed: %s", exc)

def _decode_place_records(val, off, stride):
    """Decode PlaceRecords from EF Places content using the given pointer
    offset and record stride. Returns the list of valid records."""
    MIN_TS = 946684800
    MAX_TS = 4102444800
    # EntryTypeDailyWorkPeriod (Annex 1B/1C §2.66): 0/2 = begin, 1/3 = end
    # (2/3 = GNSS-related variants). Confirmed on real card data: type 0 at
    # start of day (~03:00), type 1 at end of day.
    entry_names = {0x00: "START", 0x01: "END", 0x02: "START", 0x03: "END"}
    records = []
    try:
        for i in range(off, len(val) - stride + 1, stride):
            chunk = val[i:i + stride]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts < MIN_TS or ts > MAX_TS:
                continue
            entry_type = chunk[4]
            if entry_type not in entry_names:
                continue
            nation_code = chunk[5]
            if nation_code > 0xFD:
                continue

            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            record = {
                "timestamp": dt,
                "entry_type": entry_names[entry_type],
                "type_code": entry_type,
                "nation": get_nation(nation_code),
                "region": chunk[6],
            }
            odo_val = int.from_bytes(chunk[7:10], 'big')
            if odo_val != 0xFFFFFF and odo_val < 10000000:
                record["odometer_km"] = odo_val
            if stride >= 21:
                # GNSSPlaceRecord at offset 10: timeStamp(4) + gnssAccuracy(1)
                # + latitude(3) + longitude(3) [+ authenticationStatus(1) G2.2]
                lat = _decode_gnss_coord(chunk, 15)
                lon = _decode_gnss_coord(chunk, 18)
                if lat is not None and lon is not None:
                    record["gnss_accuracy"] = chunk[14]
                    record["latitude"] = lat
                    record["longitude"] = lon
                if stride >= 22:
                    record["gnss_authenticated"] = chunk[21] == 1
            records.append(record)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Places decode failed (off=%d, stride=%d): %s", off, stride, exc)
    return records

def parse_g1_places(val, results):
    """Parse CardPlaceDailyWorkPeriod (tag 0x0506).

    Layouts (newest-record pointer + fixed records):
      G1   (Annex 1B §2.27): placePointerNewestRecord(1) + N × PlaceRecord(10)
      G2   (Annex 1C §2.27): placePointerNewestRecord(2) + N × PlaceRecord(21)
                             (10-byte base + GNSSPlaceRecord 11)
      G2.2 (Annex 1C §2.27): pointer(2) + N × PlaceAuthRecord(22)
                             (10-byte base + GNSSPlaceAuthRecord 12)

    PlaceRecord base (10 bytes): entryTime(4) + entryTypeDailyWorkPeriod(1) +
    dailyWorkPeriodCountry(1) + dailyWorkPeriodRegion(1) + vehicleOdometerValue(3).

    A G1 card download carries both the G1 and the G2 copy of this EF; records
    are deduplicated on (timestamp, type), and the GNSS-enriched copy merges
    extra fields into an already-seen record.
    """
    if len(val) < 11:
        return
    try:
        candidates = [(off, stride)
                      for off, stride in ((1, 10), (2, 21), (2, 22), (2, 10), (2, 13), (2, 27))
                      if (len(val) - off) % stride == 0]
        if not candidates:
            return

        best = []
        for off, stride in candidates:
            records = _decode_place_records(val, off, stride)
            if len(records) > len(best):
                best = records

        existing = {(p.get("timestamp"), p.get("type_code")): p
                    for p in results["places"] if isinstance(p, dict)}
        for rec in best:
            key = (rec["timestamp"], rec["type_code"])
            if key in existing:
                for k, v in rec.items():
                    existing[key].setdefault(k, v)
            else:
                results["places"].append(rec)
                existing[key] = rec
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Places parse failed: %s", exc)

def parse_g2_card_icc_identification(val, results):
    """Parse CardIccIdentification (tag 0x0101) — Annex 1C §2.23.

    Structure (Annex 1C §2.23 / ISO 7816):
      ClockStop               1  UInt8
      ExtendedSerialNumber    8  HexValue
      ApprovalNumber          8  HexValue
      PersonaliserId          1  UInt8
      EmbedderIcAssemblerId   4  HexValue
      IcIdentifier            2  UInt16
      HistoricalBytes   variable  (remaining)
    Minimum: 24 bytes
    """
    if len(val) < 8:
        return
    try:
        chip_info = {
            "clock_stop": "Normal" if val[0] == 0 else f"Stopped(0x{val[0]:02X})",
        }
        if len(val) >= 9:
            chip_info["extended_serial_number"] = val[1:9].hex().upper()
        if len(val) >= 17:
            chip_info["approval_number"] = val[9:17].hex().upper()
        if len(val) >= 18:
            chip_info["personaliser_id"] = f"0x{val[17]:02X}"
        if len(val) >= 22:
            chip_info["embedder_ic_assembler_id"] = val[18:22].hex().upper()
        if len(val) >= 24:
            chip_info["ic_identifier"] = f"0x{struct.unpack('>H', val[22:24])[0]:04X}"
        if len(val) > 24:
            historical = val[24:]
            text = decode_string(historical)
            if text:
                chip_info["historical_info"] = text
            else:
                chip_info["historical_bytes"] = historical.hex().upper()

        results.setdefault("card_icc", {}).update(chip_info)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Card ICC identification parse failed: %s", exc)

def parse_g22_auth_subtag(val, results, tag):
    """Parse G2.2 authentication sub-tags inside security container.

    Tags handled:
      0x960F - GNSS authentication data (raw bytes retained for crypto)
      0x6399 - Load/unload authentication data (raw bytes retained for crypto)

    Attempts structure detection: header (first 4 bytes) + payload (rest).
    """
    try:
        total_len = len(val)
        header_end = min(4, total_len)
        header_bytes = val[:header_end]
        payload_bytes = val[header_end:]

        _log.debug("Auth subtag 0x%04X: total=%d header=%d payload=%d",
                   tag, total_len, header_end, len(payload_bytes))

        entry = {
            "tag": f"0x{tag:04X}",
            "length": total_len,
            "raw_hex": val.hex(),
            "header_hex": header_bytes.hex(),
            "payload_hex": payload_bytes.hex(),
            "header_length": header_end,
            "payload_length": len(payload_bytes),
        }

        dest_key = "gnss_auth" if tag == 0x960F else "load_unload_auth"
        results.setdefault(dest_key, []).append(entry)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Auth subtag parse failed for tag 0x%04X: %s", tag, exc)


def parse_g22_certificate_subtag(val, results, tag):
    """Parse G22 certificate sub-tags (5Fxx) found inside security container."""
    try:
        if tag == 0x5F20:  # G22_CardHolderName
            results.setdefault("card_icc", {})["holder_name"] = decode_string(val)
        elif tag == 0x5F24:  # G22_CardEffectiveDate
            results.setdefault("card_icc", {})["effective_date"] = decode_date(val)
        elif tag == 0x5F25:  # G22_CardExpiryDate
            results.setdefault("card_icc", {})["expiry_date"] = decode_date(val)
        elif tag == 0x5F29:  # G22_CardIssuingMemberState
            if len(val) >= 1:
                results.setdefault("card_icc", {})["issuing_nation"] = get_nation(val[0])
        elif tag == 0x5F4C:  # G22_CardExtendedSerialNumber
            results.setdefault("card_icc", {})["extended_serial"] = val.hex().upper()
    except (struct.error, IndexError, ValueError, KeyError) as exc:
        _log.debug("Certificate subtag parse failed: %s", exc)

def parse_vu_vehicle_identification(val, results):
    """Parse VU_VehicleIdentification (tag 0x0001 in VU context)."""
    if len(val) < 32:
        return
    try:
        # Only decode if format looks like standard VRN data:
        # byte[0] = nation (0x00-0xFD), byte[1:15] = readable plate, byte[15:32] = readable VIN
        nation = get_nation(val[0])
        plate = decode_string(val[1:15], is_id=True)
        vin = decode_string(val[15:32], is_id=True)
        # Validate: VIN should be 17 alphanumeric chars, plate should be non-empty
        if len(vin) == 17 and vin.isalnum() and len(plate) >= 1:
            results["vehicle"]["registration_nation"] = nation
            results["vehicle"]["plate"] = plate
            results["vehicle"]["vin"] = vin
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("VU vehicle identification parse failed: %s", exc)

def parse_ef_icc(val, results):
    """Parse EF_ICC (tag 0x0002) — Annex 1B §2.7, card chip identification.

    Structure (Annex 1B §2.7, ISO 7816):
      ClockStop               1  UInt8 (0=Normal, else=Stopped)
      ExtendedSerialNumber    8  HexValue
      ApprovalNumber          8  HexValue
      PersonaliserId          1  UInt8
      EmbedderIcAssemblerId   4  HexValue
      IcIdentifier            2  UInt16
      HistoricalBytes   variable  (remaining data)
    Minimum: 24 bytes (1+8+8+1+4+2)
    """
    if len(val) < 4:
        return
    try:
        clock_stop = val[0]
        chip_info = {
            "clock_stop": "Normal" if clock_stop == 0 else f"Stopped(0x{clock_stop:02X})",
        }
        if len(val) >= 9:
            chip_info["extended_serial_number"] = val[1:9].hex().upper()
        if len(val) >= 17:
            chip_info["approval_number"] = val[9:17].hex().upper()
        if len(val) >= 18:
            chip_info["personaliser_id"] = f"0x{val[17]:02X}"
        if len(val) >= 22:
            chip_info["embedder_ic_assembler_id"] = val[18:22].hex().upper()
        if len(val) >= 24:
            chip_info["ic_identifier"] = f"0x{struct.unpack('>H', val[22:24])[0]:04X}"
        if len(val) > 24:
            historical = val[24:]
            text = decode_string(historical)
            if text:
                chip_info["historical_info"] = text
            else:
                chip_info["historical_bytes"] = historical.hex().upper()

        results.setdefault("card_chip", {}).update(chip_info)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("EF ICC parse failed: %s", exc)

def parse_ef_ic(val, results):
    """Parse EF_IC (tag 0x0005) — Annex 1B §2.6, Integrated Circuit info.

    Structure (8 bytes, C# DriverCardData.config):
      IcSerialNumber           4  UInt32
      IcManufacturingReferences 4  UInt32
    """
    if len(val) < 8:
        return
    try:
        ic_serial = struct.unpack(">I", val[0:4])[0]
        ic_mfr = struct.unpack(">I", val[4:8])[0]
        decoded_pct = round(8 / max(len(val), 1) * 100, 1)
        results.setdefault("card_chip", {}).update({
            "ic_serial_number": f"0x{ic_serial:08X}",
            "ic_manufacturing_reference": f"0x{ic_mfr:08X}",
        })
        if decoded_pct < 100:
            results["card_chip"]["_decoded_percentage"] = decoded_pct
            _log.debug("EF IC: partially decoded (%.1f%%, total=%d bytes)", decoded_pct, len(val))
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("EF IC parse failed: %s", exc)

def parse_previous_vehicle_info(val, results):
    """Extract PreviousVehicleInfo from tag 0x0507 or 0x0520."""
    if len(val) < 19:
        return
    try:
        nation = get_nation(val[0])
        plate = decode_string(val[1:15], is_id=True)
        ts = struct.unpack(">I", val[15:19])[0]
        if ts == 0 or ts == 0xFFFFFFFF:
            return
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts < 4102444800 else "N/A"
        prev = {"plate": plate, "nation": nation, "withdrawal_time": dt}
        if len(val) >= 20:
            prev["vu_generation"] = val[19]
        results.setdefault("previous_vehicle", []).append(prev)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Previous vehicle info parse failed: %s", exc)

def parse_control_activity_data(val, results):
    """Parse ControlActivityData (tag 0x0508) — Annex 1B §2.23, inspection records.

    Record structure (46 bytes, Annex 1B §2.15a):
      ControlType           1  UInt8
      ControlTime           4  TimeReal
      ControlCardNumber    18  FullCardNumber (cardType + nation + cardNumber, §2.73)
      VehicleRegNation      1  NationNumeric
      VehicleRegNumber     14  InternationalString(13) + padding
      DownloadPeriodBegin   4  TimeReal
      DownloadPeriodEnd    4  TimeReal
    Total: 46 bytes per record

    The card EF is a single bare 46-byte record (no pointer, Annex 1B §2.15a);
    variants with a 2-byte header are detected by alignment. Records are
    deduplicated across the G1/G2 EF copies.
    """
    if len(val) < 46:
        return
    try:
        rec_size = 46
        off = 0 if len(val) % rec_size == 0 else 2
        existing = results.setdefault("control_activities", [])
        seen = {(c.get("timestamp"), c.get("control_type"))
                for c in existing if isinstance(c, dict)}
        while off + rec_size <= len(val):
            chunk = val[off:off + rec_size]
            control_type = chunk[0]
            ts = struct.unpack(">I", chunk[1:5])[0]
            if ts == 0 or ts == 0xFFFFFFFF or ts < 946684800:
                off += rec_size
                continue

            card_type = chunk[5]
            card_nation = chunk[6]
            card_num = decode_string(chunk[7:23], is_id=True)

            vehicle_nation = get_nation(chunk[23])
            vehicle_plate = decode_string(chunk[24:38])

            download_begin = struct.unpack(">I", chunk[38:42])[0]
            download_end = struct.unpack(">I", chunk[42:46])[0]

            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if (dt, control_type) in seen:
                off += rec_size
                continue
            seen.add((dt, control_type))
            begin_dt = datetime.fromtimestamp(download_begin, tz=timezone.utc).isoformat() if 946684800 <= download_begin <= 4102444800 else "N/A"
            end_dt = datetime.fromtimestamp(download_end, tz=timezone.utc).isoformat() if 946684800 <= download_end <= 4102444800 else "N/A"

            nation_char = get_nation(card_nation)
            existing.append({
                "control_type": control_type,
                "timestamp": dt,
                "control_card": f"{nation_char}{card_num}",
                "card_nation": nation_char,
                "card_type": card_type,
                "vehicle_nation": vehicle_nation,
                "vehicle_plate": vehicle_plate,
                "download_period_begin": begin_dt,
                "download_period_end": end_dt,
            })
            off += rec_size
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Control activity data parse failed: %s", exc)

def parse_card_download(val, results):
    """Parse EF Card_Download (tag 0x050E) — LastCardDownload (Annex 1B §2.18).

    The driver-card EF is exactly 4 bytes (a single TimeReal, no pointer);
    confirmed on real card downloads in both the G1 and G2 copies. Variants
    with a 2-byte header before an array of timestamps are detected by
    alignment. Records are deduplicated across the G1/G2 EF copies.
    """
    if len(val) < 4:
        return
    try:
        off = 0 if len(val) % 4 == 0 else 2
        rec_size = 4  # TimeReal timestamps
        downloads = results.setdefault("card_downloads", [])
        seen = {d.get("download_time") for d in downloads if isinstance(d, dict)}
        while off + rec_size <= len(val):
            ts = struct.unpack(">I", val[off:off+4])[0]
            off += rec_size
            if ts == 0 or ts == 0xFFFFFFFF or ts < 946684800 or ts > 4102444800:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if dt in seen:
                continue
            seen.add(dt)
            downloads.append({"download_time": dt})
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Card download parse failed: %s", exc)

def parse_specific_conditions(val, results):
    """Parse SpecificConditions (tag 0x0522) — ferry/train/out-of-scope (Annex 1B §2.27 / Annex 1C §2.152).

    Annex 1B §2.154 SpecificConditionRecord = entryTime(4) + specificConditionType(1) = 5 bytes.
    The G1 EF has no header (records only, len % 5 == 0); the G2 EF prefixes a
    2-byte conditionPointerNewestRecord. Detected by alignment; records are
    deduplicated across the G1/G2 EF copies.
    """
    if len(val) < 5:
        return
    try:
        rec_size = 5  # entryTime(4) + specificConditionType(1) per Annex 1B §2.154
        off = 0 if len(val) % rec_size == 0 else 2
        conditions = results.setdefault("specific_conditions", [])
        seen = {(c.get("timestamp"), c.get("type_code"))
                for c in conditions if isinstance(c, dict)}
        while off + rec_size <= len(val):
            chunk = val[off:off+rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts < 946684800 or ts > 4102444800:
                off += rec_size
                continue
            cond_type = chunk[4]
            if cond_type not in (0x00, 0x01, 0x02, 0x03, 0x04):
                off += rec_size
                continue
            types = {0x00: "Ferry", 0x01: "Train", 0x02: "OutOfScope",
                     0x03: "BeginAreaNoGNSS", 0x04: "EndAreaNoGNSS"}
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if (dt, cond_type) not in seen:
                seen.add((dt, cond_type))
                conditions.append({
                    "timestamp": dt,
                    "condition": types[cond_type],
                    "type_code": cond_type,
                })
            off += rec_size
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Specific conditions parse failed: %s", exc)

def parse_g1_certificate(val, results):
    """Parse G1 certificate (tags 0xC100, 0xC108, 0x0103, 0x0104) — 194 bytes.

    Structure (Annex 1B §2.29-2.30 / Annex 1C §2.30-2.31, C# config):
      Signature                 128  HexValue
      PublicKeyRemainder         58  HexValue (RSA pubkey remainder)
      Nation                      1  Country
      NationCode                  3  SimpleString (numeric)
      SerialNumber                1  UInt8
      AdditionalInfo              2  UInt16
      CaIdentifier                1  UInt8
    Total: 194 bytes
    """
    if len(val) < 194:
        return
    try:
        sig = val[0:128]
        pk_remainder = val[128:186]
        nation = get_nation(val[186])
        nation_code = val[187:190].decode('latin-1', errors='replace').strip()
        serial = val[190]
        add_info = struct.unpack(">H", val[191:193])[0]
        ca_id = val[193]

        results.setdefault("certificates", []).append({
            "signature_hex": sig.hex().upper(),
            "signature_length": 128,
            "public_key_remainder_hex": pk_remainder.hex().upper(),
            "public_key_remainder_length": 58,
            "nation": nation,
            "nation_code": nation_code,
            "serial_number": serial,
            "additional_info": f"0x{add_info:04X}",
            "ca_identifier": f"0x{ca_id:02X}",
            "total_size": 194,
        })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("G1 certificate parse failed: %s", exc)

def parse_certificate_signature(val, results):
    """Parse ECDSA certificate signature (tag 0x5F37) — Annex 1C §2.31.

    Structure: 64-byte ECDSA signature = r(32 bytes) || s(32 bytes).
    """
    try:
        sig_info = {"signature_raw": val.hex().upper()}
        if len(val) >= 64:
            r_int = int.from_bytes(val[0:32], 'big')
            s_int = int.from_bytes(val[32:64], 'big')
            sig_info.update({
                "r_hex": val[0:32].hex().upper(),
                "s_hex": val[32:64].hex().upper(),
                "r_int": str(r_int),
                "s_int": str(s_int),
            })
        results.setdefault("card_icc", {})["certificate_signature"] = sig_info
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Certificate signature parse failed: %s", exc)

EC_CURVE_OIDS = {
    "2b2403030208010107": "brainpoolP256r1",
    "2a8648ce3d030107": "secp256r1 (NIST P-256)",
}

def parse_public_key_info(val, results):
    """Parse public key info (tag 0x7F49) — EC curve OID + public key point."""
    try:
        info = {"algorithm": "ECDSA"}
        hex_val = val.hex()
        for oid_hex, curve_name in EC_CURVE_OIDS.items():
            idx = hex_val.find(oid_hex)
            if idx >= 0:
                info["curve"] = curve_name
                key_start = idx // 2 + len(oid_hex) // 2
                rest = val[key_start:]
                if rest[:1] == b'\x86' and len(rest) >= 2:
                    inner_len = rest[1]
                    if inner_len & 0x80:
                        num_len = inner_len & 0x7f
                        if len(rest) >= 2 + num_len:
                            inner_len = int.from_bytes(rest[2:2+num_len], 'big')
                            rest = rest[2+num_len:]
                        else:
                            rest = b''
                    else:
                        rest = rest[2:]
                    if len(rest) >= inner_len:
                        key_data = rest[:inner_len]
                        if key_data[:1] == b'\x04' and len(key_data) >= 65:
                            x = key_data[1:33].hex().upper()
                            y = key_data[33:65].hex().upper()
                            info["public_key_x"] = x
                            info["public_key_y"] = y
                        else:
                            info["public_key_hex"] = key_data.hex().upper()
                elif rest[:1] == b'\x04' and len(rest) >= 65:
                    info["public_key_x"] = rest[1:33].hex().upper()
                    info["public_key_y"] = rest[33:65].hex().upper()
                break
        results.setdefault("card_icc", {})["public_key"] = info
    except (struct.error, IndexError, ValueError, KeyError) as exc:
        _log.debug("Public key info parse failed: %s", exc)

def parse_card_issuer_identification(val, results):
    """Parse CardIssuerIdentification (tag 0x0100) — card number + company name.

    Attempts structured parsing first (card type + issuer code + card number),
    falls back to Italian regex, then to raw string decode for other formats.
    """
    import re
    try:
        if len(val) < 3:
            return

        issuer_entry = results.setdefault("card_issuer", {})
        raw_text = decode_string(val)

        structured_parsed = False

        # Attempt 1: Structured parsing — first byte = card type, then find issuer/card boundaries
        if len(val) >= 4:
            try:
                card_type = val[0]
                _log.debug("Card issuer structured attempt: first_byte=0x%02X, len=%d", card_type, len(val))

                # Try: card_type (1) + issuer_code (variable) + card_number (variable)
                # issuer code typically begins after a code-page byte (0x01-0x0F) or a nation byte (0x00-0xFD)
                off = 1
                if off < len(val) and val[off] < 0x10:
                    off += 1  # skip code-page byte
                # Find the numeric card number boundary
                num_start = off
                while num_start < len(val):
                    b = val[num_start]
                    if 0x30 <= b <= 0x39:  # ASCII digit start
                        break
                    num_start += 1
                if off < num_start < len(val):
                    issuer_bytes = val[off:num_start]
                    issuer_code = decode_string(issuer_bytes)
                    card_num_raw = decode_string(val[num_start:], is_id=True)
                    issuer_entry["card_type"] = f"0x{card_type:02X}"
                    if issuer_code:
                        issuer_entry["issuer_code"] = issuer_code
                    if card_num_raw:
                        issuer_entry["card_number"] = card_num_raw
                    issuer_entry["raw_string"] = raw_text
                    structured_parsed = True
                    _log.debug("Card issuer structured parse: type=0x%02X issuer=%s card=%s",
                               card_type, issuer_code, card_num_raw)
            except (IndexError, ValueError) as exc:
                _log.debug("Card issuer structured parse attempt failed: %s", exc)

        # Attempt 2: Italian card number regex (backward compat)
        if not structured_parsed and raw_text:
            match = re.search(r'[A-Z]\d{13,20}', raw_text)
            if match:
                card_num = match.group()
                rest = raw_text[raw_text.index(card_num) + len(card_num):]
                company = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]+', ' ', rest).strip()
                issuer_entry["card_number"] = card_num
                issuer_entry["company_name"] = company
                issuer_entry["raw_string"] = raw_text
                _log.debug("Card issuer Italian regex match: card=%s", card_num)
                structured_parsed = True

        # Attempt 3: Non-Italian format — store decoded string as-is
        if not structured_parsed and raw_text:
            issuer_entry["raw_string"] = raw_text
            issuer_entry["_note"] = "non-Italian format, raw string only"
            _log.debug("Card issuer: non-Italian format, raw string stored (len=%d)", len(raw_text))
    except (ValueError, TypeError, IndexError) as exc:
        _log.debug("Card issuer identification parse failed: %s", exc)

def parse_company_holder_data(val, results):
    """Parse CompanyHolderData (tag 0x2020) — card holder company name + address.

    Attempts structured split on code-page delimiters (Annex 1B §2.17):
      company name + address + card number.
    Falls back to raw text when structure cannot be determined.
    """
    import re
    try:
        if len(val) < 10:
            return
        text = decode_string(val)

        entry = {}
        structured_parsed = False

        # Attempt 1: split on visible code-page byte boundaries
        try:
            # CompanyHolderData typically: CodePage(1) + companyName + CodePage(1) + address
            # Look for delimiter bytes (code-page markers 0x01-0x0F) to split fields
            code_page_positions = [i for i, b in enumerate(val) if 0x01 <= b <= 0x10]
            if len(code_page_positions) >= 2 and code_page_positions[0] == 0:
                sections = []
                for i, cp_pos in enumerate(code_page_positions):
                    start = cp_pos
                    end = code_page_positions[i + 1] if i + 1 < len(code_page_positions) else len(val)
                    sections.append(val[start:end])
                if len(sections) >= 2:
                    # First section = company name, second = address
                    entry["company_name"] = decode_string(sections[0]).strip()
                    if len(sections) >= 2:
                        entry["company_address"] = decode_string(sections[1]).strip()
                    if len(sections) >= 3:
                        entry["card_number"] = decode_string(sections[2], is_id=True).strip()
                    if entry.get("company_name"):
                        structured_parsed = True
                        _log.debug("Company holder: structured split parsed %d sections", len(sections))
        except (IndexError, ValueError) as exc:
            _log.debug("Company holder structured split failed: %s", exc)

        # Attempt 2: look for card number pattern as delimiter
        if not structured_parsed and text:
            card_match = re.search(r'[A-Z]\d{13,20}', text)
            if card_match:
                card_num = card_match.group()
                pre_card = text[:text.index(card_num)].strip()
                post_card = text[text.index(card_num) + len(card_num):].strip()
                # Typically: company_name followed by address then card
                parts = [p.strip() for p in pre_card.split('  ') if p.strip()]
                if len(parts) >= 1:
                    entry["company_name"] = parts[0]
                if len(parts) >= 2:
                    entry["company_address"] = parts[1]
                entry["card_number"] = card_num
                if post_card:
                    entry.setdefault("company_address", "")
                    if not entry["company_address"]:
                        entry["company_address"] = post_card
                    else:
                        entry["company_address"] += " " + post_card
                structured_parsed = True
                _log.debug("Company holder: card-number delimiter parse, card=%s", card_num)

        # Fallback
        if not structured_parsed and text:
            entry["raw_text"] = text.strip()
            _log.debug("Company holder: raw text fallback (len=%d)", len(text))

        if entry:
            results.setdefault("company_holders", []).append(entry)
    except (ValueError, TypeError, IndexError) as exc:
        _log.debug("Company holder data parse failed: %s", exc)

def _parse_g1_overview_tail(body, off, results):
    """Parse the variable tail of a G1 TREP 01 Overview after the 433-byte
    fixed prefix (Annex 1B §2.2.6.1):

      VuDownloadActivityData (58): downloadingTime(4) + fullCardNumber(18) +
                                   companyOrWorkshopName(36)
      VuCompanyLocksData: noOfLocks(1) + record(98: lockIn(4) + lockOut(4) +
                          companyName(36) + companyAddress(36) + cardNumber(18))×N
      VuControlActivityData: noOfControls(1) + record(31: controlType(1) +
                          controlTime(4) + cardNumber(18) + periodBegin(4) +
                          periodEnd(4))×N

    Returns True when the structure validates (bounds + plausible counts).
    """
    try:
        if off + 58 + 2 > len(body):
            return False
        dl_ts = struct.unpack(">I", body[off:off + 4])[0]
        dl_card = _parse_full_card_number(body, off + 4)
        dl_company = decode_string(body[off + 22:off + 58])
        off += 58

        n_locks = body[off]
        off += 1
        if off + n_locks * 98 + 1 > len(body):
            return False
        locks = []
        for _ in range(n_locks):
            rec = body[off:off + 98]
            lock_in = struct.unpack(">I", rec[0:4])[0]
            lock_out = struct.unpack(">I", rec[4:8])[0]
            if 946684800 <= lock_in <= 4102444800:
                locks.append({
                    "lock_in_time": datetime.fromtimestamp(lock_in, tz=timezone.utc).isoformat(),
                    "lock_out_time": datetime.fromtimestamp(lock_out, tz=timezone.utc).isoformat()
                    if 946684800 <= lock_out <= 4102444800 else None,
                    "company_name": decode_string(rec[8:44]),
                    "company_address": decode_string(rec[44:80]),
                    "company_card": _parse_full_card_number(rec, 80),
                })
            off += 98

        n_ctrl = body[off]
        off += 1
        if off + n_ctrl * 31 > len(body):
            return False
        controls = []
        for _ in range(n_ctrl):
            rec = body[off:off + 31]
            ctrl_ts = struct.unpack(">I", rec[1:5])[0]
            if 946684800 <= ctrl_ts <= 4102444800:
                begin_ts = struct.unpack(">I", rec[23:27])[0]
                end_ts = struct.unpack(">I", rec[27:31])[0]
                controls.append({
                    "control_type": rec[0],
                    "control_time": datetime.fromtimestamp(ctrl_ts, tz=timezone.utc).isoformat(),
                    "control_card": _parse_full_card_number(rec, 5),
                    "download_period_begin": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat()
                    if 946684800 <= begin_ts <= 4102444800 else None,
                    "download_period_end": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
                    if 946684800 <= end_ts <= 4102444800 else None,
                })
            off += 31

        # A populated section must decode mostly valid records, otherwise this
        # is garbage following a false-positive container marker.
        if (n_locks + n_ctrl) > 0 and (len(locks) + len(controls)) < max(1, (n_locks + n_ctrl) // 2):
            return False

        if 946684800 <= dl_ts <= 4102444800:
            results.setdefault("vu_overview", {}).setdefault("last_download", {
                "time": datetime.fromtimestamp(dl_ts, tz=timezone.utc).isoformat(),
                "card": dl_card,
                "company": dl_company,
            })
        if dl_company:
            results.setdefault("company_info", {}).setdefault("name", dl_company)

        existing_locks = results.setdefault("company_locks", [])
        seen = {(lk.get("lock_in_time"), str(lk.get("company_card")))
                for lk in existing_locks if isinstance(lk, dict)}
        for lk in locks:
            key = (lk["lock_in_time"], str(lk["company_card"]))
            if key not in seen:
                seen.add(key)
                existing_locks.append(lk)

        existing_ctrl = results.setdefault("control_activities", [])
        seen = {(c.get("control_time"), c.get("control_type"))
                for c in existing_ctrl if isinstance(c, dict)}
        for c in controls:
            key = (c["control_time"], c["control_type"])
            if key not in seen:
                seen.add(key)
                existing_ctrl.append(c)

        _log.debug("VU overview tail: %d locks, %d controls", len(locks), len(controls))
        return True
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("VU overview tail parse failed: %s", exc)
        return False


def parse_g1_vu_overview(val, results):
    """Parse G1 VU Overview (TREP 01, container 0x7601) — Annex 1B §4.5.3.2.2.

    Fixed prefix (433 bytes, from C# VehicleUnitData.config):
      MemberStateCertificate   194  Certificate (Annex 1B §2.30)
      VuCertificate            194  Certificate (Annex 1B §2.29)
      VehicleIdentificationNumber  17  SimpleString(17) — VIN
      VehicleRegistrationNation    1  NationNumeric
      VehicleRegistrationNumber   14  InternationalString(13)
      CurrentDateTime              4  TimeReal
      MinDownloadableTimeDate      4  TimeReal
      MaxDownloadableTimeDate      4  TimeReal
      CardSlotsStatus              1  UInt8
    Total fixed: 433 bytes

    Falls back to regex heuristic for company name/card numbers extraction.
    Adds logging to indicate which fields were parsed via fixed-offset vs regex.
    """
    import re
    fixed_fields_parsed = set()
    regex_fields_parsed = set()
    try:
        if len(val) < 200:
            return

        # A candidate body alignment is accepted only when the VIN field at
        # offset 388 is a full 17-char alphanumeric string AND at least one of
        # the three TimeReal fields at 420-432 decodes to a plausible date.
        # This rejects false-positive 0x76 0x01 markers inside certificate or
        # activity data (which is dense with valid timestamps).
        body = None
        candidates = [val[2:], val] if (len(val) > 2 and val[0] == 0x00) else [val, val[2:]]
        for cand in candidates:
            if len(cand) >= 433:
                vin_check = decode_string(cand[388:405], is_id=True)
                ts_fields = struct.unpack(">III", cand[420:432])
                if (len(vin_check) == 17 and vin_check.replace(" ", "").isalnum()
                        and any(946684800 <= t <= 4102444800 for t in ts_fields)):
                    body = cand
                    break
        body_validated = body is not None
        if body is None:
            body = val[2:] if len(val) > 2 and val[0] == 0x00 else val

        if body_validated:
            try:
                parse_g1_certificate(body[0:194], results)
                fixed_fields_parsed.add("ms_certificate")
                if body[194:388]:
                    parse_g1_certificate(body[194:388], results)
                    fixed_fields_parsed.add("vu_certificate")

                vin_raw = body[388:405]
                vin = decode_string(vin_raw, is_id=True)
                if vin and len(vin) >= 8:
                    results["vehicle"]["vin"] = vin
                    fixed_fields_parsed.add("vin")

                results["vehicle"]["registration_nation"] = get_nation(body[405])
                plate = decode_string(body[406:420], is_id=True)
                if plate:
                    results["vehicle"]["plate"] = plate
                fixed_fields_parsed.add("vehicle_registration")

                ts = struct.unpack(">I", body[420:424])[0]
                if 946684800 <= ts <= 4102444800:
                    results["metadata"]["current_datetime"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                    fixed_fields_parsed.add("current_datetime")

                min_dl = struct.unpack(">I", body[424:428])[0]
                max_dl = struct.unpack(">I", body[428:432])[0]
                results.setdefault("vu_overview", {})["downloadable_period"] = {
                    "min": datetime.fromtimestamp(min_dl, tz=timezone.utc).isoformat() if 946684800 <= min_dl <= 4102444800 else "N/A",
                    "max": datetime.fromtimestamp(max_dl, tz=timezone.utc).isoformat() if 946684800 <= max_dl <= 4102444800 else "N/A",
                }
                fixed_fields_parsed.add("downloadable_period")

                slot_status = body[432]
                results.setdefault("vu_overview", {})["card_slot_status"] = {
                    "driver_slot": "occupied" if slot_status & 0x01 else "empty",
                    "codriver_slot": "occupied" if slot_status & 0x02 else "empty",
                    "raw": f"0x{slot_status:02X}",
                }
                fixed_fields_parsed.add("card_slots")

                if _parse_g1_overview_tail(body, 433, results):
                    fixed_fields_parsed.update(
                        ("download_activity", "company_locks", "control_activities"))
            except (struct.error, IndexError, ValueError) as exc:
                _log.debug("VU overview fixed-offset parse failed: %s", exc)

        _log.debug("VU overview fixed-offset fields: %s", sorted(fixed_fields_parsed))

        # Fallback: regex-based extraction for company info and card numbers
        if not results["vehicle"].get("vin"):
            _log.warning("VU overview: VIN not parsed via fixed-offset, trying regex")
            for m in re.finditer(rb'[A-Z0-9]{17}', val[:500]):
                vin = m.group().decode()
                if len(vin) == 17:
                    results["vehicle"]["vin"] = vin
                    regex_fields_parsed.add("vin")
                    break

        if not results["vehicle"].get("plate"):
            _log.warning("VU overview: plate not parsed via fixed-offset, trying regex")
            plate_match = re.search(rb'[\x01-\x1F]?([A-Z0-9]{3,14})\s{3,}', val[150:450])
            if plate_match:
                plate_raw = plate_match.group(1).decode('latin-1').strip()
                if 3 <= len(plate_raw) <= 14:
                    results["vehicle"]["plate"] = plate_raw
                    regex_fields_parsed.add("plate")

        for m in re.finditer(rb'[A-Z][A-Z .&\-]{5,35}\s{2,}', val):
            text = m.group().decode('latin-1').strip()
            if text and len(text) > 5 and not text.startswith('VU'):
                results.setdefault("company_info", {}).setdefault("name", text)
                regex_fields_parsed.add("company_name")
                break

        for m in re.finditer(rb'[A-Z][-]?\d{13,20}', val):
            cn = m.group().decode()
            if len(cn) >= 14:
                # A previous call may already have converted the set to a list.
                card_numbers = set(results.get("card_numbers") or ())
                card_numbers.add(cn)
                results["card_numbers"] = card_numbers
                regex_fields_parsed.add("card_numbers")

        if "card_numbers" in results:
            results["card_numbers"] = sorted(results["card_numbers"])

        if regex_fields_parsed:
            _log.debug("VU overview regex-heuristic fields: %s", sorted(regex_fields_parsed))
    except (ValueError, TypeError, IndexError) as exc:
        _log.debug("VU overview heuristic parse failed: %s", exc)

def parse_vu_download_messages(raw_data, results):
    """Parse VU download messages (SID 0x76 + TREP) in the raw binary data.
    
    Message types (TREP):
      0x01 = Overview (certificates + vehicle ID)
      0x02 = Activities (card holder + daily activity records)
      0x03 = Events & Faults
      0x04 = Detailed speed data
      0x05 = Technical data (calibrations)
      0x06 = Card download
    """
    try:
        pos = 0
        found_messages = []
        while pos < len(raw_data) - 1:
            if raw_data[pos] == 0x76:
                trep = raw_data[pos + 1] if pos + 1 < len(raw_data) else 0
                if trep in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06):
                    found_messages.append((pos, trep))
            pos += 1

        for msg_offset, trep in found_messages:
            data = raw_data[msg_offset + 2:]  # Skip SID+TREP
            if trep == 0x01:
                parse_g1_vu_overview(data, results)
            elif trep == 0x02:
                _parse_trep_02_activities(data, results)
            elif trep == 0x03:
                _parse_trep_03_events_faults(data, results)
            elif trep == 0x04:
                _parse_trep_04_speed(data, results)
            elif trep == 0x05:
                _parse_trep_05_technical(data, results)
            elif trep == 0x06:
                _parse_trep_06_card_download(data, results)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("VU download messages parse failed: %s", exc)

def _parse_trep_02_activities(data, results):
    """Parse TREP 02 (Activities) message: card holder + daily activity records.

    Attempts structured daily record boundary detection first (0x7622/0x7632 markers),
    then falls back to timestamp-scan heuristic.
    """
    import re
    try:
        if len(data) < 50:
            return

        # Detect G2 RecordArray format: starts with 0x76 marker or 0x6864 prefix
        # followed by structured driver records and 0x7622/0x7632 daily records
        is_g2 = False
        if len(data) >= 4:
            lead = struct.unpack(">H", data[:2])[0]
            lead2 = struct.unpack(">H", data[1:3])[0]
            if lead == 0x6864 or lead2 == 0x6864:
                is_g2 = True
        if not is_g2:
            for pattern in (b'\x76\x22', b'\x76\x32'):
                if pattern in data[:500]:
                    is_g2 = True
                    break

        if is_g2:
            _log.debug("TREP 02: G2 RecordArray format detected, delegating to structured parser")
            from .record_array import parse_g2_trep02_activities
            parse_g2_trep02_activities(data, results)
            return

        if _parse_trep_02_g1_structured(data, results):
            return

        if len(data) < 110:
            _log.debug("TREP 02: data too short for G1 parsing (len=%d)", len(data))
            return

        # Validate binary header timestamp
        header_ts = struct.unpack(">I", data[0:4])[0]
        if not (946684800 <= header_ts <= 4102444800):
            _log.debug("TREP 02: invalid header timestamp 0x%08X, aborting", header_ts)
            return

        off = 10  # skip binary header (4+2+2+2)
        surname = decode_string(data[off:off+36])
        off += 36
        if off < len(data) and data[off] <= 0x02:
            off += 1
        firstname = decode_string(data[off:off+36])
        off += 36
        if off < len(data) and data[off] <= 0x02:
            off += 1
        card_start = off
        if off < len(data) and not (0x30 <= data[off] <= 0x39 or 0x41 <= data[off] <= 0x5A):
            off += 1
        card_num = decode_string(data[off:off+17])
        off += 17

        surname_s = surname.strip()
        firstname_s = firstname.strip()

        valid_chars = sum(1 for c in surname_s if 32 <= ord(c) < 127)
        if not surname_s or valid_chars < len(surname_s) * 0.7:
            _log.debug("TREP 02: invalid surname (valid_chars=%d/%d), aborting",
                       valid_chars, len(surname_s))
            return

        # Check for plate after card holder (nation byte + alphanumeric plate)
        plate_str = ""
        plate_match = re.search(rb'([\x01-\x1F])([A-Z0-9]{3,14})\s{2,}', data[card_start:card_start+250])
        if plate_match:
            plate_str = plate_match.group(2).decode('latin-1').strip()

        # Save driver info
        drivers = results.setdefault("inserted_drivers", [])
        driver_key = f"{surname_s}|{firstname_s}|{card_num.strip()}|{plate_str}"
        if not any(d.get("_key") == driver_key for d in drivers):
            drivers.append({
                "surname": surname_s, "firstname": firstname_s,
                "card_number": card_num.strip(), "plate": plate_str,
                "_key": driver_key,
            })

        _log.debug("TREP 02: structured G1 parse — driver=%s %s, scanning for daily records from offset %d",
                   surname_s, firstname_s, card_start)

        # Attempt daily record boundary detection: look for 0x7622/0x7632 markers
        daily_boundaries = []
        for m in re.finditer(rb'(\x76\x22|\x76\x32)', data[card_start:]):
            daily_boundaries.append(card_start + m.start())

        # Find daily activity change records within the TREP 02 payload.
        # Prioritize boundary-aligned records; fall back to timestamp-scan heuristic.
        activity_list = results.setdefault("activities", [])
        activity_map = {0: "rest", 1: "available", 2: "work", 3: "drive", 4: "break_rest"}
        header_dt = datetime.fromtimestamp(header_ts, tz=timezone.utc)
        scan = card_start

        if daily_boundaries:
            _log.debug("TREP 02: found %d daily record boundaries (0x7622/0x7632 markers)", len(daily_boundaries))
        else:
            _log.debug("TREP 02: no daily record boundaries found, using timestamp-scan heuristic")

        daily_count = 0
        while scan + 10 <= len(data):
            ts = struct.unpack(">I", data[scan:scan+4])[0]
            if not (946684800 <= ts <= 4102444800):
                scan += 1
                continue

            odo = int.from_bytes(data[scan+4:scan+7], 'big')
            card_inserted = data[scan+7]
            no_changes = struct.unpack(">H", data[scan+8:scan+10])[0]

            if no_changes == 0 or no_changes > 1440:
                scan += 1
                continue

            pair_pos = scan + 10
            max_changes = min(no_changes, 300)
            changes_list = []
            for _ in range(max_changes):
                if pair_pos + 4 > len(data):
                    break
                slot = struct.unpack(">H", data[pair_pos:pair_pos+2])[0]
                act = struct.unpack(">H", data[pair_pos+2:pair_pos+4])[0]
                pair_pos += 4
                if slot <= 1440 and 0 <= act <= 10:
                    changes_list.append({"minute": slot, "activity": activity_map.get(act, f"type_{act}")})
                elif slot == 0 and act == 0:
                    break
                else:
                    changes_list = []
                    break

            if changes_list:
                type_map_it = {"drive": "DRIVE", "rest": "REST", "work": "WORK", "available": "AVAILABLE", "break_rest": "REST"}
                eventi = [
                    {"tipo": type_map_it.get(c.get("activity", "work"), "WORK"),
                     "ora": f"{c['minute'] // 60:02d}:{c['minute'] % 60:02d}"}
                    for c in changes_list[:50]
                ]
                activity_list.append({
                    "timestamp": header_dt.isoformat(),
                    "data": header_dt.strftime("%d/%m/%Y"),
                    "odometer_midnight": odo,
                    "card_inserted": bool(card_inserted),
                    "changes_count": no_changes,
                    "changes": changes_list[:50],
                    "eventi": eventi,
                    "driver": f"{surname_s} {firstname_s}".strip(),
                })
                skip_to = min((b for b in daily_boundaries if b > scan), default=-1)
                if skip_to > 0 and skip_to < pair_pos + 500:
                    scan = skip_to
                else:
                    scan = pair_pos
                daily_count += 1
            else:
                scan += 1

        if daily_boundaries and daily_count > 0:
            boundary_pct = round(daily_count / len(daily_boundaries) * 100) if daily_boundaries else 0
            _log.debug("TREP 02: boundary-aligned parse: %d/%d records (%d%%)", daily_count, len(daily_boundaries), boundary_pct)
        elif daily_count > 0:
            _log.debug("TREP 02: timestamp-scan heuristic found %d daily records", daily_count)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 02 activities parse failed: %s", exc)

def _parse_trep_02_g1_structured(data, results):
    """Parse a G1 TREP 02 (Activities) message — Annex 1B §2.2.6.2:

      dateOfDay(4, TimeReal) + odometerValueMidnight(3) +
      VuCardIWData:       noOfIWRecords(2) + VuCardIWRecord(129)×N
      VuActivityDailyData: noOfActivityChanges(2) + ActivityChangeInfo(2)×N
      VuPlaceDailyWorkPeriodData: noOfPlaceRecords(1) + record(28)×N
      VuSpecificConditionData:    noOfSpecificConditionRecords(2) + record(5)×N

    VuCardIWRecord (129): holderSurname(36) + holderFirstNames(36) +
      fullCardNumber(18) + cardExpiry(4) + insertionTime(4) + odoInsertion(3) +
      cardSlot(1) + withdrawalTime(4) + odoWithdrawal(3) +
      previousVehicle(15) + previousWithdrawalTime(4) + manualInputFlag(1)

    Place record (28): fullCardNumber(18) + entryTime(4) + entryType(1) +
      country(1) + region(1) + odometer(3)

    Validated against real G1 VU downloads (one message per downloaded day,
    each followed by its 128-byte RSA signature). Returns True when the
    structure validates; the caller falls back to the heuristic otherwise.
    """
    try:
        if len(data) < 11:
            return False
        date_ts = struct.unpack(">I", data[0:4])[0]
        if not (946684800 <= date_ts <= 4102444800):
            return False
        odo_midnight = int.from_bytes(data[4:7], 'big')
        pos = 7

        n_iw = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        if n_iw > 100 or pos + n_iw * 129 + 2 > len(data):
            return False
        iw_records = []
        for _ in range(n_iw):
            rec = data[pos:pos + 129]
            ins_ts = struct.unpack(">I", rec[94:98])[0]
            wdr_ts = struct.unpack(">I", rec[102:106])[0]
            iw_records.append({
                "holder_surname": decode_string(rec[0:36]),
                "holder_first_names": decode_string(rec[36:72]),
                "card": _parse_full_card_number(rec, 72),
                "card_expiry": decode_date(rec[90:94]),
                "insertion_time": datetime.fromtimestamp(ins_ts, tz=timezone.utc).isoformat()
                if 946684800 <= ins_ts <= 4102444800 else None,
                "odometer_insertion_km": int.from_bytes(rec[98:101], 'big'),
                "card_slot": rec[101],
                "withdrawal_time": datetime.fromtimestamp(wdr_ts, tz=timezone.utc).isoformat()
                if 946684800 <= wdr_ts <= 4102444800 else None,
                "odometer_withdrawal_km": int.from_bytes(rec[106:109], 'big'),
                "manual_input": bool(rec[128]),
            })
            pos += 129

        n_ch = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        if n_ch > 5000 or pos + n_ch * 2 + 1 > len(data):
            return False
        changes = []
        for i in range(n_ch):
            v = struct.unpack(">H", data[pos + i * 2:pos + i * 2 + 2])[0]
            changes.append(decode_activity_val(v))
        pos += n_ch * 2

        n_pl = data[pos]
        pos += 1
        if pos + n_pl * 28 + 2 > len(data):
            return False
        entry_names = {0x00: "START", 0x01: "END", 0x02: "START", 0x03: "END"}
        places = []
        for _ in range(n_pl):
            rec = data[pos:pos + 28]
            ts = struct.unpack(">I", rec[18:22])[0]
            if 946684800 <= ts <= 4102444800 and rec[22] in entry_names:
                places.append({
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "entry_type": entry_names[rec[22]],
                    "type_code": rec[22],
                    "nation": get_nation(rec[23]),
                    "region": rec[24],
                    "odometer_km": int.from_bytes(rec[25:28], 'big'),
                    "card_driver": _parse_full_card_number(rec, 0),
                })
            pos += 28

        n_sc = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        if n_sc > 1000 or pos + n_sc * 5 > len(data):
            return False
        sc_types = {0x00: "Ferry", 0x01: "Train", 0x02: "OutOfScope",
                    0x03: "BeginAreaNoGNSS", 0x04: "EndAreaNoGNSS"}
        conditions = []
        for _ in range(n_sc):
            rec = data[pos:pos + 5]
            ts = struct.unpack(">I", rec[0:4])[0]
            if 946684800 <= ts <= 4102444800 and rec[4] in sc_types:
                conditions.append({
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "condition": sc_types[rec[4]],
                    "type_code": rec[4],
                })
            pos += 5

        # Emit (with dedup — the message scan can revisit the same block).
        drivers = results.setdefault("inserted_drivers", [])
        for iw in iw_records:
            card_num = (iw["card"] or {}).get("card_number", "")
            dk = f"{iw['holder_surname']}|{iw['holder_first_names']}|{card_num}"
            if iw["holder_surname"] and not any(d.get("_key") == dk for d in drivers):
                drivers.append({
                    "surname": iw["holder_surname"],
                    "firstname": iw["holder_first_names"],
                    "card_number": card_num,
                    "_key": dk,
                })
        existing_iw = results.setdefault("card_iw_records", [])
        seen = {(r.get("insertion_time"), str(r.get("card"))) for r in existing_iw if isinstance(r, dict)}
        for iw in iw_records:
            key = (iw["insertion_time"], str(iw["card"]))
            if key not in seen:
                seen.add(key)
                existing_iw.append(iw)

        date_str = datetime.fromtimestamp(date_ts, tz=timezone.utc).strftime('%d/%m/%Y')
        if changes:
            activities = results.setdefault("activities", [])
            if not any(a.get("data") == date_str and a.get("source") == "vu_trep02"
                       for a in activities if isinstance(a, dict)):
                activities.append({
                    "data": date_str,
                    "km": odo_midnight,
                    "eventi": changes,
                    "changes_count": n_ch,
                    "source": "vu_trep02",
                })

        existing_places = results.setdefault("places", [])
        seen = {(p.get("timestamp"), p.get("type_code")) for p in existing_places if isinstance(p, dict)}
        for p in places:
            key = (p["timestamp"], p["type_code"])
            if key not in seen:
                seen.add(key)
                existing_places.append(p)

        existing_sc = results.setdefault("specific_conditions", [])
        seen = {(c.get("timestamp"), c.get("type_code")) for c in existing_sc if isinstance(c, dict)}
        for c in conditions:
            key = (c["timestamp"], c["type_code"])
            if key not in seen:
                seen.add(key)
                existing_sc.append(c)

        return True
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 02 G1 structured parse failed: %s", exc)
        return False


def _parse_full_card_number(data, offset):
    """Parse 18-byte FullCardNumber (Annex 1B §2.73):
    cardType(1) + cardIssuingMemberState(1) + cardNumber(16)."""
    if offset + 18 > len(data):
        return None
    card_type = data[offset]
    nation = get_nation(data[offset + 1])
    card_num = decode_string(data[offset + 2:offset + 18], is_id=True)
    return {
        "card_type": card_type,
        "nation": nation,
        "card_number": f"{nation}{card_num}",
    }


def _parse_vu_fault_record(data, offset):
    """Parse VuFaultRecord — ASN.1 (tachograph.asn:324-333), 82 bytes."""
    if offset + 82 > len(data):
        return None
    rec = data[offset:offset + 82]
    fault_type = rec[0]
    fault_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    if begin_ts < 946684800 or begin_ts > 4102444800:
        return None
    return {
        "descrizione": describe_fault(fault_type),
        "fault_type": fault_type,
        "fault_purpose": fault_purpose,
        "begin_time": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat(),
        "end_time": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat() if 946684800 <= end_ts <= 4102444800 else "N/A",
        "card_driver_begin": _parse_full_card_number(rec, 10),
        "card_codriver_begin": _parse_full_card_number(rec, 28),
        "card_driver_end": _parse_full_card_number(rec, 46),
        "card_codriver_end": _parse_full_card_number(rec, 64),
    }


def _parse_vu_event_record(data, offset):
    """Parse VuEventRecord — ASN.1 (tachograph.asn:335-345), 83 bytes."""
    if offset + 83 > len(data):
        return None
    rec = data[offset:offset + 83]
    evt_type = rec[0]
    evt_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    if begin_ts < 946684800 or begin_ts > 4102444800:
        return None
    return {
        "descrizione": describe_event(evt_type),
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "begin_time": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat(),
        "end_time": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat() if 946684800 <= end_ts <= 4102444800 else "N/A",
        "card_driver_begin": _parse_full_card_number(rec, 10),
        "card_codriver_begin": _parse_full_card_number(rec, 28),
        "card_driver_end": _parse_full_card_number(rec, 46),
        "card_codriver_end": _parse_full_card_number(rec, 64),
        "similar_events": rec[82],
    }


def _parse_trep_03_events_faults(data, results):
    """Parse TREP 03 (Events & Faults) — Annex 1B §2.2.6.3 deterministic layout:

      VuFaultData:             noOfVuFaults(1) + VuFaultRecord(82)×N
      VuEventData:             noOfVuEvents(1) + VuEventRecord(83)×N
      VuOverSpeedingControlData(9)
      VuOverSpeedingEventData: noOfVuOverSpeedingEvents(1) + record(31)×N
      VuTimeAdjustmentData:    noOfVuTimeAdjustments(1) + record(98)×N

    Validated against real G1 VU downloads (each TREP block is followed by its
    128-byte RSA signature). Falls back to heuristic pattern matching if the
    count-prefixed structure does not validate.
    """
    if not _parse_trep_03_structured(data, results):
        _parse_trep_03_events_faults_heuristic(data, results)


def _parse_trep_03_structured(data, results):
    """Count-prefixed TREP 03 walk. Returns True when the structure validates."""
    try:
        if len(data) < 12:
            return False
        pos = 0
        n_faults = data[pos]
        pos += 1
        if pos + n_faults * 82 > len(data):
            return False
        faults = []
        for _ in range(n_faults):
            rec = _parse_vu_fault_record(data, pos)
            if rec is not None:
                faults.append(rec)
            pos += 82

        n_events = data[pos]
        pos += 1
        if pos + n_events * 83 > len(data):
            return False
        events = []
        for _ in range(n_events):
            rec = _parse_vu_event_record(data, pos)
            if rec is not None:
                events.append(rec)
            pos += 83

        # Records can be empty (0xFF padding) but a populated structure must
        # decode mostly valid timestamps, otherwise this is a false positive.
        total = n_faults + n_events
        if total > 0 and (len(faults) + len(events)) < max(1, total // 2):
            return False

        if pos + 9 > len(data):
            return False
        osc_last = struct.unpack(">I", data[pos:pos + 4])[0]
        osc_first = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        osc_count = data[pos + 8]
        pos += 9

        n_overs = data[pos]
        pos += 1
        if pos + n_overs * 31 > len(data):
            return False
        overspeed = []
        for _ in range(n_overs):
            rec = data[pos:pos + 31]
            begin_ts = struct.unpack(">I", rec[2:6])[0]
            end_ts = struct.unpack(">I", rec[6:10])[0]
            if 946684800 <= begin_ts <= 4102444800:
                overspeed.append({
                    "descrizione": describe_event(rec[0]),
                    "event_type": rec[0],
                    "record_purpose": rec[1],
                    "begin": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat(),
                    "end": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
                    if 946684800 <= end_ts <= 4102444800 else "N/A",
                    "max_speed_kmh": rec[10],
                    "average_speed_kmh": rec[11],
                    "card_driver": _parse_full_card_number(rec, 12),
                    "similar_events": rec[30],
                })
            pos += 31

        n_adj = data[pos]
        pos += 1
        if pos + n_adj * 98 > len(data):
            return False
        adjustments = []
        for _ in range(n_adj):
            rec = data[pos:pos + 98]
            old_ts = struct.unpack(">I", rec[0:4])[0]
            new_ts = struct.unpack(">I", rec[4:8])[0]
            if 946684800 <= new_ts <= 4102444800:
                adjustments.append({
                    "old_time": datetime.fromtimestamp(old_ts, tz=timezone.utc).isoformat()
                    if 946684800 <= old_ts <= 4102444800 else "N/A",
                    "new_time": datetime.fromtimestamp(new_ts, tz=timezone.utc).isoformat(),
                    "workshop_name": decode_string(rec[8:44]),
                    "workshop_address": decode_string(rec[44:80]),
                    "workshop_card": _parse_full_card_number(rec, 80),
                })
            pos += 98

        # Emit with dedup — the message scan can hit the same block twice.
        # Keys include end time and record purpose: the VU stores distinct
        # records sharing the same (type, begin), e.g. one per record purpose.
        existing_faults = results.setdefault("faults", [])
        seen = {(f.get("fault_type"), f.get("begin_time"), f.get("end_time"), f.get("fault_purpose"))
                for f in existing_faults if isinstance(f, dict)}
        for f in faults:
            key = (f.get("fault_type"), f.get("begin_time"), f.get("end_time"), f.get("fault_purpose"))
            if key not in seen:
                seen.add(key)
                existing_faults.append(f)

        existing_events = results.setdefault("events", [])
        seen = {(e.get("type_code"), e.get("begin_time"), e.get("end_time"), e.get("record_purpose"))
                for e in existing_events if isinstance(e, dict)}
        for evt in events:
            key = (evt["event_type"], evt["begin_time"], evt["end_time"], evt["event_purpose"])
            if key not in seen:
                seen.add(key)
                existing_events.append({
                    "descrizione": describe_event(evt["event_type"]),
                    "type_code": evt["event_type"],
                    "record_purpose": evt["event_purpose"],
                    "begin_time": evt["begin_time"],
                    "end_time": evt["end_time"],
                    "similar_events": evt["similar_events"],
                    "card_driver_begin": evt["card_driver_begin"],
                })

        if 946684800 <= osc_last <= 4102444800 or 946684800 <= osc_first <= 4102444800:
            ctrl = {
                "last_control_time": datetime.fromtimestamp(osc_last, tz=timezone.utc).isoformat()
                if 946684800 <= osc_last <= 4102444800 else "N/A",
                "first_overspeed_since": datetime.fromtimestamp(osc_first, tz=timezone.utc).isoformat()
                if 946684800 <= osc_first <= 4102444800 else "N/A",
                "number_of_overspeed": osc_count,
            }
            ctrl_list = results.setdefault("overspeeding_control", [])
            if ctrl not in ctrl_list:
                ctrl_list.append(ctrl)

        existing_overs = results.setdefault("overspeeding_events", [])
        seen = {(o.get("event_type"), o.get("begin"), o.get("end"), o.get("record_purpose"))
                for o in existing_overs if isinstance(o, dict)}
        for o in overspeed:
            key = (o["event_type"], o["begin"], o["end"], o["record_purpose"])
            if key not in seen:
                seen.add(key)
                existing_overs.append(o)

        existing_adj = results.setdefault("time_adjustments", [])
        seen = {(a.get("old_time"), a.get("new_time")) for a in existing_adj if isinstance(a, dict)}
        for a in adjustments:
            key = (a["old_time"], a["new_time"])
            if key not in seen:
                seen.add(key)
                existing_adj.append(a)

        _log.debug("TREP 03 structured: %d faults, %d events, %d overspeeding, %d time adj",
                   len(faults), len(events), len(overspeed), len(adjustments))
        return True
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 03 structured parse failed: %s", exc)
        return False


def _parse_trep_03_events_faults_heuristic(data, results):
    """Fallback heuristic parser for TREP 03 — adds structured record-boundary detection
    before falling back to byte-by-byte regex scanning."""
    import re
    try:
        _log.warning("TREP 03: primary structured parser failed, entering heuristic fallback")
        surname = firstname = card_num = ""
        card_match = re.search(rb'[\x01\x02][\x1a\x1b]([A-Z]\d{14,20})', data)
        if card_match:
            card_num = card_match.group(1).decode()
            end_pos = card_match.start()
            if end_pos > 72:
                name_region = data[max(0, end_pos - 100):end_pos]
                name_match = re.search(rb'[\x01]([A-Z][A-Z ]{10,35})\s{2,}([\x01][A-Z][A-Z ]{10,35})', name_region)
                if name_match:
                    surname = name_match.group(1).decode('latin-1').strip()
                    firstname = name_match.group(2).decode('latin-1').replace('\x01', '').strip()

        if surname or firstname or card_num:
            drivers = results.setdefault("inserted_drivers", [])
            dk = f"{surname}|{firstname}|{card_num}"
            if not any(d.get("_key") == dk for d in drivers):
                drivers.append({"surname": surname, "firstname": firstname, "card_number": card_num, "_key": dk})

        # Attempt 1: Structured record-boundary detection (82B faults, 83B events)
        pos = 2
        structured_count = 0
        while pos + 82 <= len(data) and structured_count < 500:
            if 0x01 <= data[pos] <= 0xFF:
                fault = _parse_vu_fault_record(data, pos)
                if fault is not None:
                    results.setdefault("faults", []).append(fault)
                    pos += 82
                    structured_count += 1
                    continue
            if pos + 83 <= len(data):
                evt = _parse_vu_event_record(data, pos)
                if evt is not None:
                    results.setdefault("events", []).append({
                        "descrizione": describe_event(evt["event_type"]),
                        "type_code": evt["event_type"],
                        "begin_time": evt["begin_time"],
                        "end_time": evt["end_time"],
                        "similar_events": evt.get("similar_events", 0),
                        "card_driver_begin": evt.get("card_driver_begin"),
                    })
                    pos += 83
                    structured_count += 1
                    continue
            break

        if structured_count > 0:
            _log.debug("TREP 03 heuristic: structured record detection found %d records", structured_count)
            return

        # Attempt 2: byte-by-byte scan (original fallback)
        _log.debug("TREP 03 heuristic: structured record detection failed, using byte-scan")
        pos = 2
        seen_timestamps = set()
        while pos + 9 < len(data) and len(results.get("events", [])) < 200:
            ev_type = data[pos]
            if 0x01 <= ev_type <= 0x0C:
                ts1 = struct.unpack(">I", data[pos + 1:pos + 5])[0]
                ts2 = struct.unpack(">I", data[pos + 5:pos + 9])[0]
                if 946684800 <= ts1 <= 4102444800 and 946684800 <= ts2 <= 4102444800:
                    tskey = (ts1, ev_type)
                    if tskey not in seen_timestamps:
                        seen_timestamps.add(tskey)
                        dt1 = datetime.fromtimestamp(ts1, tz=timezone.utc).isoformat()
                        dt2 = datetime.fromtimestamp(ts2, tz=timezone.utc).isoformat()
                        results.setdefault("events", []).append({
                            "descrizione": describe_event(ev_type),
                            "type_code": ev_type,
                            "begin_time": dt1,
                            "end_time": dt2,
                            "driver": f"{surname} {firstname}".strip(),
                        })
                    pos += 9
                    continue
            pos += 1
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 03 heuristic parse failed: %s", exc)

def _parse_trep_04_speed(data, results):
    """Parse TREP 04 (VuDetailedSpeedData) — Annex 1B §2.2.6.4:
    noOfSpeedBlocks(2) + N × VuDetailedSpeedBlock(64), each block =
    speedBlockBeginDate(4, TimeReal) + 60 speed samples (1 byte per second).

    Consecutive one-minute blocks are aggregated into driving runs to keep
    the output compact (one entry per uninterrupted recording period).
    """
    try:
        if len(data) < 2 + 64:
            return
        n_blocks = struct.unpack(">H", data[0:2])[0]
        if n_blocks == 0 or 2 + n_blocks * 64 > len(data):
            return
        first_ts = struct.unpack(">I", data[2:6])[0]
        if not (946684800 <= first_ts <= 4102444800):
            return  # false-positive message marker

        speed_blocks = results.setdefault("speed_blocks", [])
        seen = {b.get("timestamp") for b in speed_blocks if isinstance(b, dict)}

        run_start_ts = None
        run_minutes = 0
        run_speeds = []
        prev_ts = None

        def _flush():
            if run_start_ts is None or not run_speeds:
                return
            dt = datetime.fromtimestamp(run_start_ts, tz=timezone.utc).isoformat()
            if dt in seen:
                return
            seen.add(dt)
            speed_blocks.append({
                "timestamp": dt,
                "minutes": run_minutes,
                "average_speed_kmh": round(sum(run_speeds) / len(run_speeds), 1),
                "max_speed_kmh": max(run_speeds),
                "speeds_sample": run_speeds[:60],
            })

        for i in range(n_blocks):
            blk = data[2 + i * 64:2 + (i + 1) * 64]
            ts = struct.unpack(">I", blk[0:4])[0]
            if not (946684800 <= ts <= 4102444800):
                continue
            speeds = [s for s in blk[4:64] if s != 0xFF]
            if prev_ts is None or ts - prev_ts != 60:
                _flush()
                run_start_ts = ts
                run_minutes = 0
                run_speeds = []
            run_minutes += 1
            run_speeds.extend(speeds)
            prev_ts = ts
        _flush()
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 04 speed parse failed: %s", exc)

def _parse_trep_05_technical(data, results):
    """Parse TREP 05 (Technical Data) — Annex 1B §2.2.6.5 deterministic layout:

      VuIdentification (116): manufacturerName(36) + manufacturerAddress(36) +
        partNumber(16) + serialNumber(8) + softwareVersion(4) +
        softwareInstallationDate(4) + manufacturingDate(4) + approvalNumber(8)
      SensorPaired (20): serialNumber(8) + approvalNumber(8) + pairingDateFirst(4)
      VuCalibrationData: noOfCalibrationRecords(1) + VuCalibrationRecord(167)×N

    Falls back to regex VIN-scan heuristic when the structure does not validate.
    """
    import re
    try:
        if len(data) < 50:
            _log.debug("TREP 05: data too short (len=%d)", len(data))
            return

        cal_records = results.setdefault("calibrations", [])
        workshops = results.setdefault("workshops", [])
        cal_vins = results.setdefault("calibration_vins", set())
        purpose_map = {0x01:"Activation", 0x02:"FirstInstall", 0x03:"FirstInstallOther",
                       0x04:"Inspection", 0x05:"PeriodicInspection", 0x06:"Coupling",
                       0x0A:"EnforcementInspection"}

        def _decode_cal_record(chunk):
            """Decode one 167-byte VuCalibrationRecord (Annex 1B §2.118).
            Returns the entry dict or None when the record is empty/garbage."""
            vin = decode_string(chunk[95:112], is_id=True)
            if len(vin) != 17 or not vin.isalnum():
                return None
            purpose = chunk[0]
            workshop_name = decode_string(chunk[1:37])
            workshop_address = decode_string(chunk[37:73])
            # FullCardNumber (§2.73): cardType(1) + nation(1) + cardNumber(16)
            ws_card_nation = get_nation(chunk[74])
            ws_card_number = decode_string(chunk[75:91], is_id=True)
            ws_card_expiry = decode_date(chunk[91:95])
            nation = get_nation(chunk[112])
            # VehicleRegistrationNumber = codePage(1) + 13 chars
            plate = decode_string(chunk[114:127], is_id=True)
            w_const = struct.unpack(">H", chunk[127:129])[0]
            k_const = struct.unpack(">H", chunk[129:131])[0]
            l_const = struct.unpack(">H", chunk[131:133])[0]
            tyre = decode_string(chunk[133:148])
            speed = chunk[148]
            old_odo = int.from_bytes(chunk[149:152], 'big')
            if old_odo == 0xFFFFFF:
                old_odo = None
            new_odo = int.from_bytes(chunk[152:155], 'big')
            if new_odo == 0xFFFFFF:
                new_odo = None
            old_time = decode_date(chunk[155:159])
            new_time = decode_date(chunk[159:163])
            next_cal = decode_date(chunk[163:167])
            if old_time == "N/A":
                return None
            if not (0 < w_const < 65535 and 0 < l_const < 65535):
                return None
            return {
                "_key": f"{vin}|{old_time}|{workshop_name}|{old_odo}|{purpose}",
                "timestamp": old_time,
                "purpose": purpose_map.get(purpose, f"0x{purpose:02X}" if purpose else ""),
                "purpose_code": purpose,
                "vin": vin,
                "registration_nation": nation,
                "plate": plate,
                "workshop": workshop_name,
                "workshop_address": workshop_address,
                "workshop_card": f"{ws_card_nation}{ws_card_number}",
                "workshop_card_expiry": ws_card_expiry,
                "w_constant": w_const,
                "k_constant": k_const,
                "l_tyre_circumference": l_const,
                "tyre_size": tyre,
                "speed_limit": speed,
                "odometer": old_odo,
                "new_odometer": new_odo,
                "old_time": old_time,
                "new_time": new_time,
                "next_calibration_date": next_cal,
            }

        # Attempt 1: deterministic VuIdentification + SensorPaired + calibrations
        structured_count = 0
        mfr = decode_string(data[0:36])
        addr = decode_string(data[36:72])
        n_cal = data[136] if len(data) > 136 else 0
        structure_fits = len(data) >= 137 + n_cal * 167
        if len(mfr) >= 3 and structure_fits:
            decoded = []
            for i in range(n_cal):
                chunk = data[137 + i * 167:137 + (i + 1) * 167]
                entry = _decode_cal_record(chunk)
                if entry is not None:
                    decoded.append(entry)
            # A populated calibration area must decode mostly valid records,
            # otherwise this is a false-positive message marker.
            if n_cal == 0 or len(decoded) >= max(1, n_cal // 2):
                vu_info = results.setdefault("vu_info", {})
                vu_info["manufacturer"] = mfr
                if addr:
                    vu_info["manufacturer_address"] = addr
                part_number = decode_string(data[72:88], is_id=True)
                if part_number:
                    vu_info["part_number"] = part_number
                vu_info["serial_number"] = data[88:96].hex().upper()
                sw_version = decode_string(data[96:100], is_id=True)
                if sw_version:
                    vu_info["software_version"] = sw_version
                sw_install = decode_date(data[100:104])
                if sw_install != "N/A":
                    vu_info["software_install_date"] = sw_install
                mfg_date = decode_date(data[104:108])
                if mfg_date != "N/A":
                    vu_info["manufacturing_date"] = mfg_date
                approval = decode_string(data[108:116], is_id=True)
                if approval:
                    vu_info["approval_number"] = approval
                vu_info["sensor_serial_number"] = data[116:124].hex().upper()
                sensor_approval = decode_string(data[124:132], is_id=True)
                if sensor_approval:
                    vu_info["sensor_approval_number"] = sensor_approval
                sensor_pairing = decode_date(data[132:136])
                if sensor_pairing != "N/A":
                    vu_info["sensor_pairing_date"] = sensor_pairing

                for entry in decoded:
                    if not any(c.get("_key") == entry["_key"] for c in cal_records):
                        cal_records.append(entry)
                        if entry["workshop"] and entry["workshop"] not in workshops:
                            workshops.append(entry["workshop"])
                        cal_vins.add(entry["vin"])
                        structured_count += 1

        if structured_count > 0 or (len(mfr) >= 3 and structure_fits and n_cal == 0):
            _log.debug("TREP 05: structured parse found %d calibrations", structured_count)
            return

        # Fallback: legacy header decode (manufacturer fields only)
        if mfr:
            results.setdefault("vu_info", {}).setdefault("manufacturer", mfr)
        if addr:
            results.setdefault("vu_info", {}).setdefault("manufacturer_address", addr)
        off = 80

        # Attempt 2: Regex VIN-scan heuristic (original fallback)
        _log.debug("TREP 05: structured record extraction failed, falling back to regex VIN-scan")

        for vin_match in re.finditer(rb'[A-Z0-9]{17}', data[off:]):
            vin = vin_match.group().decode()
            vin_pos = off + vin_match.start()
            if not (vin.isalnum() and len(vin) == 17):
                continue

            # Fixed structure after VIN: nation(1) + plate(14) + W(2) + K(2) + L(2) + tyre(15) + speed(1) + odo(3) = 40 bytes
            if vin_pos + 17 + 40 > len(data):
                continue
            fixed = data[vin_pos+17:vin_pos+17+40]
            nation = fixed[0]

            # Filter garbage plates (should be printable ASCII)
            plate_raw = fixed[1:15]
            plate = decode_string(plate_raw, is_id=True)
            if plate and len(plate) < 2:
                continue

            w = struct.unpack(">H", fixed[15:17])[0]
            k = struct.unpack(">H", fixed[17:19])[0]
            l_val = struct.unpack(">H", fixed[19:21])[0]
            tyre = decode_string(fixed[21:36])
            speed_limit = fixed[36]
            odo = int.from_bytes(fixed[37:40], 'big')
            if odo == 0xFFFFFF:
                odo = None

            # Find timestamp (4 bytes before VIN)
            ts = 0
            dt_str = ""
            for shift in [4, 6, 7, 8]:
                if vin_pos >= shift + 4:
                    ts_raw = data[vin_pos-shift-4:vin_pos-shift]
                    ts = struct.unpack(">I", ts_raw)[0]
                    if 946684800 <= ts <= 4102444800:
                        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                        break

            # Find workshop name backwards from VIN
            ws_name = ""
            ws_addr = ""
            search_start = max(off, vin_pos - 250)
            search_region = data[search_start:vin_pos]
            ws_match = re.search(rb'[\x01\x02]([A-Z][A-Z .&\-]{10,35})\s{2,}', search_region[-200:])
            if ws_match:
                ws_name = ws_match.group(1).decode('latin-1').strip()
                addr_region = search_region[ws_match.end()-100:min(len(search_region), ws_match.end()+100)]
                addr_match = re.search(rb'[\x01]([A-Z][A-Z.\- 0-9]{10,35})\s{2,}', bytes(addr_region))
                if addr_match:
                    ws_addr = addr_match.group(1).decode('latin-1').strip()

            # Purpose code: scan backwards from workshop
            purpose = 0
            if ws_match:
                before_ws = search_region[max(0,ws_match.start()-20):ws_match.start()]
                for b in reversed(before_ws):
                    if 0x01 <= b <= 0x0A:
                        purpose = b
                        break

            cal_key = f"{vin}|{dt_str}|{ws_name}|{odo}"
            # Deduplicate and filter garbage W/K/L
            if not any(c.get("_key") == cal_key for c in cal_records) and 0 < w < 65535 and 0 < l_val < 65535:
                cal_records.append({
                    "_key": cal_key,
                    "timestamp": dt_str,
                    "purpose": purpose_map.get(purpose, f"0x{purpose:02X}" if purpose else ""),
                    "purpose_code": purpose,
                    "vin": vin,
                    "registration_nation": get_nation(nation),
                    "plate": plate,
                    "workshop": ws_name,
                    "workshop_address": ws_addr,
                    "w_constant": w,
                    "k_constant": k,
                    "l_tyre_circumference": l_val,
                    "tyre_size": tyre,
                    "speed_limit": speed_limit,
                    "odometer": odo,
                })
                if ws_name and ws_name not in workshops:
                    workshops.append(ws_name)
                cal_vins.add(vin)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 05 technical parse failed: %s", exc)

def _parse_trep_06_card_download(data, results):
    """Parse TREP 06 (Card Download) message — data downloaded from inserted cards."""
    import re
    try:
        if len(data) < 20:
            return
        downloads = results.setdefault("card_downloads", [])
        
        # Find card numbers
        card_nums = []
        for m in re.finditer(rb'[\x01\x02][\x1a-\x1e]([A-Z]\d{14,20})', data):
            card_nums.append(m.group(1).decode())
        
        # Find download timestamps
        timestamps = []
        pos = 0
        while pos + 4 <= len(data):
            ts = struct.unpack(">I", data[pos:pos+4])[0]
            if 946684800 <= ts <= 4102444800:
                timestamps.append(datetime.fromtimestamp(ts, tz=timezone.utc).isoformat())
            pos += 1
        
        if timestamps or card_nums:
            downloads.append({
                "timestamps": timestamps[:10],
                "card_numbers": card_nums,
            })
        
        # Also extract driver names if present
        card_match = re.search(rb'([A-Z][A-Z ]{8,35})\s{2,}([\x01][A-Z][A-Z ]{8,35})', data)
        if card_match:
            s = card_match.group(1).decode('latin-1').strip()
            f = card_match.group(2).decode('latin-1').replace('\x01','').strip()
            if s and f:
                drivers = results.setdefault("inserted_drivers", [])
                dk = f"{s}|{f}|card_dl"
                if not any(d.get("_key") == dk for d in drivers):
                    drivers.append({"surname": s, "firstname": f, "card_number": "", "_key": dk})
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 06 card download parse failed: %s", exc)

def parse_g22_certificate_profile(val, results):
    """Parse G22 CertificateProfileIdentifier (tag 0x42/0x4208) — certificate metadata.

    Attempts to detect BER-TLV structure within security container data,
    identify OID/algorithm sections, and extract nested tags.
    Falls back to Latin-1 text decode + raw hex.
    """
    from core.ber_tlv import read_ber_tlv_header

    try:
        profile = {"raw_hex": val.hex().upper()}

        nested_tags = []
        parsed_bytes = 0
        pos = 0
        while pos + 2 <= len(val):
            if val[pos] in (0x00, 0xFF):
                pos += 1
                continue

            tag, length, hdr_size = read_ber_tlv_header(val, pos)
            if tag is None or length == 0 or pos + hdr_size + length > len(val):
                pos += 1
                continue

            tag_data = val[pos + hdr_size:pos + hdr_size + length]
            tag_desc = f"0x{tag:04X}"
            if tag == 0x06:
                tag_desc = "OID"
            elif tag in (0x30, 0x31):
                tag_desc = "SEQUENCE"
            elif tag == 0x04:
                tag_desc = "OCTET_STRING"
            elif tag == 0x03:
                tag_desc = "BIT_STRING"
            elif tag == 0x02:
                tag_desc = "INTEGER"
            elif tag == 0xA0:
                tag_desc = "CONTEXT_0"
            elif tag == 0xA1:
                tag_desc = "CONTEXT_1"
            nested_tags.append({
                "tag": f"0x{tag:04X}",
                "tag_desc": tag_desc,
                "length": length,
                "offset": pos,
                "data_hex": tag_data[:64].hex().upper() + ("..." if len(tag_data) > 64 else ""),
            })
            parsed_bytes += hdr_size + length
            pos += hdr_size + length

        if nested_tags:
            profile["nested_tags"] = nested_tags
            _log.debug("Certificate profile: detected %d nested BER-TLV tags", len(nested_tags))

        # Identify OID sections from hex data
        known_oids = {
            "2a8648ce3d030107": "secp256r1 (NIST P-256)",
            "2b2403030208010107": "brainpoolP256r1",
            "2a8648ce3d040303": "ECDSA with SHA-384",
            "2a8648ce3d040302": "ECDSA with SHA-256",
        }
        hex_val = val.hex()
        found_oids = []
        for oid_hex, oid_name in known_oids.items():
            if oid_hex in hex_val:
                found_oids.append({"oid": oid_hex, "name": oid_name})
        if found_oids:
            profile["identified_oids"] = found_oids
            _log.debug("Certificate profile: identified %d known OIDs", len(found_oids))

        # Latin-1 text decode
        if len(val) >= 3:
            try:
                text = val.decode('latin-1', errors='ignore')
                ascii_part = ''.join(c for c in text if 32 <= ord(c) < 127).strip()
                if ascii_part:
                    profile["text"] = ascii_part
            except (UnicodeDecodeError, ValueError):
                pass

        # Report unknown byte percentage
        if nested_tags:
            unknown_bytes = len(val) - parsed_bytes
            if unknown_bytes > 0:
                profile["unknown_bytes"] = unknown_bytes

        results.setdefault("card_icc", {})["certificate_profile"] = profile
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Certificate profile parse failed: %s", exc)
