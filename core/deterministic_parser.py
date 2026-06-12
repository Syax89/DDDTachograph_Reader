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
from .logger import get_logger

_log = get_logger(__name__)


class CoverageTracker:
    """Tracks which byte ranges have been covered during parsing."""

    def __init__(self, total_size: int):
        self.total_size = total_size
        self.covered_ranges: List[Tuple[int, int]] = []
        self.classifications: Dict[str, int] = defaultdict(int)
        self.unknown_ranges: List[Tuple[int, int, bytes]] = []

    def mark_covered(self, start: int, end: int):
        """Record [start, end) as covered, without classifying it."""
        if start < end:
            self.covered_ranges.append((start, end))

    def mark_classified(self, start: int, end: int, classification: str):
        """Cover [start, end) and tally it under *classification* (e.g. Tag_0504)."""
        self.mark_covered(start, end)
        self.classifications[classification] += (end - start)

    def mark_padding(self, start: int, end: int, fill_byte: int):
        """Cover [start, end) as a padding run of *fill_byte*."""
        self.mark_covered(start, end)
        self.classifications[f"Padding(0x{fill_byte:02X})"] += (end - start)

    def mark_unknown(self, start: int, end: int, data: bytes):
        """Cover [start, end) as undecodable; the raw bytes are kept for triage."""
        self.mark_covered(start, end)
        self.classifications["Unknown"] += (end - start)
        self.unknown_ranges.append((start, end, data))

    def merge_ranges(self):
        """Collapse overlapping/adjacent covered ranges in place."""
        if not self.covered_ranges:
            return
        from core.coverage_utils import merge_intervals
        self.covered_ranges = merge_intervals(self.covered_ranges)

    def get_coverage_pct(self) -> float:
        """Covered bytes as a percentage of the file size."""
        if self.total_size == 0:
            return 0.0
        self.merge_ranges()
        from core.coverage_utils import coverage_pct
        return coverage_pct(sum(e - s for s, e in self.covered_ranges), self.total_size)

    def get_uncovered_ranges(self) -> List[Tuple[int, int]]:
        """Gaps between covered ranges, as [start, end) pairs in file order."""
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


    def __init__(self, parser=None, registry: Optional[DecoderRegistry] = None):
        self.parser = parser
        self.registry = registry or DecoderRegistry.instance()
        # Re-created with the real size at the start of parse().
        self.coverage: CoverageTracker = CoverageTracker(0)
        self.results: Dict[str, Any] = {}
        self.is_vu: bool = False
        self.generation: str = "Unknown"
        self._ef_data: Dict[Tuple[int, int], bytes] = {}
        self._ef_signatures: Dict[Tuple[int, int], bytes] = {}

    def parse(self, raw_data: bytes, is_vu: bool) -> Dict[str, Any]:
        """Structural pass: walk the whole file and account for every byte.

        Routes to the VU stream walkers (RecordArray for G2/G2.2, SID/TREP
        for G1) or the generic STAP/BER-TLV walk for card files, then
        attaches the coverage report and per-section breakdown.
        """
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

        if is_vu and self.generation in ("G2", "G2.2"):
            # Gen2/2.2 VU downloads are recordType-keyed RecordArray streams
            # (Annex 1C Appendix 7), not TLV: walking them as BER would
            # misread 0x76 as a 1-byte tag and classify garbage.
            self._parse_vu_stream(raw_data)
        elif is_vu and self.generation == "G1" and self._parse_g1_vu_stream(raw_data):
            # G1 VU downloads are SID/TREP messages with structure-determined
            # lengths (Annex 1B §2.2.6) — walked deterministically above;
            # falls through to the generic TLV walk when validation fails
            # (e.g. synthetic/truncated files).
            pass
        else:
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

        if not is_vu:
            refined = self._refine_card_generation()
            if refined != self.generation:
                self.generation = refined
                self.results["metadata"]["generation"] = self._gen_full_label(refined)

        # Store EF data/signature payloads for card signature verification.
        if not is_vu and (self._ef_data or self._ef_signatures):
            self.results["_ef_data"] = [(tag, dtype, payload)
                                        for (tag, dtype), payload in self._ef_data.items()]
            self.results["_ef_signatures"] = [(tag, dtype, payload)
                                              for (tag, dtype), payload in self._ef_signatures.items()]

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
        """Sniff generation from the 2-byte header (0x7631=G2.2, 0x762x=G2)."""
        if len(raw_data) < 2:
            return "Unknown"
        header = raw_data[:2]
        if header == b'\x76\x31':
            return "G2.2"
        elif header in (b'\x76\x21', b'\x76\x22'):
            return "G2"
        return "G1"

    def _gen_full_label(self, gen: str) -> str:
        """Expand the short generation code to the user-facing label."""
        if gen == "G2.2":
            return "G2.2 (Smart V2)"
        elif gen == "G2":
            return "G2 (Smart)"
        elif gen == "G1":
            return "G1 (Digital)"
        return "Unknown"

    def _refine_card_generation(self) -> str:
        """Refine the generation label for card files after parsing.

        Card files carry no 0x76 header, so header sniffing always yields G1.
        The Gen2 EF copies are marked by appendix dtype 0x02/0x03, and the
        Gen2v2-only EFs (0x0525-0x052A) mark a G2.2 card.
        """
        if self.generation not in ("G1", "Unknown"):
            return self.generation
        G22_CARD_TAGS = {0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A}
        has_g2 = False
        for occs in self.results.get("raw_tags", {}).values():
            for occ in occs:
                if occ.get("data_type") in ("0x02", "0x03"):
                    has_g2 = True
                    try:
                        tid = int(occ.get("tag_id", "0x0"), 16)
                    except (ValueError, TypeError):
                        continue
                    if tid in G22_CARD_TAGS:
                        return "G2.2"
        return "G2" if has_g2 else self.generation

    def _parse_vu_stream(self, raw_data: bytes):
        """Structural pass for Gen2/2.2 VU downloads.

        Classifies coverage along the section/RecordArray boundaries produced
        by :func:`core.vu_record_dispatcher.iter_vu_sections` (the same walk
        used for semantic decoding and signature verification). Bytes outside
        any section/record are classified as padding or unknown.
        """
        from .vu_record_dispatcher import iter_vu_sections, RECORD_TYPES, TREP_SECTIONS

        data = bytes(raw_data)
        for sec in iter_vu_sections(data):
            trep = sec["trep"]
            sec_name = TREP_SECTIONS.get(trep, f"TREP_0x{trep:02X}")
            marker_pos = sec["marker"]
            sec_key = f"76{trep:02X}_VU_{sec_name}"
            self.coverage.mark_classified(marker_pos, marker_pos + 2, f"Tag_76{trep:02X}")
            self.results.setdefault("raw_tags", {}).setdefault(sec_key, []).append({
                "offset": f"0x{marker_pos:08X}", "tag_id": f"0x76{trep:02X}",
                "tag_name": f"VU_{sec_name}", "data_type": "SID/TREP",
                "length": 2, "depth": 0, "is_spec_verified": True,
                "annex_ref": "Annex 1C Appendix 7", "generation": self.generation,
                "data_hex": data[marker_pos:marker_pos + 2].hex(),
            })
            for (pos, rt, rs, nr, end) in sec["records"]:
                name, confidence = RECORD_TYPES.get(rt, (f"Unknown_0x{rt:02X}", "low"))
                self.coverage.mark_classified(pos, end, f"Tag_76{trep:02X} > RecordType_{rt:02X}")
                payload = data[pos + 5:end]
                key = f"{sec_key} > {rt:02X}_{name}"
                self.results["raw_tags"].setdefault(key, []).append({
                    "offset": f"0x{pos:08X}", "tag_id": f"0x{rt:04X}",
                    "tag_name": name, "data_type": "RecordArray",
                    "length": end - pos - 5, "depth": 1,
                    "record_size": rs, "no_of_records": nr,
                    "is_spec_verified": confidence in ("high", "medium"),
                    "annex_ref": "Annex 1C Appendix 7", "generation": self.generation,
                    "data_hex": payload.hex() if len(payload) <= 128 else f"{payload[:128].hex()}..."
                })

        self._classify_gaps(data)

    def _classify_gaps(self, data: bytes):
        """Classify bytes not covered by the structural walk as padding or
        unknown (compute the gap list first: marking mutates the ranges)."""
        from core.coverage_utils import is_padding_block

        # Some download tools append a short 0x76 0x00 trailer after the last
        # section (not a normative TREP) — classify it instead of leaving
        # unknown bytes at EOF.
        for s, e in self.coverage.get_uncovered_ranges():
            if (e == len(data) and 2 <= e - s <= 8
                    and data[s] == 0x76 and data[s + 1] == 0x00):
                self.coverage.mark_classified(s, e, "Tag_7600")
                self.results.setdefault("raw_tags", {}).setdefault("7600_DownloadTrailer", []).append({
                    "offset": f"0x{s:08X}", "tag_id": "0x7600",
                    "tag_name": "DownloadTrailer", "data_type": "RAW",
                    "length": e - s, "depth": 0, "is_spec_verified": False,
                    "annex_ref": "", "generation": self.generation,
                    "data_hex": data[s:e].hex(),
                })
        gaps = self.coverage.get_uncovered_ranges()
        for s, e in gaps:
            chunk = data[s:e]
            pad = is_padding_block(chunk)
            if pad is not None:
                self.coverage.mark_padding(s, e, pad)
                self.results.setdefault("raw_tags", {}).setdefault("Padding", []).append({
                    "offset": f"0x{s:08X}", "tag_id": "0xPAD", "tag_name": "Padding",
                    "data_type": "RAW", "length": e - s, "depth": 0,
                    "data_hex": chunk[:128].hex() + ("..." if e - s > 128 else "")
                })
            else:
                self.coverage.mark_unknown(s, e, chunk)

    def _parse_g1_vu_stream(self, raw_data) -> bool:
        """Structural pass for G1 VU downloads via the deterministic TREP walk
        (Annex 1B §2.2.6). Returns False when the stream does not validate so
        the caller can fall back to the generic TLV walk."""
        from .g1_vu_walker import iter_g1_vu_messages, TREP_NAMES

        data = bytes(raw_data)
        messages = list(iter_g1_vu_messages(data))
        if not messages:
            return False

        for msg in messages:
            trep = msg["trep"]
            name = f"G1_VU_{TREP_NAMES[trep]}"
            key = f"76{trep:02X}_{name}"
            body = data[msg["body_start"]:msg["body_end"]]
            self.coverage.mark_classified(msg["pos"], msg["body_end"], f"Tag_76{trep:02X}")
            self.results.setdefault("raw_tags", {}).setdefault(key, []).append({
                "offset": f"0x{msg['pos']:08X}", "tag_id": f"0x76{trep:02X}",
                "tag_name": name, "data_type": "SID/TREP",
                "length": len(body), "depth": 0, "is_spec_verified": True,
                "annex_ref": "Annex 1B §2.2.6", "generation": "G1",
                "data_hex": body.hex() if len(body) <= 128 else f"{body[:128].hex()}..."
            })
            if msg["sig_len"]:
                sig = data[msg["body_end"]:msg["end"]]
                self.coverage.mark_classified(
                    msg["body_end"], msg["end"], f"Tag_76{trep:02X} > Signature")
                self.results["raw_tags"].setdefault(f"{key} > Signature", []).append({
                    "offset": f"0x{msg['body_end']:08X}", "tag_id": "0xSIG",
                    "tag_name": "RSA Signature", "data_type": "RSA",
                    "length": msg["sig_len"], "depth": 1, "is_spec_verified": True,
                    "annex_ref": "Annex 1B Appendix 11", "generation": "G1",
                    "data_hex": sig.hex(),
                })

        self._classify_gaps(data)
        return True

    def _get_tag_path(self, tag: int, parent_path: str) -> str:
        """Hierarchical raw_tags key for *tag* under *parent_path*."""
        dec = self.registry.get_decoder(tag)
        tag_name = dec.name if dec else f"BER_{tag:04X}"
        raw_key = f"{tag:04X}_{tag_name}"
        return f"{parent_path} > {raw_key}" if parent_path else raw_key

    def _skip_padding(self, raw_data: bytes, pos: int, end: int) -> int:
        """Advance over a top-level padding run, classifying and recording it."""
        from core.coverage_utils import is_padding_block, KNOWN_PADDING_BYTES
        start = pos
        while pos + 1 < end and is_padding_block(bytes([raw_data[pos], raw_data[pos+1]])) is not None:
            pos += 1
        if pos > start:
            pos += 1  # include the last byte of the padding run
        elif pos + 1 == end and raw_data[pos] in KNOWN_PADDING_BYTES:
            pos += 1  # lone trailing padding byte at buffer end
        if pos > start:
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
        """Same as :meth:`_skip_padding` but inside a container (relative offsets)."""
        from core.coverage_utils import is_padding_block, KNOWN_PADDING_BYTES
        start = pos
        while pos + 1 < end and is_padding_block(bytes([data[pos], data[pos+1]])) is not None:
            pos += 1
        if pos > start:
            pos += 1  # include the last byte of the padding run
        elif pos + 1 == end and data[pos] in KNOWN_PADDING_BYTES:
            pos += 1  # lone trailing padding byte at buffer end
        if pos > start:
            self.coverage.mark_padding(base_offset + start, base_offset + pos, data[start])

            length = pos - start
            key = f"{parent_path} > Padding" if parent_path else "Padding"
            self.results.setdefault("raw_tags", {}).setdefault(key, []).append({
                "offset": f"0x{(base_offset + start):08X}", "tag_id": "0xPAD", "tag_name": "Padding",
                "data_type": "RAW", "length": length, "depth": depth,
                "data_hex": data[start:pos][:128].hex() + ("..." if length > 128 else "")
            })
        return pos

    def _try_read_stap(self, raw_data: bytes, pos: int, end: int) -> Optional[Tuple[int, int, int, bytes, Optional[int]]]:
        """Try a STAP record at *pos*: 5-byte T2L2 header with sanity checks.

        Returns ``(tag, length, header_size, payload, dtype)`` or None when
        the bytes cannot be a valid STAP record (reserved tag, dtype > 0x0F,
        oversized or truncated length).
        """
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
        """Try a BER-TLV record at *pos*; same tuple as :meth:`_try_read_stap`, dtype None."""
        tag_val, length, hdr_size = read_ber_tlv_header(raw_data, pos)
        if tag_val is None:
            return None
        if pos + hdr_size + length > end:
            return None
        payload = raw_data[pos + hdr_size:pos + hdr_size + length]
        return (tag_val, length, hdr_size, payload, None)

    def _parse_at_position(self, raw_data: bytes, pos: int, end: int) -> Optional[Tuple[int, int, int, bytes, Any]]:
        """Read whichever encoding yields a registered tag at *pos* (STAP first)."""
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
        """Append the tag occurrence to raw_tags and capture certificate payloads."""
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
                if length == 194:  # keep the G1 copy for the G1 RSA chain
                    self.parser.msca_cert_g1 = payload
            elif tag in (0xC100, 0x0103, 0xC101, 0x7F21):
                self.parser.card_cert_raw = payload
                if length == 194:
                    self.parser.card_cert_g1 = payload

    def _dispatch_decoder(self, tag: int, payload: bytes, dtype: Optional[int] = None):
        """Run the registered decoder for *tag*, respecting card/VU scope.

        Signature blocks (dtype 1/3/11/15) are collected for verification but
        never dispatched. Decoder exceptions are logged, not propagated: a
        broken field decoder must not abort the structural walk.
        """
        # Collect EF data/signature pairs for later verification.
        if self.parser and not self.is_vu and dtype is not None and dtype <= 0x03:
            if dtype in (0x00, 0x02):
                self._ef_data[(tag, dtype)] = payload
            elif dtype in (0x01, 0x03):
                self._ef_signatures[(tag, dtype)] = payload

        if dtype in (1, 3, 11, 15):
            return

        dec = self.registry.get_decoder(tag)
        if dec and dec.decoder_fn:
            # Context filter: card-only decoders must not run on VU files
            # (and vice versa) — same FID values can collide across contexts.
            if (dec.card_only and self.is_vu) or (dec.vu_only and not self.is_vu):
                return
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
                _log.warning("Decoder 0x%04X (%s) dispatch failed", tag,
                           dec.name if dec else "unknown", exc_info=True)

    def _parse_container(self, tag: int, payload: bytes, container_offset: int, depth: int, parent_path: str):
        """Recursively walk a container payload (STAP or BER per generation)."""
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


