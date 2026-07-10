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

from core.utils.logger import get_logger
from core import decoders
from core.utils.constants import RECORD_ARRAY_MAX_RECORDS, RECORD_ARRAY_MAX_SIZE
from core.utils.event_codes import describe_event, describe_fault, describe_calibration_purpose, describe_control_type, describe_record_purpose

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
    0x0E: ("VuCardRecord", "high"),                # (45) cardAndGen+serial+ver+number
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
    0x1E: ("VuTimeAdjustmentRecord", "high"),      # (99) old+new+name+addr+cardAndGen
    0x1F: ("VuPowerSupplyInterruptionRecord", "medium"),  # (87)
    0x20: ("VuSensorPairedRecord", "medium"),      # (28) serial+approval+date
    0x21: ("VuSensorExternalGNSSCoupledRecord", "medium"),  # (28) serial+approval+date
    0x22: ("VuBorderCrossingRecord", "high"),      # (55)
    0x23: ("VuLoadUnloadRecord", "high"),          # (58)
    0x24: ("VehicleRegistrationIdentification", "medium"),  # G2.2 (15)
    0x29: ("ActivityChangeInfo_Slot2", "medium"),
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
    if ts == 0:
        return "\u2014"
    return (datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            if 946684800 <= ts <= 4102444800 else None)


def decode_name(data, off, length=36):
    """Name / Address type: codePage(1) + chars(length-1). Returns the text.

    Decodes via the declared code page (defaults to latin-1) so accented
    characters in names/addresses are preserved instead of dropped.
    """
    if off + length > len(data):
        return ""
    return decoders.decode_string(data[off:off + length])


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
        "control_type_label": describe_control_type(rec[0]),
        "control_time": _iso(struct.unpack(">I", rec[1:5])[0]),
        "control_card": decode_full_card_number_gen(rec, 5),
        "download_period_begin": _iso(struct.unpack(">I", rec[24:28])[0]),
        "download_period_end": _iso(struct.unpack(">I", rec[28:32])[0]),
    }


def decode_vu_identification(rec):
    """VuIdentification (126/138): vuManufacturerName(36) + vuManufacturerAddress(36)
    + vuPartNumber(16) + vuSerialNumber(8) + software/date/generation fields."""
    if len(rec) < 96:
        return None
    out = {
        "confidence": "high",
        "manufacturer_name": decode_name(rec, 0),
        "manufacturer_address": decode_name(rec, 36),
        "part_number": _ascii(rec, 72, 16),
        "serial_number": rec[88:96].hex(),
    }
    if len(rec) >= 108:
        out.update({
            "software_version": _ascii(rec, 96, 4),
            "software_installation_date": _iso(struct.unpack(">I", rec[100:104])[0]),
            "manufacturing_date": _iso(struct.unpack(">I", rec[104:108])[0]),
        })
    if len(rec) >= 124:
        out["approval_number"] = _ascii(rec, 108, 16)
    if len(rec) >= 126:
        out["vu_generation"] = rec[124]
        out["vu_ability"] = rec[125]
    if len(rec) >= 138:
        out["digital_map_version"] = _ascii(rec, 126, 12)
    return out


def _ascii(data, off, length):
    return "".join(chr(b) if 0x20 <= b < 0x7F else "" for b in data[off:off + length]).strip()


def _decode_seal_data(data):
    """SealDataVu: five 11-byte SealRecord entries."""
    records = []
    for off in range(0, min(len(data), 55), 11):
        rec = data[off:off + 11]
        if len(rec) < 11:
            break
        records.append({
            "equipment_type": rec[0],
            "extended_seal_identifier": rec[1:11].hex(),
        })
    return records


def _load_type_label(code):
    return {0x00: "undefined", 0x01: "goods", 0x02: "passengers"}.get(code, "RFU")


