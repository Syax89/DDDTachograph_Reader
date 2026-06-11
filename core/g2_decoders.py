"""G2/G2.2 Vehicle Unit record decoders for the tag-keyed (0x05xx) dispatch path.

Real G2/G2.2 VU downloads are recordType-keyed RecordArray streams handled by
:mod:`core.vu_record_dispatcher`; this module covers the same record bodies
when they arrive wrapped in TLV tags (0x0509-0x0533). Decoders whose layout is
confirmed in the dispatcher delegate to it, so there is a single byte-level
definition per record type.
"""
import struct
from datetime import datetime, timezone

from .decoders import get_nation
from . import vu_record_dispatcher as _vrd
from core.logger import get_logger
from core.event_fault_codes import describe_fault

_log = get_logger(__name__)


def parse_g2_card_record(data: bytes, offset: int = 0):
    """Decode a G2 VuCardRecord (tag 0x0509) — Annex 1C §2.187, 45 bytes:
    cardNumberAndGenerationInformation(19) + cardExtendedSerialNumber(8) +
    cardStructureVersion(2) + cardNumber(16)."""
    return _vrd.decode_vu_card_record(data[offset:])


def parse_g2_card_iw_record(data: bytes, offset: int = 0):
    """Decode a G2 VuCardIWRecord (tag 0x050A) — Annex 1C §2.189, 131 bytes:
    holderSurname(36) + holderFirstNames(36) + fullCardNumberAndGen(19) +
    cardExpiry(4) + insertionTime(4) + odoInsertion(3) + cardSlot(1) +
    withdrawalTime(4) + odoWithdrawal(3) + previousVehicleInfo(20) +
    manualInputFlag(1)."""
    return _vrd.decode_card_iw(data[offset:])


def parse_g2_downloadable_period(data: bytes, offset: int = 0):
    """Decode VuDownloadablePeriod (tag 0x050B).

    Structure (Annex 1C, §4.5.3.2.10):
      minDownloadableTime (4 bytes: timeReal)
      maxDownloadableTime (4 bytes: timeReal)
    Total: 8 bytes
    """
    if offset + 8 > len(data):
        return None
    rec = data[offset:]
    min_ts = struct.unpack(">I", rec[0:4])[0]
    max_ts = struct.unpack(">I", rec[4:8])[0]
    return {
        "min_downloadable": datetime.fromtimestamp(min_ts, tz=timezone.utc).isoformat()
        if 946684800 <= min_ts <= 4102444800 else "N/A",
        "max_downloadable": datetime.fromtimestamp(max_ts, tz=timezone.utc).isoformat()
        if 946684800 <= max_ts <= 4102444800 else "N/A",
    }


def parse_g2_time_adjustment(data: bytes, offset: int = 0):
    """Decode a VuTimeAdjustmentRecord (tag 0x050D) — Annex 1C §2.229, 99 bytes:
    oldTimeValue(4) + newTimeValue(4) + workshopName(36) + workshopAddress(36) +
    workshopCardNumberAndGen(19)."""
    return _vrd.decode_time_adjustment(data[offset:])


def parse_g2_company_locks(data: bytes, offset: int = 0):
    """Decode a VuCompanyLocksRecord (tag 0x050F) — Annex 1C §2.183, 99 bytes:
    lockInTime(4) + lockOutTime(4) + companyName(36) + companyAddress(36) +
    companyCardNumberAndGen(19)."""
    return _vrd.decode_company_lock(data[offset:])


def parse_g2_sensor_paired(data: bytes, offset: int = 0):
    """Decode a SensorPairedRecord (tag 0x0510/0x0533) — Annex 1C §2.156, 28 bytes:
    sensorSerialNumber(8) + sensorApprovalNumber(16) + sensorPairingDate(4)."""
    return _vrd.decode_sensor_paired(data[offset:])


def parse_g2_sensor_gnss_coupled(data: bytes, offset: int = 0):
    """Decode a SensorExternalGNSSCoupledRecord (tag 0x0511/0x0532) — Annex 1C
    §2.131, 28 bytes: sensorSerialNumber(8) + sensorApprovalNumber(16) +
    sensorCouplingDate(4)."""
    return _vrd.decode_sensor_gnss_coupled(data[offset:])


