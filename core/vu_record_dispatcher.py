"""Deterministic VU RecordArray dispatcher (Gen2 / Gen2.2).

Vehicle Unit downloads are NOT organised by the 0x05xx tags used in driver-card
files. They are a stream of **RecordArrays indexed by recordType** (Annex 1C
Appendix 7), grouped into TREP sections each prefixed by a 2-byte container
marker ``0x76 0xNN`` and terminated by a SignatureRecordArray (recordType 0x08):

    0x7631  Overview                0x7632  Activities (one section per day)
    0x7633  Events & Faults         0x7634  Detailed speed
    (0x762x are the Gen2 equivalents.)

RecordArray header = recordType(1) + recordSize(2 BE) + noOfRecords(2 BE).

This module walks that stream and dispatches every record by recordType, so no
record is silently dropped. recordType→size has been confirmed empirically
against the real files in ``DDD/`` (see ``specs/vu_recordtype_map.md``). Records
with a confirmed byte-level structure are fully decoded; the rest are surfaced
raw with an explicit ``confidence`` flag rather than guessed values.

The walker also reconstructs daily activity records (date + odometer + activity
changes) in the same shape the rest of the app consumes via ``results['activities']``,
which the legacy heuristic TREP parser failed to produce for Gen2/2.2 VU files.
"""
import struct
from datetime import datetime, timezone

from core.logger import get_logger
from core import decoders

_log = get_logger(__name__)

# recordType → (human name, confidence). Names are AUTHORITATIVE: they were
# obtained by matching the observed recordType order in real files against the
# RecordArray order the regulation mandates per TREP (Appendix 7, DDP_029..033),
# then cross-checked by size. confidence reflects how fully each record is
# *decoded* here:
#   high   : structure decoded and confirmed against spec + real data
#   medium : key fields decoded, remaining bytes surfaced raw
#   low    : identified by name/size, body surfaced raw (not yet field-decoded)
RECORD_TYPES = {
    0x01: ("VuActivityDailyRecord", "high"),       # ActivityChangeInfo (2)
    0x02: ("CardSlotsStatus", "high"),             # (1)
    0x03: ("CurrentDateTime", "high"),             # TimeReal (4)
    0x04: ("MemberStateCertificate", "low"),       # (205) raw cert
    0x05: ("OdometerValueMidnight", "high"),       # OdometerShort (3)
    0x06: ("DateOfDayDownloaded", "high"),         # TimeReal (4)
    0x08: ("SignatureRecord", "high"),             # ECC (64)
    0x09: ("VuSpecificConditionRecord", "high"),   # entryTime(4)+type(1)=5
    0x0A: ("VehicleIdentificationNumber", "medium"),
    0x0B: ("VehicleRegistrationNumber", "medium"), # G2 (14)
    0x0C: ("VuCalibrationRecord", "low"),          # (222/252)
    0x0D: ("VuCardIWRecord", "low"),               # (131)
    0x0E: ("VuCardRecord", "low"),                 # (45)
    0x0F: ("VUCertificate", "low"),                # (205) raw cert
    0x10: ("VuCompanyLocksRecord", "low"),         # (99)
    0x11: ("VuControlActivityRecord", "low"),      # (32)
    0x12: ("VuDetailedSpeedBlock", "low"),         # detailed speed
    0x13: ("VuDownloadablePeriod", "high"),        # (8)
    0x14: ("VuDownloadActivityData", "medium"),    # (59)
    0x15: ("VuEventRecord", "medium"),             # (91)
    0x16: ("VuGNSSADRecord", "high"),              # (56/57) GNSS accumulated driving
    0x17: ("VuITSConsentRecord", "low"),           # (20)
    0x18: ("VuFaultRecord", "medium"),             # (90)
    0x19: ("VuIdentification", "low"),             # (126/138)
    0x1A: ("VuOverSpeedingControlData", "high"),   # (9)
    0x1B: ("VuOverSpeedingEventRecord", "medium"), # (32)
    0x1C: ("VuPlaceDailyWorkPeriodRecord", "high"),# (40/41)
    0x1E: ("VuTimeAdjustmentRecord", "medium"),    # (99)
    0x1F: ("VuPowerSupplyInterruptionRecord", "medium"),  # (87)
    0x20: ("VuSensorPairedRecord", "low"),         # (28)
    0x21: ("VuSensorExternalGNSSCoupledRecord", "low"),   # (28)
    0x22: ("VuBorderCrossingRecord", "high"),      # (55)
    0x23: ("VuLoadUnloadRecord", "high"),          # (58)
    0x24: ("VehicleRegistrationIdentification", "medium"),  # G2.2 (15)
    0x29: ("Unknown_0x29", "low"),
    0x40: ("VuDetailedSpeedSample", "low"),
    0x60: ("Terminator", "low"),
}

