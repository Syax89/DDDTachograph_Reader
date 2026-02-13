import struct
from . import decoders

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

    def parse_stap_recursive(self, start_pos, end_pos, depth=0, parent_path=""):
        """
        New Smart Hybrid Parser: Tries all known formats (STAP, BER, T2L2) 
        at each position to ensure 100% meaningful coverage.
        """
        if depth > 12: return
        pos = start_pos
        unparsed_start = -1
        
        while pos < end_pos:
            matched = False
            match_len = 0
            
            # --- 1. Try STAP (5 bytes header) ---
            if not matched and pos + 5 <= end_pos:
                try:
                    hdr = self.parser._safe_read(pos, 5)
                    if hdr:
                        tag, dtype, length = struct.unpack(">HBH", hdr)
                        if tag in self.parser.TAGS and dtype <= 0x04 and pos + 5 + length <= end_pos:
                            if unparsed_start != -1:
                                self.record_unparsed(unparsed_start, pos, depth, parent_path)
                                unparsed_start = -1
                            
                            val = self.parser._safe_read(pos + 5, length)
                            self.record_and_dispatch(tag, length, val, pos, 5, depth, parent_path, mode='stap', dtype=dtype)
                            pos += 5 + length
                            matched = True
                except Exception: pass

            # --- 2. Try BER-TLV ---
            if not matched:
                tag, length, h = self.read_ber_tlv(self.parser.raw_data, pos)
                if tag is not None and length is not None and pos + h + length <= end_pos:
                    # Valid BER match if:
                    # - Known tag
                    # - Or starts with 0x7F, 0x5F, 0xBF, 0x76, 0xAD (common tachograph roots)
                    # - Or bit 5 is set (constructed)
                    hi = tag >> 8 if tag > 0xFF else tag
                    if (tag in self.parser.TAGS or 
                        hi in (0x7F, 0x5F, 0xBF, 0x76, 0xAD) or
                        (tag > 0xFF and ((tag >> ((tag.bit_length() - 1) // 8 * 8)) & 0x20))):
                        
                        if unparsed_start != -1:
                            self.record_unparsed(unparsed_start, pos, depth, parent_path)
                            unparsed_start = -1
                        val = self.parser._safe_read(pos + h, length)
                        self.record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                        pos += h + length
                        matched = True

            # --- 3. Try Tag2 + Len2 (4 bytes header) ---
            if not matched and pos + 4 <= end_pos:
                try:
                    raw4 = self.parser._safe_read(pos, 4)
                    if raw4:
                        t2, l2 = struct.unpack(">HH", raw4)
                        if t2 in self.parser.TAGS and 0 <= l2 <= (end_pos - pos - 4):
                            if unparsed_start != -1:
                                self.record_unparsed(unparsed_start, pos, depth, parent_path)
                                unparsed_start = -1
                            val = self.parser._safe_read(pos + 4, l2)
                            self.record_and_dispatch(t2, l2, val, pos, 4, depth, parent_path, mode='annex1c')
                            pos += 4 + l2
                            matched = True
                except Exception: pass

            if not matched:
                if unparsed_start == -1: unparsed_start = pos
                pos += 1
        
        if unparsed_start != -1:
            self.record_unparsed(unparsed_start, end_pos, depth, parent_path)

    def parse_annex1c(self, start_pos, end_pos, depth, parent_path):
        # Redirect to the new hybrid parser for consistency
        self.parse_stap_recursive(start_pos, end_pos, depth, parent_path)

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
                        if tag in known_tags and dtype <= 0x04 and pos + 5 + length <= end:
                            self.parse_stap_recursive(pos, pos + 5 + length, occ['depth'] + 1, f"DEEP_{pos:X}")
                            pos += 5 + length
                            found = True
                except: pass
                
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
        tag_names_override = {
            0x0501: "G1_Identification",
            0x0502: "G1_Identification",
            0x0520: "G1_Identification"
        }
        
        tag_name = tag_names_override.get(tag, self.parser.TAGS.get(tag, f"BER_{tag:04X}"))
        self.parser.bytes_covered += h_size

        # Leaf data dispatchers (moved up)
        if tag == 0x0501 or tag == 0x0502 or tag == 0x0520:
            decoders.parse_g1_identification(val, self.parser.results)
        elif tag == 0x0521:
            decoders.parse_g1_driving_licence(val, self.parser.results)
        elif tag == 0x0505:
            decoders.parse_g1_vehicles_used(val, self.parser.results)
        elif tag == 0x0507:
            decoders.parse_g1_current_usage(val, self.parser.results)
        elif tag == 0x050C:
            decoders.parse_calibration_data(val, self.parser.results)
        elif tag == 0x0102:
            decoders.parse_card_identification(val, self.parser.results)
        elif tag == 0x0201:
            decoders.parse_driver_card_holder_identification(val, self.parser.results)
        elif tag in (0x0504, 0x0524, 0x0206) and length > 100:
            decoders.parse_cyclic_buffer_activities(val, self.parser.results)
        # Gen 2.2 tags
        elif tag == 0x0525:
            decoders.parse_g22_gnss_accumulated_driving(val, self.parser.results)
        elif tag == 0x0526 or tag == 0x0226:
            decoders.parse_g22_load_unload_operations(val, self.parser.results)
        elif tag == 0x0527 or tag == 0x0227:
            decoders.parse_g22_trailer_registrations(val, self.parser.results)
        elif tag == 0x0528 or tag == 0x0225:
            decoders.parse_g22_gnss_enhanced_places(val, self.parser.results)
        elif tag == 0x0529:
            decoders.parse_g22_load_sensor_data(val, self.parser.results)
        elif tag == 0x052A or tag == 0x0228:
            decoders.parse_g22_border_crossings(val, self.parser.results)
        elif tag == 0x0001 and length >= 17:
            vin = decoders.decode_string(val[:17], is_id=True)
            if vin: self.parser.results["vehicle"]["vin"] = vin

        # Tag che sappiamo essere contenitori (BER o STAP)
        CONTAINER_TAGS = {
            0x7621, 0x7631, 0x7F21, 0x7D21, 0xAD21, 0x7F4E, 0x7F60, 0x7F61, 
            0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A, # Nuovi G2.2
            0x0225, 0x0226, 0x0227, 0x0228
        }

        is_container = False
        if mode == 'stap' and dtype == 0x04: is_container = True
        if tag in CONTAINER_TAGS: is_container = True
        
        # Euristiche per BER-TLV (bit 5 indica costruttore/container)
        if mode == 'annex1c' and tag > 0xFF:
            first_byte = (tag >> ((tag.bit_length() - 1) // 8 * 8)) & 0xFF
            if first_byte & 0x20: is_container = True
        
        # Se non è un container noto, proviamo a vedere se "sembra" un container
        # Analizziamo i primi byte per cercare pattern TLV o STAP validi
        if not is_container and length > 10:
            # Check for STAP header pattern
            if val[2] <= 0x04 and int.from_bytes(val[3:5], 'big') < length:
                is_container = True
            # Check for BER-TLV pattern (tag > 0x40 and reasonable length)
            elif (val[0] & 0x1F) == 0x1F and val[1] < 0x80 and val[1] < length:
                is_container = True

        if not is_container: self.parser.bytes_covered += length

        # Metadata & Raw Tags storage
        raw_key = f"{tag:04X}_{tag_name}"
        full_key = f"{parent_path} > {raw_key}" if parent_path else raw_key
        dtype_hex = f"0x{dtype:02X}" if dtype is not None else ("BER" if mode == 'annex1c' else "T2L2")
        self.parser.results["raw_tags"].setdefault(full_key, []).append({
            "offset": f"0x{pos:08X}", "tag_id": f"0x{tag:04X}", "tag_name": tag_name,
            "data_type": dtype_hex, "length": length, "depth": depth,
            "data_hex": val.hex() if length <= 128 else f"{val[:128].hex()}..."
        })

        if tag in (0xC108, 0x0104): self.parser.msca_cert_raw = val
        elif tag in (0xC100, 0x0103, 0xC101, 0x7F21): self.parser.card_cert_raw = val

        if is_container:
            inner_start, inner_end = pos + h_size, pos + h_size + length
            if (tag & 0xFF00) == 0x7600:
                if length >= 2 and val[0] == 0x00: inner_start += 2
                self.parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            elif tag == 0x7F21: self.parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            elif mode == 'stap': self.parse_stap_recursive(inner_start, inner_end, depth + 1, full_key)
            else: self.parse_annex1c(inner_start, inner_end, depth + 1, full_key)
            return
