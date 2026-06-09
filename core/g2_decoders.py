"""G2/G2.2 Vehicle Unit record decoders for RecordArray format (Annex 1C Appendix 7). Handles individual VU record types (cards, IW, time adjustments, sensors, ITS, G2.2-specific records)."""
import struct
from datetime import datetime, timezone

from .decoders import decode_string, get_nation
from core.logger import get_logger

_log = get_logger(__name__)


def parse_g2_card_record(data: bytes, offset: int = 0):
    """Decode a G2 VuCardRecord (tag 0x0509).

    Structure (Annex 1C, §4.5.3.2.8):
      fullCardNumber (18 bytes: cardIssuingMemberState + cardNumber)
      cardExpiryDate (4 bytes: timeReal)
      cardConsecutiveIndex (1 byte)
      cardReplacementIndex (1 byte)
      cardRenewalIndex (1 byte)
      cardApprovalNumber (4 bytes)
    Total: 29 bytes
    """
    if offset + 29 > len(data):
        return None
    rec = data[offset:]
    card_issuer = rec[0]
    card_number = ""
    for i in range(1, 17):
        b = rec[i]
        if 0x20 <= b < 0x7F:
            card_number += chr(b)
        else:
            card_number += f"\\x{b:02X}"
    expiry_ts = struct.unpack(">I", rec[17:21])[0]
    expiry = "N/A"
    if 946684800 <= expiry_ts <= 4102444800:
        expiry = datetime.fromtimestamp(expiry_ts, tz=timezone.utc).isoformat()
    cons_idx = rec[21]
    repl_idx = rec[22]
    renew_idx = rec[23]
    approval = struct.unpack(">I", rec[24:28])[0] if len(rec) >= 28 else 0
    nation = get_nation(card_issuer)
    return {
        "card_number": f"{nation}{card_number}",
        "expiry_date": expiry,
        "consecutive_index": cons_idx,
        "replacement_index": repl_idx,
        "renewal_index": renew_idx,
        "approval_number": f"0x{approval:08X}",
    }


