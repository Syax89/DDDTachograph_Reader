import struct
from datetime import datetime, timezone

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
    if not data: return ""
    try:
        data = data.rstrip(b'\x00\xff')
        if not data: return ""

        if data[0] < 0x20:
            encodings = {0x01: 'latin-1', 0x02: 'iso-8859-2', 0x03: 'iso-8859-3',
                         0x04: 'iso-8859-4', 0x05: 'iso-8859-5', 0x06: 'iso-8859-6',
                         0x07: 'iso-8859-7', 0x08: 'iso-8859-8', 0x09: 'iso-8859-9',
                         0x0A: 'iso-8859-10', 0x0B: 'iso-8859-11', 0x0D: 'iso-8859-13',
                         0x0E: 'iso-8859-14', 0x0F: 'iso-8859-15', 0x10: 'iso-8859-16'}
            enc = encodings.get(data[0], 'latin-1')
            payload = data[1:]
        else:
            enc = 'latin-1'
            payload = data
        
        decoded = payload.decode(enc, errors='ignore').strip()
        if is_id:
            return "".join(c for c in decoded if (c.isalnum() or c == ' ') and ord(c) < 128).strip().upper()
        return "".join(c for c in decoded if c.isprintable()).strip()
    except Exception:
        return ""

def decode_date(data):
    """Decode TimeReal (4 bytes) or Datef (4 bytes)."""
    if len(data) < 4: return "N/A"
    try:
        ts = struct.unpack(">I", data[:4])[0]
        if ts == 0 or ts == 0xFFFFFFFF: return "N/A"
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%d/%m/%Y')
    except (struct.error, ValueError, OverflowError):
        return "N/A"

def decode_activity_val(val):
    """Decode 2-byte activityChangeInfo."""
    slot = (val >> 15) & 1
    driving_status = (val >> 14) & 1 # 0=Single, 1=Crew
    card_status = (val >> 13) & 1    # 0=Inserted, 1=Not
    act_code = (val >> 11) & 3
    mins = val & 0x07FF
    acts = {0: "RIPOSO", 1: "DISPONIBILITÀ", 2: "LAVORO", 3: "GUIDA"}
    return {
        "tipo": acts.get(act_code, "SCONOSCIUTO"),
        "ora": f"{mins // 60:02d}:{mins % 60:02d}",
        "slot": "Secondo" if slot else "Primo",
        "team": bool(driving_status),
        "card_present": not bool(card_status)
    }

def get_cyclic_data(data, start, length, base_offset=4):
    """Read data from a cyclic buffer handling wrap-around."""
    buf_size = len(data) - base_offset
    if buf_size <= 0: return b'\x00' * length
    
    start_rel = (start - base_offset) % buf_size
    end_rel = start_rel + length
    
    if end_rel <= buf_size:
        return data[base_offset + start_rel : base_offset + end_rel]
    else:
        part1 = data[base_offset + start_rel : base_offset + buf_size]
        part2 = data[base_offset : base_offset + (end_rel - buf_size)]
        return part1 + part2

def parse_cyclic_buffer_activities(val, results):
    if len(val) < 16: return
    try:
        # print(f"DEBUG: Parsing Cyclic Buffer (len={len(val)})")
        buf_size = len(val) - 4
        newest_ptr = struct.unpack(">H", val[2:4])[0]
        ptr = 4 + newest_ptr
        seen_dates = set()
        
        for _ in range(366):
            header_data = get_cyclic_data(val, ptr, 8)
            if len(header_data) < 8: break
            
            prev_len, rec_len, ts = struct.unpack(">HHI", header_data)
            
            if rec_len < 14 or rec_len > 2048 or ts == 0 or ts == 0xFFFFFFFF: break
            
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                date_str = dt.strftime('%d/%m/%Y')
            except:
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
                        if i + 2 > len(act_data): break
                        ev_val = struct.unpack(">H", act_data[i:i+2])[0]
                        if ev_val != 0xFFFF: # Fix Midnight Bug (allow 0)
                            daily["eventi"].append(decode_activity_val(ev_val))
                
                if daily["eventi"]: results["activities"].append(daily)
            
            if prev_len == 0 or prev_len > buf_size: break
            
            # Backward traversal with wrap-around
            curr_offset = ptr - 4
            prev_offset = (curr_offset - prev_len) % buf_size
            ptr = 4 + prev_offset
    except Exception: pass

