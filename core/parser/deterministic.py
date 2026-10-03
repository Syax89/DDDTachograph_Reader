"""Deterministic parser that guarantees 100% byte coverage.

Strategy:
1. Parse file header → detect generation (G1/G2/G2.2)
2. Parse sequentially with known STAP/BER-TLV structures
3. For containers: recursively parse inner data
4. Any remaining bytes: classify as Padding (all 0x00/0xFF/0x55) or mark as Unknown
"""

import struct
import inspect
import heapq
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from core.utils.constants import MAX_TLV_LENGTH, MAX_RECURSION_DEPTH, looks_like_g2_certificate
from core.registry.registry import DecoderRegistry
from core.utils.ber_tlv import read_ber_tlv_header
from core.utils.logger import get_logger

_log = get_logger(__name__)

# TRTP marker (byte after the 0x76 SID) → generation, from the Annex 1C
# consolidated TRTP table (§ "There are seven types of data transfer"):
#   Overview 01/21/31, Activities 02/22/32, Events and faults 03/23/33,
#   Detailed speed 04/24/24, Technical data 05/25/35, Card download 06.
#   ("TRTP 00, 31, 32, 33 and 35 are used for Generation 2 version 2" and
#   "TRTP 24 is used for Generation 2, for version 1 and version 2".)
# Only 0x24 (Detailed speed) is shared by G2 and G2.2 and is treated as G2 —
# the annex defines NO 0x34 marker. Download interface version (TREP 00) is
# Gen 2.2 only. 0x11/0x14 are reserved for manufacturer-specific requests and
# keep the pre-Batch-4 G1 default.
# A selective VU download can start with ANY of these, not just the Overview
# marker, so the leading marker (never a byte pair inside a record) selects the
# generation.
_TRTP_GENERATION = {
    0x00: "G2.2",
    0x01: "G1", 0x02: "G1", 0x03: "G1", 0x04: "G1", 0x05: "G1", 0x06: "G1",
    0x11: "G1", 0x14: "G1",
    0x21: "G2", 0x22: "G2", 0x23: "G2", 0x24: "G2", 0x25: "G2",
    0x31: "G2.2", 0x32: "G2.2", 0x33: "G2.2", 0x35: "G2.2",
}