def parse_g2_card_iw_record(data: bytes, offset: int = 0):
    """Decode a G2 VuCardIWRecord (tag 0x050A) - card Insert/Withdrawal.

    Structure (Annex 1C, §4.5.3.2.9):
      cardInsertionType (1 byte: Inserted(1)/Withdrawn(0))
      cardInsertionTime (4 bytes: timeReal)
      vehicleOdometerValue (3 bytes)
      cardSlot (1 byte: driverSlot(0)/co-driverSlot(1))
      cardIssuingMemberState (1 byte)
      cardNumber (16 bytes)
      cardConsecutiveIndex (1 byte)
      cardReplacementIndex (1 byte)
      cardRenewalIndex (1 byte)
    Total: 29 bytes
    """
    if offset + 29 > len(data):
        return None
    rec = data[offset:]
    insertion_type = rec[0]
    insertion_time = struct.unpack(">I", rec[1:5])[0]
    odo = int.from_bytes(rec[5:8], "big")
    slot = rec[8]
    issuer = rec[9]
    card_num = ""
    for i in range(10, 26):
        b = rec[i]
        if 0x20 <= b < 0x7F:
            card_num += chr(b)
        else:
            card_num += f"\\x{b:02X}"
    cons_idx = rec[26]
    repl_idx = rec[27]
    renew_idx = rec[28]
    ts = "N/A"
    if 946684800 <= insertion_time <= 4102444800:
        ts = datetime.fromtimestamp(insertion_time, tz=timezone.utc).isoformat()
    return {
        "type": "inserted" if insertion_type == 1 else "withdrawn",
        "timestamp": ts,
        "odometer": odo,
        "slot": "driver" if slot == 0 else "co-driver",
        "card_number": f"{get_nation(issuer)}{card_num}",
        "consecutive_index": cons_idx,
        "replacement_index": repl_idx,
        "renewal_index": renew_idx,
    }


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
    """Decode VuTimeAdjustmentData (tag 0x050D) — Annex 1C §4.5.3.2.12.

    Structure (variable-length, minimum 9 bytes):
      timeAdjustmentType   1  UInt8 (0=auto, 1=manual, 2=workshop)
      oldTimeValue         4  TimeReal
      newTimeValue         4  TimeReal
      [workshopName]       variable  coded string (codePage+size+text)
      [workshopCardNumber] 18 bytes  FullCardNumber
      [vehicleOdometer]    3 bytes   UInt24
    """
    if offset + 9 > len(data):
        return None
    rec = data[offset:]
    adj_type = rec[0]
    old_ts = struct.unpack(">I", rec[1:5])[0]
    new_ts = struct.unpack(">I", rec[5:9])[0]
    type_map = {0: "automatic", 1: "manual", 2: "workshop"}
    result = {
        "type": type_map.get(adj_type, f"0x{adj_type:02X}"),
        "old_time": datetime.fromtimestamp(old_ts, tz=timezone.utc).isoformat()
        if 946684800 <= old_ts <= 4102444800 else "N/A",
        "new_time": datetime.fromtimestamp(new_ts, tz=timezone.utc).isoformat()
        if 946684800 <= new_ts <= 4102444800 else "N/A",
    }
    if adj_type in (1, 2) and len(rec) >= 11:
        try:
            ws_name, pos = _read_coded_string(rec, 9)
            result["workshop_name"] = ws_name
            if pos + 18 <= len(rec):
                ws_issuer = rec[pos]
                ws_card = ""
                for i in range(pos + 1, pos + 18):
                    b = rec[i]
                    if 0x20 <= b < 0x7F:
                        ws_card += chr(b)
                    else:
                        ws_card += f"\\x{b:02X}" if i <= pos + 17 else ""
                result["workshop_card"] = f"{get_nation(ws_issuer)}{ws_card}"
                pos += 18
            if pos + 3 <= len(rec):
                odo = int.from_bytes(rec[pos:pos + 3], 'big')
                if odo != 0xFFFFFF:
                    result["odometer"] = odo
        except (struct.error, IndexError):
            _log.debug("Time adjustment workshop data parse failed (adj_type=%d)", adj_type)
    return result


def parse_g2_company_locks(data: bytes, offset: int = 0):
    """Decode VuCompanyLocksData (tag 0x050F).

    Structure (Annex 1C, §4.5.3.2.14):
      companyCardNumber (17 bytes: nation + cardNumber)
      lockInTime (4 bytes: timeReal)
      lockOutTime (4 bytes: timeReal)
    Total: 25 bytes
    """
    if offset + 25 > len(data):
        return None
    rec = data[offset:]
    issuer = rec[0]
    card_num = ""
    for i in range(1, 17):
        b = rec[i]
        if 0x20 <= b < 0x7F:
            card_num += chr(b)
        else:
            card_num += f"\\x{b:02X}"
    lock_in = struct.unpack(">I", rec[17:21])[0]
    lock_out = struct.unpack(">I", rec[21:25])[0]
    return {
        "company_card": f"{get_nation(issuer)}{card_num}",
        "lock_in": datetime.fromtimestamp(lock_in, tz=timezone.utc).isoformat()
        if 946684800 <= lock_in <= 4102444800 else "N/A",
        "lock_out": datetime.fromtimestamp(lock_out, tz=timezone.utc).isoformat()
        if 946684800 <= lock_out <= 4102444800 else "N/A",
    }


def parse_g2_sensor_paired(data: bytes, offset: int = 0):
    """Decode SensorPairedData (tag 0x0510).

    Structure (Annex 1C, §4.5.3.2.15):
      sensorSerialNumber (8 bytes)
      sensorApprovalNumber (8 bytes)
      sensorPairingDateFirst (4 bytes: timeReal)
      sensorPairingDateCurrent (4 bytes: timeReal)
    Total: 24 bytes
    """
    if offset + 24 > len(data):
        return None
    rec = data[offset:]
    serial = struct.unpack(">Q", rec[0:8])[0]
    approval = struct.unpack(">Q", rec[8:16])[0]
    first_date = struct.unpack(">I", rec[16:20])[0]
    current_date = struct.unpack(">I", rec[20:24])[0]
    return {
        "serial_number": f"0x{serial:016X}",
        "approval_number": f"0x{approval:016X}",
        "pairing_first": datetime.fromtimestamp(first_date, tz=timezone.utc).isoformat()
        if 946684800 <= first_date <= 4102444800 else "N/A",
        "pairing_current": datetime.fromtimestamp(current_date, tz=timezone.utc).isoformat()
        if 946684800 <= current_date <= 4102444800 else "N/A",
    }