def parse_g1_identification(val, results):
    if len(val) < 65: return
    off = 0
    # CardIdentification (65 bytes)
    results["driver"]["issuing_nation"] = get_nation(val[off]); off += 1
    results["driver"]["card_number"] = decode_string(val[off:off+16], is_id=True); off += 16
    off += 36 # cardIssuingAuthorityName
    off += 4 + 4 # cardIssueDate, cardValidityBegin
    results["driver"]["expiry_date"] = decode_date(val[off:off+4]); off += 4
    
    # DriverCardHolderIdentification (78 bytes)
    if len(val) >= off + 78:
        results["driver"]["surname"] = decode_string(val[off:off+36]); off += 36
        results["driver"]["firstname"] = decode_string(val[off:off+36]); off += 36
        results["driver"]["birth_date"] = decode_date(val[off:off+4]); off += 4
        results["driver"]["preferred_language"] = decode_string(val[off:off+2]); off += 2
    elif len(val) >= off + 36: # Partial (e.g. G2 internal)
        results["driver"]["surname"] = decode_string(val[off:off+36]); off += 36

def parse_g1_driving_licence(val, results):
    if len(val) < 53: return
    results["driver"]["licence_issuing_nation"] = get_nation(val[36])
    results["driver"]["licence_number"] = decode_string(val[37:53], is_id=True)

