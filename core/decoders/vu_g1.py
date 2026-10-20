"""Vehicle-unit G1 download decoders: VU overview and TREP 02-06 stream walkers (Annex 1B)."""

import struct
import typing
from datetime import datetime, timezone

from core.utils.logger import get_logger, redact
from core.decoders.common import (
    decode_activity_val, decode_date, decode_previous_vehicle_info, decode_string,
    describe_manual_input_flag, get_nation)
from core.decoders.cert import parse_g1_certificate
from core.utils.event_codes import (
    EVENT_FAULT_VERSION_G1, control_type_bits, describe_calibration_purpose,
    describe_control_type, describe_event, describe_event_fault_type,
    describe_record_purpose, event_fault_type_status,
    specific_condition_label)

_log = get_logger(__name__)

def _mark_heuristic(results, section, fields):
    """Thin wrapper over :func:`core.decoders.common.mark_heuristic` kept for
    call-site brevity within this module."""
    from core.decoders.common import mark_heuristic
    mark_heuristic(results, section, fields)


def _g1_time(ts, *, with_seconds=True):
    """ISO-8601 UTC string for a plausible TimeReal, else ``None``.

    ``None`` (not a fabricated date) is what an out-of-calendar value means, so
    callers can keep the record and the raw integer together.
    """
    if not isinstance(ts, int) or not 946684800 <= ts <= 4102444800:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _missing(value):
    """True when *value* is absent or the 'N/A' sentinel used by TachoResult
    defaults (the defaults are truthy, so bare truthiness checks are dead code)."""
    return not value or value == "N/A"


def _newest_known_time(results):
    """Newest epoch second this file already established, or None.

    Used as the plausibility horizon for records synthesized by the emergency
    heuristic scans: the vehicle unit cannot record an event after the moment
    the download was taken, so a guessed record dated beyond the newest time
    the file itself already carries is a scanner false positive, not data.
    """
    newest = None

    def _offer(value):
        nonlocal newest
        if not isinstance(value, str) or not value:
            return
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        try:
            ts = int(parsed.timestamp())
        except (OverflowError, OSError, ValueError):
            return
        if 946684800 <= ts <= 4102444800 and (newest is None or ts > newest):
            newest = ts

    _offer((results.get("metadata") or {}).get("current_datetime"))
    for section in ("activities", "events", "faults", "places", "overspeeding_events",
                    "control_activities", "download_activities", "card_iw_records",
                    "time_adjustments"):
        for rec in results.get(section) or []:
            if not isinstance(rec, dict):
                continue
            for key in ("begin_time", "end_time", "timestamp", "begin", "end",
                        "control_time", "downloading_time", "insertion_time",
                        "old_time", "new_time"):
                _offer(rec.get(key))
    return newest


