# DDD Tachograph Reader — User Manual

Welcome to **DDD Tachograph Reader**, an open-source tool for reading, exploring, and validating digital tachograph files (`.ddd` format). This manual covers everything you need to get started, whether you are a driver, fleet manager, or analyst.

---

## Table of Contents

| Section | Description |
|---------|-------------|
| [Installation](installation.md) | How to install on Windows, macOS, or from source |
| [GUI Guide](gui_guide.md) | Using the Tacho Explorer desktop application |
| [CLI Guide](cli_guide.md) | Command-line usage for scripting and automation |
| [Export Guide](export_guide.md) | Export formats: JSON, Excel, CSV, PDF |
| [FAQ](faq.md) | Frequently asked questions |
| [Troubleshooting](troubleshooting.md) | Common problems and solutions |

---

## What Is a .ddd File?

A `.ddd` file is a binary download from a digital tachograph. It contains:

- **Driver information**: name, card number, issuing country, expiry date
- **Vehicle information**: VIN, registration plate, country of registration
- **Daily activities**: driving, work, rest, and availability periods with timestamps
- **GNSS positions**: GPS coordinates recorded during trips (G2/G2.2)
- **Events and faults**: driving without card, power interruptions, sensor faults
- **Digital signatures**: cryptographic chain (ERCA → MSCA → Card/VU) proving file integrity

The tool supports all three generations of digital tachographs:

- **G1 (Generation 1)**: Classic digital tachographs, Annex 1B (Reg. 3821/85)
- **G2 (Generation 2)**: Smart Tachograph V1, Annex 1C (Reg. EU 2016/799)
- **G2.2 (Generation 2.2)**: Smart Tachograph V2, Reg. EU 2023/980

---

## Quick Start

1. **Download** the executable for your platform from [GitHub Releases](https://github.com/Syax89/ddd-tachograph-reader/releases/latest).
2. **Launch** the application (double-click on Windows, right-click → Open on macOS).
3. **Click "Open DDD file"** and select your `.ddd` file.
4. **Explore** the parsed data in the section tree, and export to PDF, Excel, CSV, or JSON.

For command-line usage, see the [CLI Guide](cli_guide.md).