def _parse_card_number_gen(data: bytes, offset: int):
    """Parse 19-byte FullCardNumberAndGeneration field (Annex 1C §2.74).

    Structure:
      cardType (1 byte: 0x01=Driver, 0x02=Company, 0x03=Control, 0x04=Workshop)
      cardIssuingMemberState (1 byte: NationNumeric)
      cardNumber (16 bytes: IA5String)
      generation (1 byte: 0x00=Gen1, 0x01=Gen2)
    Total: 19 bytes
    """
    if offset + 19 > len(data):
        return None
    rec = data[offset:]
    card_type = rec[0]
    issuer = rec[1]
    card_num = ""
    for i in range(2, 18):
        b = rec[i]
        if 0x20 <= b < 0x7F:
            card_num += chr(b)
        else:
            card_num += f"\\x{b:02X}"
    generation = rec[18]
    nation = get_nation(issuer)
    return {
        "card_type": card_type,
        "nation": nation,
        "card_number": f"{nation}{card_num}",
        "generation": generation,
    }


def parse_g22_overspeeding_event(data: bytes, offset: int = 0):
    """Decode VuOverSpeedingEventData (tag 0x052D).

    Structure (Annex 1C §2.215):
      eventType (1 byte)
      eventRecordPurpose (1 byte)
      eventBeginTime (4 bytes: timeReal)
      eventEndTime (4 bytes: timeReal)
      maxSpeedValue (1 byte: km/h)
      averageSpeedValue (1 byte: km/h)
      cardNumberAndGenDriverSlotBegin (19 bytes: FullCardNumberAndGeneration)
      similarEventsNumber (1 byte)
    Total: 32 bytes
    """
    rec_size = 32
    if offset + rec_size > len(data):
        return None
    rec = data[offset:offset + rec_size]
    evt_type = rec[0]
    evt_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    max_speed = rec[10]
    avg_speed = rec[11]
    card_info = _parse_card_number_gen(rec, 12)
    similar_events = rec[31]
    return {
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "begin_time": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat()
        if 946684800 <= begin_ts <= 4102444800 else "N/A",
        "end_time": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
        if 946684800 <= end_ts <= 4102444800 else "N/A",
        "max_speed_kmh": max_speed,
        "average_speed_kmh": avg_speed,
        "card_begin": card_info,
        "similar_events": similar_events,
    }


def parse_g22_overspeeding_control(data: bytes, offset: int = 0):
    """Decode VuOverSpeedingControlData (tag 0x052E).

    Structure (Annex 1C §2.212):
      lastOverspeedControlTime (4 bytes: timeReal)
      firstOverspeedSince (4 bytes: timeReal)
      numberOfOverspeedSince (1 byte: UInt8)
    Total: 9 bytes
    """
    rec_size = 9
    if offset + rec_size > len(data):
        return None
    rec = data[offset:offset + rec_size]
    last_ts = struct.unpack(">I", rec[0:4])[0]
    first_ts = struct.unpack(">I", rec[4:8])[0]
    num_overspeed = rec[8]
    return {
        "last_control_time": datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
        if 946684800 <= last_ts <= 4102444800 else "N/A",
        "first_overspeed_since": datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat()
        if 946684800 <= first_ts <= 4102444800 else "N/A",
        "number_of_overspeed": num_overspeed,
    }


def parse_g22_time_adj_gnss(data: bytes, offset: int = 0):
    """Decode VuTimeAdjustmentGNSSRecord (tag 0x052F).

    Structure (Annex 1C §2.230):
      oldTimeValue (4 bytes: timeReal)
      newTimeValue (4 bytes: timeReal)
    Total: 8 bytes
    """
    rec_size = 8
    if offset + rec_size > len(data):
        return None
    rec = data[offset:offset + rec_size]
    old_ts = struct.unpack(">I", rec[0:4])[0]
    new_ts = struct.unpack(">I", rec[4:8])[0]
    return {
        "old_time": datetime.fromtimestamp(old_ts, tz=timezone.utc).isoformat()
        if 946684800 <= old_ts <= 4102444800 else "N/A",
        "new_time": datetime.fromtimestamp(new_ts, tz=timezone.utc).isoformat()
        if 946684800 <= new_ts <= 4102444800 else "N/A",
    }