# TREP marker (second byte after 0x76) → section name. Covers G1/G2/G2.2.
TREP_SECTIONS = {
    0x01: "Overview", 0x21: "Overview", 0x31: "Overview",
    0x02: "Activities", 0x22: "Activities", 0x32: "Activities",
    0x03: "EventsFaults", 0x23: "EventsFaults", 0x33: "EventsFaults",
    0x04: "DetailedSpeed", 0x24: "DetailedSpeed", 0x34: "DetailedSpeed",
    0x05: "TechnicalData", 0x25: "TechnicalData", 0x35: "TechnicalData",
}


def _u24(b):
    """Unsigned 24-bit big-endian."""
    return (b[0] << 16) | (b[1] << 8) | b[2]


def _s24(b):
    """Signed 24-bit big-endian (two's complement)."""
    v = _u24(b)
    return v - 0x1000000 if v & 0x800000 else v


def _iso(ts):
    return (datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if 946684800 <= ts <= 4102444800 else None)


def decode_name(data, off, length=36):
    """Name / Address type: codePage(1) + IA5String(length-1). Returns the text."""
    if off + length > len(data):
        return ""
    body = data[off + 1:off + length]
    return "".join(chr(b) if 0x20 <= b < 0x7F else "" for b in body).strip()


def decode_company_lock(rec):
    """VuCompanyLocksRecord (99): lockInTime(4) + lockOutTime(4) + companyName(36)
    + companyAddress(36) + companyCardNumberAndGen(19)."""
    if len(rec) < 99:
        return None
    return {
        "confidence": "medium",
        "lock_in_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "lock_out_time": _iso(struct.unpack(">I", rec[4:8])[0]),
        "company_name": decode_name(rec, 8),
        "company_address": decode_name(rec, 44),
        "company_card": decode_full_card_number_gen(rec, 80),
    }


def decode_control_activity(rec):
    """VuControlActivityRecord (32): controlType(1) + controlTime(4) +
    controlCardNumberAndGen(19) + downloadPeriodBegin(4) + downloadPeriodEnd(4)."""
    if len(rec) < 32:
        return None
    return {
        "confidence": "medium",
        "control_type": rec[0],
        "control_time": _iso(struct.unpack(">I", rec[1:5])[0]),
        "control_card": decode_full_card_number_gen(rec, 5),
        "download_period_begin": _iso(struct.unpack(">I", rec[24:28])[0]),
        "download_period_end": _iso(struct.unpack(">I", rec[28:32])[0]),
    }


def decode_vu_identification(rec):
    """VuIdentification (126/138): vuManufacturerName(36) + vuManufacturerAddress(36)
    + vuPartNumber(16) + vuSerialNumber(8) + ... (software/date follow)."""
    if len(rec) < 96:
        return None
    return {
        "confidence": "high",
        "manufacturer_name": decode_name(rec, 0),
        "manufacturer_address": decode_name(rec, 36),
        "part_number": _ascii(rec, 72, 16),
        "serial_number": rec[88:96].hex(),
        "approval_number": _ascii(rec, 108, 16),
        "raw_tail_hex": rec[96:108].hex() + rec[124:].hex(),
    }


def _ascii(data, off, length):
    return "".join(chr(b) if 0x20 <= b < 0x7F else "" for b in data[off:off + length]).strip()


