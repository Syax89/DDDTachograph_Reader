# Tag/FID Decoding Matrix

The authoritative operational matrix is generated from `core.decoder_registry.DecoderRegistry`:

```bash
python3 specs/tag_decoding_matrix.py
python3 specs/tag_decoding_matrix.py --json
```

Do not maintain a second hand-written tag table here. Update `core/decoder_registry.py` or the generator when a tag/FID, generation, scope, dtype, parent context or Annex reference changes.

## Status Semantics

| Status | Meaning |
|---|---|
| `decoded` | Registered with a field decoder. |
| `container` | Registered as a structural container; semantic decoding happens in child tags or a stream walker. |
| `signature` | Registered as a certificate/signature block and used by verification flows. |
| `recognized_raw` | Known and referenced, but intentionally not field-decoded yet. |

## Required Matrix Fields

Every registry variant must expose:

| Field | Source |
|---|---|
| Tag/FID | `TagDecoder.tag` |
| Name | `TagDecoder.name` |
| Generation | `TagDecoder.generation` |
| Scope | `card_only` / `vu_only` |
| Encoding | derived by `specs/tag_decoding_matrix.py` |
| Status | derived by `specs/tag_decoding_matrix.py` |
| Decoder function | `TagDecoder.decoder_fn` |
| Record size / length limits | `record_size`, `min_length`, `max_length` |
| Context keys | `dtypes`, `parent_tags` |
| Normative reference | `annex_ref` |

## Current Residual Backlog

| Area | Status | Next Action |
|---|---|---|
| G1 VU `0x7611` sensor/special payload | Structurally classified opaque | Decode internally once normative payload layout is confirmed. |
| Deep field decode for Gen2 EF payloads | Partial (G2.2 card EFs rewritten against ASN.1) | Verify with real Gen2 card samples when available. |

## Quality Gates

The registry matrix is covered by tests so new entries cannot silently miss the minimum audit data:

```bash
python3 -m pytest tests/test_decoder_registry.py -q
```

The dataset gates remain:

```bash
python3 specs/semantic_coverage_audit.py --fail-on-regression
python3 specs/coverage_audit.py
```