def parse_vu_vehicle_identification(val, results):
    """Parse VU_VehicleIdentification (tag 0x0001 in VU context)."""
    if len(val) < 32:
        return
    try:
        # Only decode if format looks like standard VRN data (Annex 1B §2.15,
        # same layout as parse_g1_vu_overview):
        # byte[0:17] = readable VIN, byte[17] = nation (0x00-0xFD),
        # byte[18:32] = readable plate
        vin = decode_string(val[0:17], is_id=True)
        nation = get_nation(val[17])
        plate = decode_string(val[18:32], is_id=True)
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
            # A company lock is a stored record, not a date: a TimeReal outside
            # the calendar is corrupt/erased data and the record is kept with
            # its raw value and an explicit status. Dropping it would silently
            # delete a control-relevant entry (Annex 1B §2.110).
            locks.append({
                "lock_in_time": _g1_time(lock_in),
                "lock_out_time": _g1_time(lock_out),
                "lock_in_raw": lock_in,
                "lock_out_raw": lock_out,
                "time_status": ("valid" if _g1_time(lock_in) else "invalid"),
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
            begin_ts = struct.unpack(">I", rec[23:27])[0]
            end_ts = struct.unpack(">I", rec[27:31])[0]
            # Same rule as the locks: a control record is kept even when its
            # timestamp is not a calendar date (§2.44/§2.133).
            controls.append({
                "control_type": rec[0],
                # Generation 1 ControlType is 'cvpdxxxx'B (§2.44): the roadside
                # calibration bit of generation 2 does not exist here.
                "control_type_label": describe_control_type(rec[0], generation="G1"),
                "control_type_bits": control_type_bits(rec[0], generation="G1"),
                "control_time": _g1_time(ctrl_ts),
                "control_time_raw": ctrl_ts,
                "time_status": ("valid" if _g1_time(ctrl_ts) else "invalid"),
                "control_card": _parse_full_card_number(rec, 5),
                "download_period_begin": _g1_time(begin_ts),
                "download_period_end": _g1_time(end_ts),
            })
            off += 31

        # The counts are structural: every declared record is decoded above, so
        # this check now only guards against a count that does not fit the body
        # (already done above) — records are never deleted for their values.

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

#: CardSlotsStatus nibble → card type (Annex 1B §2.28, shared by every
#: generation): 0000 no card, 0001 driver, 0010 workshop, 0011 control,
#: 0100 company card, 0101..1111 unassigned.
G1_CARD_SLOT_TYPES = {0x00: "none", 0x01: "driver", 0x02: "workshop",
                      0x03: "control", 0x04: "company"}


def _g1_card_slots(value):
    """Both CardSlotsStatus nibbles, typed (high = co-driver, low = driver).

    The published short word keeps its historical vocabulary
    (``empty``/``occupied``/``reserved``); the assigned card type, its numeric
    code and its assignment status travel as model-only companions.
    """
    out = {}
    for name, nibble in (("driver_slot", value & 0x0F),
                         ("codriver_slot", (value >> 4) & 0x0F)):
        card_type = G1_CARD_SLOT_TYPES.get(nibble)
        out[name] = _card_slot_state(nibble)
        out[f"{name}_code"] = nibble
        out[f"{name}_type"] = card_type or "unassigned"
        out[f"{name}_status"] = "assigned" if card_type else "unassigned"
    out["raw"] = f"0x{value:02X}"
    return out


def _card_slot_state(code):
    """One CardSlotsStatus nibble → ``"empty"`` | ``"occupied"`` | ``"reserved"``.

    ``CardSlotsStatus`` (Annex 1B Appendix 1 §2.28) is one octet, octet aligned
    ``'ccccdddd'B``: the high nibble is the card type in the **co-driver** slot,
    the low nibble the card type in the **driver** slot, with ``0000`` no card,
    ``0001`` driver, ``0010`` workshop, ``0011`` control, ``0100`` company card
    and ``0101``..``1111`` unassigned.

    The published result only says whether a slot is in use, so an assigned
    card type reports ``occupied`` and an unassigned code reports ``reserved``
    — the type itself is never guessed into a name (naming it on screen would
    add UI text; see docs/developer/normative-completion.md).
    """
    if code == 0x00:
        return "empty"
    if code <= 0x04:
        return "occupied"
    return "reserved"

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
        # The TREP 01 body starts at the MemberStateCertificate (offset 0): the
        # caller already stripped the SID/TREP bytes. The alignment is chosen
        # from the verified field shape (VIN at 388 must be 17 alphanumeric
        # chars AND a plausible TimeReal at 420-432), NEVER from a single
        # unconstrained byte: the certificate's first byte is an RSA signature
        # byte and is 0x00 by chance ~1/256 — keying the shift on it would move
        # the VIN/plate/nation/date/slot fields and publish a wrong identity.
        body = None
        for cand in (val, val[2:]):
            if len(cand) >= 433:
                vin_check = decode_string(cand[388:405], is_id=True)
                ts_fields = struct.unpack(">III", cand[420:432])
                if (len(vin_check) == 17 and vin_check.replace(" ", "").isalnum()
                        and any(946684800 <= t <= 4102444800 for t in ts_fields)):
                    body = cand
                    break
        body_validated = body is not None
        if body is None:
            body = val

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
                # 'ccccdddd'B: high nibble = co-driver slot card type, low
                # nibble = driver slot card type (Annex 1B Appendix 1 §2.28).
                # The two keys and their value vocabulary are unchanged — only
                # the nibbles are read where the old code tested bits 0/1,
                # which reported 0x41 (both slots occupied) as co-driver empty.
                results.setdefault("vu_overview", {})["card_slot_status"] = (
                    _g1_card_slots(slot_status))
                fixed_fields_parsed.add("card_slots")

                if _parse_g1_overview_tail(body, 433, results):
                    fixed_fields_parsed.update(
                        ("download_activity", "company_locks", "control_activities"))
            except (struct.error, IndexError, ValueError) as exc:
                _log.debug("VU overview fixed-offset parse failed: %s", exc)

        _log.debug("VU overview fixed-offset fields: %s", sorted(fixed_fields_parsed))

        # Emergency heuristic fallback: regex-based extraction, run ONLY when the
        # deterministic fixed-offset parse could not validate the body OR left a
        # specific fixed-offset field empty. Every value recovered this way is
        # flagged as low-confidence in metadata so the UI/exports can mark it as
        # inferred (Annex 1B §4.5.3.2.2 defines the fixed layout; regex is a last
        # resort for non-standard/corrupt downloads only). ``card_numbers`` is not
        # a fixed-offset field, so its emptiness alone is not a recovery trigger.
        needs_recovery = (
            not body_validated
            or _missing(results["vehicle"].get("vin"))
            or _missing(results["vehicle"].get("plate"))
            or not (results.get("company_info") or {}).get("name")
        )
        if needs_recovery:
            if _missing(results["vehicle"].get("vin")):
                _log.warning("VU overview: VIN not parsed via fixed-offset, trying regex")
                for m in re.finditer(rb'[A-Z0-9]{17}', val[:500]):
                    vin = m.group().decode()
                    if len(vin) == 17:
                        results["vehicle"]["vin"] = vin
                        regex_fields_parsed.add("vin")
                        break

            if _missing(results["vehicle"].get("plate")):
                _log.warning("VU overview: plate not parsed via fixed-offset, trying regex")
                plate_match = re.search(rb'[\x01-\x1F]?([A-Z0-9]{3,14})\s{3,}', val[150:450])
                if plate_match:
                    plate_raw = plate_match.group(1).decode('latin-1').strip()
                    if 3 <= len(plate_raw) <= 14:
                        results["vehicle"]["plate"] = plate_raw
                        regex_fields_parsed.add("plate")

            if not (results.get("company_info") or {}).get("name"):
                for m in re.finditer(rb'[A-Z][A-Z .&\-]{5,35}\s{2,}', val):
                    text = m.group().decode('latin-1').strip()
                    if text and len(text) > 5 and not text.startswith('VU'):
                        results.setdefault("company_info", {})["name"] = text
                        regex_fields_parsed.add("company_name")
                        break

            if not results.get("card_numbers"):
                found = set()
                for m in re.finditer(rb'[A-Z][-]?\d{13,20}', val):
                    cn = m.group().decode()
                    if len(cn) >= 14:
                        found.add(cn)
                if found:
                    results["card_numbers"] = sorted(found)
                    regex_fields_parsed.add("card_numbers")

        if regex_fields_parsed:
            _log.debug("VU overview regex-heuristic fields: %s", sorted(regex_fields_parsed))
            _mark_heuristic(results, "vu_overview_TREP01", sorted(regex_fields_parsed))
    except (ValueError, TypeError, IndexError) as exc:
        _log.debug("VU overview heuristic parse failed: %s", exc)

def parse_vu_download_messages(raw_data, results):
    """Parse VU download messages (SID 0x76 + TREP) in the raw binary data.
    
    Message types (TREP), Annex 1B §2.2.6:
      0x01 = Overview (certificates + vehicle ID)
      0x02 = Activities (card holder + daily activity records)
      0x03 = Events & Faults
      0x04 = Detailed speed data
      0x05 = Technical data (calibrations)
      0x06 = Card download

    Runs only when the deterministic walk could not validate the whole stream.
    Each message is handed its own bounded slice of the buffer at most once;
    a CardDownload (whose length is implicit) is decoded a single time over the
    remaining tail, so k embedded ``76 06`` byte pairs no longer re-parse the
    whole tail per marker (O(k·n) → O(n)).
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

        n = len(raw_data)
        card_region_end = -1
        for i, (msg_offset, trep) in enumerate(found_messages):
            if trep == 0x06:
                # A CardDownload has no length field: decode the tail once from
                # its first marker. Subsequent 06 markers lie inside that
                # already-decoded region (embedded byte pairs), so skip them
                # instead of re-parsing the whole tail for each.
                if msg_offset < card_region_end:
                    continue
                data = raw_data[msg_offset + 2:]
                _parse_trep_06_card_download(data, results)
                card_region_end = n
                continue
            body_start = msg_offset + 2
            body_end = found_messages[i + 1][0] if i + 1 < len(found_messages) else n
            if body_end <= body_start:
                continue
            data = raw_data[body_start:body_end]
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
    except (struct.error, IndexError, ValueError) as exc:
        # This is the backup route: a swallowed error here must be visible.
        _log.warning("VU download messages parse failed: %s", exc)

def _parse_trep_02_activities(data, results):
    """Parse TREP 02 (Activities) message: card holder + daily activity records.

    Attempts structured daily record boundary detection first (0x7622/0x7632 markers),
    then falls back to timestamp-scan heuristic.
    """
    import re
    try:
        # Deterministic G1 layout first (Annex 1B §2.2.6.2). A structurally
        # valid G1 TREP 02 (including the 18-byte "card not inserted" day) is
        # authoritative: it must never be routed to the G2 parser, because an
        # odometer value such as 30242 km (0x007622) puts the byte pair
        # ``76 22`` inside the body and a naive "0x7622 in data[:500]" sniff
        # would silently discard the whole day + driver.
        if _parse_trep_02_g1_structured(data, results):
            return

        if len(data) < 50:
            return

        # G2 RecordArray format: the body begins with the 0x6864 driver-record
        # prefix (a structural marker), not merely a 0x7622/0x7632 byte pair
        # somewhere in the payload.
        is_g2 = False
        if len(data) >= 4:
            lead = struct.unpack(">H", data[:2])[0]
            lead2 = struct.unpack(">H", data[1:3])[0]
            if lead == 0x6864 or lead2 == 0x6864:
                is_g2 = True

        if is_g2:
            _log.debug("TREP 02: G2 RecordArray format detected, delegating to structured parser")
            from core.parser.record_array import parse_g2_trep02_activities
            parse_g2_trep02_activities(data, results)
            return

        if len(data) < 110:
            _log.debug("TREP 02: data too short for G1 parsing (len=%d)", len(data))
            return

        # Emergency heuristic path: the deterministic count-prefixed layout
        # (Annex 1B §2.2.6.2) did not validate. Timestamp-scan is a last resort
        # for non-standard/corrupt downloads; flag its output as inferred.
        # Emergency heuristic path: the deterministic count-prefixed layout
        # (Annex 1B §2.2.6.2) did not validate. Timestamp-scan is a last resort
        # for non-standard/corrupt downloads; flag its output as inferred only
        # if it actually recovers records (measured by delta below).
        _heur_before = (len(results.get("activities") or []),
                        len(results.get("inserted_drivers") or []))

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
                # Regex-scraped from the payload, not read from a spec offset.
                "confidence": "low",
            })

        _log.debug("TREP 02: structured G1 parse — driver=%s, scanning for daily records from offset %d",
                   redact(f"{surname_s} {firstname_s}"), card_start)

        # Attempt daily record boundary detection: look for 0x7622/0x7632 markers
        daily_boundaries = []
        for m in re.finditer(rb'(\x76\x22|\x76\x32)', data[card_start:]):
            daily_boundaries.append(card_start + m.start())

        # Find daily activity change records within the TREP 02 payload.
        # Prioritize boundary-aligned records; fall back to timestamp-scan heuristic.
        activity_list = results.setdefault("activities", [])
        activity_map = {0: "rest", 1: "available", 2: "work", 3: "drive", 4: "break_rest"}
        scan = card_start

        if daily_boundaries:
            _log.debug("TREP 02: found %d daily record boundaries (0x7622/0x7632 markers)", len(daily_boundaries))
        else:
            _log.debug("TREP 02: no daily record boundaries found, using timestamp-scan heuristic")

        daily_count = 0
        seen_days = set()
        horizon = _newest_known_time(results)
        while scan + 10 <= len(data):
            ts = struct.unpack(">I", data[scan:scan+4])[0]
            if not (946684800 <= ts <= 4102444800):
                scan += 1
                continue
            if horizon is not None and ts > horizon:
                # A guessed day can never postdate what the file itself already
                # established (the VU records nothing after its own download).
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
                if slot == 0 and act == 0:
                    # (0, 0) terminates the change stream — must be checked
                    # BEFORE the valid-range test, which also matches (0, 0)
                    # and would otherwise emit a phantom REST change at 00:00.
                    break
                elif slot <= 1440 and 0 <= act <= 10:
                    changes_list.append({"minute": slot, "activity": activity_map.get(act, f"type_{act}")})
                else:
                    changes_list = []
                    break

            if changes_list:
                type_map = {"drive": "DRIVE", "rest": "REST", "work": "WORK",
                            "available": "AVAILABLE", "break_rest": "REST"}
                changes = [
                    {"activity": type_map.get(c.get("activity", "work"), "WORK"),
                     "time": f"{c['minute'] // 60:02d}:{c['minute'] % 60:02d}",
                     "slot": "First"}
                    for c in changes_list[:50]
                ]
                # Each recovered day is labelled with ITS OWN timestamp, not the
                # message-header timestamp: a TREP02 body/tail can carry blocks
                # from several days, and stamping them all with the local header
                # date mis-attributed foreign records to the current day.
                rec_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                day_key = (rec_dt.isoformat(),
                           tuple((c["time"], c["activity"]) for c in changes))
                if day_key not in seen_days:
                    seen_days.add(day_key)
                    activity_list.append({
                        "timestamp": rec_dt.isoformat(),
                        "date": rec_dt.strftime("%d/%m/%Y"),
                        "odometer_midnight": odo,
                        "card_inserted": bool(card_inserted),
                        "changes_count": no_changes,
                        "changes": changes,
                        "driver": f"{surname_s} {firstname_s}".strip(),
                        # Synthesized by the timestamp scan, not the spec layout.
                        "confidence": "low",
                    })
                    daily_count += 1
                skip_to = min((b for b in daily_boundaries if b > scan), default=-1)
                if skip_to > 0 and skip_to < pair_pos + 500:
                    scan = skip_to
                else:
                    scan = pair_pos
            else:
                scan += 1

        if daily_boundaries and daily_count > 0:
            boundary_pct = round(daily_count / len(daily_boundaries) * 100) if daily_boundaries else 0
            _log.debug("TREP 02: boundary-aligned parse: %d/%d records (%d%%)", daily_count, len(daily_boundaries), boundary_pct)
        elif daily_count > 0:
            _log.debug("TREP 02: timestamp-scan heuristic found %d daily records", daily_count)

        # Flag as heuristic only the field kinds that actually gained records.
        _heur_after = (len(results.get("activities") or []),
                       len(results.get("inserted_drivers") or []))
        _gained = [name for name, before, after in
                   zip(("activities", "inserted_drivers"), _heur_before, _heur_after, strict=False)
                   if after > before]
        if _gained:
            _mark_heuristic(results, "vu_activities_TREP02", _gained)
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
      previousVehicleInfo(19) + manualInputFlag(1)
      where previousVehicleInfo = vehicleRegistrationIdentification(15) +
      cardWithdrawalTime(4) (Annex 1B §2.85) and manualInputFlag is the
      enumerated ManualInputFlag of §2.66 (0 = noEntry, 1 = manualEntries).

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
                # [109:128] PreviousVehicleInfo (§2.85) — previously dropped.
                "previous_vehicle": decode_previous_vehicle_info(rec, 109),
                # Numeric flag first: bool(rec[128]) maps every non-zero byte to
                # True, which is only right for the two defined values.
                "manual_input_flag": rec[128],
                "manual_input_flag_meaning": describe_manual_input_flag(rec[128]),
                "record_complete": True,
                # Kept for backward compatibility (the day-detail view reads it).
                "manual_input": bool(rec[128]),
            })
            pos += 129

        n_ch = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        if n_ch > 5000 or pos + n_ch * 2 + 1 > len(data):
            return False
        changes = []
        invalid_changes = 0
        for i in range(n_ch):
            v = struct.unpack(">H", data[pos + i * 2:pos + i * 2 + 2])[0]
            activity = decode_activity_val(v)
            if activity is not None:
                changes.append(activity)
            else:
                # An undecodable ActivityChangeInfo is counted, never published
                # as an activity: the day still reports how many stored values
                # it could not read.
                invalid_changes += 1
        pos += n_ch * 2

        n_pl = data[pos]
        pos += 1
        if pos + n_pl * 28 + 2 > len(data):
            return False
        # EntryTypeDailyWorkPeriod (Annex 1B §2.51) assigns 0..5: 4/5 are the
        # "related time assumed by VU" pair and are just as legal as 0..3. The
        # short word keeps the historical START/END vocabulary; the meaning and
        # its assignment status travel with the record.
        from core.decoders.common import (entry_type_daily_work_period,
                                          entry_type_daily_work_period_status)
        places = []
        for _ in range(n_pl):
            rec = data[pos:pos + 28]
            ts = struct.unpack(">I", rec[18:22])[0]
            short, meaning = entry_type_daily_work_period(rec[22], "G1")
            if 946684800 <= ts <= 4102444800:
                places.append({
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "entry_type": "START" if short == "BEGIN" else "END",
                    "entry_type_meaning": meaning,
                    "entry_type_status": entry_type_daily_work_period_status(
                        rec[22], "G1"),
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
        conditions = []
        for _ in range(n_sc):
            rec = data[pos:pos + 5]
            ts = struct.unpack(">I", rec[0:4])[0]
            # Generation 1 assigns '01'/'02' (out of scope begin/end) and '03'
            # (one Ferry / Train crossing); '04' is RFU here — it must not take
            # the generation-2 "crossing end" meaning, but the record is kept
            # with its numeric code and an assignment status.
            label = specific_condition_label(rec[4], generation="G1")
            if 946684800 <= ts <= 4102444800:
                conditions.append({
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "condition": label,
                    "condition_status": ("assigned" if rec[4] in (0x01, 0x02, 0x03)
                                         else "not assigned"),
                    "type_code": rec[4],
                })
            pos += 5

        # Emit (with dedup — the message scan can revisit the same block).
        date_str = datetime.fromtimestamp(date_ts, tz=timezone.utc).strftime('%d/%m/%Y')
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
                # The insertion cycle belongs to the day whose TREP 02 message
                # carried it. Deduplication stays keyed on the record payload
                # (the consumer schema is unchanged); the day association is
                # carried explicitly so a merged download keeps it.
                iw["day_date"] = date_str
                iw["record_day"] = date_str
                existing_iw.append(iw)

        # A downloaded day with no activity change is still a downloaded day
        # (a card was absent all day, for instance): the day is emitted with an
        # empty change list instead of disappearing from the report.
        activities = results.setdefault("activities", [])
        if not any(a.get("date") == date_str and a.get("source") == "vu_trep02"
                   for a in activities if isinstance(a, dict)):
            activities.append({
                "date": date_str,
                "odometer_km": odo_midnight,
                "changes": changes,
                "changes_count": n_ch,
                "invalid_changes_count": invalid_changes,
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
    """Parse VuFaultRecord — ASN.1 (tachograph.asn:324-333), 82 bytes.

    The ``faultType`` byte is an EventFaultType read against the *generation 1*
    assignment (DDP_031: the '03'H transfer). Generation-2-only ranges such as
    the GNSS/RCM faults stay "Reserved for future use" here.
    """
    if offset + 82 > len(data):
        return None
    rec = data[offset:offset + 82]
    fault_type = rec[0]
    fault_purpose = rec[1]
    begin_ts = struct.unpack(">I", rec[2:6])[0]
    end_ts = struct.unpack(">I", rec[6:10])[0]
    # A stored fault with an unusable time is still a stored fault: the record is
    # kept with `time_status: invalid` and its raw value, never deleted. The
    # caller's structural gate decides whether the whole area looks like a
    # false-positive marker.
    return {
        "description": describe_event_fault_type(
            fault_type, False, EVENT_FAULT_VERSION_G1),
        "event_fault_version": EVENT_FAULT_VERSION_G1,
        "type_status": event_fault_type_status(fault_type, EVENT_FAULT_VERSION_G1),
        "fault_type": fault_type,
        "fault_purpose": fault_purpose,
        "begin_time_raw": begin_ts,
        "time_status": "valid" if _g1_time(begin_ts) else "invalid",
        "begin_time": _g1_time(begin_ts),
        "end_time": _g1_time(end_ts) or "N/A",
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
    return {
        "begin_time_raw": begin_ts,
        "time_status": "valid" if _g1_time(begin_ts) else "invalid",
        # Generation-1 assignment ('0A'H = Vehicle Motion Conflict from the
        # amended list; generation-2-only codes stay reserved).
        "description": describe_event_fault_type(
            evt_type, True, EVENT_FAULT_VERSION_G1),
        "event_fault_version": EVENT_FAULT_VERSION_G1,
        "type_status": event_fault_type_status(evt_type, EVENT_FAULT_VERSION_G1),
        "event_type": evt_type,
        "event_purpose": evt_purpose,
        "begin_time": _g1_time(begin_ts),
        "end_time": _g1_time(end_ts) or "N/A",
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
        before = (len(results.get("events") or []), len(results.get("faults") or []),
                  len(results.get("inserted_drivers") or []))
        _parse_trep_03_events_faults_heuristic(data, results)
        after = (len(results.get("events") or []), len(results.get("faults") or []),
                 len(results.get("inserted_drivers") or []))
        gained = [name for name, b, a in
                  zip(("events", "faults", "inserted_drivers"), before, after,
                      strict=False) if a > b]
        if gained:
            _mark_heuristic(results, "vu_events_faults_TREP03", gained)
            # A route switch must never be silent: the non-standard TREP 03
            # layout produced these records, so they are heuristic, not
            # spec-verified (metadata.heuristic_fields says the same). The
            # driver block is tracked too: a regex-recovered card holder is
            # inferred even when no event/fault was recovered at all.
            _log.warning("TREP 03 (events/faults) layout did not match Annex 1B; "
                         "heuristic scan supplied %s", ", ".join(gained))

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
        # contain at least one usable timestamp, otherwise this is a
        # false-positive message marker rather than a TREP 03 body. Individual
        # records are no longer dropped for their time: they are kept with
        # ``time_status: invalid`` and their raw value.
        total = n_faults + n_events
        usable = sum(1 for r in faults + events if r.get("time_status") == "valid")
        if total > 0 and usable == 0:
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
                    "description": describe_event_fault_type(
                        rec[0], True, EVENT_FAULT_VERSION_G1),
                    "event_fault_version": EVENT_FAULT_VERSION_G1,
                    "type_status": event_fault_type_status(
                        rec[0], EVENT_FAULT_VERSION_G1),
                    "event_type": rec[0],
                    "event_type_label": describe_event_fault_type(
                        rec[0], True, EVENT_FAULT_VERSION_G1),
                    "record_purpose": rec[1],
                    "record_purpose_label": describe_record_purpose(rec[1]),
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
        # Only the two TimeReal values are needed to keep a record: a short
        # tail is a truncated record, not a reason to fail the whole section.
        if pos + n_adj * 8 > len(data):
            return False
        adjustments = []
        for _ in range(n_adj):
            rec = data[pos:pos + 98]
            pos += 98
            old_ts = struct.unpack(">I", rec[0:4])[0] if len(rec) >= 8 else None
            new_ts = struct.unpack(">I", rec[4:8])[0] if len(rec) >= 8 else None
            # VuTimeAdjustmentRecord is 98 bytes in generation 1 (§2.120). An
            # empty variant (all-zero times) or a short body is a stored record
            # too: it is kept with its raw values, a completeness flag and every
            # uninterpreted byte instead of being dropped.
            complete = len(rec) == 98
            adjustments.append({
                "old_time": _g1_time(old_ts) if old_ts is not None else None,
                "new_time": _g1_time(new_ts) if new_ts is not None else None,
                "old_time_raw": old_ts,
                "new_time_raw": new_ts,
                "time_status": ("valid" if old_ts is not None and _g1_time(new_ts)
                                else "invalid"),
                "record_bytes": len(rec),
                "record_complete": complete,
                "raw_tail_hex": rec[8:].hex() if not complete else "",
                "workshop_name": decode_string(rec[8:44]) if complete else "",
                "workshop_address": decode_string(rec[44:80]) if complete else "",
                "workshop_card": _parse_full_card_number(rec, 80) if complete else None,
            })

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
                    "description": evt["description"],
                    "event_fault_version": evt["event_fault_version"],
                    "type_status": evt["type_status"],
                    "type_code": evt["event_type"],
                    "record_purpose": evt["event_purpose"],
                    "record_purpose_label": describe_record_purpose(evt["event_purpose"]),
                    "begin_time": evt["begin_time"],
                    "end_time": evt["end_time"],
                    "similar_events": evt["similar_events"],
                    "card_driver_begin": evt["card_driver_begin"],
                    # VuEventRecord holds FOUR FullCardNumber slots (Annex 1B
                    # Appendix 1 §2.132 / DDP_031), in this order and with the
                    # same key names the Gen2 emitter uses:
                    # driverBegin, coDriverBegin, driverEnd, coDriverEnd.
                    "card_codriver_begin": evt["card_codriver_begin"],
                    "card_driver_end": evt["card_driver_end"],
                    "card_codriver_end": evt["card_codriver_end"],
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
        seen = {(a.get("old_time"), a.get("new_time"), a.get("old_time_raw"))
                for a in existing_adj if isinstance(a, dict)}
        for a in adjustments:
            key = (a["old_time"], a["new_time"], a["old_time_raw"])
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
                drivers.append({
                    "surname": surname, "firstname": firstname,
                    "card_number": card_num, "_key": dk,
                    # Regex-scraped by the fallback, not a spec-offset read.
                    "confidence": "low",
                })

        # Attempt 1: Structured record-boundary detection (82B faults, 83B events)
        # Count-prefixed TREP 03 body: noOfVuFaults(1) at offset 0, so the first
        # VuFaultRecord starts at offset 1 — not 2 (starting at 2 read the first
        # record shifted by one byte and mislabelled the event that follows as a
        # fault). Records already present are tracked so a re-run over the same
        # results does not duplicate them. The dedup key also carries the record
        # purpose: the VU stores distinct records sharing (type, begin, end) that
        # differ only by purpose, and `_parse_trep_03_structured` keys on purpose
        # for exactly that reason (audit: BATCH8_RETROSPECTIVE_REVIEW B8-R1).
        pos = 1
        structured_count = 0
        horizon = _newest_known_time(results)
        seen_fault_keys = {
            (f.get("fault_type"), f.get("begin_time"), f.get("end_time"), f.get("fault_purpose"))
            for f in results.get("faults", []) if isinstance(f, dict)
        }
        seen_event_keys = {
            (e.get("type_code"), e.get("begin_time"), e.get("end_time"), e.get("record_purpose"))
            for e in results.get("events", []) if isinstance(e, dict)
        }
        while pos + 82 <= len(data) and structured_count < 500:
            # A record this scan synthesizes may never postdate the newest time
            # the file itself already established (see _newest_known_time).
            begin_ts = struct.unpack(">I", data[pos + 2:pos + 6])[0]
            end_ts = struct.unpack(">I", data[pos + 6:pos + 10])[0]
            in_horizon = horizon is None or (
                begin_ts <= horizon
                and not (946684800 <= end_ts <= 4102444800 and end_ts > horizon))
            if in_horizon and 0x01 <= data[pos] <= 0xFF:
                fault = _parse_vu_fault_record(data, pos)
                # A byte scan has no structural proof, so a record whose time is
                # unusable is a scanner false positive here. (The nominal
                # count-aligned path keeps such records with time_status.)
                if fault is not None and fault.get("time_status") == "valid":
                    fkey = (fault.get("fault_type"), fault.get("begin_time"), fault.get("end_time"),
                            fault.get("fault_purpose"))
                    if fkey not in seen_fault_keys:
                        seen_fault_keys.add(fkey)
                        results.setdefault("faults", []).append({**fault, "confidence": "low"})
                    pos += 82
                    structured_count += 1
                    continue
            if in_horizon and pos + 83 <= len(data):
                evt = _parse_vu_event_record(data, pos)
                # Same rule as the fault scan above: no structural proof means an
                # unusable timestamp is a false positive, not a record.
                if evt is not None and evt.get("time_status") == "valid":
                    ekey = (evt["event_type"], evt["begin_time"], evt["end_time"],
                            evt.get("event_purpose"))
                    if ekey not in seen_event_keys:
                        seen_event_keys.add(ekey)
                        results.setdefault("events", []).append({
                            "description": evt["description"],
                            "event_fault_version": evt["event_fault_version"],
                            "type_status": evt["type_status"],
                            "type_code": evt["event_type"],
                            "record_purpose": evt.get("event_purpose"),
                            "record_purpose_label": describe_record_purpose(evt.get("event_purpose")),
                            "begin_time": evt["begin_time"],
                            "end_time": evt["end_time"],
                            "similar_events": evt.get("similar_events", 0),
                            "card_driver_begin": evt.get("card_driver_begin"),
                            "confidence": "low",
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
        seen_events = {(e.get("begin_time"), e.get("type_code"))
                       for e in results.get("events", []) if isinstance(e, dict)}
        while pos + 9 < len(data) and len(results.get("events", [])) < 200:
            ev_type = data[pos]
            if 0x01 <= ev_type <= 0x0C:
                ts1 = struct.unpack(">I", data[pos + 1:pos + 5])[0]
                ts2 = struct.unpack(">I", data[pos + 5:pos + 9])[0]
                # ~73% of arbitrary 4-byte values fall inside the plausible
                # window, so the range check alone invents records; a candidate
                # dated after the horizon is rejected, not appended.
                # shortcut: past-dated false positives still pass, upgrade when a validated structural walk exists.
                within_horizon = horizon is None or (ts1 <= horizon and ts2 <= horizon)
                if within_horizon and 946684800 <= ts1 <= 4102444800 and 946684800 <= ts2 <= 4102444800:
                    tskey = (ts1, ev_type)
                    if tskey not in seen_timestamps:
                        seen_timestamps.add(tskey)
                        dt1 = datetime.fromtimestamp(ts1, tz=timezone.utc).isoformat()
                        dt2 = datetime.fromtimestamp(ts2, tz=timezone.utc).isoformat()
                        if (dt1, ev_type) not in seen_events:
                            seen_events.add((dt1, ev_type))
                            results.setdefault("events", []).append({
                                "description": describe_event(ev_type),
                                "type_code": ev_type,
                                "begin_time": dt1,
                                "end_time": dt2,
                                "driver": f"{surname} {firstname}".strip(),
                                "confidence": "low",
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
        # The block count and the exact body length already prove the structure
        # (`2 + n_blocks*64`). Only a body with slack needs the timestamp as a
        # false-positive filter: a legal block whose TimeReal is unusable keeps
        # its 60 samples instead of vanishing (structural gate, not a date gate).
        if not (946684800 <= first_ts <= 4102444800) and len(data) != 2 + n_blocks * 64:
            return

        speed_blocks = results.setdefault("speed_blocks", [])
        seen = {b.get("timestamp") for b in speed_blocks if isinstance(b, dict)}

        run_start_ts = None
        run_minutes = 0
        run_speeds = []
        run_chart_speeds = []
        prev_ts = None

        run_blocks = []

        def _flush():
            if run_start_ts is None or not run_speeds:
                return
            dt = datetime.fromtimestamp(run_start_ts, tz=timezone.utc).isoformat()
            if dt in seen:
                return
            seen.add(dt)
            speed_blocks.append({
                "timestamp": dt,
                # The published row is an aggregation the *application* derives
                # (consecutive one-minute blocks merged into a driving run); the
                # normative 64-byte VuDetailedSpeedBlocks travel underneath it
                # unchanged, so nothing the standard defines is lost here.
                "aggregation": "application (consecutive 1-minute blocks merged)",
                "time_status": "valid",
                "minutes": run_minutes,
                "average_speed_kmh": round(sum(run_speeds) / len(run_speeds), 1),
                "max_speed_kmh": max(run_speeds),
                "speeds_sample": run_speeds[:60],
                # Retain every second, including unavailable values, for the
                # GUI's day chart without expanding the regular data table.
                "_chart_speeds_kmh": run_chart_speeds,
                "blocks": list(run_blocks),
            })

        def _block_record(ts, raw_speeds, speeds):
            return {
                "begin": _g1_time(ts),
                "begin_raw": ts,
                "time_status": "valid" if _g1_time(ts) else "invalid",
                "record_bytes": 64,
                "record_complete": True,
                "samples": len(speeds),
                "max_speed_kmh": max(speeds) if speeds else None,
                "_chart_speeds_kmh": list(raw_speeds),
            }

        for i in range(n_blocks):
            blk = data[2 + i * 64:2 + (i + 1) * 64]
            ts = struct.unpack(">I", blk[0:4])[0]
            raw_speeds = [None if s == 0xFF else s for s in blk[4:64]]
            speeds = [s for s in raw_speeds if s is not None]
            if not (946684800 <= ts <= 4102444800):
                # An unusable block timestamp does not delete the samples: the
                # block is published on its own, with the raw value and a
                # status, and no fabricated date.
                _flush()
                speed_blocks.append({
                    "timestamp": None,
                    "aggregation": "normative block (no usable time)",
                    "time_status": "invalid",
                    "begin_raw": ts,
                    "minutes": 1,
                    "average_speed_kmh": (round(sum(speeds) / len(speeds), 1)
                                          if speeds else None),
                    "max_speed_kmh": max(speeds) if speeds else None,
                    "_chart_speeds_kmh": raw_speeds,
                    "blocks": [_block_record(ts, raw_speeds, speeds)],
                })
                run_start_ts = None
                prev_ts = None
                continue
            block = _block_record(ts, raw_speeds, speeds)
            if prev_ts is None or ts - prev_ts != 60:
                _flush()
                run_start_ts = ts
                run_minutes = 0
                run_speeds = []
                run_chart_speeds = []
                run_blocks = []
            run_minutes += 1
            run_speeds.extend(speeds)
            run_chart_speeds.extend(raw_speeds)
            run_blocks.append(block)
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

            Every record the count declares is decoded: the regulation makes an
            *activation* calibration legal with the parameters "known at VU
            activation", i.e. an empty VIN and ``lTyreCircumference`` 0. The old
            acceptance gate ("17 alphanumeric VIN chars" and ``0 < l``) therefore
            deleted a real normative record from the download. Field-level
            plausibility is reported through ``vin_status``/``field_status``
            instead of discarding the record.
            """
            vin = decode_string(chunk[95:112], is_id=True)
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
            # Full TimeReal companions: the shortened ``timestamp``/``old_time``
            # keys stay calendar days for the existing table, while the exact
            # hour/minute survives here.
            old_time_iso = _g1_time(struct.unpack(">I", chunk[155:159])[0])
            new_time_iso = _g1_time(struct.unpack(">I", chunk[159:163])[0])
            next_cal_iso = _g1_time(struct.unpack(">I", chunk[163:167])[0])
            field_status = {}
            if not vin:
                field_status["vin"] = "empty (activation parameters)"
            if l_const == 0:
                field_status["l_tyre_circumference"] = (
                    "zero (activation, parameters known at VU activation)")
            if w_const == 0 or w_const == 0xFFFF:
                field_status["w_constant"] = f"implausible raw 0x{w_const:04X}"
            if old_time_iso is None:
                field_status["old_time"] = "TimeReal outside the calendar"
            return {
                # The record identity no longer depends on a non-empty VIN: an
                # activation record is keyed by its purpose and raw times too.
                "_key": (f"{vin}|{old_time_iso}|{workshop_name}|{old_odo}|"
                         f"{purpose}|{old_time_iso and chunk[155:159].hex()}"),
                # No ``confidence`` key: this record came from the normative
                # 167-byte layout. The repo convention is that only synthesized
                # records carry a low-confidence marker (see
                # docs/developer/normative-completion.md §3).
                "decode_path": "normative (167-byte VuCalibrationRecord)",
                "vin_status": ("empty (activation parameters)" if not vin
                               else "present"),
                "field_status": field_status,
                "old_time_iso": old_time_iso,
                "new_time_iso": new_time_iso,
                "next_calibration_iso": next_cal_iso,
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
            # Every declared record is decoded above; ``structure_fits`` (the
            # exact 167-byte stride against the body length) is the structural
            # proof that this is the calibration area, so no record is dropped
            # for its field values.
            if True:
                vu_info = results.setdefault("vu_info", {})
                vu_info["manufacturer"] = mfr
                if addr:
                    vu_info["manufacturer_address"] = addr
                part_number = decode_string(data[72:88], is_id=True)
                if part_number:
                    vu_info["part_number"] = part_number
                # vuSerialNumber / sensorSerialNumber are ExtendedSerialNumber
                # values (Annex 1B §2.56): the historical upper-case hex stays and
                # the structured reading is added next to it by the same helper
                # the generation-2 records use (no duplicated implementation).
                from core.parser.vu_dispatcher import decode_extended_serial_number
                vu_info["serial_number"] = data[88:96].hex().upper()
                vu_info["serial"] = decode_extended_serial_number(data, 88)
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
                vu_info["sensor_serial"] = decode_extended_serial_number(data, 116)
                vu_info["sensor_pairing_date_iso"] = _g1_time(
                    struct.unpack(">I", data[132:136])[0])
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
        # Records this heuristic branch adds carry inferred purpose/timestamp/
        # workshop (B-F8/XB-F2); count them so the fields actually gained can be
        # flagged heuristic, exactly like the TREP 02/03/06 fallbacks.
        _cal_before = len(cal_records)

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
                    # Reconstructed by VIN regex + fixed-offset guesswork, not
                    # by the 167-byte VuCalibrationRecord layout above.
                    "confidence": "low",
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

        # Flag the fields this inference branch actually gained as heuristic so
        # the GUI/CLI cannot present inferred calibration purpose/date/workshop
        # as decoded fact (B-F8/XB-F2).
        if len(cal_records) > _cal_before:
            _mark_heuristic(results, "vu_technical_TREP05", ["calibrations"])
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 05 technical parse failed: %s", exc)

def _parse_trep_06_card_download(data, results):
    """Parse TREP 06 (Card Download) — a full driver-card image embedded in the
    VU download (Annex 1B §2.2.6.6).

    Primary path is deterministic: the body is a STAP stream of the card's
    Elementary Files (0x0501 App Id, 0x0502 Events, 0x0503 Faults, 0x0504
    activities, 0x0520 Identification …), walked by the card parser so every EF
    is decoded through its registered decoder. Regex/timestamp scanning runs
    ONLY as an emergency fallback when the structural walk recovers nothing.
    """
    import re
    try:
        if len(data) < 20:
            return

        # ── Primary: deterministic walk of the embedded card image ──
        before_keys = {k: len(results.get(k) or []) for k in
                       ("events", "faults", "activities", "inserted_drivers")}
        driver_before = dict(results.get("driver") or {})
        _decode_embedded_card_image(data, results)
        recovered = (
            any(len(results.get(k) or []) > before_keys[k] for k in before_keys)
            or (results.get("driver") or {}) != driver_before
        )
        if recovered:
            return

        # ── Emergency fallback: heuristic scan (non-standard/corrupt images) ──
        downloads = results.setdefault("card_downloads", [])
        _dl_before = len(downloads)
        _drv_before = len(results.get("inserted_drivers") or [])

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
                # Regex/timestamp scan, not the card-EF walk.
                "confidence": "low",
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
                    drivers.append({
                        "surname": s, "firstname": f, "card_number": "",
                        "_key": dk,
                        # Regex-scraped from a non-standard card image.
                        "confidence": "low",
                    })

        gained = []
        if len(downloads) > _dl_before:
            gained.append("card_downloads")
        if len(results.get("inserted_drivers") or []) > _drv_before:
            gained.append("inserted_drivers")
        if gained:
            _mark_heuristic(results, "vu_card_download_TREP06", gained)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("TREP 06 card download parse failed: %s", exc)


def _decode_embedded_card_image(data, results):
    """Structurally decode a card-EF image embedded in a G1 VU CardDownload.

    Runs the deterministic STAP/BER walk over *data* into a scratch result,
    then merges the decoded semantic keys into the live *results*. This turns
    the previously-opaque card download blob into fully decoded EFs.
    """
    try:
        from core.parser.deterministic import DeterministicParser
    except Exception as exc:
        _log.debug("Embedded card image: parser unavailable: %s", exc)
        return

    try:
        dp = DeterministicParser()
        sub = dp.parse(bytes(data), is_vu=False)
    except Exception as exc:
        _log.debug("Embedded card image walk failed: %s", exc)
        return

    _merge_card_download(results, sub)


# Semantic keys produced by card EF decoders worth merging up from an embedded
# card image.  Lists are extended (deduped); dict/scalar keys fill only when the
# live result is still empty/N-A so a real VU value is never overwritten.
#
# The keys are derived automatically from the public TachoResult dataclass: every
# field whose type is List[...] or Dict[...] is eligible unless it is
# infrastructure metadata, clearly VU-only, Gen 2.2–only, or dead.  This means a
# new card-side decoder that sets a matching TachoResult key is merged without
# any manual allowlist update.

def _derive_card_merge_keys():
    from core.registry.models import TachoResult

    _EXCLUDED = frozenset({
        # Infrastructure / view-only keys
        "metadata", "raw_tags", "coverage", "sections", "generations",
        # VU-only list keys (never produced by a card EF decoder)
        "card_numbers", "card_iw_records", "company_locks",
        "overspeeding_events", "overspeeding_control",
        "time_adjustments", "sensor_daily_records",
        "inserted_drivers", "workshops", "calibration_vins",
        "speed_blocks", "vu_certificates", "vu_identifications",
        "card_records", "download_activities", "downloadable_periods",
        "its_consents", "power_interruptions", "sensor_pairings",
        "sensor_gnss_couplings", "vu_record_arrays", "vu_controller",
        "signed_daily_records", "sensor_faults", "time_adj_gnss",
        # VU-only dict keys
        "company_info", "vu_overview", "vu_info",
        "sensor_info", "previous_vehicle",
        "signature_verification", "certificate_temporal_validity",
        # Verification metadata, not actual card data to merge
        "ef_signature_verification",
        # Gen 2.2–only fields (card_g22.py decoders — never in a G1 card download)
        "gnss_ad_records", "load_unload_records", "trailer_registrations",
        "gnss_places", "load_sensor_data", "border_crossings",
        "gnss_auth", "load_unload_auth",
        # Dead / never produced by any card EF decoder
        "locations",
    })

    list_keys = []
    dict_keys = []

    for name, fdef in TachoResult.__dataclass_fields__.items():
        if name in _EXCLUDED:
            continue
        origin = typing.get_origin(fdef.type)
        if origin is list:
            list_keys.append(name)
        elif origin is dict:
            dict_keys.append(name)

    return tuple(list_keys), tuple(dict_keys)

_CARD_MERGE_LIST_KEYS, _CARD_MERGE_DICT_KEYS = _derive_card_merge_keys()


def _merge_card_download(results, sub):
    """Merge decoded EFs from an embedded card image into the VU results."""
    for key in _CARD_MERGE_LIST_KEYS:
        incoming = sub.get(key)
        if not isinstance(incoming, list) or not incoming:
            continue
        target = results.setdefault(key, [])
        if not isinstance(target, list):
            continue
        existing = {repr(item) for item in target}
        for item in incoming:
            if repr(item) not in existing:
                target.append(item)
                existing.add(repr(item))

    for key in _CARD_MERGE_DICT_KEYS:
        incoming = sub.get(key)
        if not isinstance(incoming, dict):
            continue
        target = results.setdefault(key, {})
        if not isinstance(target, dict):
            continue
        for field, value in incoming.items():
            if value in (None, "", "N/A"):
                continue
            if field not in target or target[field] in (None, "", "N/A"):
                target[field] = value

    # Preserve the embedded card's raw tag occurrences so the Raw/Unparsed and
    # coverage views account for what the download actually contained. Offsets
    # in the sub-parse are relative to the CardDownload body, so keep them under
    # a namespaced key rather than merging into the file-level "Unparsed Data".
    sub_raw = sub.get("raw_tags")
    if isinstance(sub_raw, dict) and sub_raw:
        live_raw = results.setdefault("raw_tags", {})
        for key, occs in sub_raw.items():
            if not occs:
                continue
            if key in ("Padding",):
                continue
            merged_key = (key if key not in live_raw
                          else f"CardDownload > {key}")
            for occ in occs:
                if isinstance(occ, dict):
                    occ.setdefault("container", "0x7606 CardDownload")
                    occ["offset_scope"] = "relative to CardDownload body"
            live_raw.setdefault(merged_key, []).extend(occs)


# ── G1 Sensor Download (0x7611) ────────────────────────────────────────────

_SENSOR_ID_SIZE = 168


def _parse_sensor_download(body, results):
    """Parse a G1 extended sensor-download payload (TREP 0x11 / 0x7611).

    **This layout is not normative.** No Annex 1B or Annex 1C structure
    describes a "sensor download": the earlier claim that Annex 1B §4.5.3.2.1
    defines it was wrong — Annex 1B §4.5.3 is "Stored data integrity", and the
    §4.5.3.2.x numbering that exists belongs to Annex 1C *card* EF layouts
    (§4.5.3.2.1 is "Application identification", a file of the tachograph
    application, not this payload). The section is a manufacturer extension
    that happens to occur on some units.

    What is decoded below is therefore an *empirical* reading of that
    proprietary payload, kept because the values are real data the VU stored:
      0-16   TOC header (17 bytes — layout not documented)
      17..   FF padding
      N..N+167  Sensor ID block (168 bytes):
        [0:4]    first_date TimeReal
        [4:8]    last_date  TimeReal
        [8:10]   param_a    UInt16
        [10:12]  param_b    UInt16
        [12:14]  param_c    UInt16
        [14:16]  param_d    UInt16
        [16:28]  reserved   (zeros)
        [28:100] padding    (FF / zeros)
        [100]    approval_prefix (0x01)
        [101]    approval_nation NationNumeric
        [102:118] approval_number (16 bytes ASCII)
      N+168..  Daily timestamp records:
        Each day: midnight_ts(4) + first_event_ts(4) + speed_data(variable)
        Days are separated by FF padding runs.
    Every field recovered from it is labelled ``confidence: low`` in the
    record and in the JSON export, so an empirically-read field kind is never
    presented as a standard-conformant one. Raw bytes are untouched
    (``raw_tags`` still carries the original payload).

    It is deliberately **not** declared as a heuristic fallback
    (``metadata.heuristic_fields`` + WARNING): a valid download did not fall
    back from anything here — TRTP 11..1F are manufacturer-specific, so no
    normative layout exists that could have failed. The low-confidence marker
    carries the uncertainty; the "recovered heuristically" banner would be a
    false alarm on a healthy file.
    """
    if len(body) < _SENSOR_ID_SIZE + 20:
        return
    try:
        _decode_sensor_block(body, results, offset=0)
    except Exception as exc:
        _log.debug("Sensor download parse failed: %s", exc)


def _decode_sensor_block(body, results, offset=0):
    """Decode one copy of the sensor data starting at *offset*."""
    n = len(body)
    pos = offset + 17  # skip TOC header
    while pos < n and body[pos] == 0xFF:
        pos += 1

    if pos + _SENSOR_ID_SIZE > n:
        return

    block = body[pos:pos + _SENSOR_ID_SIZE]

    ts_first = struct.unpack(">I", block[0:4])[0]
    ts_last = struct.unpack(">I", block[4:8])[0]

    serial_bytes = block[100:118]
    approval_prefix = serial_bytes[0]
    approval_nation = get_nation(serial_bytes[1]) if len(serial_bytes) > 1 else ""
    approval_number = ""
    try:
        raw = serial_bytes[2:18]
        end = raw.find(b'\x00')
        if end >= 0:
            raw = raw[:end]
        approval_number = raw.decode("ascii", errors="replace").strip()
    except Exception:
        approval_number = ""

    # Empirically mapped field kinds of a non-normative payload: see the
    # docstring of _parse_sensor_download. Every value here is low confidence.
    sensor_info = {
        "confidence": "low",
        "sensor_approval": approval_number,
        "approval_nation": approval_nation,
        "approval_prefix": f"0x{approval_prefix:02X}",
        "first_date": datetime.fromtimestamp(ts_first, tz=timezone.utc).strftime("%Y-%m-%d") if 946684800 <= ts_first <= 4102444800 else "N/A",
        "last_date": datetime.fromtimestamp(ts_last, tz=timezone.utc).strftime("%Y-%m-%d") if 946684800 <= ts_last <= 4102444800 else "N/A",
        "param_speed_max_kmh": struct.unpack(">H", block[10:12])[0],
        "param_speed_avg_kmh": struct.unpack(">H", block[12:14])[0],
        "param_distance_km": struct.unpack(">H", block[14:16])[0],
    }
    # Gate on plausibility: a false 0x76 0x11 marker inside another section's
    # payload would otherwise publish garbage (e.g. 25284 km/h, non-printable
    # approval text). Drop the whole block when it fails the sanity check.
    from core.decoders.validators import is_plausible_sensor_info
    if not is_plausible_sensor_info(sensor_info):
        _log.debug("Sensor block at offset %d dropped: implausible values %s",
                   offset, sensor_info)
        results.setdefault("_suspect_sections", set())
        if isinstance(results["_suspect_sections"], set):
            results["_suspect_sections"].add(0x11)
        return

    results.setdefault("sensor_info", {}).update(sensor_info)

    # Daily timestamp records
    daily_start = pos + _SENSOR_ID_SIZE
    daily = _extract_sensor_daily_records(body, daily_start, offset, n)
    if daily:
        existing = results.get("sensor_daily_records") or []
        existing.extend(daily)
        results["sensor_daily_records"] = existing


def _extract_sensor_daily_records(body, start, copy_start, copy_end):
    """Extract daily timestamp + speed records from the sensor body.

    *Empirical* per-day reading of the same non-normative manufacturer payload
    (see :func:`_parse_sensor_download`): no regulation defines these blocks, so
    each record is labelled ``confidence: low``.

    Each daily block:
      [0:4]   midnight_ts   TimeReal (seconds, divisible by 86400)
      [4:8]   first_event   TimeReal  
      [8:10]  speed_count   UInt16 BE (number of 1-byte speed samples)
      [10:]   speed_samples UInt8[count] (km/h, 0-255; values > 200 are RFU)
    Blocks are separated by FF padding.
    """
    seen = set()
    records = []
    pos = start
    end = min(copy_end, len(body))
    while pos + 10 <= end:
        while pos + 10 <= end and body[pos] == 0xFF:
            pos += 1
        if pos + 10 > end:
            break
        ts_midnight = struct.unpack(">I", body[pos:pos + 4])[0]
        ts_event = struct.unpack(">I", body[pos + 4:pos + 8])[0]
        if not (946684800 <= ts_midnight <= 4102444800):
            pos += 1
            continue
        if ts_midnight % 86400 != 0:
            pos += 4
            continue
        count = struct.unpack(">H", body[pos + 8:pos + 10])[0]
        if count > 1500:  # max 25 hours at 1/min
            pos += 8
            continue
        speed_end = pos + 10 + count
        if speed_end > end:
            break
        speeds = list(body[pos + 10:speed_end])
        valid = [s for s in speeds if s <= 200]
        date_str = datetime.fromtimestamp(ts_midnight, tz=timezone.utc).strftime("%Y-%m-%d")
        if date_str not in seen:
            seen.add(date_str)
            records.append({
                "confidence": "low",
                "date": date_str,
                "first_event": datetime.fromtimestamp(ts_event, tz=timezone.utc).isoformat()
                if 946684800 <= ts_event <= 4102444800 else None,
                "speed_samples": count,
                "speed_min": min(valid) if valid else None,
                "speed_max": max(valid) if valid else None,
                "speed_avg": round(sum(valid) / len(valid), 1) if valid else None,
                "speed_valid_count": len(valid),
            })
        pos = speed_end
    return records
