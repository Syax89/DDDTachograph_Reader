"""Card EF decoders: identification, licence, vehicles used, events/faults, places, calibration, control activities and company/workshop card data (G1 Annex 1B + G2 card EFs)."""

import struct
from datetime import datetime, timezone

from core.logger import get_logger
from core.constants import MAX_ODO_DISTANCE_KM
from core.decode_primitives import _decode_gnss_coord, decode_date, decode_string, get_nation
from core.event_fault_codes import describe_calibration_purpose, describe_control_type, describe_event, describe_fault

_log = get_logger(__name__)

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

def _vehicles_used_layouts(rec_data):
    """Candidate CardVehicleRecord layouts for EF Vehicles_Used.

    Returns (size, kind) candidates whose record size divides the data:
      31  G1   (Annex 1B): odoBegin(3) odoEnd(3) firstUse(4) lastUse(4)
                           registration(15) vuDataBlockCounter(2)
      48  G2   (Annex 1C): the G1 fields + vehicleIdentificationNumber(17)
      35  legacy non-standard variant observed in some files:
                           odoBegin(4) odoEnd(4) firstUse(4) lastUse(4)
                           nation(1) plate(14) + 4 tail bytes
    """
    return [(size, kind) for size, kind in ((31, "g1"), (48, "g2"), (35, "legacy"))
            if len(rec_data) >= size and len(rec_data) % size == 0]

def _decode_vehicle_record(chunk, kind):
    """Decode one CardVehicleRecord chunk. Returns the raw field tuple
    (odo_begin, odo_end, first_use_ts, last_use_ts, nation_code, plate, vin)."""
    vin = None
    if kind == "legacy":
        odo_begin = struct.unpack(">I", chunk[0:4])[0]
        odo_end = struct.unpack(">I", chunk[4:8])[0]
        first_use_ts = struct.unpack(">I", chunk[8:12])[0]
        last_use_ts = struct.unpack(">I", chunk[12:16])[0]
        nation_code = chunk[16]
        plate = decode_string(chunk[17:31], is_id=True)
    else:
        # G1 and G2 share the 31-byte prefix (Annex 1B/1C §2.37).
        odo_begin = int.from_bytes(chunk[0:3], byteorder='big')
        odo_end = int.from_bytes(chunk[3:6], byteorder='big')
        first_use_ts = struct.unpack(">I", chunk[6:10])[0]
        last_use_ts = struct.unpack(">I", chunk[10:14])[0]
        nation_code = chunk[14]
        plate = decode_string(chunk[15:29], is_id=True)
        if kind == "g2":
            vin = decode_string(chunk[31:48], is_id=True) or None
    return odo_begin, odo_end, first_use_ts, last_use_ts, nation_code, plate, vin

def _vehicle_record_valid(odo_begin, odo_end, first_use_ts, nation_code, plate):
    """Garbage filter for a decoded vehicle record."""
    stripped = plate.strip().rstrip('\x00')
    if not stripped or len(stripped) < 2 or len(stripped) >= 14:
        return False
    if not all(0x20 <= ord(c) < 0x7F for c in stripped):
        return False
    alpha_ratio = sum(1 for c in stripped if c.isalnum()) / len(stripped)
    if alpha_ratio < 0.5:
        return False
    # NationNumeric: known codes top out below 0x60; 0xFD-0xFF are the
    # special EC/EUR/WLD values (Annex 1B §2.101).
    if nation_code > 0x60 and nation_code not in (0xFD, 0xFE, 0xFF):
        return False
    if odo_begin not in (0xFFFFFF, 0xFFFFFFFF) and odo_begin > MAX_ODO_DISTANCE_KM * 100:
        return False
    if odo_end not in (0xFFFFFF, 0xFFFFFFFF) and odo_end > MAX_ODO_DISTANCE_KM * 100:
        return False
    if first_use_ts < 946684800 or first_use_ts > 2000000000:
        return False
    return True

