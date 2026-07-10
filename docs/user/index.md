# DDD Tachograph Reader — User Manual

Welcome to **DDD Tachograph Reader**, an open-source tool for reading, exploring, and validating digital tachograph files (`.ddd` format). This manual covers everything you need to get started, whether you are a driver, fleet manager, workshop, or analyst.

The current release is **v2.5.0 "Revolution"**, which adds interactive activity timelines, speed graphs, dashboards, and a re-engineered parser that recovers partial or malformed downloads.

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

## What's New in v2.5

- **Interactive daily activity timeline** — driving / work / availability / rest on a 24-hour chart, with crew (dual-slot) support and out-of-scope markers.
- **Vehicles driven per day** — for driver-card activity views, the vehicle(s) used each day, with switch-over times on multi-vehicle days.
- **Detailed speed graph** — the speed curve with overspeeding event markers and a shaded over-speed zone.
- **Dashboards + monthly summaries** — KPI cards and per-month totals for activities and speed.
- **Corrupt / partial download recovery** — deterministic-first parsing with best-effort salvage; recovered data is clearly flagged.
- **TREP completeness inventory** and **origin detection** (driver card vs VU download).
- **Full country names** everywhere instead of raw nation codes.

A visual product tour is available on the [project README](https://github.com/Syax89/DDDTachograph_Reader#product-tour).

---

## Quick Start

1. **Download** the build for your platform from [GitHub Releases](https://github.com/Syax89/DDDTachograph_Reader/releases/latest):
   - Windows: `TachoReader-v<version>-windows-x64.zip`
   - macOS: `TachoReader-v<version>-macos.dmg`
2. **Launch** the application (extract the zip and run `TachoReader.exe` on Windows; open the DMG and drag `TachoReader.app` to Applications on macOS).
3. **Click "Open DDD file"** and select your `.ddd` file.
4. **Explore** the parsed data in the section tree, open the activity or speed charts, and export to PDF, Excel, CSV, or JSON.

For command-line usage, see the [CLI Guide](cli_guide.md).