def parse_g1_vehicles_used(val, results):
    """
    EF_Vehicles_Used (0x0505). 
    In G1: Fixed 31-byte records.
    In G2: Fixed 35-byte records (Annex 1C).
    """
    if len(val) < 4: return
    
    # Determine record size: 31 (G1) or 35 (G2)
    # The first 2 bytes are an index/pointer
    rec_data = val[2:]
    rec_size = 31 # Default G1
    if len(rec_data) % 35 == 0:
        rec_size = 35 # G2
    
    for i in range(len(rec_data) // rec_size):
        chunk = rec_data[i*rec_size:(i+1)*rec_size]
        if len(chunk) < rec_size: break
        
        try:
            if rec_size == 31:
                # Annex 1B (G1)
                first_use_ts = struct.unpack(">I", chunk[0:4])[0]
                last_use_ts = struct.unpack(">I", chunk[4:8])[0]
                nation_code = chunk[8]
                plate = decode_string(chunk[9:23], is_id=True)
                odo_begin = int.from_bytes(chunk[23:26], byteorder='big')
                odo_end = int.from_bytes(chunk[26:29], byteorder='big')
            else:
                # Annex 1C (G2)
                # vehicleFirstUse (4), vehicleLastUse (4), vehicleRegistrationNation (1),
                # vehicleRegistrationNumber (14), vehicleOdometerBegin (4), vehicleOdometerEnd (4)
                # Note: G2 odometers are 4 bytes!
                first_use_ts = struct.unpack(">I", chunk[0:4])[0]
                last_use_ts = struct.unpack(">I", chunk[4:8])[0]
                nation_code = chunk[8]
                plate = decode_string(chunk[9:23], is_id=True)
                odo_begin = struct.unpack(">I", chunk[23:27])[0]
                odo_end = struct.unpack(">I", chunk[27:31])[0]
            
            # Sanitization
            if first_use_ts < 946684800 or first_use_ts > 2000000000: # Ignore dates before 2000 or after 2033
                continue

            if odo_begin == 0xFFFFFF or odo_begin == 0xFFFFFFFF: odo_begin = None
            if odo_end == 0xFFFFFF or odo_end == 0xFFFFFFFF: odo_end = None

            start_date = datetime.fromtimestamp(first_use_ts, tz=timezone.utc).isoformat()
            end_date = "Sessione Aperta"
            if last_use_ts != 0xFFFFFFFF and last_use_ts > 946684800:
                 try: end_date = datetime.fromtimestamp(last_use_ts, tz=timezone.utc).isoformat()
                 except: pass

            distance = (odo_end - odo_begin) if (odo_begin is not None and odo_end is not None) else 0
            if distance < 0 or distance > 1000000: distance = 0 # Anti-junk

            results["vehicle_sessions"].append({
                "vehicle_plate": plate,
                "vehicle_nation": get_nation(nation_code),
                "start": start_date,
                "end": end_date,
                "odometer_begin": odo_begin,
                "odometer_end": odo_end,
                "distance": distance
            })
        except Exception: continue

def parse_g1_current_usage(val, results):
    if len(val) < 19: return
    try:
        ts = struct.unpack(">I", val[0:4])[0]
        if ts == 0 or ts == 0xFFFFFFFF or ts > 1798758400: return
        results["vehicle"]["plate"] = decode_string(val[5:19], is_id=True)
        results["vehicle"]["registration_nation"] = get_nation(val[4])
    except: pass

def parse_card_identification(val, results):
    if len(val) < 23: return
    results["driver"]["issuing_nation"] = get_nation(val[0])
    results["driver"]["card_number"] = decode_string(val[1:17], is_id=True)
    results["driver"]["expiry_date"] = decode_date(val[19:23])

def parse_driver_card_holder_identification(val, results):
    if len(val) < 78: return
    results["driver"]["surname"] = decode_string(val[0:36])
    results["driver"]["firstname"] = decode_string(val[36:72])
    results["driver"]["birth_date"] = decode_date(val[72:76])
    results["driver"]["preferred_language"] = decode_string(val[76:78])

def parse_calibration_data(val, results):
    if len(val) < 105: return
    try:
        data = val[2:]
        rec_size = 105 if len(data) % 105 == 0 else (161 if len(data) % 161 == 0 else 105)
        for i in range(0, len(data) - rec_size + 1, rec_size):
            chunk = data[i:i+rec_size]
            w = struct.unpack(">H", chunk[33:35])[0]
            k = struct.unpack(">H", chunk[35:37])[0]
            l = struct.unpack(">H", chunk[37:39])[0]
            odo_val = int.from_bytes(chunk[55:58], byteorder='big')
            if odo_val == 0xFFFFFF: odo_val = None
            results["calibrations"].append({
                "purpose_code": chunk[0],
                "vin_at_calibration": decode_string(chunk[1:18], is_id=True),
                "plate_at_calibration": decode_string(chunk[19:33], is_id=True),
                "nation_at_calibration": get_nation(chunk[18]),
                "w_characteristic_constant": w, "k_constant": k, "l_tyre_circumference": l,
                "tyre_size": decode_string(chunk[39:54]), "speed_limit": chunk[54], "odometer_value": odo_val
            })
    except: pass

# ─── Gen 2.2 (Smart Tachograph V2) Decoders ─── Reg. EU 2023/980 ───

def _decode_gnss_coord(data, offset):
    """Decode GNSS coordinates (latitude/longitude) as signed 32-bit, unit 1/10 micro-degree."""
    if len(data) < offset + 4:
        return None
    raw = struct.unpack(">i", data[offset:offset+4])[0]
    return raw / 10_000_000.0  # degrees

def parse_g22_gnss_accumulated_driving(val, results):
    """Parse GNSS positions recorded at each activity change (Gen 2.2 mandatory)."""
    if len(val) < 12:
        return
    try:
        rec_size = 16  # timestamp(4) + lat(4) + lon(4) + speed(2) + heading(2)
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i+rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            lat = _decode_gnss_coord(chunk, 4)
            lon = _decode_gnss_coord(chunk, 8)
            speed = struct.unpack(">H", chunk[12:14])[0]
            heading = struct.unpack(">H", chunk[14:16])[0]
            if lat is not None and lon is not None:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                results.setdefault("gnss_ad_records", []).append({
                    "timestamp": dt,
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                    "speed_kmh": speed,
                    "heading": heading
                })
    except Exception:
        pass

def parse_g22_load_unload_operations(val, results):
    """Parse load/unload operation records (Gen 2.2)."""
    if len(val) < 9:
        return
    try:
        rec_size = 9  # timestamp(4) + operation_type(1) + lat(4) -- minimal
        # Flexible: try 13-byte records (ts + type + lat + lon)
        if len(val) >= 13 and len(val) % 13 == 0:
            rec_size = 13
        elif len(val) % 9 == 0:
            rec_size = 9
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i+rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            op_type = chunk[4]  # 0=load, 1=unload
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            record = {
                "timestamp": dt,
                "operation": "LOAD" if op_type == 0 else "UNLOAD"
            }
            if rec_size >= 13:
                record["latitude"] = round(_decode_gnss_coord(chunk, 5) or 0, 7)
                record["longitude"] = round(_decode_gnss_coord(chunk, 9) or 0, 7)
            results.setdefault("load_unload_records", []).append(record)
    except Exception:
        pass

def parse_g22_trailer_registrations(val, results):
    """Parse trailer registration records (Gen 2.2)."""
    if len(val) < 10:
        return
    try:
        # Each record: timestamp(4) + nation(1) + trailer_plate(up to 14) + coupling(1)
        rec_size = 24
        if len(val) % 24 != 0:
            rec_size = 20  # fallback
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i+rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            nation = get_nation(chunk[4])
            plate = decode_string(chunk[5:19], is_id=True)
            coupling = chunk[19] if rec_size > 19 else 0  # 0=coupled, 1=uncoupled
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            results.setdefault("trailer_registrations", []).append({
                "timestamp": dt,
                "nation": nation,
                "trailer_plate": plate,
                "event": "COUPLED" if coupling == 0 else "UNCOUPLED"
            })
    except Exception:
        pass

def parse_g22_gnss_enhanced_places(val, results):
    """Parse GNSS-enhanced place records (Gen 2.2)."""
    if len(val) < 12:
        return
    try:
        # timestamp(4) + lat(4) + lon(4) + place_type(1) + nation(1) + region(2)
        rec_size = 16
        if len(val) % 16 != 0:
            rec_size = 12
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i+rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            lat = _decode_gnss_coord(chunk, 4)
            lon = _decode_gnss_coord(chunk, 8)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            record = {
                "timestamp": dt,
                "latitude": round(lat or 0, 7),
                "longitude": round(lon or 0, 7)
            }
            if rec_size >= 14:
                record["place_type"] = chunk[12]
                record["nation"] = get_nation(chunk[13])
            results.setdefault("gnss_places", []).append(record)
    except Exception:
        pass

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
    except Exception:
        pass

def parse_g22_border_crossings(val, results):
    """Parse border crossing records (Gen 2.2)."""
    if len(val) < 13:
        return
    try:
        # timestamp(4) + nation_from(1) + nation_to(1) + lat(4) + lon(4) = 14 minimal
        rec_size = 14
        if len(val) % 14 != 0:
            rec_size = 10  # ts + from + to + lat(4)
        for i in range(0, len(val) - rec_size + 1, rec_size):
            chunk = val[i:i+rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            record = {
                "timestamp": dt,
                "nation_from": get_nation(chunk[4]),
                "nation_to": get_nation(chunk[5])
            }
            if rec_size >= 14:
                record["latitude"] = round(_decode_gnss_coord(chunk, 6) or 0, 7)
                record["longitude"] = round(_decode_gnss_coord(chunk, 10) or 0, 7)
            results.setdefault("border_crossings", []).append(record)
    except Exception:
        pass

# End of file