def _decode_calibration_extension(rec):
    """Decode the generation-specific tail after nextCalibrationDate."""
    if len(rec) >= 252:
        return {
            "sensor_serial_number": rec[167:175].hex(),
            "sensor_gnss_serial_number": rec[175:183].hex(),
            "rcm_serial_number": rec[183:191].hex(),
            "seal_data_vu": _decode_seal_data(rec[191:246]),
            "by_default_load_type": rec[246],
            "by_default_load_type_label": _load_type_label(rec[246]),
            "calibration_country": decoders.get_nation(rec[247]),
            "calibration_country_timestamp": _iso(struct.unpack(">I", rec[248:252])[0]),
        }
    if len(rec) >= 222:
        return {"seal_data_vu": _decode_seal_data(rec[167:222])}
    return {}


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
    out = {
        "confidence": "high",
        "calibration_purpose": rec[0],
        "calibration_purpose_label": describe_calibration_purpose(rec[0]),
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
    }
    out.update(_decode_calibration_extension(rec))
    return out


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
    """SensorPairedRecord — G2 (28): sensorSerialNumber(8) +
    sensorApprovalNumber(16) + sensorPairingDate(4).

    Shorter variants (e.g. 20/24 bytes from some G2.2 tag-keyed arrays) keep
    the serial first and the TimeReal date last, with a shorter approval
    number in between; they are decoded with ``confidence: low`` instead of
    being dropped."""
    if len(rec) < 12:
        return None
    full = len(rec) >= 28
    approval_end = 24 if full else len(rec) - 4
    date_off = 24 if full else len(rec) - 4
    return {
        "confidence": "medium" if full else "low",
        "sensor_serial": rec[0:8].hex(),
        "sensor_approval": _ascii(rec, 8, approval_end - 8),
        "pairing_date": _iso(struct.unpack(">I", rec[date_off:date_off + 4])[0]),
    }


def decode_sensor_gnss_coupled(rec):
    """SensorExternalGNSSCoupledRecord — G2 (28): sensorSerialNumber(8) +
    sensorApprovalNumber(16) + sensorCouplingDate(4).

    Shorter variants (e.g. 20 bytes from some G2.2 tag-keyed arrays) are
    decoded with the same serial-first / date-last layout, ``confidence: low``."""
    if len(rec) < 12:
        return None
    full = len(rec) >= 28
    approval_end = 24 if full else len(rec) - 4
    date_off = 24 if full else len(rec) - 4
    return {
        "confidence": "medium" if full else "low",
        "sensor_serial": rec[0:8].hex(),
        "sensor_approval": _ascii(rec, 8, approval_end - 8),
        "coupling_date": _iso(struct.unpack(">I", rec[date_off:date_off + 4])[0]),
    }


