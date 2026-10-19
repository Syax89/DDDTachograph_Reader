# Specification Documentation Reference

## Overview

The `scripts/` directory contains the authoritative reference for tachograph tag structures, byte-level encoding, and verification status. All decoders and the deterministic parser are built against these specifications.

## Key Documents

### `scripts/g1_complete_structures.md`

Comprehensive reference for **Generation 1** tags (Annex 1B, Reg. 3821/85). Contains:
- Tag ID, name, and description for every G1 tag
- Record sizes in bytes
- Field offsets within each record
- Verification status (whether confirmed against the published standard)
- Links to specific Annex 1B sections

Example entry:
```
| 0x0520 | G1_Identification | 143 bytes | Annex 1B §2.15+§2.17 | VERIFIED |
```

### `scripts/g2_g22_complete_structures.md`

Comprehensive reference for **Generation 2 and Generation 2.2** tags (Annex 1C, Reg. EU 2016/799, Reg. EU 2023/980). Contains:
- Tag ID, name, and description for every G2/G2.2 tag
- Record sizes (confirmed or estimated)
- Field structures with byte offsets
- Annex 1C section references
- Distinction between G2 and G2.2 tags
- Container vs leaf classification

### `scripts/g22_verification_status.md`

Verification status report for all G2.2 tags, grouped by confidence level:

**HIGH confidence** — Record size confirmed from published specification:
- 10 tags with confirmed dimensions and field offsets (e.g., `0x0509` VuCardRecord = 29 bytes from Annex 1C §4.5.3.2.8)

**MEDIUM confidence** — Field names known from specification, byte sizes estimated:
- 8 tags where the field list (campologia) is documented but exact byte sizes are inferred (e.g., `0x052D` VuOverSpeedingEventData ≈ 33 bytes)

**LOW confidence** — Pure reverse-engineering, no published specification:
- 7 tags where both field names and sizes are heuristic deductions from byte patterns in DDD files (e.g., `0x0529` LoadSensorData, `0x0531` VuSensorFaultData)

### VU event and fault records (Gen2, recordType 0x15 / 0x18)

`VuEventRecord` (Annex 1C Appendix 1 §2.198, 91 bytes) and `VuFaultRecord`
(§2.201, 90 bytes) are the one part of the VU RecordArray stream decoded *with a
per-record conformance verdict*. `core/parser/vu_dispatcher.py::decode_event_fault_record`
decodes every field the standard defines — `eventType`, `eventRecordPurpose`,
the two `TimeReal`s, the four `FullCardNumberAndGeneration` slots,
`similarEventsNumber` (events only) and `manufacturerSpecificEventFaultData` —
and reports on the emitted event/fault:

| Key | Meaning |
|---|---|
| `normative` | `True` when all standard-defined fields validate (size, card slots — a slot carries a tachograph card, `CardType` 1..5 — record purpose, time), `False` otherwise |
| `spec_reference` | `"Annex 1C App.1 2.198"` / `"Annex 1C App.1 2.201"` |
| `conformance_reason` | Why `normative` is `False` (absent when conformant) |
| `low_confidence_fields` | Fields whose value the standard does not define: `manufacturer_code` and `manufacturer_error_code` on every record, plus `similar_events` when it is `0` (§2.151 says 0 is "not used", yet real units write it), plus `event_type_code`/`fault_type_code` when the code is RFU or manufacturer specific in the amended `EventFaultType` assignment (point 2.70, "Generation 2, version 2" — Reg. 2018/502 + Reg. 2021/1228). In all those cases the record itself stays conformant |
| `end_semantics` | Present only on a time-conflict event (`EventFaultType '0B'H`): `end` holds the GNSS time, not an end |

Times are checked against a **plausibility window** (2000-2100), not a rule of the
standard (`TimeReal` itself runs to 2106): a time outside it is treated as a
corrupt field, which is the fail-closed choice. A record whose size is not 91/90
keeps the prefix view (`raw_tail_hex`) and is reported non-conforming — it is
surfaced, never dropped. Verification status (including the two amending acts
behind the type table) is in `scripts/g22_verification_status.md` §8.

`metadata.decode_paths` counts how the emitted events/faults were decoded:
`{"vu_events": {"normative": N, "non_normative": M}, ...}`, where
`non_normative` counts records the deterministic path decoded but whose fields
failed the conformance check. A switch to the heuristic byte scan is a different
thing and is declared separately by `metadata.decode_paths.fallback` (a list of
reasons), `metadata.heuristic_fields` and a WARNING — records from that route
carry no verdict at all, so they can never pass for the deterministic one.

