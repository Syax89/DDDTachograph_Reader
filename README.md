# DDD Tachograph Reader

> Open Source  `.ddd` digital tachograph file analyzer — full decoding with tree-structured data exploration.

[![Build and Release](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml/badge.svg)](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml)
[![Latest Release](https://img.shields.io/github/v/release/Syax89/ddd-tachograph-reader)](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue)

---

## Features

### File Decoding
- **Multi-generation**: G1 (Annex 1B), G2 Smart (Annex 1C), **Gen 2.2 Smart V2** (Reg. EU 2023/980)
- **Driver data**: Surname, first name, date of birth, card number, expiry, issuing nation
- **Daily activities**: Driving, work, availability, rest/break
- **Vehicle data**: VIN, plate, registration nation, odometer
- **GNSS positions**: Coordinates, border crossings, places
- **VU records**: Card insertions/withdrawals, calibrations, sensors, events/faults

### Integrity
- Cryptographic signature verification (ERCA → MSCA → Card/VU chain)
- Recursive BER-TLV and STAP parsing (nested containers)
- 100% byte coverage on all tested files
- Tree structure for data exploration

### Export
- PDF, Excel, CSV, JSON export
- Interactive GUI with tree navigation

---

## Download & Usage

### Pre-built Executable (recommended)
Download from the **[Releases](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)** page:

| Platform | File |
|----------|------|
| Windows | `TachoReader-Windows.zip` |
| macOS | `TachoReader-Mac.zip` |

Extract and run `TachoReader` — no installation required.

### From Source (developers)

```bash
git clone https://github.com/Syax89/ddd-tachograph-reader.git
cd ddd-tachograph-reader
pip install -r requirements.txt

# GUI
python gui_tree.py

# CLI
python tacho_cli.py path/to/file.ddd
```

---

## Project Structure

```
ddd-tachograph-reader/
├── gui_tree.py                  # GUI (tree + table, tkinter)
├── tacho_cli.py                 # Main CLI
├── main.py                      # Minimal CLI entry point
├── ddd_parser.py                # Core parser entry point
├── signature_validator.py       # Certificate chain validation
├── export_manager.py            # PDF/Excel/CSV/JSON export
├── core/
│   ├── decoders.py              # Tag decoders (G1, G2, G2.2)
│   ├── g2_decoders.py           # G2/G2.2 VU RecordArray decoders
│   ├── decoder_registry.py      # Centralized tag→decoder registry
│   ├── deterministic_parser.py  # Schema-driven deterministic parser
│   ├── g1_vu_walker.py          # Deterministic G1 VU TREP walker (Annex 1B)
│   ├── record_array.py          # RecordArray parser (Annex 1C)
│   ├── vu_record_dispatcher.py  # VU RecordArray stream dispatcher
│   ├── vu_signature_verifier.py # ECDSA + CVC certificate verification
│   ├── report_format.py         # Shared export formatting
│   ├── models.py                # Data models (TachoResult)
│   ├── tag_definitions.py       # Tag ID → name mappings
│   ├── coverage_utils.py        # Shared interval merge + padding detection
│   ├── encoding.py              # Shared BytesEncoder for JSON
│   ├── event_fault_codes.py     # Event/fault/condition descriptions (EU Reg.)
│   ├── version.py               # Single version source
│   ├── constants.py             # Shared constants
│   └── logger.py                # Centralized logging (thread-safe)
├── certs/                       # ERCA root certificates
├── tests/                       # Test suite
├── specs/                       # Specifications and audits
├── docs/                        # Documentation
└── .github/workflows/           # CI/CD (lint, tests, Windows/macOS builds)
```

---

## Supported Formats

| Generation | Standard | Header | Notes |
|------------|----------|--------|-------|
| G1 Digital | Annex 1B (Reg. 3821/85) | variable | Legacy tachographs |
| G2 Smart | Annex 1C (Reg. 2016/799) | `0x7621` | Smart Tachograph V1 |
| **G2.2 Smart V2** | Annex 1C (Reg. 2023/980) | `0x7631` | Smart Tachograph V2 |

---

## Testing

```bash
pip install pytest
pytest tests/ -v
```

123 tests: multi-generation detection, G1/G2/G2.2 parsing, byte coverage, fuzzing, digital signatures.

---

## Building from Source

```bash
pip install pyinstaller
pyinstaller build.spec
# Output: dist/TachoReader (macOS) / dist/TachoReader.exe (Windows)
```

---

## License

MIT © [Syax89](https://github.com/Syax89)
