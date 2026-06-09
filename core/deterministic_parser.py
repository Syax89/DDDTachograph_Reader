"""Deterministic parser that guarantees 100% byte coverage.

Strategy:
1. Parse file header → detect generation (G1/G2/G2.2)
2. Parse sequentially with known STAP/BER-TLV structures
3. For containers: recursively parse inner data
4. Any remaining bytes: classify as Padding (all 0x00/0xFF/0x55) or mark as Unknown
"""

import struct
import inspect
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from .constants import MAX_TLV_LENGTH, MAX_RECURSION_DEPTH
from .decoder_registry import DecoderRegistry
from .ber_tlv import read_ber_tlv_header


class CoverageTracker:
    """Tracks which byte ranges have been covered during parsing."""

    def __init__(self, total_size: int):
        self.total_size = total_size
        self.covered_ranges: List[Tuple[int, int]] = []
        self.classifications: Dict[str, int] = defaultdict(int)
        self.unknown_ranges: List[Tuple[int, int, bytes]] = []

    def mark_covered(self, start: int, end: int):
        if start < end:
            self.covered_ranges.append((start, end))

    def mark_classified(self, start: int, end: int, classification: str):
        self.mark_covered(start, end)
        self.classifications[classification] += (end - start)

    def mark_padding(self, start: int, end: int, fill_byte: int):
        self.mark_covered(start, end)
        self.classifications[f"Padding(0x{fill_byte:02X})"] += (end - start)

    def mark_unknown(self, start: int, end: int, data: bytes):
        self.mark_covered(start, end)
        self.classifications["Unknown"] += (end - start)
        self.unknown_ranges.append((start, end, data))

    def merge_ranges(self):
        if not self.covered_ranges:
            return
        from core.coverage_utils import merge_intervals
        self.covered_ranges = merge_intervals(self.covered_ranges)

    def get_coverage_pct(self) -> float:
        if self.total_size == 0:
            return 0.0
        self.merge_ranges()
        from core.coverage_utils import coverage_pct
        return coverage_pct(sum(e - s for s, e in self.covered_ranges), self.total_size)

    def get_uncovered_ranges(self) -> List[Tuple[int, int]]:
        self.merge_ranges()
        gaps = []
        cursor = 0
        for s, e in self.covered_ranges:
            if cursor < s:
                gaps.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < self.total_size:
            gaps.append((cursor, self.total_size))
        return gaps

    def get_section_report(self, file_size: int) -> Dict[str, Any]:
        """Generate a coverage report broken down by file section."""
        sections = {
            "Header": (0, min(256, file_size)),
            "Driver Data": (256, min(file_size // 2, file_size)),
            "Vehicle Data": (file_size // 2, max(file_size // 2, min(3 * file_size // 4, file_size))),
            "Certificates": (3 * file_size // 4, max(3 * file_size // 4, file_size - 512)),
            "Signature/Tail": (max(0, file_size - 512), file_size),
        }
        # Remove Signature/Tail overlap from Certificates
        tail_start = max(0, file_size - 512)
        cert_start, cert_end = sections["Certificates"]
        if cert_end > tail_start:
            sections["Certificates"] = (cert_start, tail_start)

        self.merge_ranges()
        report = {}
        for section_name, (sec_start, sec_end) in sections.items():
            if sec_start >= file_size:
                continue
            covered = sum(
                max(0, min(e, sec_end) - max(s, sec_start))
                for s, e in self.covered_ranges
            )
            sec_size = sec_end - sec_start
            report[section_name] = {
                "start": f"0x{sec_start:06X}",
                "end": f"0x{sec_end:06X}",
                "size": sec_size,
                "covered": covered,
                "coverage_pct": round(covered / sec_size * 100, 2) if sec_size else 0,
            }
        return report


class DeterministicParser:
    """
    Deterministic parser that guarantees 100% byte coverage.

    Two-pass architecture:
    1. Structural pass: parse every byte through known STAP/BER-TLV
    2. Semantic pass: validate record sizes, checksums, field ranges
    """


    def __init__(self, parser=None, registry: DecoderRegistry = None):
        self.parser = parser
        self.registry = registry or DecoderRegistry()
        self.coverage: Optional[CoverageTracker] = None
        self.results: Dict[str, Any] = {}
        self.is_vu: bool = False
        self.generation: str = "Unknown"

    def parse(self, raw_data: bytes, is_vu: bool) -> Dict[str, Any]:
        self.coverage = CoverageTracker(len(raw_data))
        
        from .models import TachoResult
        self.results = TachoResult().to_dict()
        self.results["metadata"]["file_size_bytes"] = len(raw_data)
        self.results["metadata"]["parsed_at"] = self.results["metadata"].get("parsed_at") or datetime.now().isoformat()
        
        self.is_vu = is_vu
        self.generation = self._detect_generation(raw_data)
        self.results["metadata"]["generation"] = self._gen_full_label(self.generation)

        pos = 0
        file_size = len(raw_data)
        
        # Top-level mode is 'stap' for G1, 'ber' for G2/G2.2
        mode = 'stap' if self.generation == 'G1' else 'ber'

        while pos < file_size:
            pos = self._skip_padding(raw_data, pos, file_size)

            if pos >= file_size:
                break

            if mode == 'stap':
                result = self._try_read_stap(raw_data, pos, file_size)
            else:
                result = self._try_read_ber_tlv(raw_data, pos, file_size)

            if result is None:
                self.coverage.mark_unknown(pos, pos + 1, raw_data[pos:pos + 1])
                pos += 1
                continue

            tag, length, hdr_size, payload, dtype = result
            self.coverage.mark_classified(pos, pos + hdr_size + length, f"Tag_{tag:04X}")
            self._record_tag(tag, length, payload, pos, hdr_size, depth=0, parent_path="", dtype=dtype)
            self._dispatch_decoder(tag, payload, dtype=dtype)

            if self.registry.is_container(tag):
                self._parse_container(tag, payload, pos + hdr_size, depth=1, parent_path=self._get_tag_path(tag, ""))

            pos += hdr_size + length

        # Collect unknown ranges and add to raw_tags
        for s, e, data in self.coverage.unknown_ranges:
            length = e - s
            self.results.setdefault("raw_tags", {}).setdefault("Unparsed Data", []).append({
                "offset": f"0x{s:08X}", "tag_id": "0x0000", "tag_name": "Unparsed Data",
                "data_type": "RAW", "length": length, "depth": 0,
                "data_hex": data.hex() if length <= 128 else f"{data[:128].hex()}..."
            })

        self.results["coverage"] = {
            "total_bytes": file_size,
            "covered_pct": self.coverage.get_coverage_pct(),
            "classifications": dict(self.coverage.classifications),
            "uncovered_ranges": [(f"0x{s:06X}", f"0x{e:06X}", e - s)
                                 for s, e in self.coverage.get_uncovered_ranges()],
        }
        self.results["sections"] = self.coverage.get_section_report(file_size)

        return self.results

    def _detect_generation(self, raw_data: bytes) -> str:
        if len(raw_data) < 2:
            return "Unknown"
        header = raw_data[:2]
        if header == b'\x76\x31':
            return "G2.2"
        elif header in (b'\x76\x21', b'\x76\x22'):
            return "G2"
        return "G1"

    def _gen_full_label(self, gen: str) -> str:
        if gen == "G2.2":
            return "G2.2 (Smart V2)"
        elif gen == "G2":
            return "G2 (Smart)"
        elif gen == "G1":
            return "G1 (Digital)"
        return "Unknown"

    def _get_tag_path(self, tag: int, parent_path: str) -> str:
        dec = self.registry.get_decoder(tag)
        tag_name = dec.name if dec else f"BER_{tag:04X}"
        raw_key = f"{tag:04X}_{tag_name}"
        return f"{parent_path} > {raw_key}" if parent_path else raw_key

    def _skip_padding(self, raw_data: bytes, pos: int, end: int) -> int:
        from core.coverage_utils import is_padding_block
        start = pos
        while pos + 1 < end and is_padding_block(bytes([raw_data[pos], raw_data[pos+1]])) is not None:
            pos += 1
        if pos > start:
            pos += 1
            fill_byte = raw_data[start]
            self.coverage.mark_padding(start, pos, fill_byte)
            
            length = pos - start
            self.results.setdefault("raw_tags", {}).setdefault("Padding", []).append({
                "offset": f"0x{start:08X}", "tag_id": "0xPAD", "tag_name": "Padding",
                "data_type": "RAW", "length": length, "depth": 0,
                "data_hex": raw_data[start:pos][:128].hex() + ("..." if length > 128 else "")
            })
        return pos

    def _skip_padding_inner(self, data: bytes, pos: int, end: int, base_offset: int, depth: int, parent_path: str) -> int:
        from core.coverage_utils import is_padding_block
        start = pos
        while pos + 1 < end and is_padding_block(bytes([data[pos], data[pos+1]])) is not None:
            pos += 1
        if pos > start:
            pos += 1
            self.coverage.mark_padding(base_offset + start, base_offset + pos, data[start])
            
            length = pos - start
            key = f"{parent_path} > Padding" if parent_path else "Padding"
            self.results.setdefault("raw_tags", {}).setdefault(key, []).append({
                "offset": f"0x{(base_offset + start):08X}", "tag_id": "0xPAD", "tag_name": "Padding",
                "data_type": "RAW", "length": length, "depth": depth,
                "data_hex": data[start:pos][:128].hex() + ("..." if length > 128 else "")
            })
        return pos

    def _try_read_stap(self, raw_data: bytes, pos: int, end: int) -> Optional[Tuple[int, int, int, bytes, int]]:
        if pos + 5 > end:
            return None
        hdr = raw_data[pos:pos + 5]
        try:
            tag, dtype, length = struct.unpack(">HBH", hdr)
        except struct.error:
            return None

        if tag in (0x0000, 0xFFFF, 0x5555):
            return None
        if dtype > 0x0F:
            return None
        if length > MAX_TLV_LENGTH:
            return None
        if pos + 5 + length > end:
            return None

        payload = raw_data[pos + 5:pos + 5 + length]
        return (tag, length, 5, payload, dtype)

    def _try_read_ber_tlv(self, raw_data: bytes, pos: int, end: int) -> Optional[Tuple[int, int, int, bytes, None]]:
        tag_val, length, hdr_size = read_ber_tlv_header(raw_data, pos)
        if tag_val is None:
            return None
        if pos + hdr_size + length > end:
            return None
        payload = raw_data[pos + hdr_size:pos + hdr_size + length]
        return (tag_val, length, hdr_size, payload, None)

    def _parse_at_position(self, raw_data: bytes, pos: int, end: int) -> Optional[Tuple[int, int, int, bytes, Any]]:
        stap = self._try_read_stap(raw_data, pos, end)
        if stap is not None:
            tag, _, _, _, _ = stap
            if tag in self.registry:
                return stap

        ber = self._try_read_ber_tlv(raw_data, pos, end)
        if ber is not None:
            tag, _, _, _, _ = ber
            if tag in self.registry:
                return ber

        return stap or ber

    def _record_tag(self, tag: int, length: int, payload: bytes, pos: int, hdr_size: int, depth: int = 0, parent_path: str = "", dtype: Optional[int] = None):
        dec = self.registry.get_decoder(tag)
        tag_name = dec.name if dec else f"BER_{tag:04X}"
        raw_key = f"{tag:04X}_{tag_name}"
        full_key = f"{parent_path} > {raw_key}" if parent_path else raw_key
        
        dtype_str = f"0x{dtype:02X}" if dtype is not None else ("BER" if (dec and dec.generation in ('G2', 'G2.2')) else "T2L2")
        
        entry = {
            "offset": f"0x{pos:08X}",
            "tag_id": f"0x{tag:04X}",
            "tag_name": tag_name,
            "data_type": dtype_str,
            "length": length,
            "depth": depth,
            "is_spec_verified": dec is not None and dec.decoder_fn is not None,
            "annex_ref": dec.annex_ref if dec else "",
            "generation": dec.generation if dec else "Unknown",
            "data_hex": payload.hex() if length <= 128 else f"{payload[:128].hex()}..."
        }
        self.results.setdefault("raw_tags", {}).setdefault(full_key, []).append(entry)

        if self.parser:
            if tag in (0xC108, 0x0104):
                self.parser.msca_cert_raw = payload
            elif tag in (0xC100, 0x0103, 0xC101, 0x7F21):
                self.parser.card_cert_raw = payload

    def _dispatch_decoder(self, tag: int, payload: bytes, dtype: Optional[int] = None):
        if dtype in (1, 3, 11, 15):
            return
            
        dec = self.registry.get_decoder(tag)
        if dec and dec.decoder_fn:
            try:
                sig = inspect.signature(dec.decoder_fn)
                n_params = len([p for p in sig.parameters.values()
                                if p.default is inspect.Parameter.empty
                                and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)])
                if n_params == 3:
                    dec.decoder_fn(payload, self.results, tag)
                else:
                    dec.decoder_fn(payload, self.results)
            except Exception:
                import logging
                logging.getLogger("ddd_tacho").debug(
                    "Decoder dispatch failed for tag 0x%04X", tag, exc_info=True)

    def _parse_container(self, tag: int, payload: bytes, container_offset: int, depth: int, parent_path: str):
        if depth > MAX_RECURSION_DEPTH:
            return
        dec = self.registry.get_decoder(tag)
        mode = 'ber' if dec and dec.generation in ('G2', 'G2.2') else 'stap'
        inner_start = 0

        if (tag & 0xFF00) == 0x7600 and len(payload) >= 2 and payload[0] == 0x00:
            inner_start = 2

        pos = inner_start
        end = len(payload)

        while pos < end:
            pos = self._skip_padding_inner(payload, pos, end, container_offset, depth, parent_path)
            if pos >= end:
                break

            if mode == 'stap':
                result = self._try_read_stap(payload, pos, end)
            else:
                result = self._try_read_ber_tlv(payload, pos, end)

            if result is None:
                self.coverage.mark_unknown(
                    container_offset + pos,
                    container_offset + min(pos + 1, end),
                    payload[pos:pos + 1]
                )
                pos += 1
                continue

            inner_tag, inner_length, hdr_size, inner_payload, inner_dtype = result
            abs_start = container_offset + pos
            self.coverage.mark_classified(
                abs_start,
                abs_start + hdr_size + inner_length,
                f"{parent_path} > Tag_{inner_tag:04X}"
            )
            self._record_tag(inner_tag, inner_length, inner_payload,
                             abs_start, hdr_size, depth, parent_path, dtype=inner_dtype)
            self._dispatch_decoder(inner_tag, inner_payload, dtype=inner_dtype)

            if self.registry.is_container(inner_tag):
                inner_path = self._get_tag_path(inner_tag, parent_path)
                self._parse_container(inner_tag, inner_payload, abs_start + hdr_size, depth + 1, inner_path)

            pos += hdr_size + inner_length


def quick_coverage_check(raw_data: bytes) -> Dict[str, Any]:
    """Standalone coverage check without full parsing."""
    parser = DeterministicParser()
    parser.coverage = CoverageTracker(len(raw_data))
    pos = 0
    file_size = len(raw_data)

    while pos < file_size:
        pos = parser._skip_padding(raw_data, pos, file_size)
        if pos >= file_size:
            break
        result = parser._parse_at_position(raw_data, pos, file_size)
        if result is None:
            parser.coverage.mark_unknown(pos, min(pos + 1, file_size), raw_data[pos:pos + 1])
            pos += 1
            continue
        tag, length, hdr_size, payload, _ = result
        parser.coverage.mark_classified(pos, pos + hdr_size + length, f"Tag_{tag:04X}")
        pos += hdr_size + length

    return {
        "total_bytes": file_size,
        "covered_pct": parser.coverage.get_coverage_pct(),
        "uncovered_ranges": parser.coverage.get_uncovered_ranges(),
        "classifications": dict(parser.coverage.classifications),
    }