class CoverageTracker:
    """Tracks which byte ranges have been covered during parsing."""

    def __init__(self, total_size: int):
        self.total_size = total_size
        self.covered_ranges: List[Tuple[int, int]] = []
        self.classifications: Dict[str, int] = defaultdict(int)
        self.classification_ranges: List[Tuple[int, int, str]] = []
        self.unknown_ranges: List[Tuple[int, int, bytes]] = []

    def mark_covered(self, start: int, end: int):
        """Record [start, end) as covered, without classifying it."""
        start, end = self._bounded_range(start, end)
        if start < end:
            self.covered_ranges.append((start, end))

    def mark_classified(self, start: int, end: int, classification: str):
        """Cover [start, end) and tally it under *classification* (e.g. Tag_0504)."""
        start, end = self._bounded_range(start, end)
        self.mark_covered(start, end)
        if start < end:
            self.classifications[classification] += end - start
            self.classification_ranges.append((start, end, classification))

    def mark_padding(self, start: int, end: int, fill_byte: int):
        """Cover [start, end) as a padding run of *fill_byte*."""
        self.mark_classified(start, end, f"Padding(0x{fill_byte:02X})")

    def mark_unknown(self, start: int, end: int, data: bytes):
        """Cover [start, end) as undecodable; the raw bytes are kept for triage."""
        start, end = self._bounded_range(start, end)
        self.mark_classified(start, end, "Unknown")
        if start < end:
            # Keep only a bounded sample and merge adjacent bytes. A corrupt
            # stream must not create one Python object per byte or repeatedly
            # copy an unbounded raw range.
            sample = data[:min(end - start, 128)]
            if self.unknown_ranges and self.unknown_ranges[-1][1] == start:
                previous_start, _previous_end, previous_sample = self.unknown_ranges[-1]
                remaining = 128 - len(previous_sample)
                self.unknown_ranges[-1] = (
                    previous_start, end, previous_sample + sample[:remaining])
            else:
                self.unknown_ranges.append((start, end, sample))

    def _bounded_range(self, start: int, end: int) -> Tuple[int, int]:
        """Clamp an external byte interval to this tracker's file bounds."""
        return max(0, start), min(self.total_size, end)

    def merge_ranges(self):
        """Collapse overlapping/adjacent covered ranges in place."""
        if not self.covered_ranges:
            return
        from core.utils.coverage import merge_intervals
        self.covered_ranges = merge_intervals(self.covered_ranges)

    def get_coverage_pct(self) -> float:
        """Covered bytes as a percentage of the file size."""
        from core.utils.coverage import coverage_pct
        return coverage_pct(self.get_accounted_bytes(), self.total_size)

    def get_accounted_bytes(self) -> int:
        """Return the size of the union of all structurally accounted ranges."""
        self.merge_ranges()
        return sum(end - start for start, end in self.covered_ranges)

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

    def get_non_overlapping_classifications(self) -> Dict[str, int]:
        """Return classification totals without counting nested ranges twice.

        Parent containers are classified before their children. The most recent
        range owns overlaps, leaving parents with only their header and bytes
        that were not structurally classified more specifically.
        """
        events: Dict[int, List[Tuple[int, int, str]]] = defaultdict(list)
        boundaries: set[int] = set()
        for order, (start, end, classification) in enumerate(self.classification_ranges):
            events[start].append((order, end, classification))
            boundaries.update((start, end))
        for start, end in self.covered_ranges:
            boundaries.update((start, end))
        if not boundaries:
            return {}

        totals: Dict[str, int] = defaultdict(int)
        active: List[Tuple[int, int, str]] = []
        points = sorted(boundaries)
        for index, start in enumerate(points[:-1]):
            for order, end, classification in events[start]:
                heapq.heappush(active, (-order, end, classification))
            end = points[index + 1]
            while active and active[0][1] <= start:
                heapq.heappop(active)
            if active:
                totals[active[0][2]] += end - start
            elif any(range_start <= start < range_end for range_start, range_end in self.covered_ranges):
                totals["Unclassified"] += end - start
        return dict(totals)

    def get_section_report(self, file_size: int) -> Dict[str, Any]:
        """Generate a coverage report partitioned into neutral byte ranges.

        These ranges are a display-oriented partition of the file, not parsed
        semantic sections. Their half-open offsets are included in each key so
        callers cannot infer a file format structure from the report label.
        """
        file_size = max(0, file_size)
        header_end = min(256, file_size)
        driver_end = max(header_end, min(file_size // 2, file_size))
        vehicle_end = max(driver_end, min(3 * file_size // 4, file_size))
        tail_start = max(vehicle_end, file_size - 512)
        ranges = (
            (0, header_end),
            (header_end, driver_end),
            (driver_end, vehicle_end),
            (vehicle_end, tail_start),
            (tail_start, file_size),
        )

        self.merge_ranges()
        report = {}
        for sec_start, sec_end in ranges:
            if sec_start >= sec_end:
                continue
            label = f"Bytes [0x{sec_start:06X}, 0x{sec_end:06X})"
            covered = sum(
                max(0, min(e, sec_end) - max(s, sec_start))
                for s, e in self.covered_ranges
            )
            sec_size = sec_end - sec_start
            report[label] = {
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
        self._ef_data: List[Tuple[int, int, bytes]] = []
        self._ef_signatures: List[Tuple[int, int, bytes]] = []

    def parse(self, raw_data: bytes, is_vu: bool) -> Dict[str, Any]:
        """Structural pass: walk the whole file and account for every byte.

        Routes to the VU stream walkers (RecordArray for G2/G2.2, SID/TREP
        for G1) or the generic STAP/BER-TLV walk for card files, then
        attaches the coverage report and per-section breakdown.
        """
        self.coverage = CoverageTracker(len(raw_data))
        self._ef_data = []
        self._ef_signatures = []

        from core.registry.models import TachoResult
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
                self._dispatch_decoder(tag, payload, dtype=dtype, offset=pos)

                if self.registry.is_container(tag, generation=self.generation, is_vu=self.is_vu, dtype=dtype):
                    self._parse_container(tag, payload, pos + hdr_size, depth=1,
                                          parent_path=self._get_tag_path(tag, "", dtype=dtype))

                pos += hdr_size + length

        if not is_vu:
            refined = self._refine_card_generation()
            if refined != self.generation:
                self.generation = refined
                self.results["metadata"]["generation"] = self._gen_full_label(refined)

        # Specific-condition type 0x03/0x04 mean different things per generation
        # (see _finalize_specific_conditions). The decoders run before a card's
        # generation is refined, so correct the labels once it is final.
        self._finalize_specific_conditions()

        # Store EF data/signature payloads for card signature verification.
        if not is_vu and (self._ef_data or self._ef_signatures):
            self.results["_ef_data"] = self._ef_data
            self.results["_ef_signatures"] = self._ef_signatures

        # Collect unknown ranges and add to raw_tags
        for s, e, data in self.coverage.unknown_ranges:
            length = e - s
            self.results.setdefault("raw_tags", {}).setdefault("Unparsed Data", []).append({
                "offset": f"0x{s:08X}", "tag_id": "0x0000", "tag_name": "Unparsed Data",
                "data_type": "RAW", "length": length, "depth": 0,
                "data_hex": data.hex() if length <= 128 else f"{data[:128].hex()}..."
            })

        classifications = self.coverage.get_non_overlapping_classifications()
        from core.utils.coverage import coverage_metrics
        metrics = coverage_metrics(
            file_size, self.coverage.get_accounted_bytes(), classifications
        )
        self.results["coverage"] = {
            "total_bytes": file_size,
            # Legacy name retained for API compatibility. It is byte-accounted
            # coverage, not a semantic decoding rate.
            "covered_pct": metrics["byte_accounted_pct"],
            "classifications": classifications,
            "uncovered_ranges": [(f"0x{s:06X}", f"0x{e:06X}", e - s)
                                  for s, e in self.coverage.get_uncovered_ranges()],
            **metrics,
        }
        self.results["metadata"]["coverage_pct"] = self.results["coverage"]["covered_pct"]
        self.results["sections"] = self.coverage.get_section_report(file_size)

        return self.results

    def _finalize_specific_conditions(self):
        """Apply generation-1 semantics to SpecificConditions records.

        The card/VU decoders always emit the generation-2 labels because a card's
        generation is only resolved after parsing. In generation 1 (Annex 1C
        §2.154) type 0x03 is a single ``Ferry / Train crossing`` code and 0x04 is
        RFU; both differ from generation 2. Relabel/drop once the generation is
        known. Types 0x01/0x02 are identical across generations.
        """
        if self.generation != "G1":
            return
        records = self.results.get("specific_conditions")
        if not records:
            return
        from core.utils.event_codes import specific_condition_label
        finalized = []
        for rec in records:
            code = rec.get("type_code")
            if code == 0x04:
                continue  # RFU in generation 1
            if code == 0x03:
                rec["condition"] = specific_condition_label(code, generation="G1")
            finalized.append(rec)
        self.results["specific_conditions"] = finalized

    def _detect_generation(self, raw_data: bytes) -> str:
        """Detect the generation from the leading SID/TREP marker.

        A VU download is ``SID 0x76 + TREP`` messages; a selective download may
        start with ANY TRTP marker, not just the Overview one (e.g. a Gen 2.2
        file that starts with Activities ``76 32`` or the Download interface
        version ``76 00``). The leading marker — which is record framing, never
        a byte pair inside a record — selects the generation via
        ``_TRTP_GENERATION`` (Annex 1C TRTP table). Anything else (no leading
        0x76 message marker, e.g. a card EF image) keeps the G1/Unknown default
        so the card refinement path still applies.
        """
        if len(raw_data) < 2:
            return "Unknown"
        if raw_data[0] == 0x76:
            gen = _TRTP_GENERATION.get(raw_data[1])
            if gen is not None:
                return gen
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
        A card's generation is decided by *generation-specific EF evidence*,
        never by the mere presence of a dtype-0x02/0x03 record: any bytes can
        be mis-framed as a STAP record, so a single stray dtype-0x02 record
        must not flip a valid G1 card to G2 (XD-F3). The Gen2 copies of the
        universal Application_Identification (0x0501) and the Gen2-only EFs
        VehicleUnits_Used / GNSS_Places (0x0523/0x0524) mark a G2 card; the
        Gen2v2-only EFs (0x0525-0x0530, 0x0540) mark a G2.2 card. 0x052A is
        not a V2 marker.
        """
        if self.generation not in ("G1", "Unknown"):
            return self.generation
        G22_CARD_TAGS = {0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x0530, 0x0540}
        # Gen2-exclusive EF copies that exist with the dtype-0x02 appendix only
        # on a Gen2 card (0x0501 is universal, 0x0523/0x0524 are Gen2-only).
        G2_CARD_MARKERS = {0x0501, 0x0523, 0x0524}
        has_g2 = False
        for occs in self.results.get("raw_tags", {}).values():
            for occ in occs:
                if occ.get("data_type") not in ("0x02", "0x03"):
                    continue
                try:
                    tid = int(occ.get("tag_id", "0x0"), 16)
                except (ValueError, TypeError):
                    continue
                if tid in G22_CARD_TAGS:
                    return "G2.2"
                if tid in G2_CARD_MARKERS:
                    has_g2 = True
        return "G2" if has_g2 else self.generation

    def _parse_vu_stream(self, raw_data: bytes):
        """Structural pass for Gen2/2.2 VU downloads.

        Classifies coverage along the section/RecordArray boundaries produced
        by :func:`core.vu_record_dispatcher.iter_vu_sections` (the same walk
        used for semantic decoding and signature verification). Bytes outside
        any section/record are classified as padding or unknown.
        """
        from core.parser.vu_dispatcher import (
            iter_vu_sections, RECORD_TYPES, TREP_SECTIONS, NORMATIVE_RECORD_TYPES)

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
                normative = rt in NORMATIVE_RECORD_TYPES
                self.results["raw_tags"].setdefault(key, []).append({
                    "offset": f"0x{pos:08X}", "tag_id": f"0x{rt:04X}",
                    "tag_name": name, "data_type": "RecordArray",
                    "length": end - pos - 5, "depth": 1,
                    "record_size": rs, "no_of_records": nr,
                    "is_spec_verified": normative and confidence in ("high", "medium"),
                    "annex_ref": "Annex 1C Appendix 7", "generation": self.generation,
                    "data_hex": payload.hex() if len(payload) <= 128 else f"{payload[:128].hex()}..."
                })

        self._classify_gaps(data)

    def _classify_gaps(self, data: bytes):
        """Classify bytes not covered by the structural walk as padding or
        unknown (compute the gap list first: marking mutates the ranges)."""
        from core.utils.coverage import is_padding_block

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
        from core.parser.g1_walker import iter_g1_vu_messages, TREP_NAMES

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

    def _get_tag_path(self, tag: int, parent_path: str, dtype: Optional[int] = None, parent_tag: Optional[int] = None) -> str:
        """Hierarchical raw_tags key for *tag* under *parent_path*."""
        dec = self.registry.get_decoder(tag, generation=self.generation, is_vu=self.is_vu,
                                       dtype=dtype, parent_tag=parent_tag)
        tag_name = dec.name if dec else f"BER_{tag:04X}"
        raw_key = f"{tag:04X}_{tag_name}"
        return f"{parent_path} > {raw_key}" if parent_path else raw_key

    def _skip_padding(self, raw_data: bytes, pos: int, end: int) -> int:
        """Advance over a top-level padding run, classifying and recording it."""
        from core.utils.coverage import is_padding_block, KNOWN_PADDING_BYTES
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
        from core.utils.coverage import is_padding_block, KNOWN_PADDING_BYTES
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
            if self.registry.get_decoder(tag, generation=self.generation, is_vu=self.is_vu):
                return stap

        ber = self._try_read_ber_tlv(raw_data, pos, end)
        if ber is not None:
            tag, _, _, _, _ = ber
            if self.registry.get_decoder(tag, generation=self.generation, is_vu=self.is_vu):
                return ber

        return stap or ber

    def _record_tag(self, tag: int, length: int, payload: bytes, pos: int, hdr_size: int, depth: int = 0, parent_path: str = "", dtype: Optional[int] = None, parent_tag: Optional[int] = None):
        """Append the tag occurrence to raw_tags and capture certificate payloads."""
        dec = self.registry.get_decoder(tag, generation=self.generation, is_vu=self.is_vu,
                                       dtype=dtype, parent_tag=parent_tag)
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
            # The generation-1 certificate form: the 194-byte ISO 9796-2 block
            # carried with the generation-1 appendix dtype. Valid generation-2
            # certificates may also be 194 bytes (core/crypto/signature.py), so
            # the dtype must stay in the predicate — length alone must not decide,
            # and the unconstrained leading byte of a G1 RSA block must not either.
            is_g1_form = length == 194 and (dtype is None or dtype <= 0x01)

            if tag in (0xC108, 0x0104):
                # CA / MemberState certificate. The same FID carries both the
                # generation-2 CA (CVC/DER encoded) and the generation-1 CA (the
                # G1 form above, whose leading byte is unconstrained). Mirroring
                # the CardSign guard, a generation-1 copy never claims the
                # generation-2 `msca_cert_raw` slot once a generation-2 CA has
                # claimed it, in any stream order; it still takes the slot while
                # no generation-2 CA has been seen, and it always feeds the
                # generation-1 RSA chain through `msca_cert_g1`.
                if is_g1_form:
                    if not getattr(self.parser, "ca_cert_g2_seen", False):
                        self.parser.msca_cert_raw = payload
                    self.parser.msca_cert_g1 = payload
                else:
                    self.parser.msca_cert_raw = payload
                    self.parser.ca_cert_g2_seen = True
            elif tag in (0xC101, 0x0103, 0x7F21):
                # CardSign certificate — the generation-2 EF-signing key.
                self.parser.card_cert_raw = payload
                self.parser.card_cert_sign_seen = True
                if is_g1_form:
                    self.parser.card_cert_g1 = payload
            elif tag == 0xC100:
                # In the generation-1 DF, C100 is the card certificate: the
                # 194-byte G1 form, whose leading byte is the first byte of an
                # unconstrained RSA signature and may therefore coincide with
                # the generation-2 encoding marker 0x30/0x7F. In the generation-2
                # DF the same FID is CardMA (Member Authority) — a CVC (0x7F21)
                # or DER X.509 payload that must NEVER supply the CardSign /
                # EF-signing key, in any stream order, for any appendix dtype,
                # and whether or not a C101 was seen. The real generation-2
                # encoding is a two-byte marker, so only a genuine G2 certificate
                # is kept out of the CardSign slot; a legitimate G1 card
                # certificate is no longer dropped just because its leading byte
                # looks G2, and it always feeds the generation-1 chain.
                if payload:
                    if length == 194:
                        self.parser.card_cert_g1 = payload
                    if (not looks_like_g2_certificate(payload)
                            and not getattr(self.parser, "card_cert_sign_seen", False)):
                        self.parser.card_cert_raw = payload

    def _dispatch_decoder(
        self,
        tag: int,
        payload: bytes,
        dtype: Optional[int] = None,
        parent_tag: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        """Run the registered decoder for *tag*, respecting card/VU scope.

        Signature blocks (dtype 1/3/11/15) are collected for verification but
        never dispatched. Decoder exceptions are logged, not propagated: a
        broken field decoder must not abort the structural walk.
        """
        # Collect EF data/signature pairs for later verification.
        if self.parser and not self.is_vu and dtype is not None and dtype <= 0x03:
            if dtype in (0x00, 0x02):
                self._ef_data.append((tag, dtype, payload))
            elif dtype in (0x01, 0x03):
                self._ef_signatures.append((tag, dtype, payload))

        if dtype in (1, 3, 11, 15):
            return

        dec = self.registry.get_decoder(tag, generation=self.generation, is_vu=self.is_vu,
                                       dtype=dtype, parent_tag=parent_tag)
        if dec and dec.decoder_fn:
            validation_warning = self._validate_decoder_payload(dec, payload, tag, offset)
            if validation_warning:
                self.results["metadata"].setdefault("decoder_validation_warnings", []).append(
                    validation_warning
                )
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

    @staticmethod
    def _validate_decoder_payload(dec, payload: bytes, tag: int, offset: Optional[int]) -> Optional[Dict[str, Any]]:
        """Validate registered payload constraints before semantic dispatch.

        Record decoders accept the documented bare-record layout, a two-byte EF
        pointer prefix, or a five-byte RecordArray envelope. Structural parsing
        and nested-container walking continue even when semantic dispatch is
        skipped for an invalid payload.
        """
        length = len(payload)
        issue = None
        expected = None
        if length < dec.min_length:
            issue = "min_length"
            expected = dec.min_length
        elif length > dec.max_length:
            issue = "max_length"
            expected = dec.max_length
        elif dec.record_size is not None:
            record_sizes = dec.record_size if isinstance(dec.record_size, tuple) else (dec.record_size,)
            valid = False
            pointer_expected = None
            for record_size in record_sizes:
                is_record_array = (
                    length >= 5
                    and int.from_bytes(payload[1:3], "big") == record_size
                    and 5 + record_size * int.from_bytes(payload[3:5], "big") == length
                )
                is_bare_records = length >= record_size and length % record_size == 0
                is_pointer_prefixed = length >= 2 + record_size and (length - 2) % record_size == 0
                is_documented_partial = dec.min_length < record_size and dec.min_length <= length < record_size
                layouts = {
                    "flat": is_bare_records,
                    "pointer": is_pointer_prefixed,
                    "record_array": is_record_array,
                    "flexible": (
                        is_record_array or is_bare_records or is_pointer_prefixed or is_documented_partial
                    ),
                }
                if layouts.get(dec.record_layout, layouts["flexible"]):
                    valid = True
                    # The leading 2-byte value of a cyclic record EF is the
                    # index of the newest record (Annex 1C §2.24a). An
                    # out-of-range pointer is surfaced rather than silently
                    # interpreted across the wrong slot.
                    if dec.record_layout == "pointer" and is_pointer_prefixed:
                        count = (length - 2) // record_size
                        if int.from_bytes(payload[0:2], "big") >= count:
                            pointer_expected = count
                    break
            if not valid:
                issue = "record_size"
                expected = list(record_sizes) if len(record_sizes) > 1 else record_sizes[0]
            elif pointer_expected is not None:
                issue = "pointer_range"
                expected = pointer_expected

        if issue is None:
            return None
        return {
            "severity": "warning",
            "code": f"decoder_{issue}_violation",
            "tag_id": f"0x{tag:04X}",
            "tag_name": dec.name,
            "offset": f"0x{offset:08X}" if offset is not None else None,
            "length": length,
            "expected": expected,
        }

    def _parse_container(self, tag: int, payload: bytes, container_offset: int, depth: int, parent_path: str):
        """Recursively walk a container payload (STAP or BER per generation)."""
        if depth > MAX_RECURSION_DEPTH:
            return
        dec = self.registry.get_decoder(tag, generation=self.generation, is_vu=self.is_vu)
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
                             abs_start, hdr_size, depth, parent_path,
                             dtype=inner_dtype, parent_tag=tag)
            self._dispatch_decoder(inner_tag, inner_payload, dtype=inner_dtype,
                                   parent_tag=tag, offset=abs_start)

            if self.registry.is_container(inner_tag, generation=self.generation, is_vu=self.is_vu,
                                          dtype=inner_dtype, parent_tag=tag):
                inner_path = self._get_tag_path(inner_tag, parent_path,
                                                dtype=inner_dtype, parent_tag=tag)
                self._parse_container(inner_tag, inner_payload, abs_start + hdr_size, depth + 1, inner_path)

            pos += hdr_size + inner_length
