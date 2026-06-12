# Specification Documentation Reference

## Overview

The `specs/` directory contains the authoritative reference for tachograph tag structures, byte-level encoding, and verification status. All decoders and the deterministic parser are built against these specifications.

## Key Documents

### `specs/g1_complete_structures.md`

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

### `specs/g2_g22_complete_structures.md`

Comprehensive reference for **Generation 2 and Generation 2.2** tags (Annex 1C, Reg. EU 2016/799, Reg. EU 2023/980). Contains:
- Tag ID, name, and description for every G2/G2.2 tag
- Record sizes (confirmed or estimated)
- Field structures with byte offsets
- Annex 1C section references
- Distinction between G2 and G2.2 tags
- Container vs leaf classification

### `specs/g22_verification_status.md`

Verification status report for all G2.2 tags, grouped by confidence level:

**HIGH confidence** — Record size confirmed from published specification:
- 10 tags with confirmed dimensions and field offsets (e.g., `0x0509` VuCardRecord = 29 bytes from Annex 1C §4.5.3.2.8)

**MEDIUM confidence** — Field names known from specification, byte sizes estimated:
- 8 tags where the field list (campologia) is documented but exact byte sizes are inferred (e.g., `0x052D` VuOverSpeedingEventData ≈ 33 bytes)

**LOW confidence** — Pure reverse-engineering, no published specification:
- 7 tags where both field names and sizes are heuristic deductions from byte patterns in DDD files (e.g., `0x0529` LoadSensorData, `0x0531` VuSensorFaultData)

### `specs/tachograph.asn`

Formal **ASN.1 schema** defining the complete tachograph data model. Used as the reference for:
- Data type definitions (CHOICE, SEQUENCE, OCTET STRING constraints)
- Tag numbering and hierarchy
- Mandatory vs optional fields
- Size constraints

### `specs/coverage_audit.py`

Byte coverage analysis tool. Parses all DDD files in `DDD/` and reports:
- Total bytes, covered bytes, coverage percentage per file
- Unparsed byte ranges with hex snippets
- Pattern grouping of unparsed blocks

Usage:
```bash
python3 specs/coverage_audit.py
```

Output includes a JSON report at `specs/coverage_report.json`.

### `specs/SPEC_REFERENCE.md`

General reference document linking to EU regulations and technical standards.

### `specs/tag_decoding_matrix.md`

Matrix mapping tag IDs to decoder functions and their verification status.

## How Verification Status Is Determined

Tags in `specs/g22_verification_status.md` are classified into three confidence levels:

| Level | Criteria |
|---|---|
| **HIGH** | Record size and field offsets confirmed in the published EU regulation (Annex 1B, Annex 1C, Reg. 2023/980). Decoder matches the specification byte-for-byte. |
| **MEDIUM** | Field list (campologia) is documented in the regulation, but exact byte encoding or field sizes had to be estimated from DDD file analysis. Decoder captures fields correctly but may have edge cases. |
| **LOW** | No public specification exists for this tag. Structure was reverse-engineered from byte patterns in sample DDD files. Decoder is best-effort and may miss or misparse edge cases. |

In code, per-tag verification metadata lives in `DecoderRegistry`: each `TagDecoder` entry carries `annex_ref` and `generation`, and `DeterministicParser._record_tag()` marks an occurrence `is_spec_verified` when a registered decoder exists for the tag. The VU RecordArray walk uses the per-recordType confidence levels in `core/vu_record_dispatcher.RECORD_TYPES`.

## How to Read Annex 1B/1C References

The decoder registry (`core/decoder_registry.py`) and spec documents use consistent reference notation:

- **Annex 1B §X.Y** — EU Reg. 3821/85, Annex 1B, section X.Y
- **Annex 1C §X.Y** — EU Reg. 2016/799, Annex 1C, section X.Y
- **Annex 1C §4.5.3.2.N** — VU download data structure definitions
- **Reg. EU 2023/980** — G2.2 smart tachograph V2 update
- **Reg. EU 2021/1228** — Additional G2.2 specifications (GNSS authentication, load/unload)
- **ASN.1: TypeName** — Type definition from `specs/tachograph.asn`

### Example: Decoding an Annex 1C Reference

```
Annex 1C §4.5.3.2.8 → VuCardRecord
  └── 29 bytes: cardIssuingMemberState(1B) + cardNumber(16B) +
                 cardExpiryDate(4B timeReal) + cardConsecutiveIndex(1B) +
                 cardReplacementIndex(1B) + cardRenewalIndex(1B) +
                 cardApprovalNumber(4B)
```

This maps directly to `core/g2_decoders.py:11` (`parse_g2_card_record()`).

## Key EU Regulations

| Regulation | Covers | Tags |
|---|---|---|
| Reg. 3821/85 Annex 1B | G1 digital tachograph | 0x0001-0x0005, 0x0501-0x0522, 0x7601-0x7605 |
| Reg. EU 2016/799 Annex 1C | G2 smart tachograph | 0x0101-0x0201, 0x0509-0x0524, 0x7621-0x7634 |
| Reg. EU 2023/980 | G2.2 smart tachograph V2 | 0x0525-0x0533, 0x0222-0x0228, 0x7631-0x7634 |
| Reg. EU 2021/1228 | G2.2 GNSS auth, load/unload | 0x0525, 0x0526, 0x0528 |

## Additional Spec Tools

- **`specs/coverage_audit.py`** — Per-file byte coverage breakdown against the reference DDD samples
- **`specs/semantic_coverage_audit.py`** — Checks whether decoders populate expected semantic fields
- **`specs/unparsed_pattern_triage.py`** — Analyzes patterns in unparsed byte blocks for potential new tag discovery
- **`specs/test_det.py`** — Quick harness for the deterministic parser