def parse_g22_power_interruption(data: bytes, offset: int = 0):
    """Decode VuPowerSupplyInterruptionData (tag 0x0530).

    Structure (Annex 1C §2.240):
      eventType (1 byte)
      eventRecordPurpose (1 byte)
      eventBeginTime (4 bytes: timeReal)
      eventEndTime (4 bytes: timeReal)
      cardNumberAndGenDriverSlotBegin (19 bytes)
      cardNumberAndGenDriverSlotEnd (19 bytes)
      cardNumberAndGenCodriverSlotBegin (19 bytes)
      cardNumberAndGenCodriverSlotEnd (19 bytes)
      tail (1 byte)
    Total: 87 bytes
    """
    rec_size = 87
    if offset + rec_size > len(data):
        return None
    rec = data[offset:offset + rec_size]
    evt_type = rec[0]
    evt_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    return {
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "begin_time": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat()
        if 946684800 <= begin_ts <= 4102444800 else "N/A",
        "end_time": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
        if 946684800 <= end_ts <= 4102444800 else "N/A",
        "card_driver_begin": _parse_card_number_gen(rec, 10),
        "card_driver_end": _parse_card_number_gen(rec, 29),
        "card_codriver_begin": _parse_card_number_gen(rec, 48),
        "card_codriver_end": _parse_card_number_gen(rec, 67),
    }


def parse_g22_sensor_fault(data: bytes, offset: int = 0):
    """Decode VuSensorFaultData (tag 0x0531).

    Structure analogous to VuPowerSupplyInterruptionRecord but with
    sensor-specific data. No public byte-level spec available.
    Conservative decoder: parses event header + reports payload characteristics.

    Estimated record size: 90 bytes (same as 0x0530).
    """
    rec_size = 90
    if offset + rec_size > len(data):
        return None
    rec = data[offset:offset + rec_size]
    evt_type = rec[0]
    evt_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]

    payload = rec[10:]
    payload_len = len(payload)

    # Detect known fault type patterns
    fault_type_hint = "unknown"
    if evt_type == 0x01:
        fault_type_hint = "communication_error"
    elif evt_type == 0x02:
        fault_type_hint = "data_integrity"
    elif evt_type == 0x03:
        fault_type_hint = "sensor_timeout"
    elif evt_type == 0x04:
        fault_type_hint = "power_supply"
    elif evt_type == 0x05:
        fault_type_hint = "signal_error"
    elif evt_type == 0x0B:
        fault_type_hint = "generic_sensor_fault"
    elif evt_type == 0x0C:
        fault_type_hint = "internal_vu_fault"

    # Identify non-zero patterns in payload
    non_zero_regions = []
    run_start = None
    for i, b in enumerate(payload):
        if b != 0x00 and b != 0xFF:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                non_zero_regions.append((run_start, i))
                run_start = None
    if run_start is not None:
        non_zero_regions.append((run_start, len(payload)))

    payload_preview = payload[:32].hex()
    if payload_len > 32:
        payload_preview += "..."

    return {
        "descrizione": describe_fault(evt_type),
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "fault_type_hint": fault_type_hint,
        "begin_time": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat()
        if 946684800 <= begin_ts <= 4102444800 else "N/A",
        "end_time": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
        if 946684800 <= end_ts <= 4102444800 else "N/A",
        "card_driver_begin": _parse_card_number_gen(rec, 10),
        "card_driver_end": _parse_card_number_gen(rec, 29),
        "card_codriver_begin": _parse_card_number_gen(rec, 48),
        "card_codriver_end": _parse_card_number_gen(rec, 67),
        "payload_bytes": payload_len,
        "payload_hex": payload_preview,
        "non_zero_regions": non_zero_regions if non_zero_regions else [],
        "raw_hex": rec[10:].hex(),
    }


def parse_g22_detailed_speed(data: bytes, offset: int = 0):
    """Decode VuDetailedSpeedData (tag 0x052C).

    G2.2 detailed speed records are fixed 64-byte records in the current
    internal spec notes. This conservative decoder exposes the timestamp and
    minute-level speed samples without assigning unverified extra semantics.
    """
    if offset + 64 > len(data):
        return None
    rec = data[offset:offset + 64]
    timestamp = struct.unpack(">I", rec[0:4])[0]
    speeds = list(rec[4:64])
    valid_speeds = [speed for speed in speeds if speed != 0xFF]
    return {
        "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        if 946684800 <= timestamp <= 4102444800 else "N/A",
        "raw_timestamp": timestamp,
        "speeds_kmh": speeds,
        "valid_speed_count": len(valid_speeds),
        "max_speed_kmh": max(valid_speeds) if valid_speeds else None,
        "avg_speed_kmh": round(sum(valid_speeds) / len(valid_speeds), 2) if valid_speeds else None,
    }


