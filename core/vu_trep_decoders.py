"""Vehicle-unit download decoders: VU overview, TREP 02-06 walkers (Annex 1B) and the G2/G2.2 VU RecordArray dispatcher."""

import struct
from datetime import datetime, timezone

from core.logger import get_logger
from core.decode_primitives import decode_activity_val, decode_date, decode_string, get_nation, parse_cyclic_buffer_activities
from core.cert_decoders import parse_g1_certificate
from core.event_fault_codes import describe_calibration_purpose, describe_control_type, describe_event, describe_fault

_log = get_logger(__name__)

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

        hdr = _RAP.parse_header(val, 0)
        if hdr and hdr["record_size"] > 0 and hdr["no_of_records"] > 0:
            records = []
            for _idx, rec, _ in _RAP.iter_records(val, 0):
                decoded = decode_fn(rec, 0)
                if decoded:
                    records.append(decoded)
            if records:
                results.setdefault(result_key, []).extend(records)
        else:
            # Bare record without a RecordArray header: same destination key,
            # so consumers (GUI/export) see the data regardless of wrapping.
            decoded = decode_fn(val, 0)
            if decoded:
                results.setdefault(result_key, []).append(decoded)
    except (struct.error, IndexError, ValueError, KeyError, AttributeError) as exc:
        _log.debug("G2 VU record parse failed for tag 0x%04X: %s", tag, exc)

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
                    "control_type_label": describe_control_type(rec[0]),
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
                # Store raw certificates for chain validation in ddd_parser.py.
                results["_g1_vu_msca_cert"] = body[0:194]
                if body[194:388]:
                    parse_g1_certificate(body[194:388], results)
                    fixed_fields_parsed.add("vu_certificate")
                    results["_g1_vu_card_cert"] = body[194:388]

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
                type_map = {"drive": "DRIVE", "rest": "REST", "work": "WORK",
                            "available": "AVAILABLE", "break_rest": "REST"}
                changes = [
                    {"activity": type_map.get(c.get("activity", "work"), "WORK"),
                     "time": f"{c['minute'] // 60:02d}:{c['minute'] % 60:02d}"}
                    for c in changes_list[:50]
                ]
                activity_list.append({
                    "timestamp": header_dt.isoformat(),
                    "date": header_dt.strftime("%d/%m/%Y"),
                    "odometer_midnight": odo,
                    "card_inserted": bool(card_inserted),
                    "changes_count": no_changes,
                    "changes": changes,
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
        from core.event_fault_codes import specific_condition_label
        conditions = []
        for _ in range(n_sc):
            rec = data[pos:pos + 5]
            ts = struct.unpack(">I", rec[0:4])[0]
            # Valid SpecificConditionType codes are 0x01-0x04 (Annex 1C §2.154).
            if 946684800 <= ts <= 4102444800 and rec[4] in (0x01, 0x02, 0x03, 0x04):
                conditions.append({
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "condition": specific_condition_label(rec[4]),
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
            if not any(a.get("date") == date_str and a.get("source") == "vu_trep02"
                       for a in activities if isinstance(a, dict)):
                activities.append({
                    "date": date_str,
                    "odometer_km": odo_midnight,
                    "changes": changes,
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
        "description": describe_fault(fault_type),
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
        "description": describe_event(evt_type),
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
                    "description": describe_event(rec[0]),
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
                    "description": describe_event(evt["event_type"]),
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
                        "description": describe_event(evt["event_type"]),
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
                            "description": describe_event(ev_type),
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
                "purpose": describe_calibration_purpose(purpose),
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
                    "purpose": describe_calibration_purpose(purpose),
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
        
        # Card download data contains the card's Elementary Files including
        # the cyclic buffer of daily activities (tag 0x0504, Annex 1B §2.32).
        # This EF is the same for both G1 and G2 driver cards.
        # Embedded as STAP records: tag(2BE) + dtype(1) + length(2BE) + payload.
        pos = 0
        while pos + 5 <= len(data):
            stag, dtype, slen = struct.unpack(">HBH", data[pos:pos + 5])
            if stag == 0x0504 and dtype <= 0x0F and 16 <= slen <= 0x100000 \
                    and pos + 5 + slen <= len(data):
                end = pos + 5 + slen
                try:
                    parse_cyclic_buffer_activities(data[pos + 5:end], results)
                except Exception as exc:
                    _log.debug("TREP 06 embedded 0x0504 parse failed: %s", exc)
                pos = end  # don't rescan inside the matched EF
            else:
                pos += 1
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 06 card download parse failed: %s", exc)
