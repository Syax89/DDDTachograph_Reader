"""Main parser entry point for DDD tachograph files. Provides TachoParser with generation detection, deterministic parsing, and post-processing (dedup, signature validation)."""
import os
import json
import mmap
import warnings
import logging
from datetime import datetime, timezone

from core.crypto.signature import SignatureValidator
from core.registry.registry import DecoderRegistry
from core.registry.models import TachoResult, build_generations_tree
from core.utils import load_trace
from core.utils.version import __version__
from core import decoders
from core.decoders.common import mark_heuristic
from core.utils.logger import decoder_failure_count, decoder_failures, reset_decoder_failures

logger = logging.getLogger(__name__)

#: Result keys that are bookkeeping, not decoded data: the generation-1/2 walk
#: publishes ``vu_record_arrays`` as it goes and writes ``metadata`` continuously,
#: so neither may count as "the walk wrote records".
_BOOKKEEPING_KEYS = frozenset({"metadata", "vu_record_arrays"})


def _result_records(results):
    """The decoded record collections of a parse result (never bookkeeping)."""
    return {key: value for key, value in results.items()
            if isinstance(value, (list, dict))
            and key not in _BOOKKEEPING_KEYS
            and not str(key).startswith("_")}


def _results_size(results):
    """Total length of the decoded record collections: "has the walk written yet".

    ``_declare_vu_fallback`` compares this before and after the deterministic
    walk. A walk that wrote nothing can still be backed by the byte scan; a walk
    that wrote *something* and then failed must never be rescanned, because the
    scan reads the same bytes and would duplicate whatever already landed — and
    that is true wherever inside the walk it failed, including half-way through
    emitting the very first section. Bookkeeping is excluded on purpose: a section
    that emitted no records must not look like walk output.
    """
    return sum(len(value) for value in _result_records(results).values())


