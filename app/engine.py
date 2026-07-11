"""Main parser entry point for DDD tachograph files. Provides TachoParser with generation detection, deterministic parsing, and post-processing (dedup, signature validation)."""
import os
import json
import mmap
import warnings
import logging
from datetime import datetime

from core.crypto.signature import SignatureValidator
from core.registry.registry import DecoderRegistry
from core.registry.models import TachoResult, build_generations_tree
from core.utils.version import __version__
from core import decoders
from core.utils.logger import decoder_failure_count, decoder_failures, reset_decoder_failures

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
        """Load registry names and optional fallbacks for unregistered tags."""
        tags = DecoderRegistry.instance().get_tag_names()

        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'all_tacho_tags.json')
        if not os.path.exists(json_path):
            json_path = 'all_tacho_tags.json'
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    extra_tags = json.load(f)
                    for k, v in extra_tags.items():
                        try:
                            tag = int(k, 16)
                            # Registered names are owned by DecoderRegistry;
                            # external files can only label unknown tags.
                            tags.setdefault(tag, v)
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
        """Percentage of bytes structurally accounted for, including unknown bytes.

        Returns None if no parse has occurred yet (raw_data is None).
        """
        if self.raw_data is None:
            return None
        if self.file_size == 0:
            return 0.0
        cov = self.results.get("coverage", {})
        if cov:
            return cov.get("byte_accounted_pct", cov.get("covered_pct", 0.0))
        return self.results.get("metadata", {}).get("coverage_pct", 0.0)

    def get_section_report(self):
        """Human-readable per-byte-range accounted coverage summary."""
        if self.file_size == 0:
            return {"error": "Empty file, no coverage data"}

        sections = self.results.get("sections", {})
        if not sections:
            return {"error": "No byte-range data available. Run parse() first."}

        summary = []
        for name, info in sections.items():
            if isinstance(info, dict) and "coverage_pct" in info:
                summary.append(f"  {name}: Byte-accounted {info['coverage_pct']}% "
                               f"({info.get('covered', 0):,}/{info.get('size', 0):,} bytes)")

        return {
            "sections": sections,
            "summary": "\n".join(summary) if summary else "No section data",
            "total_coverage_pct": sections.get("TOTAL", {}).get("coverage_pct", 0),
        }

    def parse(self):
        """Parse the file and return the results dict.

        Orchestrates the pipeline: structural parse (deterministic, byte
        coverage), VU semantic decoding, activity dedup, certificate chain
        and EF signature verification, generations tree.
        """
        if not os.path.exists(self.file_path):
            self.results["metadata"]["integrity_check"] = "File Not Found"
            self.results["metadata"]["parse_error"] = {
                "code": "file_not_found",
                "message": "File not found",
            }
            return self.results
        if self.file_size == 0:
            self.results["metadata"]["integrity_check"] = "Empty File"
            self.results["metadata"]["parse_error"] = {
                "code": "empty_file",
                "message": "File is empty",
            }
            return self.results

        reset_decoder_failures()
        self._reset_state()

        try:
            self._open_file()
            # Structural pass: this is the foundation. If it fails there is no
            # data to show, so it stays a fatal parse_error below.
            self._run_structural_parse()
            self._log_unhandled_tags()

            # Post-structural phases are best-effort: a failure in any one of
            # them must NOT discard the structural data already recovered. Each
            # runs in isolation and records a parse_warning on failure so the
            # UI can still render everything that was decoded.
            self._run_phase("vu_semantics", self._decode_vu_semantics)
            self._run_phase("vu_salvage", self._salvage_partial_download)
            self.results["metadata"]["coverage_pct"] = \
                self.results.get("coverage", {}).get("covered_pct", 100.0)
            self._run_phase("activity_dedup", self._dedup_and_sort_activities)
            self._run_phase("certificate_chain", self._validate_certificate_chain)
            self._run_phase("g1_vu_signatures", self._verify_g1_vu_signatures)
            self._run_phase("ef_signatures", self._verify_ef_signatures)

            self.results["metadata"]["integrity_check"] = self.validation_status
            self.results["metadata"]["decoder_failure_count"] = decoder_failure_count()
            self.results["metadata"]["decoder_failures"] = decoder_failures()
            self._run_phase(
                "generations_tree",
                lambda: self.results.__setitem__(
                    "generations", build_generations_tree(self.results, self.TAGS)))

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error("Parse failed for %s: %s", self.file_path, e, exc_info=True)
            self.results["metadata"]["integrity_check"] = f"Error: {str(e)}"
            self.results["metadata"]["parse_error"] = {
                "code": "parse_exception",
                "message": str(e) or type(e).__name__,
                "exception_type": type(e).__name__,
            }
        finally:
            self._close_file()

        return self.results

    def _run_phase(self, phase_name, fn):
        """Run a best-effort post-structural phase in isolation.

        A failure is recorded in ``metadata["parse_warnings"]`` and logged, but
        never aborts the parse: structural data already recovered stays intact
        so partial/corrupt files still surface everything that was decoded.
        """
        try:
            fn()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.warning("Parse phase '%s' failed: %s", phase_name, exc,
                           exc_info=True)
            self.results["metadata"].setdefault("parse_warnings", []).append({
                "phase": phase_name,
                "message": str(exc) or type(exc).__name__,
                "exception_type": type(exc).__name__,
            })


    # ── parse() phases ─────────────────────────────────────────────────

    def _reset_state(self):
        """Re-initialize results and certificate state for a fresh parse."""
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

    def _open_file(self):
        """Memory-map the file and detect VU vs card (first byte 0x76 = VU)."""
        self._fd = open(self.file_path, 'rb')
        try:
            self.raw_data = mmap.mmap(self._fd.fileno(), 0, access=mmap.ACCESS_READ)
        except Exception:
            self._fd.close()
            self._fd = None
            raise
        self.is_vu = (self._safe_read(0, 1) == b'\x76')

    def _close_file(self):
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

    def _run_structural_parse(self):
        """Structural pass: deterministic STAP/BER-TLV parse with byte coverage."""
        from core.parser.deterministic import DeterministicParser
        dp = DeterministicParser(parser=self)
        self.results = dp.parse(self.raw_data, is_vu=self.is_vu)
        # dp.parse() returns a fresh results dict — restore file metadata.
        self.results["metadata"]["filename"] = os.path.basename(self.file_path)
        self.results["metadata"]["app_version"] = __version__

    def _log_unhandled_tags(self):
        """Debug aid: report registered tags that never appeared in the file."""
        if not logger.isEnabledFor(logging.DEBUG):
            return
        from core.registry.registry import DecoderRegistry
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

    def _decode_vu_semantics(self):
        """Semantic pass for VU downloads (the structural pass above is layout-only).

        G2/G2.2: RecordArray stream dispatch + ECDSA download signature
        verification. G1: deterministic TREP walk. Both fall back to the
        byte-scan heuristic when the primary path recovers nothing.
        """
        self.results["metadata"]["is_vu"] = self.is_vu
        if not self.is_vu:
            self.results["metadata"]["origin"] = "driver_card"
            return
        generation = self.results["metadata"].get("generation", "")
        if generation.startswith("G2"):
            # Gen2/Gen2.2 VU downloads are a deterministic RecordArray
            # stream keyed by recordType — dispatch it instead of the
            # legacy regex/timestamp heuristics (which recover almost
            # nothing for these files).
            try:
                from core.parser.vu_dispatcher import walk_vu_record_arrays
                walker_success = walk_vu_record_arrays(self.raw_data, self.results)
                # Only fall back to heuristic if the walker produced NO results
                if not walker_success or not self.results.get("vu_record_arrays"):
                    decoders.parse_vu_download_messages(self.raw_data, self.results)
            except Exception as exc:
                logger.debug("VU RecordArray dispatch failed: %s", exc, exc_info=False)
                if not self.results.get("vu_record_arrays"):
                    decoders.parse_vu_download_messages(self.raw_data, self.results)
            self._build_trep_report(generation, complete_walk=True)
            # Cryptographic integrity: verify the ECDSA download signatures
            # and the MSCA→VU certificate chain (Annex 1C Appendix 11).
            try:
                from core.crypto.vu_signature import (
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
                from core.parser.g1_walker import walk_g1_vu
                _messages, complete = walk_g1_vu(self.raw_data, self.results)
            except Exception as exc:
                logger.debug("G1 VU walk failed: %s", exc, exc_info=False)
                complete = False
                _messages = []
            if not complete:
                decoders.parse_vu_download_messages(self.raw_data, self.results)
            present = sorted({m["trep"] for m in (_messages or [])})
            self._build_trep_report(generation, complete_walk=complete,
                                    present_treps=present)

    def _build_trep_report(self, generation, complete_walk=True, present_treps=None):
        """Summarise TREP completeness (mandatory read / total) into metadata.

        ``present_treps`` may be supplied by the G1 walk; for G2 it is derived
        from the decoded RecordArray sections. TREPs flagged during decoding as
        implausible (``_suspect_sections``) are reported as 'suspect'.

        First confirms the file origin from its content: a driver-card image
        wrapped in a stand-alone TREP 06 Card Download is a valid selective
        download (Annex 1B §2.2.6.6), not a VU stream, so it is reclassified as
        a card and no VU completeness report is produced for it.
        """
        from core.parser.trep_inventory import build_trep_report, format_trep_summary
        from core.parser.origin_detector import detect_origin, ORIGIN_CARD
        if present_treps is None:
            present_treps = []
            for sec in self.results.get("vu_record_arrays") or []:
                try:
                    present_treps.append(int(sec.get("trep", "0x0"), 16))
                except (TypeError, ValueError):
                    continue

        origin, note, is_wrapped = detect_origin(
            self.is_vu, self.results, present_treps)
        self.results["metadata"]["origin"] = origin
        if note:
            self.results["metadata"]["origin_note"] = note
        if origin == ORIGIN_CARD:
            # A card image (possibly VU-wrapped): treat as a card, not a
            # partial VU download. No TREP completeness report.
            self.is_vu = False
            self.results["metadata"]["is_vu"] = False
            self.results.pop("_suspect_sections", None)
            return

        suspect = self.results.pop("_suspect_sections", None) or set()
        report = build_trep_report(
            generation, present_treps, suspect_treps=suspect,
            complete_walk=complete_walk)
        self.results["metadata"]["trep_report"] = report
        if report.get("is_partial"):
            logger.info("Partial VU download: %s", format_trep_summary(report))

    def _salvage_partial_download(self):
        """Anchor-based recovery for partial/corrupt VU downloads.

        Runs only when the TREP report flags the file as partial, scanning any
        unrecovered byte regions for self-validating card images / event
        records. Recovered data is flagged heuristic.
        """
        if not self.is_vu:
            return
        from core.parser.salvage import should_salvage, salvage_vu_download
        if not should_salvage(self.results):
            return
        gained = salvage_vu_download(self.raw_data, self.results)
        if gained:
            self.results["metadata"]["salvage_recovered"] = gained

    def _dedup_and_sort_activities(self):
        """Drop duplicate daily activity blocks and sort newest-first.

        The same day can be emitted twice when a region is reached both by
        the EF walk and a container re-scan. Only complete, structurally
        identical records are duplicates.
        """
        def _safe_parse_date(val):
            try:
                return datetime.strptime(val, '%d/%m/%Y')
            except (ValueError, TypeError):
                return datetime.min

        def _canonical(value):
            """Build a deterministic, hashable representation of decoded data."""
            if isinstance(value, dict):
                items = ((_canonical(key), _canonical(item)) for key, item in value.items())
                return ("dict", tuple(sorted(items, key=repr)))
            if isinstance(value, list):
                return ("list", tuple(_canonical(item) for item in value))
            if isinstance(value, tuple):
                return ("tuple", tuple(_canonical(item) for item in value))
            if isinstance(value, set):
                return ("set", tuple(sorted((_canonical(item) for item in value), key=repr)))
            if isinstance(value, bytes):
                return ("bytes", value.hex())
            return (type(value).__module__, type(value).__qualname__, repr(value))

        seen = set()
        unique = []
        for act in self.results["activities"]:
            key = _canonical(act)
            if key not in seen:
                seen.add(key)
                unique.append(act)
        unique.sort(key=lambda x: _safe_parse_date(x.get("date")) or datetime.min, reverse=True)
        self.results["activities"] = unique

    def _validate_certificate_chain(self):
        """Validate the ERCA→MSCA→Card/VU chain and set validation_status."""
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

        if self.validator.last_chain_temporal_validity:
            self.results["certificate_temporal_validity"] = \
                self.validator.last_chain_temporal_validity

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

    def _verify_ef_signatures(self):
        """Verify each EF data block against the card public key (data integrity)."""
        ef_data_raw = self.results.pop("_ef_data", None)
        ef_sig_raw = self.results.pop("_ef_signatures", None)
        if ef_data_raw is None or ef_sig_raw is None:
            return
        from core.crypto.ef_signature import pair_ef_records, verify_ef_pairs
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        pairs = pair_ef_records(ef_data_raw, ef_sig_raw)
        key_type = "RSA" if isinstance(self.card_public_key, _rsa.RSAPublicKey) else (
            "EC" if self.card_public_key is not None else None)
        # Extract a G2 CVC key whenever one is available. It is a data-integrity
        # fallback for ECDSA EF pairs, not evidence that the CVC chain verified.
        card_ec_key = None
        card_ec_hash = None
        if self.card_cert_raw:
            try:
                from core.crypto.vu_signature import parse_cvc, cvc_public_key
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

    def _verify_g1_vu_signatures(self):
        """Verify every signed G1 VU TREP after recovering the VU public key.

        The certificate chain alone authenticates the VU key, not the downloaded
        payload. A file without valid TREP signatures must never retain a fully
        verified integrity status.
        """
        generation = self.results["metadata"].get("generation", "")
        if not self.is_vu or not generation.startswith("G1"):
            return

        from core.parser.g1_walker import TREP_NAMES, iter_g1_vu_messages

        messages = list(iter_g1_vu_messages(bytes(self.raw_data)))
        report = {
            "available": self.card_public_key is not None,
            "algorithm": "RSA-SHA1",
            "msca_to_vu": self.card_public_key is not None,
            "root_anchored": self.validation_status == "Verified",
            "treps": [],
            "all_treps_valid": False,
            "missing_signatures": 0,
            "summary": "",
        }
        if not messages:
            report["summary"] = "No G1 VU TREP sections found"
            self.results["signature_verification"] = report
            return
        if self.card_public_key is None:
            report["summary"] = "G1 VU public key unavailable; TREP signatures not verified"
            self.results["signature_verification"] = report
            return

        all_valid = True
        signed_messages = 0
        for message in messages:
            entry = {
                "trep": f"0x{message['trep']:02X}",
                "section": TREP_NAMES.get(message["trep"], f"TREP 0x{message['trep']:02X}"),
            }
            # TREP 11/14 are the sensor-download extension and its raw trailer,
            # not Annex 1B signed data messages. Their absence of an RSA block
            # must not invalidate the signed preceding download payload.
            if message["trep"] in (0x11, 0x14):
                entry.update({"signature_valid": None, "reason": "signature not applicable"})
                report["treps"].append(entry)
                continue
            signed_messages += 1
            if not message["sig_len"]:
                entry.update({"signature_valid": False, "reason": "signature missing"})
                report["missing_signatures"] += 1
                all_valid = False
            else:
                signature = bytes(self.raw_data[message["body_end"]:message["end"]])
                payload_start = message["body_start"]
                if message["trep"] == 0x01:
                    # The G1 Overview begins with MSCA and VU certificates.
                    # They authenticate the key but are excluded from the
                    # download-data signature (Annex 1B Appendix 11).
                    payload_start += 194 + 194
                payload = bytes(self.raw_data[payload_start:message["body_end"]])
                valid = self.validator.verify_g1_data_signature(
                    self.card_public_key, signature, payload)
                entry["signature_valid"] = valid
                if not valid:
                    all_valid = False
            report["treps"].append(entry)

        report["all_treps_valid"] = signed_messages > 0 and all_valid
        valid_count = sum(entry["signature_valid"] is True for entry in report["treps"])
        report["summary"] = (
            f"G1 VU TREP signatures: {valid_count}/{signed_messages} valid"
        )
        self.results["signature_verification"] = report

        if self.validation_status == "Verified":
            if all_valid:
                self.validation_status = "Verified (G1 VU chain and TREP signatures)"
            elif report["missing_signatures"]:
                self.validation_status = "Incomplete (G1 VU TREP signatures missing)"
            else:
                self.validation_status = "Invalid G1 VU TREP Signature"

if __name__ == "__main__":
    import sys
    from core.utils.encoding import BytesEncoder

    if len(sys.argv) > 1:
        print(json.dumps(TachoParser(sys.argv[1]).parse(), indent=2, cls=BytesEncoder))
