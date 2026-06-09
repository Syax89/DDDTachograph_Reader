# AGENTS.md — DDD Tachograph Reader

## Project overview
Cross-platform (Windows/macOS) application for parsing, analyzing and visualizing data from digital tachograph files (`.ddd` format). EU digital tachographs record driver activity, vehicle data, GNSS positions, and security certificate chains.

## Key architecture
- **Core parser**: `ddd_parser.py` → `core/tag_navigator.py` (STAP/BER-TLV recursive) → `core/decoders.py` (field-level decoders)
- **Coverage**: `_fill_coverage_gaps()` in `ddd_parser.py` guarantees 100% byte coverage
- **Decoder registry**: `core/decoder_registry.py` — centralized tag→decoder mapping with spec references
- **Deterministic parser**: `core/deterministic_parser.py` — schema-driven two-pass parser (migration target)
- **Three generations**: G1 (Annex 1B, STAP encoding), G2 (Annex 1C, BER-TLV), G2.2 (Annex 1C update, BER-TLV)
- **Detection**: First 2 bytes of file: `0x7631`=G2.2, `0x7621`/`0x7622`=G2, else G1
- **Output models**: `core/models.py` (TachoResult hierarchy)

## Running tests
```bash
/usr/local/bin/python3.9 -m pytest tests/ -v
```
Requires: `pip install cryptography reportlab pandas openpyxl requests`

## Spec documentation
All tag specifications are in `specs/`:
- `g1_complete_structures.md` — G1 tags, record sizes, field offsets, verification status
- `g2_g22_complete_structures.md` — G2/G2.2 tags with Annex 1C references
- `g22_verification_status.md` — G2.2 tag verification status (HIGH/MEDIUM/LOW confidence)
- `tachograph.asn` — Formal ASN.1 schema
- `architecture_migration_plan.md` — Migration plan to deterministic parser
- `coverage_audit.py` — Run with `python3 specs/coverage_audit.py` for file-by-file coverage report

## Key regulations
- Reg. 3821/85 Annex 1B — G1 tachograph spec
- Reg. EU 2016/799 Annex 1C — G2 smart tachograph spec
- Reg. EU 2023/980 — G2.2 smart tacho V2
- Reg. EU 2021/1228 — G2.2 additional specs

## Coverage guarantee
All 8 DDD files in `DDD/` achieve **100% byte coverage** (0 unparsed blocks). The `_fill_coverage_gaps()` method in `ddd_parser.py` ensures any bytes missed by the STAP/BER parser are filled as gap-tracked ranges. Coverage audit: `python3 specs/coverage_audit.py`.
