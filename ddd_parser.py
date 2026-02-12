import struct
import os
import json
import mmap
import string
from datetime import datetime, timezone

try:
    from geocoding_engine import process_locations_with_geocoding
    GEOCODING_AVAILABLE = True
except ImportError:
    GEOCODING_AVAILABLE = False

from signature_validator import SignatureValidator

class TachoParser:
    """
    Professional analysis engine for Tachograph files (.DDD).
    Version 5.0 - Forensic Security Edition (Certification Chain & Integrity)
    """
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        self.raw_data = None
        self._fd = None
        self.validator = SignatureValidator()
        self.bytes_covered = 0
        self.card_public_key = None
        self.msca_cert_raw = None
        self.card_cert_raw = None
        self.validation_status = "Pending"
        self.results = {
            "metadata": {
                "filename": os.path.basename(file_path),
                "generation": "Unknown",
                "parsed_at": datetime.now().isoformat(),
                "integrity_check": "Pending",
                "file_size_bytes": self.file_size,
                "coverage_pct": 0.0
            },
            "driver": {
                "card_number": "N/A",
                "surname": "N/A",
                "firstname": "N/A",
                "birth_date": "N/A",
                "expiry_date": "N/A",
                "issuing_nation": "N/A",
                "preferred_language": "N/A",
                "licence_number": "N/A",
                "licence_issuing_nation": "N/A"
            },
            "vehicle": {
                "vin": "N/A", 
                "plate": "N/A",
                "registration_nation": "N/A"
            },
            "activities": [],
            "vehicle_sessions": [],
            "events": [],
            "faults": [],
            "locations": [],
            "places": [],
            "calibrations": [],
            "raw_tags": {},
            "signatures": []
        }
        self.TAGS = self._load_tags()

    def _load_tags(self):
        """Load tags from JSON file and merge with internal defaults."""
        tags = {
            # === VU (Vehicle Unit) download tags ===
            0x0001: "VU_VehicleIdentification",
            0x0002: "EF_ICC",  # Card ICC data (or VU VehicleRegistration in VU files)
            0x0005: "EF_IC",   # Card IC data
            # === G2 card tags (DF_Tachograph_G2 via APDU / older mapping) ===
            0x0101: "G2_CardIccIdentification",
            0x0102: "G2_CardIdentification",
            0x0103: "G2_CardCertificate",
            0x0104: "G2_MemberStateCertificate",
            0x0201: "G2_DriverCardHolderIdentification",
            # === G1 Driver Card tags (DF_Tachograph, Annex 1B) ===
            0x0501: "G1_CardIccIdentification",
            0x0502: "G1_EventsData",            # EF_Events_Data (NOT CardIdentification!)
            0x0503: "G1_FaultsData",             # EF_Faults_Data
            0x0504: "G1_DriverActivityData",     # EF_Driver_Activity_Data (cyclic buffer)
            0x0505: "G1_VehiclesUsed",           # EF_Vehicles_Used (31-byte records)
            0x0506: "G1_Places",                 # EF_Places
            0x0507: "G1_CurrentUsage",           # EF_Current_Usage (session open)
            0x0508: "G1_ControlActivityData",    # EF_Control_Activity_Data
            0x050C: "CalibrationData",
            0x050E: "G1_CardDownload",           # EF_Card_Download
            0x0520: "G1_Identification",         # EF_Identification (card#, holder name, birth)
            0x0521: "G1_DrivingLicenceInfo",     # EF_Driving_Licence_Info
            0x0522: "G1_SpecificConditions",     # EF_Specific_Conditions
            0x0523: "G2_VehiclesUsed",           # EF_Vehicles_Used (G2, under DF_Tachograph_G2)
            0x0524: "G2_DriverActivityData",     # EF_Driver_Activity_Data (G2)
            0x0206: "VU_ActivityDailyRecord",
            0x0222: "EF_GNSS_Places",
            0x0223: "EF_GNSS_Accumulated_Position",
            0xC100: "G1_CardCertificate",
            0xC108: "G1_CA_Certificate",
            0xC101: "G2_CardCertificate",
            0xC109: "G2_CA_Certificate"
        }
        
        json_path = os.path.join(os.path.dirname(os.path.dirname(self.file_path)), 'all_tacho_tags.json')
        if not os.path.exists(json_path):
             json_path = 'all_tacho_tags.json'
             
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    extra_tags = json.load(f)
                    for k, v in extra_tags.items():
                        tags[int(k, 16)] = v
            except Exception:
                pass
        return tags

    def _get_nation(self, code):
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

    def _decode_string(self, data, is_id=False):
        """Decode binary string handling CodePage byte (Annex 1B/1C)."""
        if not data: return ""
        try:
            # Handle FF/00 padding
            data = data.rstrip(b'\x00\xff')
            if not data: return ""

            # Check for CodePage byte (0x01 to 0x10)
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
                # IDs must be alphanumeric ASCII
                return "".join(c for c in decoded if (c.isalnum() or c == ' ') and ord(c) < 128).strip().upper()
            
            # General strings: remove non-printable except spaces
            return "".join(c for c in decoded if c.isprintable()).strip()
        except Exception:
            return ""

    def _decode_date(self, data):
        """Decode TimeReal (4 bytes) or Datef (4 bytes)."""
        if len(data) < 4: return "N/A"
        try:
            ts = struct.unpack(">I", data[:4])[0]
            if ts == 0 or ts == 0xFFFFFFFF: return "N/A"
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%d/%m/%Y')
        except (struct.error, ValueError, OverflowError):
            return "N/A"

    def _decode_activity_val(self, val):
        """Decode 2-byte activityChangeInfo."""
        slot = (val >> 15) & 1
        crew = (val >> 14) & 1
        card = (val >> 13) & 1
        act_code = (val >> 11) & 3
        mins = val & 0x07FF
        acts = {0: "RIPOSO", 1: "DISPONIBILITÀ", 2: "LAVORO", 3: "GUIDA"}
        return {
            "tipo": acts.get(act_code, "SCONOSCIUTO"),
            "ora": f"{mins // 60:02d}:{mins % 60:02d}",
            "slot": "Secondo" if slot else "Primo"
        }

    def _safe_read(self, pos, length):
        if pos < 0 or length < 0 or (pos + length) > self.file_size:
            return None
        try:
            return self.raw_data[pos : pos + length]
        except Exception:
            return None

    def get_coverage_report(self):
        """Returns the percentage of bytes assigned to identified fields."""
        if self.file_size == 0: return 0.0
        return round((self.bytes_covered / self.file_size) * 100, 2)

    def _parse_g1_identification(self, val):
        """EF_Identification (0x0520) for G1 driver cards. Annex 1B compliant.
        
        Structure (143 bytes):
          CardIdentification (65 bytes):
            cardIssuingMemberState    NationNumeric    1
            cardNumber                CardNumber       16
            cardIssuingAuthorityName  Name             36
            cardIssueDate             TimeReal         4
            cardValidityBegin         TimeReal         4
            cardExpiryDate            TimeReal         4
          DriverCardHolderIdentification (78 bytes):
            holderSurname             Name             36
            holderFirstNames          Name             36
            cardHolderBirthDate       TimeReal/Datef   4
            cardHolderPreferredLanguage                 2
        """
        if len(val) < 65: return
        
        off = 0
        self.results["driver"]["issuing_nation"] = self._get_nation(val[off]); off += 1
        self.results["driver"]["card_number"] = self._decode_string(val[off:off+16], is_id=True); off += 16
        # cardIssuingAuthorityName (36 bytes) - skip
        off += 36
        # cardIssueDate (4), cardValidityBegin (4)
        off += 4 + 4
        self.results["driver"]["expiry_date"] = self._decode_date(val[off:off+4]); off += 4
        
        # DriverCardHolderIdentification (78 bytes)
        if len(val) >= off + 78:
            self.results["driver"]["surname"] = self._decode_string(val[off:off+36]); off += 36
            self.results["driver"]["firstname"] = self._decode_string(val[off:off+36]); off += 36
            self.results["driver"]["birth_date"] = self._decode_date(val[off:off+4]); off += 4
            self.results["driver"]["preferred_language"] = self._decode_string(val[off:off+2]); off += 2

    def _parse_g1_driving_licence(self, val):
        """EF_Driving_Licence_Info (0x0521) for G1 driver cards.
        
        Structure (53 bytes):
            drivingLicenceIssuingAuthority  Name             36
            drivingLicenceIssuingNation     NationNumeric    1
            drivingLicenceNumber                             16
        """
        if len(val) < 53: return
        self.results["driver"]["licence_issuing_nation"] = self._get_nation(val[36])
        self.results["driver"]["licence_number"] = self._decode_string(val[37:53], is_id=True)

    def _parse_g1_vehicles_used(self, val):
        """EF_Vehicles_Used (0x0505) for G1 driver cards. Annex 1B compliant.
        
        Structure:
            vehiclePointerNewestRecord  2 bytes
            cardVehicleRecords          N x 31 bytes:
                vehicleOdometerBegin    OdometerShort    3
                vehicleOdometerEnd      OdometerShort    3
                vehicleFirstUse         TimeReal         4
                vehicleLastUse          TimeReal         4
                vehicleRegistration:
                    nation              NationNumeric    1
                    codePage                             1
                    vehicleRegNumber                     13
                vuDataBlockCounter                       2
        """
        if len(val) < 4: return
        rec_size = 31
        rec_data = val[2:]  # skip 2-byte pointer
        
        for i in range(len(rec_data) // rec_size):
            chunk = rec_data[i*rec_size:(i+1)*rec_size]
            if len(chunk) < rec_size: break
            
            odo_begin = int.from_bytes(chunk[0:3], byteorder='big')
            odo_end = int.from_bytes(chunk[3:6], byteorder='big')
            first_use_ts = struct.unpack(">I", chunk[6:10])[0]
            last_use_ts = struct.unpack(">I", chunk[10:14])[0]
            
            # Bug Fix 2: Odometer Overflow (0xFFFFFF = missing/null)
            if odo_begin == 0xFFFFFF: odo_begin = None
            if odo_end == 0xFFFFFF: odo_end = None

            if first_use_ts == 0 or first_use_ts == 0xFFFFFFFF: continue
            
            # Bug Fix 1: Future Date (2106 / open sessions)
            # If last_use_ts > current year (2026), it's considered an "Open Session"
            end_date = "Sessione Aperta"
            if last_use_ts != 0xFFFFFFFF and last_use_ts <= 1798758400: # 1798758400 approx end of 2026
                 try:
                     end_date = datetime.fromtimestamp(last_use_ts, tz=timezone.utc).isoformat()
                 except (ValueError, OverflowError, OSError):
                     pass
            
            # Distance calculation fix
            distance = 0
            if odo_begin is not None and odo_end is not None:
                distance = odo_end - odo_begin

            nation = self._get_nation(chunk[14])
            plate = self._decode_string(chunk[15:29], is_id=True)
            
            try:
                self.results["vehicle_sessions"].append({
                    "vehicle_plate": plate,
                    "vehicle_nation": nation,
                    "start": datetime.fromtimestamp(first_use_ts, tz=timezone.utc).isoformat(),
                    "end": end_date,
                    "odometer_begin": odo_begin,
                    "odometer_end": odo_end,
                    "distance": distance
                })
            except (ValueError, OverflowError, OSError):
                continue

    def _parse_g1_current_usage(self, val):
        """EF_Current_Usage (0x0507) for G1 driver cards.
        
        Structure (19 bytes):
            sessionOpenTime         TimeReal              4
            sessionOpenVehicle:
                nation              NationNumeric         1
                codePage                                  1
                vehicleRegNumber                          13
        """
        if len(val) < 19: return
        try:
            ts = struct.unpack(">I", val[0:4])[0]
            
            # Bug Fix 1: Future Date (2106)
            # If sessionOpenTime is in the future (> 2026), skip or handle as open
            if ts == 0 or ts == 0xFFFFFFFF or ts > 1798758400:
                return

            nation = self._get_nation(val[4])
            plate = self._decode_string(val[5:19], is_id=True)
            self.results["vehicle"]["plate"] = plate
            self.results["vehicle"]["registration_nation"] = nation
        except Exception:
            pass

    def _parse_card_identification(self, val):
        """G2 CardIdentification (0x0102). Decodes fields per Annex 1C."""
        if len(val) < 23: return
        self.results["driver"]["issuing_nation"] = self._get_nation(val[0])
        self.results["driver"]["card_number"] = self._decode_string(val[1:17], is_id=True)
        self.results["driver"]["expiry_date"] = self._decode_date(val[19:23])

    def _parse_driver_card_holder_identification(self, val):
        """G2 DriverCardHolderIdentification (0x0201). Decodes fields per Annex 1C."""
        if len(val) < 78: return
        self.results["driver"]["surname"] = self._decode_string(val[0:36])
        self.results["driver"]["firstname"] = self._decode_string(val[36:72])
        self.results["driver"]["birth_date"] = self._decode_date(val[72:76])
        self.results["driver"]["preferred_language"] = self._decode_string(val[76:78])

    def _parse_calibration_data(self, val):
        """EF_Calibration (0x050C). Decodes technical parameters."""
        # cyclic record size: 105 bytes (Annex 1B) or 161 (Annex 1C/G2)
        if len(val) < 105: return
        try:
            # Usually preceded by 2 bytes pointer
            ptr = struct.unpack(">H", val[0:2])[0]
            data = val[2:]
            
            # Identification of record size by total length
            rec_size = 105 # G1 default
            if len(data) % 161 == 0:
                rec_size = 161 # G2
                
            for i in range(0, len(data) - rec_size + 1, rec_size):
                chunk = data[i:i+rec_size]
                
                # purpose (1), vin (17), nation (1), plate (14), w (2), k (2), l (2), tyre (15), speed (1), odo (3), time (4)...
                purpose_code = chunk[0]
                old_vin = self._decode_string(chunk[1:18], is_id=True)
                old_nation_code = chunk[18]
                old_plate = self._decode_string(chunk[19:33], is_id=True)
                
                w = struct.unpack(">H", chunk[33:35])[0]
                k = struct.unpack(">H", chunk[35:37])[0]
                l = struct.unpack(">H", chunk[37:39])[0]
                tyre_circ = self._decode_string(chunk[39:54]) # TyreSize
                speed_limit = chunk[54]
                odo_val = int.from_bytes(chunk[55:58], byteorder='big')
                if odo_val == 0xFFFFFF: odo_val = None
                
                # If it's a newer record, it might contain the updated VIN/Plate
                # For G1, we focus on the core parameters
                self.results["calibrations"].append({
                    "purpose_code": purpose_code,
                    "vin_at_calibration": old_vin,
                    "plate_at_calibration": old_plate,
                    "nation_at_calibration": self._get_nation(old_nation_code),
                    "w_characteristic_constant": w,
                    "k_constant": k,
                    "l_tyre_circumference": l,
                    "tyre_size": tyre_circ,
                    "speed_limit": speed_limit,
                    "odometer_value": odo_val
                })
        except Exception:
            pass

    def _parse_vehicle_used(self, val):
        if len(val) < 2: return
        try:
            # Each record is 31 bytes per Annex 1B G1 specifications
            rec_size = 31
            data = val[2:]
            for i in range(0, len(data) - rec_size + 1, rec_size):
                chunk = data[i:i+rec_size]
                # vehicleFirstUse: offset 0 (4 bytes, TimeReal)
                begin_ts = struct.unpack(">I", chunk[0:4])[0]
                # vehicleLastUse: offset 4 (4 bytes, TimeReal)
                end_ts = struct.unpack(">I", chunk[4:8])[0]
                
                if begin_ts == 0 or begin_ts == 0xFFFFFFFF: continue
                
                # vehicleRegistrationNumber: offset 9 (14 bytes: 1 byte CodePage + 13 bytes Plate)
                # Offset 8 in chunk is the nation (part of VRN structure usually or separate field)
                # In G1 Annex 1B, VRN starts at offset 9 with CodePage
                nation = self._get_nation(chunk[8])
                plate = self._decode_string(chunk[9:23], is_id=True)
                
                # vehicleOdometerBegin: offset 23 (3 bytes, Big-Endian)
                odo_begin = int.from_bytes(chunk[23:26], byteorder='big')
                # vehicleOdometerEnd: offset 26 (3 bytes, Big-Endian)
                odo_end = int.from_bytes(chunk[26:29], byteorder='big')
                
                # Bug Fix 2: Odometer Overflow (0xFFFFFF = missing/null)
                if odo_begin == 0xFFFFFF: odo_begin = None
                if odo_end == 0xFFFFFF: odo_end = None

                # Bug Fix 1: Future Date (2106 / open sessions)
                # If end_ts > current year (2026), it's considered an "Open Session"
                end_date = "Sessione Aperta"
                if end_ts != 0xFFFFFFFF and end_ts <= 1798758400: # 1798758400 approx end of 2026
                     try:
                         end_date = datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()
                     except (ValueError, OverflowError, OSError):
                         pass
                
                # Distance calculation fix
                distance = 0
                if odo_begin is not None and odo_end is not None:
                    distance = odo_end - odo_begin

                self.results["vehicle_sessions"].append({
                    "vehicle_plate": plate,
                    "vehicle_nation": nation,
                    "start": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat(),
                    "end": end_date,
                    "odometer_begin": odo_begin,
                    "odometer_end": odo_end,
                    "distance": distance
                })
        except Exception:
            pass

    def _parse_cyclic_buffer_activities(self, val):
        if len(val) < 16: return
        try:
            oldest_ptr = struct.unpack(">H", val[0:2])[0]
            newest_ptr = struct.unpack(">H", val[2:4])[0]
            buf_size = len(val) - 4
            ptr = 4 + newest_ptr
            seen_dates = set()
            for _ in range(366):
                if ptr < 4 or ptr + 12 > len(val): break
                prev_len, rec_len, ts = struct.unpack(">HHI", val[ptr:ptr+8])
                if rec_len < 14 or rec_len > 2048 or ts == 0 or ts == 0xFFFFFFFF: break
                
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                date_str = dt.strftime('%d/%m/%Y')
                if date_str not in seen_dates:
                    seen_dates.add(date_str)
                    pres, dist = struct.unpack(">HH", val[ptr+8:ptr+12])
                    daily = {"data": date_str, "km": int(dist), "eventi": []}
                    for i in range(12, rec_len, 2):
                        if ptr + i + 2 > len(val): break
                        ev_val = struct.unpack(">H", val[ptr+i:ptr+i+2])[0]
                        if ev_val == 0 or ev_val == 0xFFFF: continue
                        daily["eventi"].append(self._decode_activity_val(ev_val))
                    if daily["eventi"]: self.results["activities"].append(daily)
                if prev_len == 0 or prev_len > buf_size: break
                ptr -= prev_len
                if ptr < 4: ptr += buf_size
        except Exception: pass

    # ====================================================================
    # G2 / Annex 1C: BER-TLV reader
    # ====================================================================
    def _read_ber_tlv(self, data, pos):
        """Read a BER-TLV tag+length at *pos* inside *data* (bytes-like).
        Returns (tag_int, payload_length, header_size) or (None, None, 0).
        """
        if pos >= len(data):
            return None, None, 0
        try:
            start = pos
            b0 = data[pos]; pos += 1
            if b0 in (0x00, 0xFF):
                return None, None, 0            # padding byte
            tag = b0
            if (b0 & 0x1F) == 0x1F:            # multi-byte tag
                while pos < len(data):
                    b = data[pos]; pos += 1
                    tag = (tag << 8) | b
                    if not (b & 0x80):
                        break
            if pos >= len(data):
                return None, None, 0
            # length
            lb = data[pos]; pos += 1
            if lb < 0x80:
                length = lb
            else:
                nb = lb & 0x7F
                if nb == 0 or nb > 3 or pos + nb > len(data):
                    return None, None, 0
                length = int.from_bytes(data[pos:pos+nb], 'big')
                pos += nb
            if length > 0x100000:
                return None, None, 0
            return tag, length, pos - start
        except Exception:
            return None, None, 0

    # ====================================================================
    # Annex 1C parser  (BER-TLV *or* Tag2+Len2 — no type byte)
    # Used INSIDE G2 containers (0x76xx)
    # ====================================================================
    def _parse_annex1c(self, start_pos, end_pos, depth, parent_path):
        """Parse Annex 1C encoded data (inside a G2 container).
        
        Strategy:
         1. Try BER-TLV for multi-byte tags (0x7Fxx, 0x5Fxx, 0xBFxx etc.)
         2. Try Tag(2)+Len(2) for known 2-byte Annex 1C data tags (0x0102, 0x0201 …)
         3. Skip unknown bytes
        """
        if depth > 12:
            return
        pos = start_pos
        while pos < end_pos:
            matched = False

            # --- 1. BER-TLV multi-byte tags (first byte has low 5 bits set → 0x_F) ---
            if pos < end_pos and (self.raw_data[pos] & 0x1F) == 0x1F:
                tag, length, h = self._read_ber_tlv(self.raw_data, pos)
                if tag is not None and length is not None and pos + h + length <= end_pos:
                    hi = tag >> 8 if tag > 0xFF else 0
                    if tag in self.TAGS or hi in (0x7F, 0x5F, 0xBF):
                        val = self._safe_read(pos + h, length)
                        if val is not None:
                            self._record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                            pos += h + length
                            matched = True

            # --- 2. Tag(2)+Len(2) for known Annex 1C data tags ---
            if not matched and pos + 4 <= end_pos:
                raw4 = self._safe_read(pos, 4)
                if raw4:
                    t2, l2 = struct.unpack(">HH", raw4)
                    if t2 in self.TAGS and 0 <= l2 <= (end_pos - pos - 4):
                        val = self._safe_read(pos + 4, l2)
                        if val is not None:
                            self._record_and_dispatch(t2, l2, val, pos, 4, depth, parent_path, mode='annex1c')
                            pos += 4 + l2
                            matched = True

            # --- 3. BER-TLV single-byte tag as last resort ---
            if not matched:
                tag, length, h = self._read_ber_tlv(self.raw_data, pos)
                if tag is not None and tag in self.TAGS and pos + h + length <= end_pos:
                    val = self._safe_read(pos + h, length)
                    if val is not None:
                        self._record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                        pos += h + length
                        matched = True

            if not matched:
                pos += 1

    # ====================================================================
    # STAP parser  (Tag2 + Type1 + Len2) — top-level .ddd format
    # ====================================================================
    def _parse_tags_recursive(self, start_pos, end_pos, depth=0, parent_path=""):
        """Top-level STAP (Tag2+Type1+Len2) parser."""
        if depth > 12:
            return
        pos = start_pos
        while pos + 5 <= end_pos:
            try:
                hdr = self._safe_read(pos, 5)
                if not hdr:
                    break
                tag, dtype, length = struct.unpack(">HBH", hdr)

                # Validity checks
                if tag == 0 or tag == 0xFFFF:
                    pos += 1; continue
                if dtype > 0x04:
                    pos += 1; continue
                if pos + 5 + length > end_pos:
                    pos += 1; continue

                tag_name = self.TAGS.get(tag)
                if not tag_name:
                    pos += 5 + length; continue     # unknown — skip

                val = self._safe_read(pos + 5, length)
                if val is None:
                    pos += 1; continue

                self._record_and_dispatch(tag, length, val, pos, 5, depth, parent_path, mode='stap', dtype=dtype)
                pos += 5 + length
            except Exception:
                pos += 1

    # ====================================================================
    # Unified record + dispatch
    # ====================================================================
    def _record_and_dispatch(self, tag, length, val, pos, h_size, depth, parent_path, mode='stap', dtype=None):
        """Store the tag in raw_tags, decide if container, dispatch decoder."""
        tag_name = self.TAGS.get(tag, f"BER_{tag:04X}")
        self.bytes_covered += h_size

        # --- Container detection ---
        is_container = False
        if mode == 'stap' and dtype == 0x04:
            is_container = True                                     # STAP constructed
        if tag in (0x7621, 0x7F21, 0x7D21, 0xAD21):
            is_container = True                                     # known G2 containers
        # BER constructed bit
        if mode == 'annex1c' and tag > 0xFF:
            first_byte = (tag >> ((tag.bit_length() - 1) // 8 * 8)) & 0xFF
            if first_byte & 0x20:
                is_container = True

        if not is_container:
            self.bytes_covered += length

        # --- Store in raw_tags ---
        raw_key = f"{tag:04X}_{tag_name}"
        full_key = f"{parent_path} > {raw_key}" if parent_path else raw_key
        dtype_hex = f"0x{dtype:02X}" if dtype is not None else ("BER" if mode == 'annex1c' else "T2L2")
        entry = {
            "offset": f"0x{pos:08X}",
            "tag_id": f"0x{tag:04X}",
            "tag_name": tag_name,
            "data_type": dtype_hex,
            "length": length,
            "depth": depth,
            "data_hex": val.hex() if length <= 128 else f"{val[:128].hex()}..."
        }
        self.results["raw_tags"].setdefault(full_key, []).append(entry)

        # --- Certificate chain storage ---
        if tag in (0xC108, 0x0104):
            self.msca_cert_raw = val
        elif tag in (0xC100, 0x0103, 0xC101, 0x7F21):
            self.card_cert_raw = val

        # --- Recurse into containers ---
        if is_container:
            inner_start = pos + h_size
            inner_end   = pos + h_size + length

            # G2 container (0x76xx): skip 2-byte index, switch to Annex 1C parser
            if (tag & 0xFF00) == 0x7600:
                if length >= 2 and val[0] == 0x00:
                    inner_start += 2                                # skip noOfRecords / index
                self._parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            elif tag == 0x7F21:
                # Certificate body — parse children as BER-TLV
                self._parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            elif mode == 'stap':
                # Normal STAP container (G1)
                self._parse_tags_recursive(inner_start, inner_end, depth + 1, full_key)
            else:
                # Annex 1C sub-container
                self._parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            return   # dispatchers below handle leaf data; container dispatchers follow

        # --- Leaf data dispatchers ---
        if mode == 'stap' and dtype in (0x01, 0x03):
            return                                                  # signature — skip

        # G1 tags
        if tag == 0x0520:
            self._parse_g1_identification(val)
        elif tag == 0x0521:
            self._parse_g1_driving_licence(val)
        elif tag == 0x0505:
            self._parse_g1_vehicles_used(val)
        elif tag == 0x0507:
            self._parse_g1_current_usage(val)
        elif tag in (0x0504, 0x0524, 0x0206) and length > 100:
            self._parse_cyclic_buffer_activities(val)
        elif tag == 0x050C:
            self._parse_calibration_data(val)
        elif tag == 0x0001 and length >= 17:
            vin = self._decode_string(val[:17], is_id=True)
            if vin:
                self.results["vehicle"]["vin"] = vin
        # G2 / Annex 1C tags
        elif tag == 0x0102:
            self._parse_card_identification(val)
        elif tag == 0x0201:
            self._parse_driver_card_holder_identification(val)


    def parse(self):
        if not os.path.exists(self.file_path):
            self.results["metadata"]["integrity_check"] = "File Not Found"
            return self.results
        
        if self.file_size == 0:
            self.results["metadata"]["integrity_check"] = "Empty File"
            return self.results

        try:
            self._fd = open(self.file_path, 'rb')
            self.raw_data = mmap.mmap(self._fd.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception as e:
            self.results["metadata"]["integrity_check"] = f"Error opening: {str(e)}"
            return self.results

        try:
            header = self._safe_read(0, 2)
            self.results["metadata"]["generation"] = "G2 (Smart)" if header == b'\x76\x21' else "G1 (Digital)"

            # Start recursive parsing from the beginning of the file
            self._parse_tags_recursive(0, self.file_size)

            self.results["metadata"]["coverage_pct"] = self.get_coverage_report()
            
            # Post-processing: Deduplication & Sorting
            seen = {}
            unique = []
            for act in self.results["activities"]:
                key = f"{act['data']}_{len(act['eventi'])}"
                if key not in seen:
                    seen[key] = True
                    unique.append(act)
            
            unique.sort(
                key=lambda x: datetime.strptime(x["data"], '%d/%m/%Y') if x["data"] != "N/A" else datetime.min,
                reverse=True
            )
            self.results["activities"] = unique
            
            # --- Forensic Chain Validation ---
            if self.card_cert_raw and self.msca_cert_raw:
                status, pubkey = self.validator.validate_tacho_chain(self.card_cert_raw, self.msca_cert_raw)
                if status is True:
                    self.validation_status = "Verified"
                    self.card_public_key = pubkey
                elif status == "Incomplete (Missing ERCA)":
                    self.validation_status = "Verified (Local Chain)"
                    self.card_public_key = pubkey
                else:
                    self.validation_status = "Invalid Certificate Chain"
            else:
                self.validation_status = "Incomplete Certificates"

            self.results["metadata"]["integrity_check"] = self.validation_status

            if GEOCODING_AVAILABLE and self.results["locations"]:
                try:
                    self.results = process_locations_with_geocoding(self.results)
                except Exception: pass

        finally:
            if self.raw_data: self.raw_data.close()
            if self._fd: self._fd.close()
        
        return self.results

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(TachoParser(sys.argv[1]).parse(), indent=2))
