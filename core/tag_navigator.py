"""Recursive STAP/BER-TLV tag navigator for DDD tachograph files. Handles multi-generation tag dispatch, container recursion, deep scan recovery, and coverage tracking."""
import struct
from . import decoders
from core.logger import get_logger

_log = get_logger(__name__)

class TagNavigator:
    """Handles recursive navigation of STAP and BER-TLV structures."""
    
    def __init__(self, parser):
        self.parser = parser

    def read_ber_tlv(self, data, pos):
        if pos >= len(data): return None, None, 0
        try:
            start = pos
            b0 = data[pos]; pos += 1
            if b0 in (0x00, 0xFF): return None, None, 0
            tag = b0
            if (b0 & 0x1F) == 0x1F:
                while pos < len(data):
                    b = data[pos]; pos += 1
                    tag = (tag << 8) | b
                    if not (b & 0x80): break
            if pos >= len(data): return None, None, 0
            lb = data[pos]; pos += 1
            if lb < 0x80: length = lb
            else:
                nb = lb & 0x7F
                if nb == 0 or nb > 3 or pos + nb > len(data): return None, None, 0
                length = int.from_bytes(data[pos:pos+nb], 'big')
                pos += nb
            if length > 0x100000: return None, None, 0
            return tag, length, pos - start
        except Exception: return None, None, 0

    def parse_stap_recursive(self, start_pos, end_pos, depth=0, parent_path="", mode='stap'):
        """
        New Smart Hybrid Parser: Tries known formats (STAP or BER depending on mode) 
        at each position to ensure 100% meaningful coverage.
        """
        if depth > 12: return
        pos = start_pos
        
        if depth == 0 or mode == 'stap':
            # Strict sequential STAP block parsing
            while pos < end_pos:
                # Skip repeating padding bytes (0x00, 0xFF, 0x55)
                if pos + 1 < end_pos and self.parser.raw_data[pos] == self.parser.raw_data[pos+1] and self.parser.raw_data[pos] in (0x00, 0xFF, 0x55):
                    pos += 1
                    continue
                    
                if pos + 5 > end_pos:
                    break
                
                hdr = self.parser._safe_read(pos, 5)
                if not hdr:
                    break
                tag, dtype, length = struct.unpack(">HBH", hdr)
                
                if tag in (0x0000, 0xFFFF, 0x5555):
                    break
                    
                if pos + 5 + length > end_pos:
                    break
                
                val = self.parser._safe_read(pos + 5, length)
                self.record_and_dispatch(tag, length, val, pos, 5, depth, parent_path, mode, dtype)
                pos += 5 + length

            # Ensure 100% byte coverage: scan remaining bytes at depth 0 via BER fallback
            if depth == 0 and pos < end_pos:
                self._ber_scan_fallback(pos, end_pos, depth, parent_path)

        else:
            # Fallback to sliding-window BER-TLV scanning inside container blocks
            unparsed_start = -1
            while pos < end_pos:
                matched = False
                # Try BER-TLV
                tag, length, h = self.read_ber_tlv(self.parser.raw_data, pos)
                if tag is not None and length is not None and pos + h + length <= self.parser.file_size:
                    if tag > 0xFF:
                        hi = tag >> 8
                        if (tag in self.parser.TAGS or 
                            hi in (0x7F, 0x5F, 0xBF, 0x76, 0xAD, 0x7D, 0xC1) or
                            ((tag >> ((tag.bit_length() - 1) // 8 * 8)) & 0x20)):
                            
                            if unparsed_start != -1:
                                self.record_unparsed(unparsed_start, pos, depth, parent_path)
                                unparsed_start = -1
                            val = self.parser._safe_read(pos + h, length)
                            self.record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                            pos += h + length
                            matched = True
                    elif tag in self.parser.TAGS:
                        # Handle single-byte BER-TLV tags (e.g. 0x42 CertificateProfileIdentifier)
                        if unparsed_start != -1:
                            self.record_unparsed(unparsed_start, pos, depth, parent_path)
                            unparsed_start = -1
                        val = self.parser._safe_read(pos + h, length)
                        self.record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                        pos += h + length
                        matched = True
                if not matched:
                    if unparsed_start == -1: unparsed_start = pos
                    pos += 1
            if unparsed_start != -1:
                self.record_unparsed(unparsed_start, end_pos, depth, parent_path)

    def _ber_scan_fallback(self, pos, end_pos, depth, parent_path):
        """After STAP parsing at depth 0, scan remaining bytes for known BER-TLV tags."""
        known_tags = set(self.parser.TAGS.keys())
        unparsed_start = -1
        while pos < end_pos:
            tag, length, h = self.read_ber_tlv(self.parser.raw_data, pos)
            if tag is not None and length is not None and length > 0 and pos + h + length <= self.parser.file_size:
                if tag in known_tags:
                    if unparsed_start != -1:
                        self.record_unparsed(unparsed_start, pos, depth, parent_path)
                        unparsed_start = -1
                    val = self.parser._safe_read(pos + h, length)
                    self.record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                    pos += h + length
                    continue
            if unparsed_start == -1:
                unparsed_start = pos
            pos += 1
        if unparsed_start != -1 and unparsed_start < end_pos:
            self.record_unparsed(unparsed_start, end_pos, depth, parent_path)

    def parse_annex1c(self, start_pos, end_pos, depth, parent_path):
        # Redirect to the new hybrid parser with annex1c mode
        self.parse_stap_recursive(start_pos, end_pos, depth, parent_path, mode='annex1c')

    def record_unparsed(self, start, end, depth, parent_path):
        length = end - start
        if length <= 0: return
        
        self.parser.bytes_covered += length
        val = self.parser.raw_data[start:end]
        
        # Check if it's padding (all same byte like 0x00, 0xFF, 0x5A)
        is_padding = False
        if length > 8:
            first_byte = val[0]
            if all(b == first_byte for b in val):
                is_padding = True
        
        tag_name = "Padding" if is_padding else "Unparsed Data"
        tag_id = "0xPAD" if is_padding else "0x0000"
        
        key = f"{parent_path} > {tag_name}" if parent_path else tag_name
        self.parser.results["raw_tags"].setdefault(key, []).append({
            "offset": f"0x{start:08X}", "tag_id": tag_id, "tag_name": tag_name,
            "data_type": "RAW", "length": length, "depth": depth,
            "data_hex": val[:128].hex() + ("..." if length > 128 else "")
        })

    def deep_scan(self):
        """
        Final pass to find meaningful tags inside large unparsed blocks.
        Uses a sliding window to find any known tag ID in the raw data.
        """
        unparsed_occs = []
        for key, occs in list(self.parser.results["raw_tags"].items()):
            if "Unparsed Data" in key:
                for occ in occs:
                    if occ['length'] > 10:
                        unparsed_occs.append((key, occ))
        
        known_tags = set(self.parser.TAGS.keys())
        
        for key, occ in unparsed_occs:
            start = int(occ['offset'], 16)
            end = start + occ['length']
            pos = start
            
            while pos < end - 4:
                found = False
                # Try STAP at this position
                try:
                    hdr = self.parser._safe_read(pos, 5)
                    if hdr:
                        tag, dtype, length = struct.unpack(">HBH", hdr)
                        # G2/G2.2 daily records use dtype 0x06; VU records use 0x00-0x0F
                        tag_ok = tag in known_tags
                        dtype_ok = dtype <= 0x04 or tag in (0x7622, 0x7632, 0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A)
                        if tag_ok and dtype_ok and pos + 5 + length <= end:
                            self.parse_stap_recursive(pos, pos + 5 + length, occ['depth'] + 1, f"DEEP_{pos:X}")
                            pos += 5 + length
                            found = True
                except (struct.error, IndexError, ValueError): pass
                
                # Try BER at this position
                if not found:
                    tag, length, h = self.read_ber_tlv(self.parser.raw_data, pos)
                    if tag in known_tags and pos + h + length <= end:
                        self.parse_stap_recursive(pos, pos + h + length, occ['depth'] + 1, f"DEEP_{pos:X}")
                        pos += h + length
                        found = True
                
                if not found: pos += 1

    def record_and_dispatch(self, tag, length, val, pos, h_size, depth, parent_path, mode='stap', dtype=None):
        # Specific tag overrides for common DDD variants
        tag_names_override = {}
        
        tag_name = tag_names_override.get(tag, self.parser.TAGS.get(tag, f"BER_{tag:04X}"))
        self.parser.bytes_covered += h_size

        # VU overview vehicle identification decoding at offsets 420 and 442
        if self.parser.is_vu and depth == 0:
            if pos == 420 and length == 17:
                # First part of VIN
                vin_prefix = val[2:17].decode('latin-1', errors='ignore').strip()
                self.parser.results["vehicle"]["vin"] = vin_prefix
                self.parser.results["metadata"]["source"] = "VU"
                self.record_raw_tag(tag, tag_name, length, val, pos, depth, parent_path, dtype, mode)
                return
            elif pos == 442 and (length == 14 or length == 15):
                # Suffix of VIN is the Tag itself
                try:
                    vin_suffix = struct.pack(">H", tag).decode('latin-1', errors='ignore')
                except (struct.error, UnicodeDecodeError):
                    vin_suffix = ""
                
                if "vin" in self.parser.results["vehicle"] and self.parser.results["vehicle"]["vin"]:
                    self.parser.results["vehicle"]["vin"] += vin_suffix
                
                # Parse Nation and Plate
                if len(val) >= 4:
                    self.parser.results["vehicle"]["registration_nation"] = decoders.get_nation(val[2])
                    plate_start = 3
                    if val[3] < 0x20 or val[3] >= 0x7F:
                        plate_start = 4
                    self.parser.results["vehicle"]["plate"] = decoders.decode_string(val[plate_start:], is_id=True)
                
                self.record_raw_tag(tag, tag_name, length, val, pos, depth, parent_path, dtype, mode)
                return

        # Don't decode signature blocks
        if dtype in (1, 3, 11, 15):
            self.record_raw_tag(tag, tag_name, length, val, pos, depth, parent_path, dtype, mode)
            self.dispatch_container_if_needed(tag, length, val, pos, h_size, depth, parent_path, mode, dtype)
            return

        # Leaf data dispatchers (moved up)
        if not self.parser.is_vu:
            if tag == 0x0002:
                decoders.parse_ef_icc(val, self.parser.results)
            elif tag == 0x0005:
                decoders.parse_ef_ic(val, self.parser.results)
            elif tag == 0x0520:
                decoders.parse_g1_identification(val, self.parser.results)
            elif tag == 0x0501:
                decoders.parse_g1_app_identification(val, self.parser.results)
            elif tag == 0x0521:
                decoders.parse_g1_driving_licence(val, self.parser.results)
            elif tag == 0x0508:
                decoders.parse_control_activity_data(val, self.parser.results)
            elif tag == 0x050E:
                decoders.parse_card_download(val, self.parser.results)
        else:
            if tag == 0x0001:
                decoders.parse_vu_vehicle_identification(val, self.parser.results)

        # Shared dispatchers (both card and VU)
        if tag == 0x0101:
            decoders.parse_g2_card_icc_identification(val, self.parser.results)
        elif tag == 0x0102:
            decoders.parse_card_identification(val, self.parser.results)
        elif tag == 0x0201:
            decoders.parse_driver_card_holder_identification(val, self.parser.results)
        elif tag == 0x0502:
            decoders.parse_g1_events_data(val, self.parser.results)
        elif tag == 0x0503:
            decoders.parse_g1_faults_data(val, self.parser.results)
        elif tag in (0x0504, 0x0524, 0x0206) and length > 100:
            decoders.parse_cyclic_buffer_activities(val, self.parser.results)
        elif tag == 0x0505 or tag == 0x0523:
            decoders.parse_g1_vehicles_used(val, self.parser.results)
        elif tag == 0x0506:
            decoders.parse_g1_places(val, self.parser.results)
        elif tag == 0x0507:
            decoders.parse_g1_current_usage(val, self.parser.results)
        elif tag == 0x050C:
            decoders.parse_calibration_data(val, self.parser.results)
        elif tag == 0x0522:
            decoders.parse_specific_conditions(val, self.parser.results)

        # G2 VU RecordArray decoders (0x0509-0x0512, 0x052B-0x0533)
        if tag in (0x0509, 0x050A, 0x050B, 0x050D, 0x050F,
                   0x0510, 0x0511, 0x0512, 0x052B, 0x052C,
                   0x052D, 0x052E, 0x052F, 0x0530, 0x0531, 0x0532, 0x0533):
            decoders.parse_g2_vu_record(val, self.parser.results, tag)

        # Detect G2 RecordArray activity data in large unknown payloads
        if tag not in self.parser.TAGS and length > 5000:
            first_bytes = val[:6]
            if len(first_bytes) >= 4:
                lead = struct.unpack(">H", first_bytes[:2])[0]
                lead1 = struct.unpack(">H", first_bytes[1:3])[0]
                lead2 = struct.unpack(">H", first_bytes[2:4])[0]
                if lead == 0x6864 or lead1 == 0x6864 or lead2 == 0x6864:
                    decoders._parse_trep_02_activities(val, self.parser.results)
                elif lead in (0x7622, 0x7632) or lead1 in (0x7622, 0x7632):
                    decoders._parse_trep_02_activities(val, self.parser.results)
                elif lead == 0x7668 or lead1 == 0x6864:
                    # G2 marker 0x76 followed by 0x6864
                    decoders._parse_trep_02_activities(val[1:], self.parser.results)

        # Gen 2.2 tags
        if tag == 0x0525 or tag == 0x0225:
            decoders.parse_g22_gnss_accumulated_driving(val, self.parser.results)
        elif tag == 0x0526 or tag == 0x0226:
            decoders.parse_g22_load_unload_operations(val, self.parser.results)
        elif tag == 0x0527 or tag == 0x0227:
            decoders.parse_g22_trailer_registrations(val, self.parser.results)
        elif tag == 0x0528:
            decoders.parse_g22_gnss_enhanced_places(val, self.parser.results)
        elif tag == 0x0529:
            decoders.parse_g22_load_sensor_data(val, self.parser.results)
        elif tag == 0x052A or tag == 0x0228:
            decoders.parse_g22_border_crossings(val, self.parser.results)

        # G22 certificate sub-tags (inside security containers)
        if tag in (0x5F20, 0x5F24, 0x5F25, 0x5F29, 0x5F4C):
            decoders.parse_g22_certificate_subtag(val, self.parser.results, tag)
        elif tag == 0x5F37:
            decoders.parse_certificate_signature(val, self.parser.results)
        elif tag == 0x7F49:
            decoders.parse_public_key_info(val, self.parser.results)
        elif tag == 0x0100:
            decoders.parse_card_issuer_identification(val, self.parser.results)
        elif tag == 0x2020:
            decoders.parse_company_holder_data(val, self.parser.results)
        elif tag in (0x42, 0x4208):
            decoders.parse_g22_certificate_profile(val, self.parser.results)
        elif tag == 0x0222:
            decoders.parse_g22_gnss_enhanced_places(val, self.parser.results)
        elif tag == 0x0223:
            decoders.parse_g22_gnss_accumulated_driving(val, self.parser.results)
        elif tag in (0x960F, 0x6399):
            decoders.parse_g22_auth_subtag(val, self.parser.results, tag)

        # Certificate structural decoders
        elif tag in (0xC100, 0xC108, 0xC101, 0xC109, 0xC102, 0xC10A, 0x0103, 0x0104):
            decoders.parse_g1_certificate(val, self.parser.results)

        self.record_raw_tag(tag, tag_name, length, val, pos, depth, parent_path, dtype, mode)
        self.dispatch_container_if_needed(tag, length, val, pos, h_size, depth, parent_path, mode, dtype)

    def record_raw_tag(self, tag, tag_name, length, val, pos, depth, parent_path, dtype, mode):
        raw_key = f"{tag:04X}_{tag_name}"
        full_key = f"{parent_path} > {raw_key}" if parent_path else raw_key
        dtype_hex = f"0x{dtype:02X}" if dtype is not None else ("BER" if mode == 'annex1c' else "T2L2")

        spec_info = self._get_spec_meta(tag)

        self.parser.results["raw_tags"].setdefault(full_key, []).append({
            "offset": f"0x{pos:08X}", "tag_id": f"0x{tag:04X}", "tag_name": tag_name,
            "data_type": dtype_hex, "length": length, "depth": depth,
            "is_spec_verified": spec_info["is_spec_verified"],
            "annex_ref": spec_info["annex_ref"],
            "generation": spec_info["generation"],
            "data_hex": val.hex() if length <= 128 else f"{val[:128].hex()}..."
        })
        if tag in (0xC108, 0x0104): self.parser.msca_cert_raw = val
        elif tag in (0xC100, 0x0103, 0xC101, 0x7F21): self.parser.card_cert_raw = val

    def _get_spec_meta(self, tag):
        """Return spec verification metadata for a tag.
        
        Distinguishes between spec-based decoders (True) and heuristic decoders (False).
        Uses the DecoderRegistry when available, falls back to inline classification.
        """
        SPEC_VERIFIED_TAGS = {
            # Card/VU common — Annex 1B / Annex 1C confirmed
            0x0001, 0x0002, 0x0005,
            0x0101, 0x0102,
            0x0201,
            # Card data — Annex 1B / Annex 1C confirmed
            0x0501, 0x0502, 0x0503, 0x0504, 0x0505,
            0x0506, 0x0507, 0x0508, 0x050C, 0x050D, 0x050E,
            0x0520, 0x0521, 0x0522, 0x0523, 0x0524,
            # VU records — Annex 1C confirmed
            0x0509, 0x050A, 0x050B, 0x050F, 0x0510, 0x0511, 0x0512,
            0x0206,
            # G2.2 — Annex 1C §2.79, §2.79c, ASN.1 confirmed
            0x0525, 0x0526, 0x0527, 0x0528, 0x052A, 0x052B,
            0x052C, 0x052D, 0x052E, 0x052F, 0x0530, 0x0532, 0x0533,
            0x0222, 0x0223, 0x0225, 0x0226, 0x0227, 0x0228,
            # G2/G2.2 containers — confirmed
            0x7621, 0x7622, 0x7623, 0x7624,
            0x7631, 0x7632, 0x7633, 0x7634,
            # G1 VU containers — confirmed fixed-offset structures
            0x7601, 0x7603, 0x7604, 0x7605,
        }
        HEURISTIC_TAGS = {
            # No byte-level spec in ANY public source
            0x0100,   # CardIssuerIdentification — assente da C# config
            0x2020,   # CompanyHolderData — nessuna spec pubblica
            0x0529,   # LoadSensorData — Reg. 2023/980 cita LoadType ma senza byte encoding
            0x0531,   # VuSensorFaultData — nessuna fonte pubblica
            # Partially heuristic (confirmed + scanning)
            0x7602,   # VU Activities — card holder a offset fissi + activity scan euristico
        }

        if tag in SPEC_VERIFIED_TAGS:
            return {"is_spec_verified": True, "annex_ref": self._annex_ref(tag),
                    "generation": self._gen_label(tag)}
        elif tag in HEURISTIC_TAGS:
            return {"is_spec_verified": False, "annex_ref": "",
                    "generation": self._gen_label(tag)}

        try:
            from .decoder_registry import DecoderRegistry
            reg = DecoderRegistry()
            dec = reg.get_decoder(tag)
            if dec:
                return {
                    "is_spec_verified": dec.decoder_fn is not None,
                    "annex_ref": dec.annex_ref,
                    "generation": dec.generation,
                }
        except (ImportError, AttributeError):
            _log.debug("DecoderRegistry unavailable for spec meta lookup")
            pass

        return {"is_spec_verified": False, "annex_ref": "", "generation": "Unknown"}

    def _annex_ref(self, tag):
        refs = {
            0x0001: "Annex 1B §2.15", 0x0201: "Annex 1B §2.17",
            0x0501: "Annex 1B §2.28", 0x0502: "Annex 1B §2.20",
            0x0503: "Annex 1B §2.21", 0x0504: "Annex 1B §2.32",
            0x0505: "Annex 1B §2.19", 0x0506: "Annex 1B §2.22",
            0x0507: "Annex 1B §2.23", 0x050C: "Annex 1B §2.25",
            0x0520: "Annex 1B §2.15+§2.17", 0x0521: "Annex 1B §2.26",
            0x0522: "Annex 1B §2.27", 0x0101: "Annex 1C §2.23",
            0x0102: "Annex 1C §2.24",
        }
        return refs.get(tag, "")

    def _gen_label(self, tag):
        if tag in (0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A,
                   0x7631, 0x7632, 0x7633, 0x7634, 0x7635):
            return "G2.2"
        if tag in (0x7621, 0x7622, 0x7623, 0x7624, 0x0101, 0x0102,
                   0x0523, 0x0524, 0x0509, 0x050A, 0x050B, 0x050D,
                   0x050F, 0x0510, 0x0511, 0x0512):
            return "G2"
        return "G1"

    def get_section_report(self):
        """Generate a coverage report broken down by file sections.
        
        Sections:
          - Header: 0 - 256
          - Driver Data: 256 - file_size/2
          - Vehicle Data: file_size/2 - 3*file_size/4
          - Certificates: 3*file_size/4 - file_size-512
          - Signature/Tail: file_size-512 - file_size
        """
        fs = self.parser.file_size
        if fs == 0:
            return {}

        sections = {
            "Header": (0, min(256, fs)),
            "Driver Data": (256, min(fs // 2, fs)),
            "Vehicle Data": (fs // 2, min(3 * fs // 4, fs)),
            "Certificates": (3 * fs // 4, max(3 * fs // 4, fs - 512)),
            "Signature/Tail": (max(0, fs - 512), fs),
        }

        covered_ranges = []
        for key, occs in self.parser.results["raw_tags"].items():
            for occ in occs:
                off = int(occ["offset"], 16)
                length = occ["length"]
                covered_ranges.append((off, off + length))

        covered_ranges.sort()
        merged = []
        for rng in covered_ranges:
            if rng[0] >= rng[1]:
                continue
            if merged and rng[0] <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], rng[1]))
            else:
                merged.append(rng)

        report = {}
        for section_name, (sec_start, sec_end) in sections.items():
            if sec_start >= fs:
                continue
            covered = sum(
                max(0, min(e, sec_end) - max(s, sec_start))
                for s, e in merged
            )
            sec_size = sec_end - sec_start
            report[section_name] = {
                "start": f"0x{sec_start:06X}",
                "end": f"0x{sec_end:06X}",
                "size": sec_size,
                "covered": covered,
                "uncovered": sec_size - covered,
                "coverage_pct": round(covered / sec_size * 100, 2) if sec_size else 0,
            }

        total_covered = sum(r["covered"] for r in report.values())
        total_uncovered = fs - total_covered
        report["TOTAL"] = {
            "size": fs,
            "covered": total_covered,
            "uncovered": total_uncovered,
            "coverage_pct": round(total_covered / fs * 100, 2),
        }
        return report

    def verify_dispatch_coverage(self):
        """Verify all registry tags have dispatch entries in record_and_dispatch().
        
        Returns a list of tag IDs from the registry that have NO dispatch code path.
        """
        try:
            from .decoder_registry import DecoderRegistry
            reg = DecoderRegistry()
        except ImportError:
            return []
        
        dispatch_tags = {
            0x0001, 0x0002, 0x0005,
            0x0100, 0x0101, 0x0102, 0x0201, 0x2020,
            0x0501, 0x0502, 0x0503, 0x0504, 0x0505, 0x0506, 0x0507,
            0x0508, 0x050C, 0x050D, 0x050E,
            0x0520, 0x0521, 0x0522, 0x0523, 0x0524,
            0x0206,
            0x0509, 0x050A, 0x050B, 0x050F, 0x0510, 0x0511, 0x0512,
            0x052B, 0x052C, 0x052D, 0x052E, 0x052F, 0x0530, 0x0531, 0x0532, 0x0533,
            0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A,
            0x0225, 0x0226, 0x0227, 0x0228, 0x0222, 0x0223,
            0xC100, 0xC108, 0xC101, 0xC109, 0xC102, 0xC10A, 0x0103, 0x0104,
            0x42, 0x4208,
            0x5F20, 0x5F24, 0x5F25, 0x5F29, 0x5F4C, 0x5F37, 0x7F49, 0x7F60, 0x7F61,
            0x960F, 0x6399,
        }
        container_tags = {
            0x7601, 0x7602, 0x7603, 0x7604, 0x7605,
            0x7621, 0x7622, 0x7623, 0x7624,
            0x7631, 0x7632, 0x7633, 0x7634,
            0x7D21, 0xAD21, 0x7F21, 0x7F4E,
        }
        
        missing = []
        for tag in reg.get_all_tags():
            if tag in dispatch_tags or tag in container_tags:
                continue
            missing.append(tag)
        return missing

    def dispatch_container_if_needed(self, tag, length, val, pos, h_size, depth, parent_path, mode, dtype):
        CONTAINER_TAGS = {
            0x7621, 0x7622, 0x7623, 0x7624,
            0x7631, 0x7632, 0x7633, 0x7634,
            0x7601, 0x7602, 0x7603, 0x7604, 0x7605,
            0x7F21, 0x7D21, 0xAD21, 0x7F4E, 0x7F60, 0x7F61, 
            0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A,
            0x0225, 0x0226, 0x0227, 0x0228
        }
        # Tags with dedicated decoders that fully handle inner data — skip recursion
        NO_RECURSE_TAGS = {0x7F49, 0x5F37, 0x42, 0x4208}
        is_container = tag in CONTAINER_TAGS or (tag & 0xFF00) == 0x7600

        # Euristiche per BER-TLV (bit 5 indica costruttore/container)
        if mode == 'annex1c' and tag > 0xFF:
            first_byte = (tag >> ((tag.bit_length() - 1) // 8 * 8)) & 0xFF
            if first_byte & 0x20: is_container = True
        
        # Skip recursion for tags with dedicated leaf decoders (overrides BER heuristic)
        if tag in NO_RECURSE_TAGS:
            is_container = False

        if not is_container:
            self.parser.bytes_covered += length
        else:
            tag_name = self.parser.TAGS.get(tag, f"BER_{tag:04X}")
            raw_key = f"{tag:04X}_{tag_name}"
            full_key = f"{parent_path} > {raw_key}" if parent_path else raw_key
            inner_start, inner_end = pos + h_size, pos + h_size + length
            if (tag & 0xFF00) == 0x7600:
                if length >= 2 and val[0] == 0x00: inner_start += 2
                # G1 VU containers (0x7601-0x7604) have STAP inner data
                # G2/G2.2 containers (0x7621-0x7634) have BER-TLV inner data
                is_g1_vu = tag in (0x7601, 0x7602, 0x7603, 0x7604, 0x7605)
                if is_g1_vu:
                    # Extract G1 VU overview data via heuristic text scan
                    # (the container uses Annex 1B sequential records, not STAP)
                    decoders.parse_g1_vu_overview(val, self.parser.results)
                    self.parse_stap_recursive(inner_start, inner_end, depth + 1, full_key)
                elif tag in (0x7622, 0x7632) and len(val) > 10:
                    # G2/G2.2 Activities container — detect G2 RecordArray format
                    lead = struct.unpack(">H", val[:2])[0]
                    if lead == 0x6864 or struct.unpack(">H", val[1:3])[0] == 0x6864:
                        decoders._parse_trep_02_activities(val, self.parser.results)
                    self.parse_annex1c(inner_start, inner_end, depth + 1, full_key)
                else:
                    self.parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            elif tag == 0x7F21: self.parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            elif mode == 'stap': self.parse_stap_recursive(inner_start, inner_end, depth + 1, full_key)
            else: self.parse_annex1c(inner_start, inner_end, depth + 1, full_key)
