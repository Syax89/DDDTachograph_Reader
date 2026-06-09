# Developer Documentation — DDD Tachograph Reader

Cross-platform (Windows/macOS) application for parsing, analyzing and visualizing data from EU digital tachograph files (`.ddd` format).

## Documents

| Document | Description |
|---|---|
| [Architecture](./architecture.md) | System design, pipeline flow, design patterns, component descriptions |
| [Adding a Decoder](./adding_decoder.md) | Step-by-step guide for implementing new tag decoders |
| [Parsing Pipeline](./parsing_pipeline.md) | Deep dive into STAP, BER-TLV, RecordArray formats and coverage tracking |
| [Testing](./testing.md) | How to run tests, write new tests, generate mock DDD files, and fuzz |
| [Specs References](./specs.md) | How to use the specification documentation and verification statuses |
| [Glossary](./glossary.md) | Terminology: tachograph concepts, layers, EU regulations |

## Quick Links

- **Parsing entry point**: `ddd_parser.py:120` — `TachoParser.parse()`
- **Tag dispatch**: `core/tag_navigator.py:206` — `TagNavigator.record_and_dispatch()`
- **Decoder registry**: `core/decoder_registry.py:28` — `DecoderRegistry`
- **Deterministic parser**: `core/deterministic_parser.py:105` — `DeterministicParser`
- **Run tests**: `python3.9 -m pytest tests/ -v`
- **Coverage audit**: `python3 specs/coverage_audit.py`

## Generations Supported

| Generation | Regulation | Detection | Encoding |
|---|---|---|---|
| G1 (Digital) | Reg. 3821/85 Annex 1B | First byte ≠ 0x76 | STAP (T2L2) |
| G2 (Smart) | Reg. EU 2016/799 Annex 1C | `0x7621` / `0x7622` | BER-TLV |
| G2.2 (Smart V2) | Reg. EU 2023/980 | `0x7631` | BER-TLV |

## Repository Layout

```
ddd-tachograph-reader/
├── core/                    # Core parsing engine
│   ├── decoders.py          # Field-level decoders (G1/G2/G2.2)
│   ├── g2_decoders.py       # G2/G2.2 VU record decoders
│   ├── decoder_registry.py  # Centralized tag → decoder mapping
│   ├── tag_navigator.py     # Recursive STAP/BER-TLV parser
│   ├── deterministic_parser.py  # Schema-driven two-pass parser
│   ├── models.py            # TachoResult data hierarchy
│   ├── tag_definitions.py   # Default tag name dictionary
│   ├── record_array.py      # RecordArray (Appendix 7) format
│   └── logger.py            # Shared logging
├── ddd_parser.py            # Main TachoParser entry point
├── compliance_engine.py     # EU 561/2006 compliance checks
├── signature_validator.py   # ERCA/MSCA certificate validation
├── export_manager.py        # Excel/CSV export
├── export_pdf.py            # PDF report generation
├── fines_calculator.py      # Infraction fine estimates
├── fleet_analytics.py       # Multi-driver fleet analysis
├── gui_tree.py              # Desktop GUI (tkinter: tree + Excel-style table)
├── tacho_cli.py             # CLI interface
├── specs/                   # Specification documentation
├── tests/                   # Test suite
└── DDD/                     # Sample DDD files
```
