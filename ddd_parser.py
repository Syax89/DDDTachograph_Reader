"""Main parser entry point for DDD tachograph files. Provides TachoParser with generation detection, deterministic parsing, and post-processing (dedup, signature validation)."""
import os
import json
import mmap
import warnings
import logging
from datetime import datetime

from signature_validator import SignatureValidator
from core.models import TachoResult, build_generations_tree
from core.version import __version__
from core import decoders
from core.tag_definitions import TACHO_TAGS
from core.logger import decoder_failure_count, decoder_failures, reset_decoder_failures

logger = logging.getLogger(__name__)

class TachoParser:
    """Analysis engine for tachograph files (.DDD): driver cards and VU
    downloads, generations G1 (Annex 1B), G2 and G2.2 (Annex 1C)."""

    def __init__(self, file_path, use_deterministic=True):
        if not use_deterministic:
            warnings.warn(
                "The legacy (non-deterministic) parsing path has been removed; "
                "the deterministic parser is always used.",
                DeprecationWarning, stacklevel=2)
        self.file_path = file_path
        self.file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        self.raw_data = None
        self._fd = None
        self.validator = SignatureValidator()
        self.card_public_key = None
        self.msca_cert_raw = None
        self.card_cert_raw = None
        self.msca_cert_g1 = None
        self.card_cert_g1 = None
        self.validation_status = "Pending"
        self.is_vu = False

        # Initialize results using the model but keep it as a dict for legacy compatibility
        self.results = TachoResult().to_dict()
        self.results["metadata"]["filename"] = os.path.basename(file_path)
        self.results["metadata"]["file_size_bytes"] = self.file_size

        self.TAGS = self._load_tags()

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
                    for k, v in extra_tags.items():
                        try:
                            tags[int(k, 16)] = v
                        except (ValueError, TypeError):
                            logger.debug("Skipping non-hex tag key: %s", k)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to load extra tags from {json_path}: {e}")
        return tags

    def _safe_read(self, pos, length):
        if pos < 0 or length < 0 or (pos + length) > self.file_size:
            return None
        try:
            return self.raw_data[pos : pos + length]
        except Exception as e:
            logger.error(f"Safe read failed at pos {pos}, length {length}: {e}")
            return None

    def get_coverage_report(self):
        """Percentage of bytes assigned to identified fields.

        Returns None if no parse has occurred yet (raw_data is None).
        """
        if self.raw_data is None:
            return None
        if self.file_size == 0:
            return 0.0
        cov = self.results.get("coverage", {})
        if cov:
            return cov.get("covered_pct", 0.0)
        return self.results.get("metadata", {}).get("coverage_pct", 0.0)

    def get_section_report(self):
        """Human-readable per-section coverage summary."""
        if self.file_size == 0:
            return {"error": "Empty file, no coverage data"}

        sections = self.results.get("sections", {})
        if not sections:
            return {"error": "No section data available. Run parse() first."}

        summary = []
        for name, info in sections.items():
            if isinstance(info, dict) and "coverage_pct" in info:
                summary.append(f"  {name}: {info['coverage_pct']}% "
                               f"({info.get('covered', 0):,}/{info.get('size', 0):,} bytes)")

        return {
            "sections": sections,
            "summary": "\n".join(summary) if summary else "No section data",
            "total_coverage_pct": sections.get("TOTAL", {}).get("coverage_pct", 0),
        }

    def parse(self):
        if not os.path.exists(self.file_path):
            self.results["metadata"]["integrity_check"] = "File Not Found"
            return self.results
        if self.file_size == 0:
            self.results["metadata"]["integrity_check"] = "Empty File"
            return self.results

        reset_decoder_failures()

        self.results = TachoResult().to_dict()
        self.results["metadata"]["filename"] = os.path.basename(self.file_path)
        self.results["metadata"]["file_size_bytes"] = self.file_size
        self.results["metadata"]["app_version"] = __version__
        self.card_public_key = None
        self.msca_cert_raw = None
        self.card_cert_raw = None
        self.msca_cert_g1 = None
        self.card_cert_g1 = None
        self.validation_status = "Pending"

        try:
            self._fd = open(self.file_path, 'rb')
            try:
                self.raw_data = mmap.mmap(self._fd.fileno(), 0, access=mmap.ACCESS_READ)
            except Exception:
                self._fd.close()
                self._fd = None
                raise

            first_byte = self._safe_read(0, 1)
            self.is_vu = (first_byte == b'\x76')

            from core.deterministic_parser import DeterministicParser
            dp = DeterministicParser(parser=self)
            self.results = dp.parse(self.raw_data, is_vu=self.is_vu)
            self.results["metadata"]["filename"] = os.path.basename(self.file_path)
            self.results["metadata"]["app_version"] = __version__

            # Verify dispatch coverage in debug mode
            if logger.isEnabledFor(logging.DEBUG):
                from core.decoder_registry import DecoderRegistry
                reg = DecoderRegistry.instance()
                registered = {t for t in reg.get_all_tags()
                              if reg.get_decoder(t) and reg.get_decoder(t).decoder_fn}
                seen = set()
                for occs in self.results.get("raw_tags", {}).values():
                    for occ in occs:
                        try:
                            seen.add(int(occ.get("tag_id", "0x0"), 16))
                        except (ValueError, KeyError):
                            continue
                unhandled = registered - seen
                if unhandled:
                    logger.debug("Registered tags not encountered in file: %s",
                                 [f"0x{t:04X}" for t in sorted(unhandled)])

            # VU semantic decoding (the deterministic pass above is structural)
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
                        walker_success = walk_vu_record_arrays(self.raw_data, self.results)
                        # Only fall back to heuristic if the walker produced NO results
                        if not walker_success or not self.results.get("vu_record_arrays"):
                            decoders.parse_vu_download_messages(self.raw_data, self.results)
                    except Exception as exc:
                        logger.debug("VU RecordArray dispatch failed: %s", exc, exc_info=False)
                        if not self.results.get("vu_record_arrays"):
                            decoders.parse_vu_download_messages(self.raw_data, self.results)
                    # Cryptographic integrity: verify the ECDSA download signatures
                    # and the MSCA→VU certificate chain (Annex 1C Appendix 11).
                    try:
                        from core.vu_signature_verifier import (
                            verify_vu_download, decode_vu_certificates)
                        erca_keys = self.validator._g2_erca_keys() or None
                        self.results["signature_verification"] = verify_vu_download(
                            self.raw_data, erca_keys=erca_keys)
                        self.results["vu_certificates"] = decode_vu_certificates(self.raw_data)
                    except Exception as exc:
                        logger.debug("VU signature verification unavailable: %s", exc, exc_info=False)
                        self.results["signature_verification"] = {"overall": "unavailable"}
                else:
                    # G1 VU: deterministic TREP walk (Annex 1B §2.2.6) with
                    # the byte-scan heuristic as fallback for files the walk
                    # cannot validate (truncated/non-standard downloads).
                    try:
                        from core.g1_vu_walker import walk_g1_vu
                        _messages, complete = walk_g1_vu(self.raw_data, self.results)
                    except Exception as exc:
                        logger.debug("G1 VU walk failed: %s", exc, exc_info=False)
                        complete = False
                    if not complete:
                        decoders.parse_vu_download_messages(self.raw_data, self.results)

            self.results["metadata"]["coverage_pct"] = self.results.get("coverage", {}).get("covered_pct", 100.0)

            # Post-processing: Deduplication & Sorting
            def _safe_parse_date(val):
                try:
                    return datetime.strptime(val, '%d/%m/%Y')
                except (ValueError, TypeError):
                    return datetime.min

            seen = {}
            unique = []
            for act in self.results["activities"]:
                key = f"{act.get('date', 'N/A') or 'N/A'}_{len(act.get('changes', []))}"
                if act.get("driver"):
                    key += f"_{act['driver']}"
                if act.get("daily_counter"):
                    key += f"_{act['daily_counter']}"
                if key not in seen:
                    seen[key] = True
                    unique.append(act)
            unique.sort(key=lambda x: _safe_parse_date(x.get("date")) or datetime.min, reverse=True)
            self.results["activities"] = unique

            # Forensic Validation
            # G1 VU files carry certificates inside TREP 01 Overview rather than
            # as separate STAP/BER-TLV records — pull them from the internal keys
            # set by parse_g1_vu_overview when the deterministic parser didn't
            # capture them.
            g1_vu_msca = self.results.pop("_g1_vu_msca_cert", None)
            g1_vu_card = self.results.pop("_g1_vu_card_cert", None)
            if not self.card_cert_raw and not self.msca_cert_raw:
                if g1_vu_msca and g1_vu_card:
                    self.card_cert_g1 = g1_vu_card
                    self.msca_cert_g1 = g1_vu_msca
            if self.card_cert_raw and self.msca_cert_raw:
                status, pubkey = self.validator.validate_tacho_chain(self.card_cert_raw, self.msca_cert_raw)
                # The last certificates seen in the file may be the G2 copies;
                # if the chain did not fully verify and distinct G1 (194-byte)
                # certificates are also present, try the G1 chain and keep the
                # better outcome.
                if status is not True and self.card_cert_g1 and self.msca_cert_g1 and \
                        (self.card_cert_g1 != self.card_cert_raw or self.msca_cert_g1 != self.msca_cert_raw):
                    g1_status, g1_pubkey = self.validator.validate_tacho_chain(
                        self.card_cert_g1, self.msca_cert_g1)
                    rank = {True: 4,
                            "Incomplete (Missing ERCA)": 3,
                            "Partial — MSCA→Card verified (no ERCA root)": 2,
                            "Cannot Verify (Missing ERCA Root)": 1}
                    if rank.get(g1_status, 0) > rank.get(status, 0):
                        status, pubkey = g1_status, g1_pubkey
            elif self.card_cert_g1 and self.msca_cert_g1:
                # G1 VU files: certificates were extracted from TREP 01 Overview
                # and stored directly as the G1 copies.
                status, pubkey = self.validator.validate_tacho_chain(
                    self.card_cert_g1, self.msca_cert_g1)
            else:
                status, pubkey = False, None

            if status is True:
                self.validation_status = "Verified"
                self.card_public_key = pubkey
            elif status == "Partial — MSCA→Card verified (no ERCA root)":
                self.validation_status = "Verified (Partial — CVC MSCA→Card)"
                self.card_public_key = pubkey
            elif status == "Incomplete (Missing ERCA)":
                self.validation_status = "Verified (Local Chain)"
                self.card_public_key = pubkey
            elif status == "Cannot Verify (Missing ERCA Root)":
                self.validation_status = "Unverified (Missing ERCA Root)"
            elif status is not False:
                self.validation_status = str(status)
            else:
                self.validation_status = "Invalid Certificate Chain"

            had_certs = bool((self.card_cert_raw and self.msca_cert_raw)
                             or (self.card_cert_g1 and self.msca_cert_g1))
            if not self.card_public_key:
                # Card chain didn't produce a key — check VU verification.
                sv = self.results.get("signature_verification") or {}
                if sv.get("msca_to_vu") is True:
                    if sv.get("all_treps_valid") and sv.get("root_anchored"):
                        self.validation_status = "Verified (VU Chain)"
                    elif sv.get("all_treps_valid"):
                        self.validation_status = "Verified (VU — TREP ok, chain partial)"
                    else:
                        self.validation_status = "Partial (VU — chain ok)"
                elif not had_certs:
                    self.validation_status = "Incomplete Certificates"
                # else: keep the negative chain outcome (e.g. "Invalid
                # Certificate Chain") — a failed chain must stay visible.

            # EF signature verification: verify each EF data block against
            # the card public key (forensic data integrity check).
            ef_data_raw = self.results.pop("_ef_data", None)
            ef_sig_raw = self.results.pop("_ef_signatures", None)
            if ef_data_raw is not None and ef_sig_raw is not None:
                from core.ef_signature_verifier import pair_ef_records, verify_ef_pairs
                from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
                ef_data_map = {(tag, dtype): payload for tag, dtype, payload in ef_data_raw}
                ef_sig_map = {(tag, dtype): payload for tag, dtype, payload in ef_sig_raw}
                pairs = pair_ef_records(ef_data_map, ef_sig_map)
                key_type = "RSA" if isinstance(self.card_public_key, _rsa.RSAPublicKey) else (
                    "EC" if self.card_public_key is not None else None)
                # When the G2 chain failed, try to extract the EC public key
                # from the G2 CVC certificate for G2 EF ECDSA verification.
                card_ec_key = None
                card_ec_hash = None
                if key_type == "RSA" and self.card_cert_raw:
                    try:
                        from core.vu_signature_verifier import parse_cvc, cvc_public_key
                        cvc = parse_cvc(self.card_cert_raw)
                        if cvc and cvc.get("public_point"):
                            card_ec_key, card_ec_hash = cvc_public_key(cvc)
                    except Exception:
                        pass
                ef_report = verify_ef_pairs(pairs, self.card_public_key,
                                            self.validator,
                                            self.results["metadata"]["generation"],
                                            key_type, card_ec_key, card_ec_hash)
                self.results["ef_signature_verification"] = ef_report

            self.results["metadata"]["integrity_check"] = self.validation_status
            self.results["metadata"]["decoder_failure_count"] = decoder_failure_count()
            self.results["metadata"]["decoder_failures"] = decoder_failures()

            # Build hierarchical generations tree
            self.results["generations"] = build_generations_tree(self.results, self.TAGS)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error("Parse failed for %s: %s", self.file_path, e, exc_info=True)
            self.results["metadata"]["integrity_check"] = f"Error: {str(e)}"
        finally:
            try:
                if self.raw_data:
                    self.raw_data.close()
            except Exception:
                pass
            try:
                if self._fd:
                    self._fd.close()
            except Exception:
                pass

        return self.results

if __name__ == "__main__":
    import sys
    from core.encoding import BytesEncoder

    if len(sys.argv) > 1:
        print(json.dumps(TachoParser(sys.argv[1]).parse(), indent=2, cls=BytesEncoder))