def parse_g2_its_consent(data: bytes, offset: int = 0):
    """Decode a VuITSConsentRecord (tag 0x0512) — Annex 1C §2.208, 20 bytes:
    cardNumberAndGen(19) + consent(1)."""
    return _vrd.decode_its_consent(data[offset:])


def parse_g22_controller_identification(data: bytes, offset: int = 0):
    """Decode VuControllerIdentification (tag 0x052B).

    G2.2 specific - VU controller information.
    Structure (EU 2021/1228):
      manufacturerCode (1 byte)
      manufacturerName (variable, coded string)
      hardwareVersion (variable, coded string)
      softwareVersion (variable, coded string)
      approvalNumber (8 bytes)
      serialNumber (8 bytes)
      manufacturingYear (1 byte)
    """
    if offset + 2 > len(data):
        return None
    rec = data[offset:]
    pos = 0
    try:
        manufacturer_code = rec[pos]
        pos += 1
        manuf_name, pos = _read_coded_string(rec, pos)
        hw_version, pos = _read_coded_string(rec, pos)
        sw_version, pos = _read_coded_string(rec, pos)
        if pos + 18 > len(rec):
            return None
        approval = struct.unpack(">Q", rec[pos:pos + 8])[0]
        pos += 8
        serial = struct.unpack(">Q", rec[pos:pos + 8])[0]
        pos += 8
        mfg_year = rec[pos] if pos < len(rec) else 0
        return {
            "manufacturer_code": manufacturer_code,
            "manufacturer_name": manuf_name,
            "hardware_version": hw_version,
            "software_version": sw_version,
            "approval_number": f"0x{approval:016X}",
            "serial_number": f"0x{serial:016X}",
            "manufacturing_year": mfg_year + 2000 if mfg_year else "N/A",
        }
    except (struct.error, IndexError):
        return None


def _read_coded_string(data: bytes, offset: int):
    """Read a coded string (codePage + size + text) from binary data.

    Per Annex 1B/1C, the code_page byte selects the character encoding:
      0x01 = Latin-1, 0x02 = Latin-2, etc.
    Defaults to latin-1 for unknown code pages.
    """
    if offset + 2 > len(data):
        return "", offset
    code_page = data[offset]
    size = data[offset + 1]
    offset += 2
    if offset + size > len(data):
        return "", min(offset, len(data))

    encoding_map = {
        0x01: "iso-8859-1",
        0x02: "iso-8859-2",
        0x03: "iso-8859-3",
        0x04: "iso-8859-4",
        0x05: "iso-8859-5",
        0x06: "iso-8859-6",
        0x07: "iso-8859-7",
        0x08: "iso-8859-8",
        0x09: "iso-8859-9",
        0x0A: "iso-8859-10",
        0x0B: "iso-8859-11",
        0x0D: "iso-8859-13",
        0x0E: "iso-8859-14",
        0x0F: "iso-8859-15",
        0x10: "iso-8859-16",
    }
    encoding = encoding_map.get(code_page, "latin-1")
    text = data[offset:offset + size].decode(encoding, errors="replace").strip()
    return text, offset + size


G2_VU_RECORD_DECODERS = {
    0x0509: ("CardRecord", parse_g2_card_record, 45),
    0x050A: ("CardIWRecord", parse_g2_card_iw_record, 131),
    0x050B: ("DownloadablePeriod", parse_g2_downloadable_period, 8),
    0x050D: ("TimeAdjustment", parse_g2_time_adjustment, 99),
    0x050F: ("CompanyLocks", parse_g2_company_locks, 99),
    0x0510: ("SensorPaired", parse_g2_sensor_paired, 28),
    0x0511: ("SensorGNSS", parse_g2_sensor_gnss_coupled, 28),
    0x0512: ("ITSConsent", parse_g2_its_consent, 20),
    0x052B: ("ControllerIdentification", parse_g22_controller_identification, 0),
    0x052C: ("DetailedSpeed", parse_g22_detailed_speed, 64),
    0x052D: ("OverSpeedingEvent", parse_g22_overspeeding_event, 32),
    0x052E: ("OverSpeedingControl", parse_g22_overspeeding_control, 9),
    0x052F: ("TimeAdjGNSS", parse_g22_time_adj_gnss, 8),
    0x0530: ("PowerInterruption", parse_g22_power_interruption, 87),
    0x0531: ("SensorFault", parse_g22_sensor_fault, 90),
    0x0532: ("SensorGNSS", parse_g2_sensor_gnss_coupled, 20),
    0x0533: ("SensorPaired", parse_g2_sensor_paired, 24),
}
