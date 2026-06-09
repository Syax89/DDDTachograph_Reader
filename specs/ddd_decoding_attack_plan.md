# DDD Decoding Attack Plan

This document is the operational plan for completing semantic decoding of DDD files across G1, G2, and G2.2 card/VU formats.

## Mission

Reach measurable, regression-protected semantic decoding for all supported DDD families:

- G1 digital tachograph files, card and VU.
- G2 smart tachograph files, card and VU.
- G2.2 smart tachograph V2 files, card and VU.

The key rule is that tracked byte coverage is not enough. Bytes filled as `Unparsed Data` count as tracked, but not decoded.

## Control Metrics

- `tracked_byte_coverage`: percentage reported by the parser after known tags, padding, and gap tracking.
- `unparsed_bytes`: bytes present in `Unparsed Data` raw-tag ranges.
- `decoded_bytes`: `file_size - unparsed_bytes - padding_bytes`.
- `decoded_byte_coverage`: `decoded_bytes / file_size * 100`.
- `decoder_failure_count`: number of decoder exceptions or suppressed failures once instrumented.

Initial acceptance gates:

- `tracked_byte_coverage == 100%` on every real DDD file.
- `unparsed_bytes` must not increase versus `specs/semantic_coverage_report.json` baseline.
- G1 decoded byte coverage target: 90% initial, 98% final.
- G2 decoded byte coverage target: 85% initial, 95% final.
- G2.2 decoded byte coverage target: 75% initial, 90% final.

## Agent Roster

### Coordinator Agent

Owns sequencing, integration, and merge criteria.

Responsibilities:

- Maintain `specs/tag_decoding_matrix.md`.
- Assign one generation/tag family at a time.
- Require source reference, decoder, unit test, fixture/golden test, and metric delta before marking a tag complete.
- Keep parser changes minimal and centered on `core/decoder_registry.py` where possible.

Deliverables:

- Updated matrix.
- Per-iteration status: tags improved, DDD files improved, `unparsed_bytes` before/after, residual risk.

### Specification Agent

Owns normative and reverse-engineering evidence.

Responsibilities:

- Collect Annex 1B, Annex 1C, Reg. EU 2021/1228, Reg. EU 2023/980, Appendix 2/7/11 references.
- Confirm G2.2 structures currently marked LOW/MEDIUM confidence.
- Reconcile stale internal documents, especially older compliance notes versus current specs.

Deliverables:

- Source-backed tag rows in `specs/tag_decoding_matrix.md`.
- Confidence upgrades/downgrades with reasons.

### G1 Parser Agent

Responsibilities:

- Replace G1 VU heuristics with byte-level structures.
- Focus tags: `0x7601`, `0x7602`, `0x7603`, `0x7605`, `0x0508`, `0x050C`, `0x0222`, `0x0223`.
- Improve G1 certificate raw handling.

Deliverables:

- Decoder functions and registry entries.
- Tests for short input, nominal records, and multi-record data.

### G2 Parser Agent

Responsibilities:

- Complete BER-TLV and RecordArray decoding for Annex 1C VU records.
- Focus tags: `0x0509`, `0x050A`, `0x050B`, `0x050D`, `0x050F`, `0x0510`, `0x0511`, `0x0512`.

Deliverables:

- Deterministic parser compatibility.
- Golden deltas for G2 real files.

### G2.2 Parser Agent

Responsibilities:

- Attack the largest semantic gap first.
- Confirm containers `0x7631`, `0x7632`, `0x7633`, `0x7634`.
- Implement high-confidence missing decoders first: `0x052C`, `0x0532`, `0x0533`.
- Then handle `0x052D` through `0x0531`, `0x960F`, `0x6399`.

Deliverables:

- Reduced G2.2 `unparsed_bytes` on real files.
- Confidence status per tag.

### Security Agent

Responsibilities:

- Decode certificate structures, not only store raw bytes.
- Separate cryptographic signature verification from tachograph policy validation.
- Add negative tests for expired certificates, wrong issuer, tampering, wrong key usage, and unsupported algorithms.

Deliverables:

- Certificate parsing outputs.
- Policy validation tests.

### QA Agent

Responsibilities:

- Own semantic coverage gates.
- Build golden snapshots for real DDD files.
- Replace weak assertions such as `coverage >= 0` with meaningful gates.

Deliverables:

- `specs/semantic_coverage_audit.py` reports.
- Golden dataset snapshots.
- Regression tests that fail on lost fields or increased `unparsed_bytes`.

### Fuzz Agent

Responsibilities:

- Generate malformed DDD/TLV/STAP inputs.
- Validate parser never crashes with unhandled exceptions.
- Add file truncation, invalid BER length, impossible nesting, and padding anomalies.

Deliverables:

- Robustness corpus.
- Runtime and memory guardrails.

## Execution Order

1. Freeze current metrics with semantic coverage reporting.
2. Maintain the tag matrix as the single operational backlog.
3. Add golden snapshots for the 8 real files in `DDD/`.
4. Implement G2.2 high-confidence tags first.
5. Formalize G1 VU containers.
6. Complete G2 RecordArray VU structures.
7. Harden security/certificate validation.
8. Add fuzz/performance gates.

## Definition Of Done For A Tag

A tag is complete only when all of these are true:

- Source reference is listed.
- Record length or variable-length rules are documented.
- Decoder is registered in `core/decoder_registry.py`.
- Decoder has nominal, short-buffer, and multi-record tests where applicable.
- Real-file metric delta is recorded.
- Output fields are represented in models or raw structured output.
- Confidence is HIGH, or the remaining uncertainty is explicitly documented.