def parse_g2_sensor_gnss_coupled(data: bytes, offset: int = 0):
    """Decode SensorExternalGNSSCoupledData (tag 0x0511/0x0532).

    Structure (Annex 1C, §4.5.3.2.16):
      serialNumber (8 bytes)
      approvalNumber (8 bytes)
      couplingDate (4 bytes: timeReal)
    Total: 20 bytes
    """
    if offset + 20 > len(data):
        return None
    rec = data[offset:]
    serial = struct.unpack(">Q", rec[0:8])[0]
    approval = struct.unpack(">Q", rec[8:16])[0]
    coupling_date = struct.unpack(">I", rec[16:20])[0]
    return {
        "serial_number": f"0x{serial:016X}",
        "approval_number": f"0x{approval:016X}",
        "coupling_date": datetime.fromtimestamp(coupling_date, tz=timezone.utc).isoformat()
        if 946684800 <= coupling_date <= 4102444800 else "N/A",
    }


def _parse_card_number_gen(data: bytes, offset: int):
    """Parse 20-byte FullCardNumber+Gen field.

    Structure (Annex 1C):
      cardGeneration (1 byte)
      cardIssuingMemberState (1 byte)
      cardNumber (16 bytes)
      replacementIndex (1 byte)
      renewalIndex (1 byte)
    Total: 20 bytes
    """
    if offset + 20 > len(data):
        return None
    rec = data[offset:]
    generation = rec[0]
    issuer = rec[1]
    card_num = ""
    for i in range(2, 18):
        b = rec[i]
        if 0x20 <= b < 0x7F:
            card_num += chr(b)
        else:
            card_num += f"\\x{b:02X}"
    repl_idx = rec[18]
    renew_idx = rec[19]
    nation = get_nation(issuer)
    return {
        "generation": generation,
        "nation": nation,
        "card_number": f"{nation}{card_num}",
        "replacement_index": repl_idx,
        "renewal_index": renew_idx,
    }