The conformance keys stay in the JSON: `normative`, `spec_reference`,
`conformance_reason`, `low_confidence_fields`, `end_semantics` and
`manufacturer_error_code` are hidden from the tables (GUI and reports), exactly
like `confidence`. The visible `Events`/`Faults` columns are the ones the
generation-1 records already used (card-and-generation slots, similar events,
manufacturer code), so no new translatable label is introduced.

### `scripts/tachograph.asn`

Formal **ASN.1 schema** defining the complete tachograph data model. Used as the reference for:
- Data type definitions (CHOICE, SEQUENCE, OCTET STRING constraints)
- Tag numbering and hierarchy
- Mandatory vs optional fields
- Size constraints

### `scripts/coverage_audit.py`

Byte coverage analysis tool. Parses all DDD files in `DDD/` and reports:
- Total bytes, covered bytes, coverage percentage per file
- Unparsed byte ranges with hex snippets
- Pattern grouping of unparsed blocks

Usage:
```bash
python3 scripts/coverage_audit.py
```

Output includes a JSON report at `scripts/coverage_report.json`.

### `scripts/SPEC_REFERENCE.md`

General reference document linking to EU regulations and technical standards.

### `scripts/tag_decoding_matrix.md`

Matrix mapping tag IDs to decoder functions and their verification status.

## How Verification Status Is Determined

Tags in `scripts/g22_verification_status.md` are classified into three confidence levels:

| Level | Criteria |
|---|---|
| **HIGH** | Record size and field offsets confirmed in the published EU regulation (Annex 1B, Annex 1C, Reg. 2023/980). Decoder matches the specification byte-for-byte. |
| **MEDIUM** | Field list (campologia) is documented in the regulation, but exact byte encoding or field sizes had to be estimated from DDD file analysis. Decoder captures fields correctly but may have edge cases. |
| **LOW** | No public specification exists for this tag. Structure was reverse-engineered from byte patterns in sample DDD files. Decoder is best-effort and may miss or misparse edge cases. |


## How to Read Annex 1B/1C References

The decoder registry (`core/registry/registry.py`) and spec documents use consistent reference notation:

- **Annex 1B §X.Y** — EU Reg. 3821/85, Annex 1B, section X.Y
- **Annex 1C §X.Y** — EU Reg. 2016/799, Annex 1C, section X.Y
- **Annex 1C §4.5.3.2.N** — VU download data structure definitions
- **Reg. EU 2023/980** — G2.2 smart tachograph V2 update
- **Reg. EU 2021/1228** — Additional G2.2 specifications (GNSS authentication, load/unload)
- **ASN.1: TypeName** — Type definition from `scripts/tachograph.asn`

### Example: Decoding an Annex 1C Reference

```
Annex 1C §4.5.3.2.8 → VuCardRecord
  └── 29 bytes: cardIssuingMemberState(1B) + cardNumber(16B) +
                 cardExpiryDate(4B timeReal) + cardConsecutiveIndex(1B) +
                 cardReplacementIndex(1B) + cardRenewalIndex(1B) +
                 cardApprovalNumber(4B)
```

This maps directly to `decode_vu_card_record()` in `core/parser/vu_dispatcher.py` (dispatched via `core/decoders/vu_g2.py`).

## Key EU Regulations

| Regulation | Covers | Tags |
|---|---|---|
| Reg. 3821/85 Annex 1B | G1 digital tachograph | 0x0001-0x0005, 0x0501-0x0522, 0x7601-0x7605 |
| Reg. EU 2016/799 Annex 1C | G2 smart tachograph | 0x0101-0x0201, 0x0509-0x0524, 0x7621-0x7634 |
| Reg. EU 2023/980 | G2.2 smart tachograph V2 | 0x0525-0x0533, 0x0222-0x0228, 0x7631-0x7634 |
| Reg. EU 2021/1228 | G2.2 GNSS auth, load/unload | 0x0525, 0x0526, 0x0528 |

## Additional Spec Tools

- **`scripts/coverage_audit.py`** — Per-file byte coverage breakdown against the reference DDD samples
- **`scripts/semantic_coverage_audit.py`** — Checks whether decoders populate expected semantic fields
- **`scripts/unparsed_pattern_triage.py`** — Analyzes patterns in unparsed byte blocks for potential new tag discovery
