# Aurora DDD Analytics — User Manual

Welcome to **Aurora DDD Analytics**, the professional tool for reading, analyzing, and validating digital tachograph files (`.ddd` format). This manual covers everything you need to get started, whether you are a truck driver, fleet manager, or compliance officer.

---

## Table of Contents

| Section | Description |
|---------|-------------|
| [Installation](installation.md) | How to install on Windows, macOS, or from source |
| [GUI Guide](gui_guide.md) | Using the Aurora DDD Analytics desktop application |
| [CLI Guide](cli_guide.md) | Command-line usage for scripting and automation |
| [Compliance Guide](compliance_guide.md) | Understanding EU 561/2006 rules and infraction reports |
| [Export Guide](export_guide.md) | Export formats: JSON, Excel, CSV, PDF |
| [FAQ](faq.md) | Frequently asked questions |
| [Troubleshooting](troubleshooting.md) | Common problems and solutions |

---

## What Is a .ddd File?

A `.ddd` file is a binary download from a digital tachograph. It contains:

- **Driver information**: name, card number, issuing country, expiry date
- **Vehicle information**: VIN, registration plate, country of registration
- **Daily activities**: driving, work, rest, and availability periods with timestamps
- **GNSS positions**: GPS coordinates recorded during trips
- **Events and faults**: driving without card, power interruptions, sensor faults
- **Digital signatures**: cryptographic chain (ERCA → MSCA → Card) proving file integrity

The tool supports all three generations of digital tachographs:

- **G1 (Generation 1)**: Classic digital tachographs, Annex 1B (Reg. 3821/85)
- **G2 (Generation 2)**: Smart Tachograph V1, Annex 1C (Reg. 2016/799)
- **G2.2 (Generation 2.2)**: Smart Tachograph V2, Reg. EU 2023/980

---

## Quick Start

1. **Download** the executable for your platform from [GitHub Releases](https://github.com/Syax89/ddd-tachograph-reader/releases/latest).
2. **Launch** the application (double-click on Windows, right-click → Open on macOS).
3. **Click "Carica File .ddd"** and select your `.ddd` file.
4. **Explore** the parsed data across the tabs.

For command-line usage, see the [CLI Guide](cli_guide.md).