def parse_g22_overspeeding_event(data: bytes, offset: int = 0):
    """Decode VuOverSpeedingEventData (tag 0x052D).

    Structure (Annex 1C §2.215, G2 estimate):
      eventType (1 byte)
      eventRecordPurpose (1 byte)
      eventBeginTime (4 bytes: timeReal)
      eventEndTime (4 bytes: timeReal)
      maxSpeedValue (1 byte: km/h)
      averageSpeedValue (1 byte: km/h)
      cardNumberAndGenDriverSlotBegin (20 bytes: FullCardNumber+Gen)
      similarEventsNumber (1 byte)
    Total: 33 bytes
    """
    rec_size = 33
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
    similar_events = rec[32]
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

    Structure (Annex 1C §2.212, G2):
      lastOverspeedControlTime (4 bytes: timeReal)
      firstOverspeedSince (4 bytes: timeReal)
      numberOfOverspeedSince (2 bytes: UInt16)
    Total: 10 bytes
    """
    rec_size = 10
    if offset + rec_size > len(data):
        return None
    rec = data[offset:offset + rec_size]
    last_ts = struct.unpack(">I", rec[0:4])[0]
    first_ts = struct.unpack(">I", rec[4:8])[0]
    num_overspeed = struct.unpack(">H", rec[8:10])[0]
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

    Structure (Annex 1C §2.240, G2 estimate):
      eventType (1 byte)
      eventRecordPurpose (1 byte)
      eventBeginTime (4 bytes: timeReal)
      eventEndTime (4 bytes: timeReal)
      cardNumberAndGenDriverSlotBegin (20 bytes: FullCardNumber+Gen)
      cardNumberAndGenDriverSlotEnd (20 bytes: FullCardNumber+Gen)
      cardNumberAndGenCodriverSlotBegin (20 bytes: FullCardNumber+Gen)
      cardNumberAndGenCodriverSlotEnd (20 bytes: FullCardNumber+Gen)
    Total: 90 bytes
    """
    rec_size = 90
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
        "card_driver_end": _parse_card_number_gen(rec, 30),
        "card_codriver_begin": _parse_card_number_gen(rec, 50),
        "card_codriver_end": _parse_card_number_gen(rec, 70),
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
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "fault_type_hint": fault_type_hint,
        "begin_time": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat()
        if 946684800 <= begin_ts <= 4102444800 else "N/A",
        "end_time": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
        if 946684800 <= end_ts <= 4102444800 else "N/A",
        "card_driver_begin": _parse_card_number_gen(rec, 10),
        "card_driver_end": _parse_card_number_gen(rec, 30),
        "card_codriver_begin": _parse_card_number_gen(rec, 50),
        "card_codriver_end": _parse_card_number_gen(rec, 70),
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
    """Decode VuITSConsentData (tag 0x0512).

    Structure (Annex 1C, §4.5.3.2.17):
      consentType (1 byte: noConsentGiven(0)/consentGiven(1))
      consentTime (4 bytes: timeReal)
      cardNumber (18 bytes)
    Total: 23 bytes
    """
    if offset + 23 > len(data):
        return None
    rec = data[offset:]
    consent_type = rec[0]
    consent_time = struct.unpack(">I", rec[1:5])[0]
    issuer = rec[5]
    card_num = ""
    for i in range(6, 22):
        b = rec[i]
        if 0x20 <= b < 0x7F:
            card_num += chr(b)
        else:
            card_num += f"\\x{b:02X}"
    return {
        "consent": "given" if consent_type == 1 else "not_given",
        "timestamp": datetime.fromtimestamp(consent_time, tz=timezone.utc).isoformat()
        if 946684800 <= consent_time <= 4102444800 else "N/A",
        "card_number": f"{get_nation(issuer)}{card_num}",
    }


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
        manufacturer_code = rec[pos]; pos += 1
        manuf_name, pos = _read_coded_string(rec, pos)
        hw_version, pos = _read_coded_string(rec, pos)
        sw_version, pos = _read_coded_string(rec, pos)
        if pos + 18 > len(rec):
            return None
        approval = struct.unpack(">Q", rec[pos:pos + 8])[0]; pos += 8
        serial = struct.unpack(">Q", rec[pos:pos + 8])[0]; pos += 8
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
    0x0509: ("CardRecord", parse_g2_card_record, 29),
    0x050A: ("CardIWRecord", parse_g2_card_iw_record, 29),
    0x050B: ("DownloadablePeriod", parse_g2_downloadable_period, 8),
    0x050D: ("TimeAdjustment", parse_g2_time_adjustment, 9),
    0x050F: ("CompanyLocks", parse_g2_company_locks, 25),
    0x0510: ("SensorPaired", parse_g2_sensor_paired, 24),
    0x0511: ("SensorGNSS", parse_g2_sensor_gnss_coupled, 20),
    0x0512: ("ITSConsent", parse_g2_its_consent, 23),
    0x052B: ("ControllerIdentification", parse_g22_controller_identification, 0),
    0x052C: ("DetailedSpeed", parse_g22_detailed_speed, 64),
    0x052D: ("OverSpeedingEvent", parse_g22_overspeeding_event, 33),
    0x052E: ("OverSpeedingControl", parse_g22_overspeeding_control, 10),
    0x052F: ("TimeAdjGNSS", parse_g22_time_adj_gnss, 8),
    0x0530: ("PowerInterruption", parse_g22_power_interruption, 90),
    0x0531: ("SensorFault", parse_g22_sensor_fault, 90),
    0x0532: ("SensorGNSS", parse_g2_sensor_gnss_coupled, 20),
    0x0533: ("SensorPaired", parse_g2_sensor_paired, 24),
}
