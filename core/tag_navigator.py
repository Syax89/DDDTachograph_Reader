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

    def parse_annex1c(self, start_pos, end_pos, depth, parent_path):
        if depth > 12: return
        pos = start_pos
        while pos < end_pos:
            matched = False
            # 1. BER-TLV multi-byte
            if pos < end_pos and (self.parser.raw_data[pos] & 0x1F) == 0x1F:
                tag, length, h = self.read_ber_tlv(self.parser.raw_data, pos)
                if tag is not None and length is not None and pos + h + length <= end_pos:
                    hi = tag >> 8 if tag > 0xFF else 0
                    if tag in self.parser.TAGS or hi in (0x7F, 0x5F, 0xBF):
                        val = self.parser._safe_read(pos + h, length)
                        if val is not None:
                            self.record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                            pos += h + length; matched = True
            # 2. Tag2+Len2
            if not matched and pos + 4 <= end_pos:
                raw4 = self.parser._safe_read(pos, 4)
                if raw4:
                    t2, l2 = struct.unpack(">HH", raw4)
                    if t2 in self.parser.TAGS and 0 <= l2 <= (end_pos - pos - 4):
                        val = self.parser._safe_read(pos + 4, l2)
                        if val is not None:
                            self.record_and_dispatch(t2, l2, val, pos, 4, depth, parent_path, mode='annex1c')
                            pos += 4 + l2; matched = True
            # 3. BER-TLV single-byte
            if not matched:
                tag, length, h = self.read_ber_tlv(self.parser.raw_data, pos)
                if tag is not None and tag in self.parser.TAGS and pos + h + length <= end_pos:
                    val = self.parser._safe_read(pos + h, length)
                    if val is not None:
                        self.record_and_dispatch(tag, length, val, pos, h, depth, parent_path, mode='annex1c')
                        pos += h + length; matched = True
            if not matched: pos += 1

    def parse_stap_recursive(self, start_pos, end_pos, depth=0, parent_path=""):
        if depth > 12: return
        pos = start_pos
        while pos + 5 <= end_pos:
            try:
                hdr = self.parser._safe_read(pos, 5)
                if not hdr: break
                tag, dtype, length = struct.unpack(">HBH", hdr)
                
                # Validity check: tag must not be 0/0xFFFF, dtype must be 0-4, length must fit
                if tag in (0, 0xFFFF) or dtype > 0x04 or pos + 5 + length > end_pos:
                    pos += 1; continue
                
                # Check if tag is known or if it looks like a valid STAP header
                tag_name = self.parser.TAGS.get(tag)
                if not tag_name:
                    tag_name = f"Unknown_{tag:04X}"

                val = self.parser._safe_read(pos + 5, length)
                if val is None:
                    pos += 1; continue
                self.record_and_dispatch(tag, length, val, pos, 5, depth, parent_path, mode='stap', dtype=dtype)
                pos += 5 + length
            except Exception: pos += 1

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

        is_container = False
        if mode == 'stap' and dtype == 0x04: is_container = True
        if tag in (0x7621, 0x7631, 0x7F21, 0x7D21, 0xAD21): is_container = True
        if mode == 'annex1c' and tag > 0xFF:
            first_byte = (tag >> ((tag.bit_length() - 1) // 8 * 8)) & 0xFF
            if first_byte & 0x20: is_container = True

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
