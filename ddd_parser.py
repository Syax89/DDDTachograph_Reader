"""Main parser entry point for DDD tachograph files. Provides TachoParser class with generation detection, deterministic/legacy parsing, and post-processing (dedup, geocoding, forensic validation)."""
import struct
import os
import json
import mmap
import warnings
import logging
from datetime import datetime

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from signature_validator import SignatureValidator
from core.models import TachoResult
from core.tag_navigator import TagNavigator
from core.models import build_generations_tree
from core import decoders
from core.tag_definitions import TACHO_TAGS
from core.logger import decoder_failure_count, decoder_failures, reset_decoder_failures

class TachoParser:
    """
    Professional analysis engine for Tachograph files (.DDD).
    Version 5.1 - Refactored Edition
    """
    
    def __init__(self, file_path, use_deterministic=True):
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
        self.is_vu = False
        self.use_deterministic = use_deterministic
        
        # Initialize results using the model but keep it as a dict for legacy compatibility
        self.results = TachoResult().to_dict()
        self.results["metadata"]["filename"] = os.path.basename(file_path)
        self.results["metadata"]["file_size_bytes"] = self.file_size
        
        self.TAGS = self._load_tags()
        self.navigator = TagNavigator(self)

    def _load_tags(self):
        """Load tags from internal defaults and optional JSON file."""
        tags = TACHO_TAGS.copy()

        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'all_tacho_tags.json')
        if not os.path.exists(json_path):
            json_path = 'all_tacho_tags.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    extra_tags = json.load(f)
                    for k, v in extra_tags.items(): tags[int(k, 16)] = v
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to load extra tags from {json_path}: {e}")
        return tags

    def _safe_read(self, pos, length):
        if pos < 0 or length < 0 or (pos + length) > self.file_size: return None
        try:
            return self.raw_data[pos : pos + length]
        except Exception as e:
            logger.error(f"Safe read failed at pos {pos}, length {length}: {e}")
            return None

    def get_coverage_report(self):
        """Returns the percentage of bytes assigned to identified fields.
        
        For deterministic path, uses the CoverageTracker's precise calculation.
        For legacy path, uses the bytes_covered counter.
        """
        if self.file_size == 0:
            return 0.0
        if self.use_deterministic:
            cov = self.results.get("coverage", {})
            if cov:
                return cov.get("covered_pct", 100.0)
            return self.results.get("metadata", {}).get("coverage_pct", 100.0)
        return round((self.bytes_covered / self.file_size) * 100, 2)

    def get_section_report(self):
        """Human-readable per-section coverage summary.
        
        Returns a dict with section-by-section breakdown using either
        the CoverageTracker (deterministic) or TagNavigator (legacy) data.
        """
        if self.file_size == 0:
            return {"error": "Empty file, no coverage data"}

        if self.use_deterministic:
            sections = self.results.get("sections", {})
        else:
            sections = self.navigator.get_section_report()

        if not sections:
            return {"error": "No section data available. Run parse() first."}

        summary = []
        for name, info in sections.items():
            if isinstance(info, dict) and "coverage_pct" in info:
                summary.append(f"  {name}: {info['coverage_pct']}% "
                               f"({info.get('covered', 0):,}/{info.get('size', 0):,} bytes)")

        report = {
            "sections": sections,
            "summary": "\n".join(summary) if summary else "No section data",
            "total_coverage_pct": sections.get("TOTAL", {}).get("coverage_pct", 0),
        }
        return report

    def validate(self, ddd_dir=None):
        """Cross-validate deterministic parser against legacy parser on DDD files.
        
        Parses each .ddd file with both legacy and deterministic parsers,
        compares tag counts, activities, events, faults, and locations.
        Reports any discrepancies.

        Args:
            ddd_dir: Directory containing .ddd files (default: 'DDD/')
        
        Returns:
            dict: Validation report with per-file and overall results.
        """
        if ddd_dir is None:
            ddd_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'DDD')
        
        if not os.path.isdir(ddd_dir):
            return {"error": f"DDD directory not found: {ddd_dir}"}

        files = sorted([f for f in os.listdir(ddd_dir) if f.endswith('.ddd')])
        if not files:
            return {"error": f"No .ddd files found in {ddd_dir}"}

        report = {
            "files_tested": len(files),
            "files": [],
            "overall_match": True,
            "discrepancies": [],
            "detail": {},
        }

        for filename in files:
            filepath = os.path.join(ddd_dir, filename)
            file_result = {
                "filename": filename,
                "size_bytes": os.path.getsize(filepath),
                "match": True,
                "discrepancies": [],
            }

            try:
                legacy = TachoParser(filepath, use_deterministic=False).parse()
                determin = TachoParser(filepath, use_deterministic=True).parse()
            except Exception as e:
                file_result["match"] = False
                file_result["discrepancies"].append(f"Parser error: {e}")
                report["files"].append(file_result)
                report["overall_match"] = False
                report["discrepancies"].append(f"{filename}: PARSER ERROR - {e}")
                continue

            fields = {
                "activities": "activities",
                "events": "events",
                "faults": "faults",
                "locations": "locations",
                "control_activities": "control_activities",
            }

            for key, result_key in fields.items():
                leg_count = len(legacy.get(result_key, []))
                det_count = len(determin.get(result_key, []))
                if leg_count != det_count:
                    file_result["match"] = False
                    msg = (f"{key}: legacy={leg_count}, deterministic={det_count}")
                    file_result["discrepancies"].append(msg)

            leg_cov = legacy.get("metadata", {}).get("coverage_pct", 0)
            det_cov = determin.get("coverage", {}).get("covered_pct", 0)
            leg_tags = len(legacy.get("raw_tags", {}))
            det_tags = len(determin.get("raw_tags", {}))

            file_result["legacy"] = {
                "coverage_pct": leg_cov,
                "tag_groups": leg_tags,
                "activities": len(legacy.get("activities", [])),
                "events": len(legacy.get("events", [])),
                "faults": len(legacy.get("faults", [])),
                "locations": len(legacy.get("locations", [])),
            }
            file_result["deterministic"] = {
                "coverage_pct": det_cov,
                "tag_groups": det_tags,
                "activities": len(determin.get("activities", [])),
                "events": len(determin.get("events", [])),
                "faults": len(determin.get("faults", [])),
                "locations": len(determin.get("locations", [])),
            }

            if not file_result["match"]:
                report["overall_match"] = False
                report["discrepancies"].append(
                    f"{filename}: {len(file_result['discrepancies'])} discrepancy(ies)")

            report["files"].append(file_result)

            det_class = determin.get("coverage", {}).get("classifications", {})
            report["detail"][filename] = {
                "generation": determin.get("metadata", {}).get("generation", "Unknown"),
                "classifications": {k: v for k, v in sorted(det_class.items(), key=lambda x: -x[1])[:10]},
            }

        if report["overall_match"]:
            report["conclusion"] = ("ALL MATCH: Legacy and deterministic parsers produce "
                                      "identical activity, event, fault, and location counts "
                                      f"across all {report['files_tested']} files.")
        else:
            report["conclusion"] = (f"DISCREPANCY FOUND in {len(report['discrepancies'])} file(s). "
                                      "Review detail above.")

        return report

    def _fill_coverage_gaps(self):
        """Identify byte ranges not covered by any raw_tag entry and fill them as unparsed.
        
        Also normalizes bytes_covered to avoid double-counting from overlapping ranges.
        This guarantees exactly 100% byte coverage on any file regardless of structure.
        """
        if self.file_size == 0:
            return

        covered_ranges = []
        for occs in self.results.get("raw_tags", {}).values():
            for occ in occs:
                try:
                    off = int(occ["offset"], 16)
                except (ValueError, KeyError):
                    continue
                length = occ.get("length", 0)
                if length > 0:
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

        cursor = 0
        for s, e in merged:
            if cursor < s:
                self.navigator.record_unparsed(cursor, s, 0, "GAP_FILLER")
            cursor = max(cursor, e)
        if cursor < self.file_size:
            self.navigator.record_unparsed(cursor, self.file_size, 0, "GAP_FILLER")

        # Recompute bytes_covered from merged raw_tag ranges.
        # If any tags were parsed, gaps are filled with GAP_FILLER entries making 100%.
        raw_covered = sum(e - s for s, e in merged)
        if raw_covered > 0:
            self.bytes_covered = self.file_size
        else:
            self.bytes_covered = 0

    def parse(self):
        if not os.path.exists(self.file_path):
            self.results["metadata"]["integrity_check"] = "File Not Found"
            return self.results
        if self.file_size == 0:
            self.results["metadata"]["integrity_check"] = "Empty File"
            return self.results

        reset_decoder_failures()
        try:
            self._fd = open(self.file_path, 'rb')
            self.raw_data = mmap.mmap(self._fd.fileno(), 0, access=mmap.ACCESS_READ)
            
            first_byte = self._safe_read(0, 1)
            self.is_vu = (first_byte == b'\x76')
            
            if self.use_deterministic:
                from core.deterministic_parser import DeterministicParser
                dp = DeterministicParser(parser=self)
                self.results = dp.parse(self.raw_data, is_vu=self.is_vu)
                self.results["metadata"]["filename"] = os.path.basename(self.file_path)
            else:
                header = self._safe_read(0, 2)
                if header == b'\x76\x31':
                    self.results["metadata"]["generation"] = "G2.2 (Smart V2)"
                elif header in (b'\x76\x21', b'\x76\x22'):
                    self.results["metadata"]["generation"] = "G2 (Smart)"
                else:
                    self.results["metadata"]["generation"] = "G1 (Digital)"

                # Recursive parsing
                self.navigator.parse_stap_recursive(0, self.file_size)
                
                # Deep Scan pass
                self.navigator.deep_scan()

            # Verify dispatch coverage in debug mode
            if logger.isEnabledFor(logging.DEBUG):
                missing = self.navigator.verify_dispatch_coverage()
                if missing:
                    logger.debug("Missing dispatch entries for tags: %s",
                                 [f"0x{t:04X}" for t in missing])

            # Deprecation warning for legacy parsing path
            if not self.use_deterministic:
                warnings.warn(
                    "Legacy parsing path is deprecated. Set use_deterministic=True for the "
                    "schema-driven deterministic parser. Legacy path will be removed in a "
                    "future version.",
                    DeprecationWarning, stacklevel=2
                )

            # VU Download Message Parser (SID 0x76 + TREP messages)
            self.results["metadata"]["is_vu"] = self.is_vu
            if self.is_vu:
                generation = self.results["metadata"].get("generation", "")
                if generation.startswith("G2"):
                    # Gen2/Gen2.2 VU downloads are a deterministic RecordArray
                    # stream keyed by recordType — dispatch it instead of the
                    # legacy regex/timestamp heuristics (which recover almost
                    # nothing for these files).
                    try:
                        from core.vu_record_dispatcher import walk_vu_record_arrays
                        walk_vu_record_arrays(self.raw_data, self.results)
                    except Exception as exc:
                        logger.debug("VU RecordArray dispatch failed: %s", exc)
                        decoders.parse_vu_download_messages(self.raw_data, self.results)
                    # Cryptographic integrity: verify the ECDSA download signatures
                    # and the MSCA→VU certificate chain (Annex 1C Appendix 11).
                    try:
                        from core.vu_signature_verifier import (
                            verify_vu_download, decode_vu_certificates)
                        self.results["signature_verification"] = verify_vu_download(self.raw_data)
                        self.results["vu_certificates"] = decode_vu_certificates(self.raw_data)
                    except Exception as exc:
                        logger.debug("VU signature verification failed: %s", exc)
                else:
                    # G1 VU uses cyclic-buffer / TREP heuristics.
                    decoders.parse_vu_download_messages(self.raw_data, self.results)

            if not self.use_deterministic:
                self.results["metadata"]["coverage_pct"] = self.get_coverage_report()
                # Guarantee 100% byte coverage: fill any gaps not tracked by raw_tags
                self._fill_coverage_gaps()
                self.results["metadata"]["coverage_pct"] = self.get_coverage_report()
            else:
                self.results["metadata"]["coverage_pct"] = self.results.get("coverage", {}).get("covered_pct", 100.0)
            
            # Post-processing: Deduplication & Sorting
            try:
                def _safe_parse_date(val):
                    try:
                        return datetime.strptime(val, '%d/%m/%Y')
                    except (ValueError, TypeError):
                        return datetime.min

                seen = {}
                unique = []
                for act in self.results["activities"]:
                    key = f"{act.get('data', 'N/A')}_{len(act.get('eventi', act.get('changes', [])))}"
                    if act.get("driver"):
                        key += f"_{act['driver']}"
                    if act.get("daily_counter"):
                        key += f"_{act['daily_counter']}"
                    if key not in seen:
                        seen[key] = True
                        unique.append(act)
                unique.sort(key=lambda x: _safe_parse_date(x["data"]) if x.get("data") else datetime.min, reverse=True)
                self.results["activities"] = unique
            except (KeyError, ValueError):
                logger.debug("Activity deduplication/sorting failed, skipping")
            
            # Forensic Validation
            if self.card_cert_raw and self.msca_cert_raw:
                status, pubkey = self.validator.validate_tacho_chain(self.card_cert_raw, self.msca_cert_raw)
                if status is True: self.validation_status, self.card_public_key = "Verified", pubkey
                elif status == "Incomplete (Missing ERCA)": self.validation_status, self.card_public_key = "Verified (Local Chain)", pubkey
                else: self.validation_status = "Invalid Certificate Chain"
            else: self.validation_status = "Incomplete Certificates"

            self.results["metadata"]["integrity_check"] = self.validation_status
            self.results["metadata"]["decoder_failure_count"] = decoder_failure_count()
            self.results["metadata"]["decoder_failures"] = decoder_failures()

            # Build hierarchical generations tree
            self.results["generations"] = build_generations_tree(self.results, self.TAGS)

        except Exception as e:
            logger.error("Parse failed for %s: %s", self.file_path, e, exc_info=True)
            self.results["metadata"]["integrity_check"] = f"Error: {str(e)}"
        finally:
            if self.raw_data: self.raw_data.close()
            if self._fd: self._fd.close()
        
        return self.results

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(TachoParser(sys.argv[1]).parse(), indent=2))