def decode_calibration(rec):
    """VuCalibrationRecord — offsets confirmed against real data (recordSize 222 G2 /
    252 G2.2). Base layout (Annex 1C §2.174):
      calibrationPurpose(1) workshopName(36) workshopAddress(36)
      workshopCardNumber[FullCardNumber](18) workshopCardExpiryDate(4)
      vehicleIdentificationNumber(17) vehicleRegistrationIdentification(15)
      wVehicleCharacteristicConstant(2) kConstantOfRecordingEquipment(2)
      lTyreCircumference(2) tyreSize(15) authorisedSpeed(1)
      oldOdometerValue(3) newOdometerValue(3)
      oldTimeValue(4) newTimeValue(4) nextCalibrationDate(4) → 167
      then sealDataVu (G2) / sensorSerialNumber (G2.2) tail.
    """
    if len(rec) < 167:
        return None
    return {
        "confidence": "high",
        "calibration_purpose": rec[0],
        "workshop_name": decode_name(rec, 1),
        "workshop_address": decode_name(rec, 37),
        "workshop_card": {
            "card_type": rec[73],
            "nation": decoders.get_nation(rec[74]),
            "card_number": _ascii(rec, 75, 16),
        },
        "workshop_card_expiry": _iso(struct.unpack(">I", rec[91:95])[0]),
        "vin": _ascii(rec, 95, 17),
        "vehicle_registration": {
            "nation": decoders.get_nation(rec[112]),
            "plate": _ascii(rec, 114, 13),
        },
        "w_vehicle_constant": struct.unpack(">H", rec[127:129])[0],
        "k_constant": struct.unpack(">H", rec[129:131])[0],
        "l_tyre_circumference": struct.unpack(">H", rec[131:133])[0],
        "tyre_size": _ascii(rec, 133, 15),
        "authorised_speed_kmh": rec[148],
        "old_odometer_km": _u24(rec[149:152]),
        "new_odometer_km": _u24(rec[152:155]),
        "old_time": _iso(struct.unpack(">I", rec[155:159])[0]),
        "new_time": _iso(struct.unpack(">I", rec[159:163])[0]),
        "next_calibration_date": _iso(struct.unpack(">I", rec[163:167])[0]),
        "raw_tail_hex": rec[167:].hex(),
    }


def decode_card_iw(rec):
    """VuCardIWRecord (131): holderSurname(36) + holderFirstNames(36) +
    fullCardNumberAndGen(19) + cardExpiry(4) + insertionTime(4) +
    odoInsertion(3) + cardSlot(1) + withdrawalTime(4) + odoWithdrawal(3) + tail."""
    if len(rec) < 110:
        return None
    return {
        "confidence": "medium",
        "holder_surname": decode_name(rec, 0),
        "holder_first_names": decode_name(rec, 36),
        "card": decode_full_card_number_gen(rec, 72),
        "card_expiry": _iso(struct.unpack(">I", rec[91:95])[0]),
        "insertion_time": _iso(struct.unpack(">I", rec[95:99])[0]),
        "odometer_insertion_km": _u24(rec[99:102]),
        "card_slot": rec[102],
        "withdrawal_time": _iso(struct.unpack(">I", rec[103:107])[0]),
        "odometer_withdrawal_km": _u24(rec[107:110]),
    }


def decode_download_activity(rec):
    """VuDownloadActivityData (59): downloadingTime(4) + fullCardNumberAndGen(19)
    + companyOrWorkshopName(36)."""
    if len(rec) < 59:
        return None
    return {
        "confidence": "medium",
        "downloading_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "card": decode_full_card_number_gen(rec, 4),
        "company_or_workshop_name": decode_name(rec, 23),
    }


def decode_sensor_paired(rec):
    """SensorPairedRecord (28): sensorSerialNumber(8) + sensorApprovalNumber(16) +
    sensorPairingDate(4)."""
    if len(rec) < 28:
        return None
    return {
        "confidence": "medium",
        "sensor_serial": rec[0:8].hex(),
        "sensor_approval": "".join(chr(b) if 0x20 <= b < 0x7F else "" for b in rec[8:24]).strip(),
        "pairing_date": _iso(struct.unpack(">I", rec[24:28])[0]),
    }