def decode_vu_card_record(rec):
    """VuCardRecord (45): cardNumberAndGenerationInformation(19) +
    cardExtendedSerialNumber(8) + cardStructureVersion(2) + cardNumber(16).
    Confirmed against real G2/G2.2 VU downloads."""
    if len(rec) < 19:
        return None
    out = {"confidence": "medium", "card": decode_full_card_number_gen(rec, 0)}
    if len(rec) >= 45:
        out["confidence"] = "high"
        out["card_extended_serial"] = rec[19:27].hex()
        out["card_structure_version"] = rec[27:29].hex()
        out["card_number"] = _ascii(rec, 29, 16)
    else:
        out["raw_tail_hex"] = rec[19:].hex()
    return out


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
    if not number:
        # Zero/partial filler (cardType 0, generation 0xFF): no card in slot.
        return {"present": False}
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
    each coded as ±DDMM.M ×10 (Annex 1C §2.76). Unknown position is encoded
    as 0x7FFFFF (per coordinate); all-0xFF marks an empty/padded record."""
    if off + 6 > len(data):
        return None
    lat_raw = data[off:off + 3]
    lon_raw = data[off + 3:off + 6]
    if (lat_raw == b"\xff\xff\xff" and lon_raw == b"\xff\xff\xff") or \
            lat_raw == b"\x7f\xff\xff" or lon_raw == b"\x7f\xff\xff":
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
    """VuSpecificConditionRecord (5 bytes): entryTime(4) + specificConditionType(1).

    Type codes per Annex 1C §2.154: 0x01/0x02 = Out of scope Begin/End,
    0x03/0x04 = Ferry-Train crossing Begin/End, 0x00 = RFU.
    """
    if len(rec) < 5:
        return None
    from core.utils.event_codes import specific_condition_label
    code = rec[4]
    return {
        "confidence": "high",
        "timestamp": _iso(struct.unpack(">I", rec[0:4])[0]),
        "condition": specific_condition_label(code),
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
        "event_type_label": describe_event(rec[0]),
        "record_purpose": rec[1],
        "record_purpose_label": describe_record_purpose(rec[1]),
        "begin": _iso(struct.unpack(">I", rec[2:6])[0]),
        "end": _iso(struct.unpack(">I", rec[6:10])[0]),
        "max_speed_kmh": rec[10],
        "average_speed_kmh": rec[11],
        "card_driver": decode_full_card_number_gen(rec, 12),
        "similar_events": rec[31],
    }


def decode_power_interruption(rec):
    """VuPowerSupplyInterruptionRecord (87 bytes): eventType(1) + recordPurpose(1)
    + beginTime(4) + endTime(4) + 4×FullCardNumberAndGen(19) + similarEventsNumber(1)."""
    if len(rec) < 86:
        return None
    out = {
        "confidence": "medium",
        "event_type": rec[0],
        "event_type_label": describe_event(rec[0]),
        "record_purpose": rec[1],
        "record_purpose_label": describe_record_purpose(rec[1]),
        "begin": _iso(struct.unpack(">I", rec[2:6])[0]),
        "end": _iso(struct.unpack(">I", rec[6:10])[0]),
        "card_driver_begin": decode_full_card_number_gen(rec, 10),
        "card_driver_end": decode_full_card_number_gen(rec, 29),
        "card_codriver_begin": decode_full_card_number_gen(rec, 48),
        "card_codriver_end": decode_full_card_number_gen(rec, 67),
    }
    if len(rec) >= 87:
        out["similar_events_number"] = rec[86]
    return out


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
    """VuTimeAdjustmentRecord (99): oldTimeValue(4) + newTimeValue(4) +
    workshopName(36) + workshopAddress(36) + workshopCardNumberAndGen(19)."""
    if len(rec) < 8:
        return None
    out = {
        "confidence": "medium",
        "old_time": _iso(struct.unpack(">I", rec[0:4])[0]),
        "new_time": _iso(struct.unpack(">I", rec[4:8])[0]),
    }
    if len(rec) >= 99:
        out["confidence"] = "high"
        out["workshop_name"] = decode_name(rec, 8)
        out["workshop_address"] = decode_name(rec, 44)
        out["workshop_card"] = decode_full_card_number_gen(rec, 80)
    else:
        out["raw_tail_hex"] = rec[8:].hex()
    return out


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


_RECORD_DECODERS = {
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
    0x0E: decode_vu_card_record,
    0x14: decode_download_activity,
    0x20: decode_sensor_paired,
    0x21: decode_sensor_gnss_coupled,
}

def _decode_record(record_type, rec):
    """Decode a single record by recordType. Returns a dict (always includes
    record_type, size, confidence)."""
    name, confidence = RECORD_TYPES.get(record_type, (f"Unknown_0x{record_type:02X}", "low"))
    out = {"record_type": f"0x{record_type:02X}", "name": name,
           "size": len(rec), "confidence": confidence}

    if record_type in _RECORD_DECODERS:
        decoded = _RECORD_DECODERS[record_type](rec)
        if decoded:
            out.update(decoded)
        else:
            out["raw_hex"] = rec[:48].hex()
        return out
    if record_type == 0x01 and len(rec) >= 2:
        activity = decoders.decode_activity_val(struct.unpack(">H", rec[0:2])[0])
        if activity is not None:
            out["activity"] = activity
        else:
            out["raw_hex"] = rec[:2].hex()
        return out
    if record_type == 0x29 and len(rec) >= 2:
        val = struct.unpack(">H", rec[0:2])[0]
        activity = decoders.decode_activity_val(val)
        # 0x29 is strongly suspected to be the co-driver slot's
        # ActivityChangeInfo on VU models that partition by slot (observed on
        # Stoneridge V6006 G2.2).  The bit layout is identical to 0x01.
        if activity is not None:
            out["activity"] = activity
            out["confidence"] = "medium"
            out["note"] = "probable co-driver slot (ActivityChangeInfo, recordType 0x29)"
            return out
        out["raw_hex"] = rec[:2].hex()
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
            type_code = prefix.get("type_code")
            out["description"] = describe_event(type_code) if record_type == 0x15 else describe_fault(type_code)
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
        raw_speeds = [None if s == 0xFF else s for s in rec[4:64]]
        samples = [s for s in raw_speeds if s is not None]
        out["confidence"] = "high"
        out["begin"] = _iso(struct.unpack(">I", rec[0:4])[0])
        # Internal chart data: excluded from GUI tables and exports.
        out["_chart_speeds_kmh"] = raw_speeds
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


def iter_vu_sections(data):
    """Yield sections from a VU RecordArray stream as {marker, trep, records: [(pos, rt, rs, nr, end), ...]}.

    This is the canonical section iterator shared by ``walk_vu_record_arrays``
    and ``vu_signature_verifier._iter_sections``.
    """
    n = len(data)
    pos = 0
    cur = None
    # Valid TREP bytes following a 0x76 section marker (G1/G2/G2.2 + card download).
    trep_bytes = set(TREP_SECTIONS) | {0x06, 0x26, 0x36}
    while pos + 5 <= n:
        if data[pos] == 0x76 and data[pos + 1] in trep_bytes:
            if cur:
                yield cur
            cur = {"marker": pos, "trep": data[pos + 1], "records": []}
            pos += 2
            continue
        rt = data[pos]
        rs = struct.unpack(">H", data[pos + 1:pos + 3])[0]
        nr = struct.unpack(">H", data[pos + 3:pos + 5])[0]
        if rt < 0x01 or rt > 0x60 or rs > RECORD_ARRAY_MAX_SIZE or nr > RECORD_ARRAY_MAX_RECORDS or (rs == 0 and nr > 0 and rt != 0x60):
            # Resync one byte at a time: skipping a whole header width here
            # could jump over the start of a valid RecordArray after junk.
            pos += 1
            continue
        if pos + 5 + rs * nr > n:
            break
        if cur is not None:
            cur["records"].append((pos, rt, rs, nr, pos + 5 + rs * nr))
        pos += 5 + rs * nr
    if cur:
        yield cur


def walk_vu_record_arrays(data, results):
    """Walk the VU RecordArray stream, dispatch by recordType, and populate
    ``results``. Returns a list of section summaries (also stored under
    ``results['vu_record_arrays']``)."""
    data = bytes(data)
    sections = []

    for sec in iter_vu_sections(data):
        current = {"trep": sec["trep"], "name": TREP_SECTIONS.get(sec["trep"], f"TREP_0x{sec['trep']:02X}"),
                   "records": {}}
        for (pos, rt, rs, nr, _end) in sec["records"]:
            rpos = pos + 5
            for _ in range(nr):
                rec = data[rpos:rpos + rs]
                current["records"].setdefault(rt, []).append(_decode_record(rt, rec))
                rpos += rs
        sections.append({
            "trep": f"0x{current['trep']:02X}",
            "section": current["name"],
            "record_counts": {f"0x{rt:02X}": len(v) for rt, v in current["records"].items()},
        })
        _emit_section(current, results)

    results["vu_record_arrays"] = sections
    return sections


def _emit_section(section, results):
    """Map decoded section records into the app's existing result lists."""
    recs = section["records"]

    # Vehicle identification: write the first found VIN, plate, nation
    # into results["vehicle"]. G2 uses 0x0B (VehicleRegistrationNumber),
    # G2.2 uses 0x24 (VehicleRegistrationIdentification), both use 0x0A (VIN).
    for rt in (0x0A, 0x0B, 0x24):
        for r in recs.get(rt, []):
            vin = r.get("vin")
            nation = r.get("nation")
            plate = r.get("plate")
            if vin and results["vehicle"]["vin"] == "N/A":
                results["vehicle"]["vin"] = vin
            if nation and results["vehicle"]["registration_nation"] == "N/A":
                results["vehicle"]["registration_nation"] = nation
            if plate and results["vehicle"]["plate"] == "N/A":
                results["vehicle"]["plate"] = plate

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
                    (0x0E, "card_records"), (0x14, "download_activities"),
                    (0x20, "sensor_pairings"), (0x21, "sensor_gnss_couplings")):
        for r in recs.get(rt, []):
            results.setdefault(key, []).append(r)

    # VuDetailedSpeedBlock (0x12) → speed_blocks (same key the G1 TREP 04
    # walk uses, so the GUI "Detailed Speed Blocks" section covers both
    # generations). Padding blocks decode with begin=None and are skipped.
    for r in recs.get(0x12, []):
        if r.get("begin"):
            results.setdefault("speed_blocks", []).append(r)

    # VuEventRecord (0x15) → events, VuFaultRecord (0x18) → faults.
    # Only the standard prefix is decoded; flagged confidence: low.
    for rt, key in ((0x15, "events"), (0x18, "faults")):
        for r in recs.get(rt, []):
            if r.get("begin"):
                type_code = r.get("type_code")
                desc = describe_event(type_code) if key == "events" else describe_fault(type_code)
                results.setdefault(key, []).append({
                    "description": desc,
                    "event_type_code" if key == "events" else "fault_type_code": type_code,
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
            if not isinstance(t, str) or t == "—":
                continue
            try:
                date_str = datetime.fromisoformat(t).strftime("%d/%m/%Y")
            except ValueError:
                continue
            break
        km = 0
        for r in recs.get(0x05, []):
            if r.get("odometer_km"):
                km = r["odometer_km"]
                break
        changes = [r["activity"] for r in recs.get(0x01, []) if r.get("activity")]
        if changes:
            results.setdefault("activities", []).append(
                {"date": date_str, "odometer_km": int(km), "changes": changes,
                 "source": "vu_recordarray"})


# ── Additional G2.2 record decoders (moved from g2_decoders) ──────────────


def decode_downloadable_period(rec):
    """VuDownloadablePeriod (8 bytes): minDownloadableTime(4) + maxDownloadableTime(4)."""
    if len(rec) < 8:
        return None
    min_ts = struct.unpack(">I", rec[0:4])[0]
    max_ts = struct.unpack(">I", rec[4:8])[0]
    return {
        "min_downloadable": _iso(min_ts) or "N/A",
        "max_downloadable": _iso(max_ts) or "N/A",
    }


def decode_time_adj_gnss(rec):
    """VuTimeAdjustmentGNSSRecord (8 bytes): oldTimeValue(4) + newTimeValue(4)."""
    if len(rec) < 8:
        return None
    old_ts = struct.unpack(">I", rec[0:4])[0]
    new_ts = struct.unpack(">I", rec[4:8])[0]
    return {
        "old_time": _iso(old_ts) or "N/A",
        "new_time": _iso(new_ts) or "N/A",
    }


def decode_sensor_fault(rec):
    """VuSensorFaultData (90 bytes): event header + sensor-specific payload."""
    if len(rec) < 90:
        return None
    evt_type = rec[0]
    evt_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    fault_hint = {
        0x01: "communication_error", 0x02: "data_integrity",
        0x03: "sensor_timeout", 0x04: "power_supply",
        0x05: "signal_error", 0x0B: "generic_sensor_fault",
        0x0C: "internal_vu_fault",
    }.get(evt_type, "unknown")
    payload = rec[10:]
    non_zero = []
    run_start = None
    for i, b in enumerate(payload):
        if b not in (0x00, 0xFF):
            if run_start is None:
                run_start = i
        elif run_start is not None:
            non_zero.append((run_start, i))
            run_start = None
    if run_start is not None:
        non_zero.append((run_start, len(payload)))
    return {
        "description": describe_fault(evt_type),
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "fault_type_hint": fault_hint,
        "begin_time": _iso(begin_ts) or "N/A",
        "end_time": _iso(end_ts) or "N/A",
        "card_driver_begin": decode_full_card_number_gen(rec, 10),
        "card_driver_end": decode_full_card_number_gen(rec, 29),
        "card_codriver_begin": decode_full_card_number_gen(rec, 48),
        "card_codriver_end": decode_full_card_number_gen(rec, 67),
        "payload_bytes": len(payload),
        "payload_hex": payload[:32].hex() + ("..." if len(payload) > 32 else ""),
        "non_zero_regions": non_zero,
        "confidence": "low",
    }


def decode_detailed_speed(rec):
    """VuDetailedSpeedData (64 bytes): timestamp(4) + 60 x speed UInt8 km/h."""
    if len(rec) < 64:
        return None
    timestamp = struct.unpack(">I", rec[0:4])[0]
    speeds = list(rec[4:64])
    valid = [s for s in speeds if s != 0xFF]
    return {
        "timestamp": _iso(timestamp) or "N/A",
        "speeds_kmh": speeds,
        "valid_speed_count": len(valid),
        "max_speed_kmh": max(valid) if valid else None,
        "avg_speed_kmh": round(sum(valid) / len(valid), 2) if valid else None,
        "confidence": "medium",
    }


def _read_coded_string(data, off):
    """Read codePage(1) + size(1) + text(size) from binary data."""
    if off + 2 > len(data):
        return "", off
    code_page = data[off]
    size = data[off + 1]
    off += 2
    if off + size > len(data):
        return "", min(off, len(data))
    enc = {0x01: "iso-8859-1", 0x02: "iso-8859-2", 0x03: "iso-8859-3",
           0x04: "iso-8859-4", 0x05: "iso-8859-5", 0x06: "iso-8859-6",
           0x07: "iso-8859-7", 0x08: "iso-8859-8", 0x09: "iso-8859-9",
           0x0A: "iso-8859-10", 0x0B: "iso-8859-11",
           0x0D: "iso-8859-13", 0x0E: "iso-8859-14",
           0x0F: "iso-8859-15", 0x10: "iso-8859-16"}.get(code_page, "latin-1")
    text = data[off:off + size].decode(enc, errors="replace").strip()
    return text, off + size


def decode_controller_identification(rec):
    """VuControllerIdentification: manufacturer + HW/SW versions + approval + serial."""
    if len(rec) < 2:
        return None
    try:
        pos = 0
        mfg_code = rec[pos]
        pos += 1
        mfg_name, pos = _read_coded_string(rec, pos)
        hw_ver, pos = _read_coded_string(rec, pos)
        sw_ver, pos = _read_coded_string(rec, pos)
        if pos + 18 > len(rec):
            return None
        approval = struct.unpack(">Q", rec[pos:pos + 8])[0]
        pos += 8
        serial = struct.unpack(">Q", rec[pos:pos + 8])[0]
        pos += 8
        mfg_year = rec[pos] if pos < len(rec) else 0
        return {
            "manufacturer_code": mfg_code,
            "manufacturer_name": mfg_name,
            "hardware_version": hw_ver,
            "software_version": sw_ver,
            "approval_number": f"0x{approval:016X}",
            "serial_number": f"0x{serial:016X}",
            "manufacturing_year": mfg_year + 2000 if mfg_year else "N/A",
            "confidence": "medium",
        }
    except (struct.error, IndexError):
        return None
