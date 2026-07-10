# DDD Tachograph Reader

<p align="center">
  <img src="assets/lockup-horizontal.png" alt="TachoReader" width="600">
</p>

> Open Source  `.ddd` digital tachograph file analyzer — full decoding with tree-structured data exploration.

[![Build and Release](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml/badge.svg)](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml)
[![Latest Release](https://img.shields.io/github/v/release/Syax89/ddd-tachograph-reader)](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)

---

## Features

### File Decoding
- **Multi-generation**: G1 (Annex 1B), G2 Smart (Annex 1C), **Gen 2.2 Smart V2** (Reg. EU 2023/980)
- **Driver data**: Surname, first name, date of birth, card number, expiry, issuing nation
- **Daily activities**: Driving, work, availability, rest/break
- **Vehicle data**: VIN, plate, registration nation, odometer
- **GNSS positions**: Coordinates, border crossings, places
- **VU records**: Card insertions/withdrawals, calibrations, sensors, events/faults
- **Per-day vehicles**: Vehicle(s) driven each day shown in the driver activity chart
- **Full nation names**: Registration/issuing/sensor nation codes expanded to English names

### Integrity
- Cryptographic signature verification (ERCA → MSCA → Card/VU chain)
- Recursive BER-TLV and STAP parsing (nested containers)
- 100% byte coverage on all tested files
- TREP completeness inventory and origin detection (driver card vs VU download)
- Plausibility gating and best-effort salvage of partial/corrupted downloads
- Tree structure for data exploration

### Export
- PDF, Excel, CSV, JSON export
- Interactive GUI with tree navigation

---

## Product Tour

<p align="center">
  <img src="docs/screenshots/product-tour.gif" alt="Animated product tour showing the activity dashboard, activity timeline, speed dashboard, and detailed speed graph" width="960">
</p>

<p align="center"><sub>Activity dashboard · daily activity timeline · speed dashboard · detailed speed graph</sub></p>


<details>
<summary>Open the full-resolution screenshots</summary>

1. [Activity dashboard](docs/screenshots/01_activity_dashboard.png)
2. [Daily activity timeline](docs/screenshots/02_activity_timeline.png)
3. [Speed dashboard](docs/screenshots/03_speed_dashboard.png)
4. [Detailed speed graph](docs/screenshots/04_speed_graph.png)
</details>

---

## Download & Usage

### Pre-built Executable (recommended)
Download from the **[Releases](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)** page:

| Platform | File |
|----------|------|
| Windows | `TachoReader-v<version>-windows-x64.zip` |
| macOS | `TachoReader-v<version>-macos.dmg` |

Extract the Windows archive and run `TachoReader.exe`. Open the macOS disk image
and drag `TachoReader.app` to Applications.

### From Source (developers)

```bash
git clone https://github.com/Syax89/ddd-tachograph-reader.git
cd ddd-tachograph-reader
pip install -r requirements.txt

# GUI
python app/gui.py

# CLI
python app/cli.py path/to/file.ddd
```

---

## Project Structure

```
ddd-tachograph-reader/
├── app/
│   ├── cli.py                  # Command-line interface
│   ├── main.py                 # CLI compatibility entry point
│   ├── gui.py                  # GUI (tree + table, tkinter)
│   ├── engine.py               # TachoParser entry point
│   └── export.py               # PDF/Excel/CSV/JSON export
├── core/
│   ├── decoders/                # Field-level decoders and primitives
│   ├── parser/                  # Deterministic, G1, and VU parsers
│   ├── registry/                # Decoder registry and result models
│   ├── crypto/                  # Certificate and signature validation
│   └── utils/                   # Shared helpers, constants, and version
├── certs/                       # ERCA root certificates
├── tests/                       # Test suite
├── scripts/                     # Specifications and audits
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
pip install -r requirements.txt
python -m pytest tests/ -v
```

The suite covers multi-generation detection, G1/G2/G2.2 parsing, byte coverage,
fuzzing, and digital signatures. Tests requiring private DDD samples skip when
those fixtures are unavailable.

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

---

## Acknowledgments & Support

Thank you to everyone who has used, tested, and contributed to this project.
Your feedback and support keep it moving forward.

This project **is and will remain open source** and free to use. If it has been
useful to you and you'd like to say thanks, you can buy me a coffee — completely
optional, but always appreciated.

<p align="center">
  <a href="https://buymeacoffee.com/syax89" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50" width="210">
  </a>
</p>
