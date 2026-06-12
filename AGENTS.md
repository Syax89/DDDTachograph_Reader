# AGENTS.md — DDD Tachograph Reader

## Project overview
Cross-platform (Windows/macOS) application for parsing, analyzing and visualizing data from digital tachograph files (`.ddd` format). EU digital tachographs record driver activity, vehicle data, GNSS positions, and security certificate chains.

## Key architecture
- **Core parser**: `ddd_parser.py` → `core/deterministic_parser.py` (STAP/BER-TLV + VU stream walks, full byte coverage) → `core/decoders.py` facade (field-level decoders in core/card_decoders.py, core/vu_trep_decoders.py, etc.)
- **Coverage**: `CoverageTracker` in `core/deterministic_parser.py` — every byte classified (tag/padding/unknown); shared range-merging via `core/coverage_utils.py`
- **Decoder registry**: `core/decoder_registry.py` — centralized tag→decoder mapping with spec references (singleton pattern)
- **Deterministic parser**: `core/deterministic_parser.py` — the only parser (the legacy TagNavigator has been removed)
- **VU RecordArray**: `core/vu_record_dispatcher.py` walks the Annex 1C RecordArray stream by recordType; `core/record_array.py` provides the low-level parser
- **VU crypto**: `core/vu_signature_verifier.py` — ECDSA TREP signatures + CVC certificate chain verification (Appendix 11)
- **Event/fault codes**: `core/event_fault_codes.py` — 28 event types + 17 fault types per EU Reg. 2016/799 + 2023/980
- **Shared utils**: `core/coverage_utils.py` (interval merging, padding detection), `core/encoding.py` (BytesEncoder for JSON), `core/constants.py` (epochs, MAX_TLV_LENGTH)
- **Logger**: `core/logger.py` — centralized logging with _CountingHandler for decoder failure metrics; thread-safe via lock
- **Three generations**: G1 (Annex 1B, STAP encoding), G2 (Annex 1C, BER-TLV), G2.2 (Annex 1C update, BER-TLV)
- **Detection**: First 2 bytes of file: `0x7631`=G2.2, `0x7621`/`0x7622`=G2, else G1
- **Output models**: `core/models.py` (TachoResult hierarchy)
- **GUI**: `gui_tree.py` — regedit-style tree + table viewer with Excel/CSV/JSON export
- **CLI**: `tacho_cli.py` — full-featured CLI; `main.py` — minimal CLI
- **Export**: `export_manager.py` — comprehensive multi-sheet Excel + flat CSV export

## Running tests
```bash
python3 -m pytest tests/ -v
```
Requires: `pip install -r requirements.txt` (pytest, pyinstaller, cryptography, openpyxl, reportlab)

Tests use a conftest.py fixture that resets the DecoderRegistry singleton between tests.

## Spec documentation
All tag specifications are in `specs/`:
- `g1_complete_structures.md` — G1 tags, record sizes, field offsets, verification status
- `g2_g22_complete_structures.md` — G2/G2.2 tags with Annex 1C references
- `g22_verification_status.md` — G2.2 tag verification status (HIGH/MEDIUM/LOW confidence)
- `tachograph.asn` — Formal ASN.1 schema
- `architecture_migration_plan.md` — Migration plan to deterministic parser
- `coverage_audit.py` — Run with `python3 specs/coverage_audit.py` for file-by-file coverage report
- `semantic_coverage_audit.py` — Semantic coverage audit (unparsed bytes per file)
- `compare_parsers.py` — Legacy vs deterministic parser comparison

## Key regulations
- Reg. 3821/85 Annex 1B — G1 tachograph spec
- Reg. EU 2016/799 Annex 1C — G2 smart tachograph spec
- Reg. EU 2023/980 — G2.2 smart tacho V2
- Reg. EU 2021/1228 — G2.2 additional specs

## Coverage guarantee
files in `DDD/`. `DeterministicParser._classify_gaps()` sweeps any bytes missed by the structural walk, classifying them as padding or tracked unknown ranges. Shared interval merging via `core/coverage_utils.merge_intervals()`. Coverage audit: `python3 specs/coverage_audit.py`.
