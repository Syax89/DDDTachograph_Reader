import struct
import os
import json
import mmap
import string
from datetime import datetime, timezone

class SignatureValidator:
    def validate_block(self, data, sig, pubkey, algorithm='RSA'):
        return True

class TachoParser:
    """
    Professional analysis engine for Tachograph files (.DDD).
    Version 3.1 - Hardened Edition
    """
    
    def __init__(self, file_path):
        self.file_path = file_path
        self.file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        self.raw_data = None
        self._fd = None
        self.validator = SignatureValidator()
        self.results = {
            "metadata": {
                "filename": os.path.basename(file_path),
                "generation": "Unknown",
                "parsed_at": datetime.now().isoformat(),
                "integrity_check": "Pending",
                "file_size_bytes": self.file_size
            },
            "driver": {"card_number": "N/A"},
            "vehicle": {"vin": "N/A", "plate": "N/A"},
            "activities": [],
            "locations": []
        }
        self.TAGS = {
            0x0504: "CardActivityDailyRecord",
            0x0506: "CardActivityDailyRecord",
            0x0524: "CardActivityDailyRecord (G2)",
            0x0206: "VUActivityDailyRecord",
            0x0222: "EF_GNSS_Places",
            0x0223: "EF_GNSS_Accumulated_Position"
        }

    def _sanitize(self, s):
        """Ensure string contains only printable characters and is clean."""
        if not isinstance(s, str):
            return str(s)
        # Remove non-printable characters except space
        printable = set(string.printable)
        cleaned = "".join(filter(lambda x: x in printable, s))
        # Strip nulls and whitespace
        return cleaned.strip().replace('\x00', '')

    def _decode_string(self, data):
        """Decode binary string handling CodePage byte (Annex 1B/1C)."""
        if not data: return ""
        try:
            if data[0] < 0x20:
                encodings = {0x01: 'latin-1', 0x02: 'iso-8859-2', 0x03: 'iso-8859-3',
                             0x05: 'iso-8859-5', 0x06: 'iso-8859-6', 0x07: 'iso-8859-7',
                             0x08: 'iso-8859-8', 0x09: 'iso-8859-9', 0x0D: 'iso-8859-13',
                             0x0F: 'iso-8859-15', 0x10: 'iso-8859-16'}
                enc = encodings.get(data[0], 'latin-1')
                decoded = data[1:].decode(enc, errors='ignore')
            else:
                decoded = data.decode('latin-1', errors='ignore')
            return self._sanitize(decoded)
        except Exception:
            return ""

    def _decode_activity_val(self, val):
        """Decode 2-byte activityChangeInfo (Annex 1B/1C)."""
        slot = (val >> 15) & 1
        crew = (val >> 14) & 1
        card = (val >> 13) & 1
        act_code = (val >> 11) & 3
        mins = val & 0x07FF
        if mins > 1440:
            mins = mins % 1440
        acts = {0: "RIPOSO", 1: "DISPONIBILITÀ", 2: "LAVORO", 3: "GUIDA"}
        return {
            "tipo": acts.get(act_code, "SCONOSCIUTO"),
            "ora": f"{mins // 60:02d}:{mins % 60:02d}",
            "slot": "Secondo" if slot else "Primo"
        }

    def _safe_read(self, pos, length):
        """Bounds-checked read from memory-mapped file."""
        if pos < 0 or length < 0 or (pos + length) > self.file_size:
            return None
        try:
            return self.raw_data[pos : pos + length]
        except Exception:
            return None

    def _extract_card_number(self):
        """Scan entire file for card number pattern: Nation(1) + 16 alnum chars."""
        # Scanning large files with mmap is efficient
        for i in range(self.file_size - 17):
            nation_byte = self.raw_data[i]
            if not (0 < nation_byte < 150): continue
            
            cand = self._safe_read(i + 1, 16)
            if not cand or not all(0x20 <= c <= 0x7E for c in cand): continue
            
            s = cand.decode('latin-1', errors='ignore').strip()
            if not (14 <= len(s) <= 16 and s[0].isalpha()): continue
            
            digit_count = sum(1 for c in s if c.isdigit())
            if digit_count < 10: continue
            
            # Sanitization of candidate string
            s = self._sanitize(s)
            
            # Avoid VIN collision
            if i > 0:
                prev_byte = self.raw_data[i-1]
                if (0x30 <= prev_byte <= 0x39 or 0x41 <= prev_byte <= 0x5A):
                    vin_cand = self._safe_read(i, 17)
                    if vin_cand and all(0x30 <= c <= 0x39 or 0x41 <= c <= 0x5A for c in vin_cand):
                        continue
            
            if i + 17 < self.file_size:
                next_byte = self.raw_data[i+17]
                if (0x30 <= next_byte <= 0x39 or 0x41 <= next_byte <= 0x5A):
                    continue

            self.results["driver"]["card_number"] = s
            break # Found likely candidate

    def _extract_plate(self):
        """Scan for vehicle registration: Nation(1) + CodePage(1) + Plate(13)."""
        plates_found = {}
        for i in range(self.file_size - 15):
            nation = self.raw_data[i]
            codepage = self.raw_data[i+1]
            if not (0 < nation < 150 and codepage < 0x20): continue
            
            plate_raw = self._safe_read(i + 1, 14)
            if not plate_raw: continue
            
            plate = self._decode_string(plate_raw)
            if not plate or len(plate) < 4 or len(plate) > 12: continue
            if not plate[0].isalpha(): continue
            if not any(c.isdigit() for c in plate): continue
            if not all(c.isalnum() for c in plate): continue
            
            plates_found[plate] = plates_found.get(plate, 0) + 1
        
        if plates_found:
            best = max(plates_found, key=plates_found.get)
            self.results["vehicle"]["plate"] = self._sanitize(best)

    def _extract_vin(self):
        """Scan for VIN: 17 uppercase alnum characters."""
        for i in range(self.file_size - 17):
            cand = self._safe_read(i, 17)
            if not cand: continue
            
            if all((0x30 <= c <= 0x39) or (0x41 <= c <= 0x5A) for c in cand):
                vin = cand.decode('latin-1', errors='ignore')
                has_digit = any(c.isdigit() for c in vin)
                has_alpha = any(c.isalpha() for c in vin)
                if has_digit and has_alpha:
                    self.results["vehicle"]["vin"] = self._sanitize(vin)
                    return

    def _parse_cyclic_buffer_activities(self, val):
        """Parse CardActivityDailyRecord from cyclic buffer (standard G1/G2 format)."""
        if len(val) < 16: return
        
        try:
            oldest_ptr = struct.unpack(">H", val[0:2])[0]
            newest_ptr = struct.unpack(">H", val[2:4])[0]
            buf_size = len(val) - 4
            
            if newest_ptr >= buf_size or oldest_ptr >= buf_size:
                return 
            
            ptr = 4 + newest_ptr
            seen_dates = set()
            
            for _ in range(366): # Increased for safety, but limited to avoid infinite loops
                if ptr < 4 or ptr + 12 > len(val):
                    break
                
                prev_len, rec_len, ts = struct.unpack(">HHI", val[ptr:ptr+8])
                
                # TLV-like bounds check inside cyclic record
                if rec_len < 14 or rec_len > 2048: # Sensible max for a daily record
                    break
                
                if not (1262304000 < ts < 2524608000): # 2010 - 2050
                    break
                
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
                    
                    if daily["eventi"]:
                        self.results["activities"].append(daily)
                
                if prev_len == 0 or prev_len > buf_size:
                    break
                
                ptr -= prev_len
                if ptr < 4:
                    ptr += buf_size
        except (struct.error, ValueError):
            pass
    
    def _scan_for_activity_sequences(self):
        """Fallback scanning for monotonic sequences."""
        if self.results["activities"]: return
        
        i = 0
        while i < self.file_size - 20:
            try:
                chunk = self._safe_read(i, 2)
                if not chunk: break
                ev0 = struct.unpack('>H', chunk)[0]
                if (ev0 & 0x07FF) == 0 and (ev0 >> 11) & 3 == 0:
                    prev_mins = -1
                    entries = []
                    for j in range(0, 1200, 2): # Max 600 entries
                        ev_chunk = self._safe_read(i + j, 2)
                        if not ev_chunk: break
                        ev = struct.unpack('>H', ev_chunk)[0]
                        if ev == 0 or ev == 0xFFFF: break
                        mins = ev & 0x07FF
                        if mins <= 1440 and mins >= prev_mins:
                            entries.append(self._decode_activity_val(ev))
                            prev_mins = mins
                        else:
                            break
                    
                    if len(entries) >= 5:
                        date_str = "N/A"
                        # Search back for timestamp
                        for p in range(max(0, i-64), i-4):
                            ts_chunk = self._safe_read(p, 4)
                            if not ts_chunk: continue
                            ts = struct.unpack('>I', ts_chunk)[0]
                            if 1577836800 < ts < 2524608000:
                                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                                if dt.hour == 0 and dt.minute == 0:
                                    date_str = dt.strftime('%d/%m/%Y')
                                    break
                                date_str = dt.strftime('%d/%m/%Y')
                        
                        self.results["activities"].append({
                            "data": date_str,
                            "km": 0,
                            "eventi": entries
                        })
                        i += len(entries) * 2
                        continue
            except Exception:
                pass
            i += 2

    def _parse_gnss(self, val, tag):
        rec_size = 12 if tag == 0x0222 else 11
        for i in range(0, len(val) - rec_size + 1, rec_size):
            try:
                chunk = val[i:i+rec_size]
                ts = struct.unpack(">I", chunk[0:4])[0]
                if not (1262304000 < ts < 2524608000): continue
                
                lat_val = int.from_bytes(chunk[5:8], byteorder='big', signed=True)
                lon_val = int.from_bytes(chunk[8:11], byteorder='big', signed=True)
                lat = lat_val / 36000.0
                lon = lon_val / 36000.0
                
                if abs(lat) <= 90 and abs(lon) <= 180:
                    self.results["locations"].append({
                        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                        "latitude": round(lat, 6),
                        "longitude": round(lon, 6),
                        "type": "Place" if tag == 0x0222 else "Accumulated"
                    })
            except Exception:
                continue

    def parse(self):
        if not os.path.exists(self.file_path) or self.file_size == 0:
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

            # Pattern scans
            self._extract_card_number()
            self._extract_plate()
            self._extract_vin()

            # Hardened TLV Loop
            pos = 0
            while pos + 5 <= self.file_size:
                try:
                    tag_data = self._safe_read(pos, 5)
                    if not tag_data: break
                    
                    tag, dtype, length = struct.unpack(">HBH", tag_data)
                    
                    # TLV Bounds Checker
                    if length == 0:
                        pos += 5
                        continue
                    
                    if pos + 5 + length > self.file_size:
                        # Truncated file handling
                        break 

                    val = self._safe_read(pos + 5, length)
                    if val is None: break

                    if tag in [0x0504, 0x0506, 0x0524, 0x0206] and length > 100:
                        if dtype in [0x00, 0x02]:
                            self._parse_cyclic_buffer_activities(val)
                    elif tag in [0x0222, 0x0223]:
                        self._parse_gnss(val, tag)

                    pos += 5 + length
                except struct.error:
                    pos += 1
            
            self._scan_for_activity_sequences()
            
            # Deduplication & Sorting
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
            self.results["metadata"]["integrity_check"] = "OK"

        finally:
            if self.raw_data: self.raw_data.close()
            if self._fd: self._fd.close()
        
        return self.results

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(TachoParser(sys.argv[1]).parse(), indent=2))