def parse_g1_vehicles_used(val, results):
    """EF Vehicles_Used (tags 0x0505/0x0523) — Annex 1B/1C §2.37.

    Layout: vehiclePointerNewestRecord(2) + N × CardVehicleRecord.
    Record size is detected among the candidates in
    :func:`_vehicles_used_layouts` by scoring how many records validate.
    Records are deduplicated across the G1/G2 EF copies on
    (plate, start, odometer_begin).
    """
    if len(val) < 4:
        return

    rec_data = val[2:]  # skip vehiclePointerNewestRecord
    candidates = _vehicles_used_layouts(rec_data)
    if not candidates:
        return

    # Score each layout by the number of records passing validation and keep
    # the best one (a misaligned stride yields almost no valid records).
    best_kind, best_size, best_count = None, 0, -1
    for size, kind in candidates:
        count = 0
        for i in range(len(rec_data) // size):
            chunk = rec_data[i * size:(i + 1) * size]
            try:
                ob, oe, fu, lu, nc, plate, _ = _decode_vehicle_record(chunk, kind)
            except (struct.error, IndexError):
                continue
            if _vehicle_record_valid(ob, oe, fu, nc, plate):
                count += 1
        if count > best_count:
            best_kind, best_size, best_count = kind, size, count
    if best_count <= 0:
        return

    sessions = results["vehicle_sessions"]
    seen = {(s.get("vehicle_plate"), s.get("start"), s.get("odometer_begin"))
            for s in sessions if isinstance(s, dict)}

    for i in range(len(rec_data) // best_size):
        chunk = rec_data[i * best_size:(i + 1) * best_size]
        try:
            odo_begin, odo_end, first_use_ts, last_use_ts, nation_code, plate, vin = \
                _decode_vehicle_record(chunk, best_kind)

            if not _vehicle_record_valid(odo_begin, odo_end, first_use_ts, nation_code, plate):
                continue

            if odo_begin in (0xFFFFFF, 0xFFFFFFFF):
                odo_begin = None
            if odo_end in (0xFFFFFF, 0xFFFFFFFF):
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

            key = (plate, start_date, odo_begin)
            if key in seen:
                # The G2 EF copy repeats the G1 records (adding the VIN):
                # enrich the existing session instead of duplicating it.
                if vin:
                    for s in sessions:
                        if (s.get("vehicle_plate"), s.get("start"), s.get("odometer_begin")) == key:
                            s.setdefault("vin", vin)
                            break
                continue
            seen.add(key)

            session = {
                "vehicle_plate": plate,
                "vehicle_nation": get_nation(nation_code),
                "start": start_date,
                "end": end_date,
                "odometer_begin": odo_begin,
                "odometer_end": odo_end,
                "distance": distance
            }
            if vin:
                session["vin"] = vin
            sessions.append(session)
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
                "purpose": describe_calibration_purpose(purpose),
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
                "description": describe_event(ev_type),
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
                "description": describe_fault(fault_type),
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

def parse_card_vehicle_units(val, results):
    """Parse EF VehicleUnits_Used (tag 0x0523) — Annex 1C §2.39, G2 driver card.

    Layout: vehicleUnitPointerNewestRecord(2) + N × CardVehicleUnitRecord(10):
      timeStamp           4  TimeReal
      manufacturerCode    1  ManufacturerCode (Annex 1C §2.93)
      deviceID            1  UInt8
      vuSoftwareVersion   4  IA5String
    Confirmed against real G2 card downloads (record count matches
    noOfCardVehicleUnitRecords in ApplicationIdentification).
    """
    if len(val) < 12:
        return
    try:
        rec_size = 10
        data = val[2:]  # skip vehicleUnitPointerNewestRecord
        if len(data) % rec_size != 0:
            return
        units = results.setdefault("vehicle_units", [])
        seen = {(u.get("timestamp"), u.get("manufacturer_code"))
                for u in units if isinstance(u, dict)}
        for i in range(0, len(data), rec_size):
            chunk = data[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts < 946684800 or ts > 4102444800:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            mfr = chunk[4]
            if (dt, mfr) in seen:
                continue
            seen.add((dt, mfr))
            units.append({
                "timestamp": dt,
                "manufacturer_code": mfr,
                "device_id": chunk[5],
                "vu_software_version": decode_string(chunk[6:10], is_id=True),
            })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Vehicle units used parse failed: %s", exc)

def parse_card_gnss_places(val, results):
    """Parse EF GNSS_Places (tag 0x0524) — Annex 1C §2.78, G2 driver card.

    Layout: gnssADPointerNewestRecord(2) + N × GNSSAccumulatedDrivingRecord:
      timeStamp              4  TimeReal
      gnssPlaceRecord       11  timeStamp(4) + gnssAccuracy(1) + geoCoordinates(6)
      vehicleOdometerValue   3  OdometerShort
    Record size 18 (G2); the G2.2 variant carries a GNSSPlaceAuthRecord (12)
    → 19 bytes. Confirmed against real G2 card downloads.
    """
    if len(val) < 20:
        return
    try:
        data = val[2:]  # skip gnssADPointerNewestRecord
        if len(data) % 18 == 0:
            rec_size = 18
        elif len(data) % 19 == 0:
            rec_size = 19
        else:
            return
        records = results.setdefault("gnss_ad_records", [])
        seen = {(r.get("timestamp"), r.get("latitude"), r.get("longitude"))
                for r in records if isinstance(r, dict)}
        for i in range(0, len(data), rec_size):
            chunk = data[i:i + rec_size]
            ts = struct.unpack(">I", chunk[0:4])[0]
            if ts < 946684800 or ts > 4102444800:
                continue
            lat = _decode_gnss_coord(chunk, 9)
            lon = _decode_gnss_coord(chunk, 12)
            if lat is None or lon is None:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if (dt, lat, lon) in seen:
                continue
            seen.add((dt, lat, lon))
            rec = {
                "timestamp": dt,
                "gnss_accuracy": chunk[8],
                "latitude": lat,
                "longitude": lon,
            }
            odo_off = 15 if rec_size == 18 else 16
            if rec_size == 19:
                rec["gnss_authenticated"] = chunk[15] == 1
            odo = int.from_bytes(chunk[odo_off:odo_off + 3], 'big')
            if odo != 0xFFFFFF and odo < 10000000:
                rec["odometer_km"] = odo
            records.append(rec)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Card GNSS places parse failed: %s", exc)

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
                "control_type_label": describe_control_type(control_type),
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
    """Parse SpecificConditions (tag 0x0522) — out-of-scope / ferry-train (Annex 1C §2.154).

    SpecificConditionRecord = entryTime(4) + specificConditionType(1) = 5 bytes.
    The G1 EF has no header (records only, len % 5 == 0); the G2 EF prefixes a
    2-byte conditionPointerNewestRecord. Detected by alignment; records are
    deduplicated across the G1/G2 EF copies.
    """
    from core.event_fault_codes import specific_condition_label
    if len(val) < 5:
        return
    try:
        rec_size = 5  # entryTime(4) + specificConditionType(1) per Annex 1C §2.154
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
            # 0x00 is RFU and 0x05+ undefined (Annex 1C §2.154) — skip as garbage.
            if cond_type not in (0x01, 0x02, 0x03, 0x04):
                off += rec_size
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if (dt, cond_type) not in seen:
                seen.add((dt, cond_type))
                conditions.append({
                    "timestamp": dt,
                    "condition": specific_condition_label(cond_type),
                    "type_code": cond_type,
                })
            off += rec_size
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Specific conditions parse failed: %s", exc)

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
