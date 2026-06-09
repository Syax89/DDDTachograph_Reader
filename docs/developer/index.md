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

- **Parsing entry point**: `ddd_parser.py:272` — `TachoParser.parse()`
- **Tag dispatch**: `core/tag_navigator.py:206` — `TagNavigator.record_and_dispatch()`
- **Decoder registry**: `core/decoder_registry.py:28` — `DecoderRegistry`
- **Deterministic parser**: `core/deterministic_parser.py:105` — `DeterministicParser`
- **Run tests**: `/usr/local/bin/python3.9 -m pytest tests/ -v`
- **Coverage audit**: `python3 specs/coverage_audit.py`

## Generations Supported

| Generation | Regulation | Detection | Encoding |
|---|---|---|---|
| G1 (Digital) | Reg. 3821/85 Annex 1B | First byte not 0x76 | STAP (T2L2) |
| G2 (Smart) | Reg. EU 2016/799 Annex 1C | `0x7621` / `0x7622` | BER-TLV |
| G2.2 (Smart V2) | Reg. EU 2023/980 | `0x7631` | BER-TLV |

## Repository Layout

```
ddd-tachograph-reader/
├── core/                    # Core parsing engine
│   ├── decoders.py          # Field-level decoders (G1/G2/G2.2)
│   ├── g2_decoders.py       # G2/G2.2 VU record decoders
│   ├── decoder_registry.py  # Centralized tag -> decoder mapping
│   ├── tag_navigator.py     # Recursive STAP/BER-TLV parser
│   ├── deterministic_parser.py  # Schema-driven two-pass parser
│   ├── models.py            # TachoResult data hierarchy
│   ├── tag_definitions.py   # Default tag name dictionary
│   ├── record_array.py      # RecordArray (Appendix 7) format
│   ├── vu_record_dispatcher.py # VU stream dispatcher
│   ├── vu_signature_verifier.py # VU ECDSA verification
│   ├── constants.py         # Shared constant definitions
│   └── logger.py            # Shared logging
├── ddd_parser.py            # Main TachoParser entry point
├── signature_validator.py   # Certificate chain validation
├── export_manager.py        # Excel/CSV export
├── gui_tree.py              # Desktop GUI (tkinter: tree + Excel-style table)
├── tacho_cli.py             # CLI interface
├── main.py                  # Legacy CLI
├── specs/                   # Specification documentation
├── tests/                   # Test suite (>150 tests)
└── DDD/                     # Sample DDD files
```
