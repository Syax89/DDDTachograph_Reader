# AGENTS.md — DDD Tachograph Reader

## Project overview
Cross-platform (Windows/macOS) application for parsing, analyzing and visualizing data from digital tachograph files (`.ddd` format). EU digital tachographs record driver activity, vehicle data, GNSS positions, and security certificate chains.

## Key architecture
- **Entry point**: `app/main.py` (CLI) → `app/engine.py` (TachoParser) → `core/parser/deterministic.py` (STAP/BER-TLV + VU stream walks, full byte coverage)
- **Decoders**: `core/decoders/` — field-level decoders (card, g22_card, cert, vu_trep, g2_dispatch) + `primitives.py` shared helpers
- **Parser engine**: `core/parser/` — deterministic.py, record_array.py, vu_dispatcher.py (RecordArray walker), g1_walker.py
- **Registry**: `core/registry/` — decoder_registry.py (tag→decoder mapping), models.py (TachoResult)
- **Crypto**: `core/crypto/` — signature.py (root validator), vu_signature.py (ECDSA TREP + CVC chain), ef_signature.py (card data integrity)
- **Utils**: `core/utils/` — ber_tlv, coverage, encoding, constants, logger, version, report_format, event_codes, tag_defs
- **GUI**: `app/gui.py` — regedit-style tree + table viewer with Excel/CSV/JSON export
- **CLI**: `app/cli.py` — full-featured CLI; `app/main.py` — minimal CLI
- **Export**: `app/export.py` — multi-sheet Excel + CSV + PDF
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