def _parse_timestamp(value):
    """Parse an ISO-8601 tachograph timestamp to an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
        self.card_cert_sign_seen = False
        # A generation-2 (CVC/DER encoded) CA has claimed the generation-2
        # `msca_cert_raw` slot; a later generation-1 CA copy must not take it.
        self.ca_cert_g2_seen = False
        self.msca_cert_g1 = None
        self.card_cert_g1 = None
        self.validation_status = "Pending"
        self.is_vu = False
        # Per-generation chain trust. A verified chain for one generation must
        # never launder another generation's untrusted signing key.
        self._chain_trust = {"G1": False, "G2": False}
        self._chain_present = {"G1": False, "G2": False}

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
            chain_phase_ok = self._run_phase(
                "certificate_chain", self._validate_certificate_chain)
            self._run_phase("g1_vu_signatures", self._verify_g1_vu_signatures)
            ef_phase_ok = self._run_phase("ef_signatures", self._verify_ef_signatures)
            self._run_phase("embedded_cards", self._decode_embedded_cards)
            # The certificate chain authenticates the card key, not the EF
            # payloads, so EF verification must be folded into the overall
            # verdict before it is published (an EF failure must not keep the
            # file looking identical to a clean one).
            self._apply_ef_verdict(ef_phase_ok, chain_phase_ok)

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
        Returns ``True`` when the phase completed, ``False`` when it raised so
        callers can fail closed on integrity-relevant phases.
        """
        try:
            with load_trace.span("phase." + phase_name):
                fn()
            return True
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
            return False


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
        self.card_cert_sign_seen = False
        self.ca_cert_g2_seen = False
        self.msca_cert_g1 = None
        self.card_cert_g1 = None
        self.validation_status = "Pending"
        self._chain_trust = {"G1": False, "G2": False}
        self._chain_present = {"G1": False, "G2": False}

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
        # A stand-alone TREP 06 envelope is a card image relayed through the VU:
        # SID 0x76 + TREP 06 followed by the complete card. It is the plain card
        # plus two bytes, so it takes the plain card route (never the VU stream
        # walk, which cannot verify the card's EF signatures or read its
        # generation-2 side). Anything that does not walk as a clean card image
        # stays on the VU path.
        self._envelope = None
        self._envelope_rejected = None
        if self.is_vu:
            from core.parser.card_envelope import trep06_envelope
            head = bytes(self.raw_data[:2])
            envelope = trep06_envelope(bytes(self.raw_data))
            if envelope is None and head == b"\x76\x06":
                # Several relayed cards back to back: the first one gives the file
                # its identity and verdict, the others keep their own per-region
                # verdict instead of degrading the first.
                from core.parser.card_envelope import trep06_card_regions
                regions = trep06_card_regions(bytes(self.raw_data))
                if regions:
                    extra = [{"offset": start, "bytes": length, "tlvs": None,
                              "tlv_complete": True,
                              "boundary": "STAP/EF framing", "delegated": False}
                             for start, length in regions[1:]]
                    envelope = {"bytes": regions[0][0], "card_bytes": regions[0][1],
                                "elements": None, "extra_regions": extra,
                                "multi": True}
            if envelope:
                self._envelope = envelope
                self.is_vu = False
            elif head == b"\x76\x06":
                # A TREP 06 transfer whose card image does not close: the file is
                # NOT decoded as a card (the bytes are not a clean image), and the
                # reason is reported instead of passing as a partial VU stream.
                self._envelope_rejected = {
                    "trep": "0x06",
                    "status": "card_envelope_incomplete",
                    "detail": ("76 06 header but the card EF stream does not close"),
                    "missing_bytes": 0,
                    "trailing_bytes": 0,
                }

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
        offset = 0
        data = self.raw_data
        if self._envelope:
            # Decode the card exactly as if the file had no transfer header, then
            # account for the two bytes: every offset is shifted and the coverage
            # total stays the real file size.
            offset = int(self._envelope["bytes"])
            limit = self._envelope.get("card_bytes")
            data = bytes(self.raw_data[offset:offset + limit]) if limit else (
                bytes(self.raw_data[offset:]))
        self.results = dp.parse(data, is_vu=self.is_vu)
        # dp.parse() returns a fresh results dict — restore file metadata.
        self.results["metadata"]["filename"] = os.path.basename(self.file_path)
        self.results["metadata"]["app_version"] = __version__
        if self._envelope_rejected:
            self.results["metadata"].setdefault("vu_integrity", []).append(
                dict(self._envelope_rejected))
        if offset:
            self.results["metadata"]["envelope"] = {
                "type": "TREP 06 card download relayed by the VU",
                "bytes": offset,
            }
            if self._envelope.get("extra_regions"):
                self.results["metadata"]["envelope"]["further_regions"] = len(
                    self._envelope["extra_regions"])
                self.results["metadata"].setdefault(
                    "vu_card_download_sections", []).extend(
                        self._envelope["extra_regions"])
            # Same wording the content-based origin detector uses for a card
            # image behind a TREP 06 transfer.
            self.results["metadata"]["origin_note"] = (
                "Card image extracted from a VU Card Download "
                "(TREP 06, DDP_049/DDP_050) \u2014 valid selective download")
            self._shift_envelope_offsets(self.results, offset)

    @staticmethod
    def _shift_envelope_offsets(results, delta):
        """Shift the offsets produced by an envelope parse by *delta* bytes.

        The card was decoded from ``raw[delta:]``: every reported offset (the
        per-tag table, the coverage ranges) is relative to the card image, so it is
        moved back onto the real file. Percentages do not change.
        """
        def shift(value):
            if isinstance(value, dict):
                return {k: (f"0x{int(v, 16) + delta:08X}"
                            if k == "offset" and isinstance(v, str)
                            else shift(v))
                        for k, v in value.items()}
            if isinstance(value, list):
                return [shift(item) for item in value]
            return value

        # Every offset-bearing structure is shifted: the per-tag table, the
        # generations tree (which carries its own copy) and the coverage ranges.
        for key in list(results):
            if key == "metadata":
                continue
            results[key] = shift(results[key]) if key != "coverage" else results[key]
        coverage = results.get("coverage")
        if isinstance(coverage, dict):
            coverage["total_bytes"] = int(coverage.get("total_bytes") or 0) + delta
            coverage["uncovered_ranges"] = shift(coverage.get("uncovered_ranges") or [])

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
        verification. G1: deterministic TREP walk. When the deterministic path
        cannot vouch for the file, the byte-scan heuristic may still recover
        data — but the switch is declared (WARNING + metadata), never silent.
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
            fallback_reason = None
            written_before = _results_size(self.results)
            try:
                from core.parser.vu_dispatcher import walk_vu_record_arrays
                walker_success = walk_vu_record_arrays(self.raw_data, self.results)
                # Completeness comes from the real walk outcome: a truncated
                # array (rs*nr beyond EOF) or the global record cap leaves the
                # stream incomplete and is reported as partial, never complete.
                complete = bool(self.results.get("_vu_walk_complete", False))
                # Only fall back to heuristic if the walker produced NO results
                if not walker_success or not self.results.get("vu_record_arrays"):
                    fallback_reason = "RecordArray walk produced no sections"
                    self._record_fallback_reason(
                        "vu_fallback_scan", "unknown_or_misplaced_section",
                        detail=fallback_reason)
                    complete = False
            except Exception as exc:
                # The traceback is diagnostic detail; the fallback itself is
                # declared at WARNING by _declare_vu_fallback below.
                logger.debug("VU RecordArray dispatch raised: %s", exc, exc_info=True)
                complete = False
                fallback_reason = f"RecordArray walk raised {type(exc).__name__}: {exc}"
                self._record_fallback_reason(
                    "vu_fallback_scan", "normative_decoder_exception",
                    detail=fallback_reason)
            if fallback_reason:
                self._declare_vu_fallback(
                    fallback_reason,
                    walker_wrote=_results_size(self.results) > written_before)
            if not complete:
                logger.warning("VU download incomplete: %s",
                               "record cap reached" if self.results.get("_vu_walk_record_cap")
                               else "truncated/partial RecordArray stream")
            self._build_trep_report(generation, complete_walk=complete)
            # Cryptographic integrity: verify the ECDSA download signatures
            # and the MSCA→VU certificate chain (Annex 1C Appendix 11).
            try:
                from core.crypto.vu_signature import (
                    verify_vu_download, decode_vu_certificates)
                erca_keys = self.validator._g2_erca_keys() or None
                self.results["signature_verification"] = verify_vu_download(
                    self.raw_data, erca_keys=erca_keys,
                    verification_time=self._signature_timestamp())
                self.results["vu_certificates"] = decode_vu_certificates(self.raw_data)
            except Exception as exc:
                logger.warning("VU signature verification unavailable: %s", exc,
                               exc_info=False)
                self.results["signature_verification"] = {"overall": "unavailable"}
        else:
            # G1 VU: deterministic TREP walk (Annex 1B §2.2.6) with
            # the byte-scan heuristic as fallback for files the walk
            # cannot validate (truncated/non-standard downloads).
            reason = "G1 deterministic walk did not cover the file"
            cause = "unknown_or_misplaced_section"
            walk_raised = False
            try:
                from core.parser.g1_walker import walk_g1_vu
                _messages, complete = walk_g1_vu(self.raw_data, self.results)
                # Integrity findings (a truncated marker, a card region that does
                # not close, a short signature block) make the download partial in
                # this generation exactly as they do in the RecordArray walker; the
                # heuristic scan is still not run for them.
                if (self.results.get("metadata") or {}).get("vu_integrity"):
                    complete = False
            except Exception as exc:
                logger.debug("G1 VU walk raised: %s", exc, exc_info=True)
                complete = False
                _messages = []
                reason = f"G1 walk raised {type(exc).__name__}: {exc}"
                cause = "normative_decoder_exception"
                walk_raised = True
            if not complete:
                # INTEGRITY vs DECODABILITY. A short signature block or trailing
                # junk is an integrity finding: every declared record of every
                # message was decoded normatively, so the byte scan must not run —
                # it would only add low-confidence duplicates on top. The walk
                # reports the download as partial (and metadata.vu_integrity says
                # why), exactly like the Gen2 path.
                # The primary cause: a stream that does not even open with a known
                # TREP marker is misplaced/unknown; a known marker whose declared
                # body does not fit the bytes is a truncated file; a walker that
                # raised is our defect.
                from core.parser.g1_walker import TREP_NAMES
                head = self.raw_data[:2]
                if walk_raised:
                    cause = "normative_decoder_exception"
                elif len(head) < 2 or head[0] != 0x76 or head[1] not in TREP_NAMES:
                    cause = "unknown_or_misplaced_section"
                else:
                    cause = "file_truncated"
                if (self.results.get("metadata") or {}).get("vu_units"):
                    # Per-TREP rule: the walk already ran the heuristic on each
                    # failed unit's own byte range, so the whole-file scan would
                    # re-read bytes the normative walk vouched for. The failure is
                    # still declared (the reason above) and the affected sections
                    # keep their heuristic marking.
                    # No byte scan ran here: the walk bounded the damage per TREP
                    # and declared the zones. The route says exactly that.
                    self._record_fallback_reason(
                        "vu_walk_incomplete", cause,
                        trep=(f"0x{(_messages or [{}])[-1].get('trep', 0):02X}"
                              if _messages else None),
                        detail=reason)
                    self._declare_vu_fallback(reason, walker_wrote=True)
                elif self.results.get("_g1_walk_decoded_all"):
                    logger.warning(
                        "VU download incomplete: %s",
                        "signature block shorter than the normative length"
                        if any(entry.get("status") == "signature_truncated"
                               for entry in (self.results.get("metadata") or {})
                               .get("vu_integrity") or [])
                        else "trailing bytes after the last message")
                else:
                    # Gen1 keeps its long-standing recovery for a walk that could
                    # not decode data. What is new is that the switch is declared
                    # with a structured cause and everything the scan adds is
                    # marked heuristic.
                    # The primary cause: a stream that does not even open with a
                    # known TREP marker is misplaced/unknown; a known marker whose
                    # declared body does not fit the bytes is a truncated file.
                    # The cause was determined above; the walker's exception, when
                    # there was one, already kept its honest classification.
                    self._record_fallback_reason(
                        "vu_fallback_scan", cause,
                        trep=(f"0x{(_messages or [{}])[-1].get('trep', 0):02X}"
                              if _messages else None),
                        offset=((_messages or [{}])[-1].get("end")
                                if _messages else None),
                        detail=reason)
                    self._declare_vu_fallback(reason)
            present = sorted({m["trep"] for m in (_messages or [])})
            self._build_trep_report(generation, complete_walk=complete,
                                    present_treps=present)

    def _decode_embedded_cards(self):
        """Run the *plain card* pipeline over every embedded card region.

        A ``76 06`` section inside a VU stream carries a card image. The structural
        walk alone gives its EFs but not its EF signatures, certificate chain or
        full generations tree — the card's generation-2 data can then be missing or
        partial. Each region is therefore parsed through the same pipeline a plain
        card file takes, its semantic keys are merged into the VU result, and its
        verdict is reported per region (never folded into the VU chain verdict).
        """
        regions = ((self.results.get("metadata") or {})
                   .get("vu_card_download_sections") or [])
        for info in regions:
            # A region is processed when its byte range is known and closes; the
            # generation-2 walker marks it "delegated", the generation-1 walker
            # records the same fields without delegating itself.
            if not info.get("tlv_complete"):
                continue
            start, size = int(info.get("offset", 0)), int(info.get("bytes", 0))
            if size <= 0:
                continue
            chunk = bytes(self.raw_data[start:start + size])
            sub = self._parse_card_bytes(chunk)
            if not sub:
                info["plain_card_parse"] = "failed"
                continue
            from core.decoders.vu_g1 import _merge_card_download
            _merge_card_download(self.results, sub)
            ef = sub.get("ef_signature_verification") or {}
            info["plain_card_parse"] = "ok"
            info["integrity_check"] = (sub.get("metadata") or {}).get(
                "integrity_check")
            info["ef_signatures"] = {
                "verified": ef.get("verified"), "failed": ef.get("failed"),
                "total": ef.get("total"), "summary": ef.get("summary")}
            info["generation"] = (sub.get("metadata") or {}).get("generation")
            self.results["metadata"].setdefault("embedded_card_verdicts", []).append({
                "offset": f"0x{start:08X}", "bytes": size,
                "generation": info["generation"],
                "integrity_check": info["integrity_check"],
                "ef_signatures": info["ef_signatures"],
            })
            failed = int(info["ef_signatures"].get("failed") or 0)
            if failed:
                # A damaged embedded card is REPORTED (the tree above is the VU's
                # own state, so its verdict cannot carry the card's failure).
                self.results["metadata"].setdefault("vu_integrity", []).append({
                    "trep": "0x06", "status": "card_ef_signature_invalid",
                    "detail": f"{failed} EF signature(s) failed in the embedded card",
                    "missing_bytes": 0, "trailing_bytes": 0})

    @staticmethod
    def _parse_card_bytes(chunk):
        """Parse a card image held in memory through the plain card pipeline."""
        import tempfile
        handle = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
        try:
            handle.write(chunk)
            handle.close()
            from core.registry.registry import DecoderRegistry
            DecoderRegistry.reset_instance()
            return TachoParser(handle.name).parse()
        except Exception as exc:                        # pragma: no cover
            logger.debug("Embedded card parse failed: %s", exc, exc_info=False)
            return None
        finally:
            try:
                os.unlink(handle.name)
            except OSError:
                pass

    def _record_fallback_reason(self, route, cause, **kwargs):
        """Record one structured fallback reason (see core.parser.fallback_reasons)."""
        from core.parser.fallback_reasons import record_fallback_reason
        return record_fallback_reason(self.results, route, cause, **kwargs)

    def _fallback_log_reason(self, sentence):
        """``<cause> @ <trep>:<offset>`` for the log line, else *sentence*."""
        from core.parser.fallback_reasons import primary_reason
        primary = primary_reason(self.results)
        if not primary:
            return sentence
        location = primary.get("trep") or "stream"
        if primary.get("offset") is not None:
            location = f"{location}@{primary['offset']}"
        detail = primary.get("detail") or sentence
        return (f"{primary['cause']} at {location} "
                f"({primary['classification']}): {detail}")

    def _declare_vu_fallback(self, reason, walker_wrote=False):
        """Declare a VU decode route switch and recover what the scan still can.

        The deterministic walk is the only path that can vouch for a record
        conforming to the standard, so nothing a backup route recovers may look
        spec-verified: the gained sections are marked heuristic
        (``metadata.heuristic_fields``) and the switch itself is recorded in
        ``metadata.decode_paths`` and logged at WARNING. Records the scan
        produces never carry ``normative``/``confidence: high``, so a backup
        route cannot launder a record into looking standard-conformant.

        The scan re-reads the *whole* stream, so on the Gen2 RecordArray path it
        runs only when the walk wrote nothing at all: ``walker_wrote`` says so
        wherever inside the walk it failed. ``vu_record_arrays`` is deliberately
        *not* consulted — it is bookkeeping that exists even for a section that
        emitted no records, and a record-less walk must not block the scan.

        The Gen1 TREP walk keeps its long-standing recovery **unchanged**: it calls
        this without ``walker_wrote``, so its scan always runs, exactly as before
        this change. That scan dedupes only byte-identical records, so over an
        incomplete walk it can still add records decoded from bytes the walk had
        already read — pre-existing behaviour, deliberately untouched. What this
        change adds there is visibility: everything the scan adds is marked
        heuristic, by its own sub-parsers (``vu_events_faults_TREP03``,
        ``vu_activities_TREP02``, …) and by the ``vu_fallback_scan`` entry written
        here. The never-rescan-over-written-records guard is Gen2-only.
        """
        paths = self.results.setdefault("metadata", {}).setdefault("decode_paths", {})
        paths.setdefault("fallback", []).append(reason)
        # The byte scan re-reads the whole stream, so it only runs when the
        # deterministic walk wrote no records: a partly-emitted stream would
        # otherwise be decoded twice, once per route.
        if walker_wrote:
            logger.warning("VU deterministic decode fell back (%s): the affected "
                           "sections stay partial, no heuristic rescan",
                           self._fallback_log_reason(reason))
            return
        before = {key: len(value) for key, value in _result_records(self.results).items()}
        decoders.parse_vu_download_messages(self.raw_data, self.results)
        # Everything the scan added, whatever kind of record it is (overview
        # fields live in a mapping, not in a list) — not just the keys the caller
        # happens to care about.
        gained = sorted(key for key, value in _result_records(self.results).items()
                        if len(value) > before.get(key, 0))
        if gained:
            mark_heuristic(self.results, "vu_fallback_scan", gained)
        # The sentence and metadata.heuristic_fields must describe the same set.
        marked = sorted((self.results.get("metadata") or {}).get("heuristic_fields") or {})
        logger.warning("VU deterministic decode fell back (%s): heuristic byte "
                       "scan recovered %s; sections marked heuristic: %s",
                       self._fallback_log_reason(reason),
                       ", ".join(gained) or "nothing", ", ".join(marked) or "none")

    def _build_trep_report(self, generation, complete_walk=True, present_treps=None):
        """Summarise TREP completeness (mandatory read / total) into metadata.

        ``present_treps`` may be supplied by the G1 walk; for G2 it is derived
        from the decoded RecordArray sections. TREPs flagged during decoding as
        implausible (``_suspect_sections``) are reported as 'suspect'.

        First confirms the file origin from its content: a driver-card image
        wrapped in a stand-alone TREP 06 Card Download is a valid selective
        download (DDP_049/DDP_050), not a VU stream, so it is reclassified as
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
            """Deterministic, hashable representation of decoded data.

            ``json.dumps`` with sorted keys is the cheap equivalent of the
            recursive tuple builder this used to be: key order does not matter,
            types are kept distinct, and a day block no longer costs one Python
            call per nested value (it was the single most expensive call of a
            full parse).
            """
            return json.dumps(value, sort_keys=True, default=repr)

        def _fingerprint(record):
            """A cheap, stable identity for one day: its scalar fields + list sizes.

            A pure function of the record, so two canonically identical days always
            share it; it exists only to keep the recursive ``_canonical`` walk off
            the hot path (it used to run over every activity change of every day).
            Two days with the same fingerprint are still compared canonically, so
            the definition of "duplicate" does not change.
            """
            scalars, shapes = [], []
            for field, value in record.items():
                if isinstance(value, (list, tuple, set, dict)):
                    shapes.append((field, type(value).__name__, len(value)))
                else:
                    scalars.append((field, _canonical(value)))
            return (tuple(sorted(scalars, key=repr)), tuple(sorted(shapes)))

        buckets = {}
        unique = []
        for act in self.results["activities"]:
            bucket = buckets.setdefault(_fingerprint(act), [])
            if bucket:
                key = _canonical(act)
                if any(_canonical(existing) == key for existing in bucket):
                    continue
            bucket.append(act)
            unique.append(act)
        unique.sort(key=lambda x: _safe_parse_date(x.get("date")) or datetime.min, reverse=True)
        self.results["activities"] = unique

    def _signature_timestamp(self):
        """The moment the download was signed, for certificate-date evaluation.

        For a VU download this is the latest VuDownloadActivityData
        ``downloading_time``; for a driver card the EF Card_Download date.
        Returns ``None`` when the file carries no such timestamp, so an undated
        file keeps its historical "not checked" behaviour instead of being
        judged against the wall clock (a historic download's expired certificate
        remains useful evidence).
        """
        candidates = []
        for entry in self.results.get("download_activities") or []:
            if isinstance(entry, dict):
                candidates.append(entry.get("downloading_time"))
        for entry in self.results.get("card_downloads") or []:
            if isinstance(entry, dict):
                candidates.append(entry.get("download_time"))
        parsed = [t for t in (_parse_timestamp(value) for value in candidates) if t]
        return max(parsed) if parsed else None

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
        # Each generation present in the file is validated independently so its
        # trust outcome can be retained: a fully-anchored chain for one
        # generation must never launder an unanchored/failed key of another
        # (see _apply_ef_verdict).
        chain_trust = {"G1": False, "G2": False}
        chain_present = {"G1": False, "G2": False}
        temporal = {}

        status, pubkey = False, None
        if self.card_cert_raw and self.msca_cert_raw:
            # The last certificates seen in the file may be the G2 copies; a
            # file can also carry distinct G1 (194-byte) certificates whose
            # leading byte is unconstrained. The validator reports the
            # generation it actually validated (it retries the G1 chain when a
            # G1 certificate happens to start with the 0x30/0x7F G2 marker), so
            # per-generation trust follows the real chain, not the raw byte.
            verify_time = self._signature_timestamp()
            status, pubkey = self.validator.validate_tacho_chain(
                self.card_cert_raw, self.msca_cert_raw,
                verification_time=verify_time)
            raw_gen = getattr(self.validator, "last_chain_generation", None) or "G2"
            chain_present[raw_gen] = True
            if status is True:
                chain_trust[raw_gen] = True
            temporal.update(self.validator.last_chain_temporal_validity)

            if self.card_cert_g1 and self.msca_cert_g1 and \
                    (self.card_cert_g1 != self.card_cert_raw
                     or self.msca_cert_g1 != self.msca_cert_raw):
                g1_status, g1_pubkey = self.validator.validate_tacho_chain(
                    self.card_cert_g1, self.msca_cert_g1,
                    verification_time=verify_time)
                chain_present["G1"] = True
                if g1_status is True:
                    chain_trust["G1"] = True
                # Keep the temporal status already reported by the G2 chain;
                # the G1 path does not populate it.
                for key, value in self.validator.last_chain_temporal_validity.items():
                    temporal.setdefault(key, value)
                # Keep the better chain outcome for the reported verdict, and on
                # a full-verify tie keep the G1 key: it is the RSA key the G1 EF
                # signatures need, while the G2 CVC key stays available as the
                # ECDSA fallback in _verify_ef_signatures.
                rank = {True: 4,
                        "Incomplete (Missing ERCA)": 3,
                        "Partial — MSCA→Card verified (no ERCA root)": 2,
                        "Cannot Verify (Missing ERCA Root)": 1}
                if (rank.get(g1_status, 0) > rank.get(status, 0)
                        or (g1_status is True and status is True)):
                    status, pubkey = g1_status, g1_pubkey
        elif self.card_cert_g1 and self.msca_cert_g1:
            # G1 VU files: certificates were extracted from TREP 01 Overview
            # and stored directly as the G1 copies.
            status, pubkey = self.validator.validate_tacho_chain(
                self.card_cert_g1, self.msca_cert_g1,
                verification_time=self._signature_timestamp())
            chain_present["G1"] = True
            if status is True:
                chain_trust["G1"] = True
            temporal.update(self.validator.last_chain_temporal_validity)

        self._chain_trust = chain_trust
        self._chain_present = chain_present

        if temporal:
            self.results["certificate_temporal_validity"] = temporal
            self.validator.last_chain_temporal_validity = temporal

        if status is True:
            self.validation_status = "Verified"
            self.card_public_key = pubkey
        elif status == "Partial — MSCA→Card verified (no ERCA root)":
            # MSCA→Card link holds, but the chain is not anchored to a trusted
            # ERCA root: a self-signed attacker chain would land here, so this
            # must never read as verified.
            self.validation_status = "Unverified (CVC MSCA→Card ok, no ERCA anchor)"
        elif status == "Partial — MSCA→Card verified (ERCA anchor FAILED)":
            self.validation_status = "Unverified (CVC MSCA→Card ok, ERCA anchor failed)"
        elif status == "Incomplete (Missing ERCA)":
            # Local (self-asserted) chain only — no trusted root, so not verified.
            self.validation_status = "Unverified (Local Chain Only — ERCA Missing)"
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
            # A presented card certificate chain that failed outright must keep
            # its negative verdict: valid VU signatures elsewhere in the file
            # prove the VU payload, not the card, and must never launder a
            # broken card chain. The overall verdict is the worst of the parts,
            # not the best.
            card_chain_failed = had_certs and status is False
            sv = self.results.get("signature_verification") or {}
            if sv.get("msca_to_vu") is True and not card_chain_failed:
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
        from core.crypto.ef_signature import (
            missing_core_efs,
            observed_generations,
            pair_ef_records,
            verify_ef_pairs,
        )
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
        # Record, per EF generation actually present, whether the chain that
        # supplied its signing key is trusted. The overall verdict requires every
        # applicable generation to be trusted (see _apply_ef_verdict and
        # core.utils.report_format.integrity_verdict).
        chain_trust = getattr(self, "_chain_trust", None) or {}
        # Only generations an EF result actually evidences: an ``unsupported``
        # lone signature must not report a phantom untrusted signing key
        # (audit: BATCH7_RETROSPECTIVE_REVIEW F1).
        present = observed_generations(ef_report.get("ef_results", []))
        ef_report["untrusted_generations"] = sorted(
            gen for gen in present if not chain_trust.get(gen, False))
        ef_report["missing_core_efs"] = missing_core_efs(pairs)
        self.results["ef_signature_verification"] = ef_report

    def _apply_ef_verdict(self, ef_phase_ok, chain_phase_ok=True):
        """Fold chain + EF signature verification into the overall verdict.

        The certificate chain authenticates the card key, not the EF payloads,
        so a download can only read as Verified when *every* applicable EF
        generation is backed by a trusted chain and its signatures verified.
        The fold only ever downgrades: an already invalid/unanchored chain is
        never upgraded. VU downloads carry their own verdict via
        ``signature_verification`` and are left untouched.
        """
        if self.is_vu:
            return
        if not chain_phase_ok:
            # The chain phase raised: never publish a stale positive verdict.
            self.validation_status = "Unverified (Certificate Chain Error)"
            return
        if not str(self.validation_status).startswith("Verified"):
            # Keep the authoritative negative/partial chain verdict.
            return
        if not ef_phase_ok:
            self.validation_status = "Unverified (EF Signature Verification Failed)"
            return
        efv = self.results.get("ef_signature_verification") or {}
        missing_core = efv.get("missing_core_efs") or []
        if missing_core:
            # A signed EF was removed outright (both data and signature
            # copies): it leaves no trace in ef_results, so a chain-only
            # check would read this as "nothing to verify, OK"
            # (E-F3/CARD-MANDATORY-MISSING).
            self.validation_status = "Unverified (Missing EF: {})".format(
                ", ".join(f"0x{tag:04X}" for tag in missing_core))
            return
        untrusted = efv.get("untrusted_generations") or []
        if untrusted:
            # EF maths may check out against an attacker key; without a trusted
            # chain for that generation the download is still unverified.
            self.validation_status = "Unverified ({} card key not trusted)".format(
                "/".join(untrusted))
        elif not (efv.get("ef_results") or []):
            # No signed EF pair at all: a certificate chain alone does not make
            # a download fully verified.
            self.validation_status = "Unverified (No EF Signature Pairs)"
        elif efv.get("failed", 0):
            self.validation_status = "Unverified (EF Signature Mismatch)"
        elif efv.get("skipped", 0):
            self.validation_status = "Unverified (EF Signatures Incomplete)"

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
        # Root anchoring comes from the structured per-generation chain trust
        # recorded by _validate_certificate_chain, never from the human-readable
        # verdict string: a suffixed status ("Verified (…)", "Partial …") must
        # not make an anchored chain look unanchored (or vice versa), and a
        # re-run over an already-suffixed verdict must stay consistent.
        chain_trust = getattr(self, "_chain_trust", None) or {}
        report = {
            "available": self.card_public_key is not None,
            "algorithm": "RSA-SHA1",
            "msca_to_vu": self.card_public_key is not None,
            "root_anchored": bool(chain_trust.get("G1")),
            "treps": [],
            "all_treps_valid": False,
            "missing_signatures": 0,
            "summary": "",
        }
        if not messages:
            report["summary"] = "No G1 VU TREP sections found"
            self.results["signature_verification"] = report
            if self.validation_status.startswith("Verified"):
                self.validation_status = "Unverified (G1 VU TREP Signatures Not Checked)"
            return
        if self.card_public_key is None:
            report["summary"] = "G1 VU public key unavailable; TREP signatures not verified"
            self.results["signature_verification"] = report
            if self.validation_status.startswith("Verified"):
                self.validation_status = "Unverified (G1 VU TREP Signatures Not Checked)"
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
            if message.get("card_region"):
                # Card data forwarded inside the VU transfer (DDP_049): the card
                # carries its own EF signatures, so the region is neither a VU
                # TREP payload nor a missing VU signature. Counting it as one
                # would flip a healthy VU download to "incomplete".
                entry.update({"signature_valid": None,
                              "reason": "card data forwarded in the VU transfer"})
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

        if self.validation_status.startswith("Verified"):
            if report["all_treps_valid"]:
                self.validation_status = "Verified (G1 VU chain and TREP signatures)"
            elif report["missing_signatures"]:
                self.validation_status = "Incomplete (G1 VU TREP signatures missing)"
            elif signed_messages == 0:
                # Only unsigned TREP 0x11/0x14 sections were present: nothing
                # to check, so "Verified" must not stand, but nothing failed
                # either -- E-F4 (CRYPTO-G1-VU-STALE-VERDICT).
                self.validation_status = "Unverified (G1 VU TREP Signatures Not Checked)"
            else:
                self.validation_status = "Invalid G1 VU TREP Signature"

if __name__ == "__main__":
    import sys
    from core.utils.encoding import BytesEncoder

    if len(sys.argv) > 1:
        print(json.dumps(TachoParser(sys.argv[1]).parse(), indent=2, cls=BytesEncoder))