def decode_full_card_number_gen(data, off):
    """FullCardNumberAndGeneration (19 bytes): cardType(1) + nation(1) +
    cardNumber(16) + generation(1). Confirmed against real border-crossing data."""
    if off + 19 > len(data):
        return None
    rec = data[off:off + 19]
    if rec == b"\xff" * 19:
        return {"present": False}
    card_type = rec[0]
    nation = decoders.get_nation(rec[1])
    number = "".join(chr(b) if 0x20 <= b < 0x7F else "" for b in rec[2:18]).strip()
    generation = rec[18]
    return {
        "present": True,
        "card_type": card_type,
        "nation": nation,
        "card_number": number,
        "generation": generation,
    }


def _coord_to_deg(raw):
    """Convert a signed GeoCoordinates value (±DDMM.M ×10) to decimal degrees."""
    sign = -1 if raw < 0 else 1
    v = abs(raw) / 10.0          # DDMM.M
    deg = int(v // 100)
    minutes = v - deg * 100
    return round(sign * (deg + minutes / 60.0), 5)


def decode_geo_coordinates(data, off):
    """GeoCoordinates (6 bytes): latitude(3) + longitude(3), signed int24,
    each coded as ±DDMM.M ×10 (Annex 1C §2.76). 0xFFFFFF = no fix."""
    if off + 6 > len(data):
        return None
    lat_raw = data[off:off + 3]
    lon_raw = data[off + 3:off + 6]
    if lat_raw == b"\xff\xff\xff" and lon_raw == b"\xff\xff\xff":
        return {"fix": False}
    lat = _s24(lat_raw)
    lon = _s24(lon_raw)
    return {
        "fix": True,
        "latitude_raw": lat,
        "longitude_raw": lon,
        "latitude_deg": _coord_to_deg(lat),
        "longitude_deg": _coord_to_deg(lon),
    }


def decode_gnss_place_auth(data, off):
    """GNSSPlaceAuthRecord (12 bytes): timeStamp(4) + gnssAccuracy(1) +
    geoCoordinates(6) + authenticationStatus(1)."""
    if off + 12 > len(data):
        return None
    rec = data[off:off + 12]
    ts = struct.unpack(">I", rec[0:4])[0]
    return {
        "timestamp": _iso(ts),
        "gnss_accuracy": rec[4],
        "geo": decode_geo_coordinates(rec, 5),
        "authentication_status": rec[11],
    }


def decode_gnss_place(data, off, with_auth):
    """GNSSPlaceRecord (G2, 11 bytes) or GNSSPlaceAuthRecord (G2.2, 12 bytes)."""
    size = 12 if with_auth else 11
    if off + size > len(data):
        return None
    rec = data[off:off + size]
    out = {
        "timestamp": _iso(struct.unpack(">I", rec[0:4])[0]),
        "gnss_accuracy": rec[4],
        "geo": decode_geo_coordinates(rec, 5),
    }
    if with_auth:
        out["authentication_status"] = rec[11]
    return out


def decode_place_daily(rec):
    """VuPlaceDailyWorkPeriodRecord — G2 (40 bytes) / G2.2 (41 bytes):
    fullCardNumberAndGen(19) + entryTime(4) + entryType(1) + country(1) +
    region(1) + odometer(3) + GNSSPlace(11 G2 / 12 G2.2)."""
    if len(rec) < 40:
        return None
    with_auth = len(rec) >= 41
    entry_type = rec[23]
    # EntryTypeDailyWorkPeriod (Annex 1C §2.66): 0/2 = Begin, 1/3 = End.
    entry_names = {0x00: "BEGIN", 0x01: "END", 0x02: "BEGIN", 0x03: "END"}
    return {
        "confidence": "high",
        "card_driver": decode_full_card_number_gen(rec, 0),
        "timestamp": _iso(struct.unpack(">I", rec[19:23])[0]),
        "entry_type": entry_names.get(entry_type, f"0x{entry_type:02X}"),
        "type_code": entry_type,
        "nation": decoders.get_nation(rec[24]),
        "region": rec[25],
        "odometer_km": _u24(rec[26:29]),
        "gnss_place": decode_gnss_place(rec, 29, with_auth),
    }


def decode_specific_condition(rec):
    """VuSpecificConditionRecord (5 bytes): entryTime(4) + specificConditionType(1)."""
    if len(rec) < 5:
        return None
    types = {0x00: "Ferry", 0x01: "Train", 0x02: "OutOfScope",
             0x03: "BeginAreaNoGNSS", 0x04: "EndAreaNoGNSS"}
    code = rec[4]
    return {
        "confidence": "high",
        "timestamp": _iso(struct.unpack(">I", rec[0:4])[0]),
        "condition": types.get(code, f"0x{code:02X}"),
        "type_code": code,
    }


def decode_gnss_ad(rec):
    """VuGNSSADRecord — GNSS accumulated driving, G2 (56) / G2.2 (57):
    timeStamp(4) + cardDriver(19) + cardCodriver(19) + GNSSPlace(11/12) + odometer(3)."""
    if len(rec) < 56:
        return None
    with_auth = len(rec) >= 57
    # ts(4) + cardDriver(19) + cardCodriver(19) + GNSSPlace(11/12) + odometer(3)
    odo_off = 42 + (12 if with_auth else 11)
    return {
        "confidence": "high",
        "timestamp": _iso(struct.unpack(">I", rec[0:4])[0]),
        "card_driver": decode_full_card_number_gen(rec, 4),
        "card_codriver": decode_full_card_number_gen(rec, 23),
        "gnss_place": decode_gnss_place(rec, 42, with_auth),
        "odometer_km": _u24(rec[odo_off:odo_off + 3]) if odo_off + 3 <= len(rec) else None,
    }


def decode_overspeeding_control(rec):
    """VuOverSpeedingControlData (9 bytes): lastOverspeedControlTime(4) +
    firstOverspeedSince(4) + numberOfOverspeedSince(1)."""
    if len(rec) < 9:
        return None
    return {
        "confidence": "high",
        "last_control_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "first_overspeed_since": _iso(struct.unpack(">I", rec[4:8])[0]),
        "number_of_overspeed": rec[8],
    }


def decode_overspeeding_event(rec):
    """VuOverSpeedingEventRecord (32 bytes): eventType(1) + recordPurpose(1) +
    beginTime(4) + endTime(4) + maxSpeed(1) + avgSpeed(1) +
    cardNumberAndGenDriverSlotBegin(19) + similarEventsNumber(1)."""
    if len(rec) < 32:
        return None
    return {
        "confidence": "high",
        "event_type": rec[0],
        "record_purpose": rec[1],
        "begin": _iso(struct.unpack(">I", rec[2:6])[0]),
        "end": _iso(struct.unpack(">I", rec[6:10])[0]),
        "max_speed_kmh": rec[10],
        "average_speed_kmh": rec[11],
        "card_driver": decode_full_card_number_gen(rec, 12),
        "similar_events": rec[31],
    }


def decode_power_interruption(rec):
    """VuPowerSupplyInterruptionRecord (87 bytes): eventType(1) + recordPurpose(1)
    + beginTime(4) + endTime(4) + 4×FullCardNumberAndGen(19) + tail(1)."""
    if len(rec) < 86:
        return None
    return {
        "confidence": "medium",
        "event_type": rec[0],
        "record_purpose": rec[1],
        "begin": _iso(struct.unpack(">I", rec[2:6])[0]),
        "end": _iso(struct.unpack(">I", rec[6:10])[0]),
        "card_driver_begin": decode_full_card_number_gen(rec, 10),
        "card_driver_end": decode_full_card_number_gen(rec, 29),
        "card_codriver_begin": decode_full_card_number_gen(rec, 48),
        "card_codriver_end": decode_full_card_number_gen(rec, 67),
        "raw_tail_hex": rec[86:].hex(),
    }


def decode_its_consent(rec):
    """VuITSConsentRecord (20 bytes): cardNumberAndGen(19) + consent(1)."""
    if len(rec) < 20:
        return None
    return {
        "confidence": "high",
        "card": decode_full_card_number_gen(rec, 0),
        "consent": bool(rec[19] & 0x01),
    }


def decode_time_adjustment(rec):
    """VuTimeAdjustmentRecord — oldTimeValue(4) + newTimeValue(4) + workshop info.
    Decode the two timestamps; surface the rest raw."""
    if len(rec) < 8:
        return None
    return {
        "confidence": "medium",
        "old_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "new_time": _iso(struct.unpack(">I", rec[4:8])[0]),
        "raw_tail_hex": rec[8:].hex(),
    }


def decode_border_crossing(rec):
    """VuBorderCrossingRecord (55 bytes) — confirmed on real data."""
    if len(rec) < 55:
        return None
    return {
        "confidence": "high",
        "card_driver": decode_full_card_number_gen(rec, 0),
        "card_codriver": decode_full_card_number_gen(rec, 19),
        "country_left": decoders.get_nation(rec[38]),
        "country_entered": decoders.get_nation(rec[39]),
        "gnss_place": decode_gnss_place_auth(rec, 40),
        "odometer_km": _u24(rec[52:55]),
    }


def decode_load_unload(rec):
    """VuLoadUnloadRecord (58 bytes): timeStamp(4) + operationType(1) +
    cardDriver(19) + cardCodriver(19) + gnssPlaceAuth(12) + odometer(3)."""
    if len(rec) < 58:
        return None
    ts = struct.unpack(">I", rec[0:4])[0]
    op = rec[4]
    op_names = {0x01: "load", 0x02: "unload", 0x03: "simultaneous"}
    return {
        "confidence": "medium",
        "timestamp": _iso(ts),
        "operation_type": op_names.get(op, f"0x{op:02X}"),
        "card_driver": decode_full_card_number_gen(rec, 5),
        "card_codriver": decode_full_card_number_gen(rec, 24),
        "gnss_place": decode_gnss_place_auth(rec, 43),
        "odometer_km": _u24(rec[55:58]),
    }


def _decode_event_fault_prefix(rec):
    """Common Gen2 VuEventRecord / VuFaultRecord prefix (10 bytes):
    eventType(1) + eventRecordPurpose(1) + eventBeginTime(4) + eventEndTime(4).
    The remaining bytes (card numbers, similar-events count, manufacturer data)
    are surfaced raw — their exact layout is not verified here."""
    if len(rec) < 10:
        return None
    begin = struct.unpack(">I", rec[2:6])[0]
    end = struct.unpack(">I", rec[6:10])[0]
    return {
        "type_code": rec[0],
        "record_purpose": rec[1],
        "begin": _iso(begin),
        "end": _iso(end),
        "raw_tail_hex": rec[10:].hex(),
    }


def _decode_record(record_type, rec):
    """Decode a single record by recordType. Returns a dict (always includes
    record_type, size, confidence)."""
    name, confidence = RECORD_TYPES.get(record_type, (f"Unknown_0x{record_type:02X}", "low"))
    out = {"record_type": f"0x{record_type:02X}", "name": name,
           "size": len(rec), "confidence": confidence}

    _structured = {
        0x22: decode_border_crossing,
        0x23: decode_load_unload,
        0x1C: decode_place_daily,
        0x09: decode_specific_condition,
        0x16: decode_gnss_ad,
        0x1A: decode_overspeeding_control,
        0x1B: decode_overspeeding_event,
        0x1E: decode_time_adjustment,
        0x1F: decode_power_interruption,
        0x17: decode_its_consent,
        0x10: decode_company_lock,
        0x11: decode_control_activity,
        0x19: decode_vu_identification,
        0x0C: decode_calibration,
        0x0D: decode_card_iw,
        0x14: decode_download_activity,
        0x20: decode_sensor_paired,
    }
    if record_type in _structured:
        decoded = _structured[record_type](rec)
        if decoded:
            out.update(decoded)
        else:
            out["raw_hex"] = rec[:48].hex()
        return out
    if record_type == 0x01 and len(rec) >= 2:
        out["activity"] = decoders.decode_activity_val(struct.unpack(">H", rec[0:2])[0])
        return out
    if record_type in (0x03, 0x06) and len(rec) >= 4:
        out["time"] = _iso(struct.unpack(">I", rec[0:4])[0])
        return out
    if record_type == 0x05 and len(rec) >= 3:
        out["odometer_km"] = _u24(rec[0:3])
        return out
    if record_type in (0x15, 0x18):
        prefix = _decode_event_fault_prefix(rec)
        if prefix:
            out.update(prefix)
        else:
            out["raw_hex"] = rec[:48].hex()
        return out
    if record_type == 0x24 and len(rec) >= 15:
        out["nation"] = decoders.get_nation(rec[0])
        out["plate"] = decoders.decode_string(rec[1:15])
        return out
    if record_type == 0x0A and len(rec) >= 17:
        out["confidence"] = "high"
        out["vin"] = decoders.decode_string(rec[:17], is_id=True)
        return out
    if record_type == 0x0B and len(rec) >= 14:
        out["confidence"] = "high"
        out["nation"] = decoders.get_nation(rec[0])
        out["plate"] = decoders.decode_string(rec[1:14], is_id=True)
        return out
    if record_type == 0x0E and len(rec) >= 19:
        # VuCardRecord: cardNumberAndGenerationInformation(19) + serial + ...
        out["confidence"] = "medium"
        out["card"] = decode_full_card_number_gen(rec, 0)
        out["raw_tail_hex"] = rec[19:].hex()
        return out
    if record_type == 0x02 and len(rec) >= 1:
        out["confidence"] = "high"
        out["card_slots_status"] = rec[0]
        return out
    if record_type == 0x13 and len(rec) >= 8:
        out["confidence"] = "high"
        out["min_downloadable_time"] = _iso(struct.unpack(">I", rec[0:4])[0])
        out["max_downloadable_time"] = _iso(struct.unpack(">I", rec[4:8])[0])
        return out
    if record_type == 0x12 and len(rec) >= 5:
        # VuDetailedSpeedBlock: speedBlockBeginDate(4) + 60×speed(1/sec).
        # Summarised (not expanded) to avoid a 60×N value dump.
        samples = [s for s in rec[4:] if s != 0xFF]
        out["confidence"] = "high"
        out["begin"] = _iso(struct.unpack(">I", rec[0:4])[0])
        if samples:
            out["max_speed_kmh"] = max(samples)
            out["min_speed_kmh"] = min(samples)
            out["avg_speed_kmh"] = round(sum(samples) / len(samples), 1)
            out["samples"] = len(samples)
        return out
    if record_type == 0x08:
        # ECC SignatureRecord — opaque crypto blob; recognised, nothing to decode.
        out["confidence"] = "high"
        out["type"] = "ECC signature"
        return out
    if record_type in (0x04, 0x0F):
        # Certificate — kept raw here; structured parsing belongs to the
        # certificate/signature layer (signature_validator).
        out["confidence"] = "medium"
        out["type"] = "certificate (raw)"
        return out

    # Unconfirmed: surface raw bytes (truncated) instead of inventing values.
    out["raw_hex"] = rec[:48].hex() + ("..." if len(rec) > 48 else "")
    return out


def walk_vu_record_arrays(data, results):
    """Walk the VU RecordArray stream, dispatch by recordType, and populate
    ``results``. Returns a list of section summaries (also stored under
    ``results['vu_record_arrays']``)."""
    data = bytes(data)
    n = len(data)
    sections = []
    current = None
    pos = 0
    guard = 0

    def finalize(section):
        if section is None:
            return
        sections.append({
            "trep": f"0x{section['trep']:02X}",
            "section": section["name"],
            "record_counts": {f"0x{rt:02X}": len(v) for rt, v in section["records"].items()},
        })
        _emit_section(section, results)

    while pos + 5 <= n and guard < 2_000_000:
        guard += 1
        # TREP section marker 0x76 0xNN (recordType can never be 0x76)
        if data[pos] == 0x76:
            trep = data[pos + 1]
            finalize(current)
            current = {"trep": trep, "name": TREP_SECTIONS.get(trep, f"TREP_0x{trep:02X}"),
                       "records": {}}
            pos += 2
            continue

        record_type = data[pos]
        record_size = struct.unpack(">H", data[pos + 1:pos + 3])[0]
        no_of_records = struct.unpack(">H", data[pos + 3:pos + 5])[0]

        # Validate; bail to the deterministic parser's territory on garbage.
        if record_type > 0x60 or record_size > 4096 or no_of_records > 20000:
            break
        if record_size == 0 and no_of_records > 0:
            break
        end = pos + 5 + record_size * no_of_records
        if end > n:
            break

        if current is None:
            current = {"trep": 0x00, "name": "Unframed", "records": {}}

        bucket = current["records"].setdefault(record_type, [])
        rpos = pos + 5
        for _ in range(no_of_records):
            rec = data[rpos:rpos + record_size]
            bucket.append(_decode_record(record_type, rec))
            rpos += record_size
        pos = end

    finalize(current)
    results["vu_record_arrays"] = sections
    return sections


def _emit_section(section, results):
    """Map decoded section records into the app's existing result lists."""
    recs = section["records"]

    # Border crossings (0x22) and load/unload (0x23) — confirmed structures.
    for rt, key in ((0x22, "border_crossings"), (0x23, "load_unload_records")):
        for r in recs.get(rt, []):
            if r.get("card_driver") is not None or r.get("timestamp"):
                results.setdefault(key, []).append(r)

    # Places (0x1C) and specific conditions (0x09) → existing result lists.
    for r in recs.get(0x1C, []):
        if r.get("timestamp"):
            results.setdefault("places", []).append(r)
    for r in recs.get(0x09, []):
        if r.get("timestamp"):
            results.setdefault("specific_conditions", []).append(r)
    for r in recs.get(0x16, []):
        if r.get("timestamp"):
            results.setdefault("gnss_ad_records", []).append(r)
    for rt, key in ((0x1B, "overspeeding_events"), (0x1A, "overspeeding_control"),
                    (0x1F, "power_interruptions"), (0x17, "its_consents"),
                    (0x1E, "time_adjustments"), (0x10, "company_locks"),
                    (0x11, "control_activities"), (0x19, "vu_identifications"),
                    (0x0C, "calibrations"), (0x0D, "card_iw_records"),
                    (0x14, "download_activities"), (0x20, "sensor_pairings")):
        for r in recs.get(rt, []):
            results.setdefault(key, []).append(r)

    # VuEventRecord (0x15) → events, VuFaultRecord (0x18) → faults.
    # Only the standard prefix is decoded; flagged confidence: low.
    for rt, key in ((0x15, "events"), (0x18, "faults")):
        for r in recs.get(rt, []):
            if r.get("begin"):
                results.setdefault(key, []).append({
                    "event_type_code" if key == "events" else "fault_type_code": r.get("type_code"),
                    "record_purpose": r.get("record_purpose"),
                    "begin": r.get("begin"),
                    "end": r.get("end") or "N/A",
                    "confidence": "low",
                    "source": "vu_recordarray",
                })

    # Daily activities: an Activities section carries date(0x06)+odometer(0x05)+
    # activityChangeInfo(0x01). Rebuild a daily record matching results['activities'].
    if section["name"] == "Activities":
        date_str = "N/A"
        for r in recs.get(0x06, []):
            t = r.get("time")
            if t:
                date_str = datetime.fromisoformat(t).strftime("%d/%m/%Y")
                break
        km = 0
        for r in recs.get(0x05, []):
            if r.get("odometer_km"):
                km = r["odometer_km"]
                break
        eventi = [r["activity"] for r in recs.get(0x01, []) if r.get("activity")]
        if eventi:
            results.setdefault("activities", []).append(
                {"data": date_str, "km": int(km), "eventi": eventi, "source": "vu_recordarray"})
