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

- **Parsing entry point**: `app/engine.py` — `TachoParser.parse()`
- **Tag dispatch**: `core/parser/deterministic.py` — `DeterministicParser._dispatch_decoder()`
- **Decoder registry**: `core/registry/registry.py` — `DecoderRegistry`
- **Run tests**: `python -m pytest tests/ -v`
- **Coverage audit**: `python3 scripts/coverage_audit.py`

## Generations Supported

| Generation | Regulation | Detection | Encoding |
|---|---|---|---|
| G1 (Digital) | Reg. 3821/85 Annex 1B | First byte not 0x76 | STAP (T2L2) |
| G2 (Smart) | Reg. EU 2016/799 Annex 1C | `0x7621` / `0x7622` | BER-TLV |
| G2.2 (Smart V2) | Reg. EU 2023/980 | `0x7631` | BER-TLV |

## Repository Layout

```
ddd-tachograph-reader/
├── core/                        # Core parsing engine
│   ├── decoders/                # Field-level decoders (facade + type-split modules)
│   │   ├── __init__.py          # Facade re-exporting the public decoder API
│   │   ├── common.py            # Shared low-level decode helpers
│   │   ├── card_ef.py           # Card EF decoders (multi-generation)
│   │   ├── card_g22.py          # Gen 2.2 card decoders
│   │   ├── cert.py              # Certificate / public-key decoders
│   │   ├── vu_g1.py             # G1 VU overview + TREP walkers
│   │   └── vu_g2.py             # G2/G2.2 VU RecordArray dispatch
│   ├── parser/                  # Structural walkers
│   │   ├── deterministic.py     # Deterministic full-coverage parser
│   │   ├── record_array.py      # RecordArray (Appendix 7) format
│   │   ├── g1_walker.py         # G1 VU stream walker
│   │   └── vu_dispatcher.py     # G2/G2.2 VU record decoders
│   ├── registry/                # Tag → decoder mapping + models
│   │   ├── registry.py          # Centralized DecoderRegistry
│   │   └── models.py            # TachoResult data hierarchy
│   ├── crypto/                  # Signature / certificate-chain validation
│   └── utils/                   # Constants, logging, BER-TLV, coverage, tag defs
├── app/engine.py                # Main TachoParser entry point
├── app/export.py                # Excel/CSV/PDF export
├── app/gui.py                   # Desktop GUI (tkinter: tree + Excel-style table)
├── app/cli.py                   # CLI interface
├── app/main.py                  # Compatibility CLI entry point
├── scripts/                     # Specification documentation + audits
├── tests/                       # Test suite
└── DDD/                         # Optional private sample DDD files (not committed)
```
