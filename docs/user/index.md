# DDD Tachograph Reader — User Manual

Welcome to **DDD Tachograph Reader**, an open-source tool for reading, exploring, and validating digital tachograph files (`.ddd` format). This manual covers everything you need to get started, whether you are a driver, fleet manager, workshop, or analyst.

The latest release and its download files are on the
[Releases page](https://github.com/Syax89/DDDTachograph_Reader/releases/latest);
Windows, macOS and Linux (x86_64 Flatpak) builds are all produced by CI.

---

## Table of Contents

| Section | Description |
|---------|-------------|
| [Installation](installation.md) | How to install on Windows, macOS or Linux (Flatpak), or run from source |
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

## Highlights

- **34 languages** — the window can run in English, the 23 other official EU
  languages, Norwegian, Icelandic, Russian, Ukrainian, Belarusian, Turkish,
  Serbian, Bosnian, Albanian or Macedonian, with a separate switch for
  translating the labels decoded from the file.
- **Summary first** — a file opens on one page with its identity, integrity,
  activity totals and file state, and the window is fully usable from the
  keyboard.
- **Recent files and drag & drop** — the last 8 successfully opened files are one
  click away, and a `.ddd` file can be dropped on the window.
- **Interactive daily activity timeline** — driving / work / availability / rest
  on a 24-hour chart, with crew (dual-slot) support and out-of-scope markers.
- **Vehicles driven per day** — for driver-card activity views, the vehicle(s)
  used each day, with switch-over times on multi-vehicle days.
- **Detailed speed graph** — the speed envelope as a band with a mean line,
  shaded recording gaps, overspeeding event markers and per-day cards.
- **Dashboards + monthly summaries** — KPI cards and per-month totals for
  activities and speed.
- **Corrupt / partial download recovery** — deterministic-first parsing with
  best-effort salvage; recovered data is clearly flagged.
- **TREP completeness inventory** and **origin detection** (driver card vs VU
  download).
- **Excel and PDF reports built for reading** — typed spreadsheet cells with a
  Summary index, and a PDF with a structured cover and a Technical Appendix.
- **Full country names** everywhere instead of raw nation codes.

Release-by-release notes are in the [CHANGELOG](../../CHANGELOG.md). A visual
product tour is available on the
[project README](https://github.com/Syax89/DDDTachograph_Reader#product-tour).

---

## Quick Start

1. **Download** the build for your platform from [GitHub Releases](https://github.com/Syax89/DDDTachograph_Reader/releases/latest):
   - Windows: `TachoReader-v<version>-windows-x64.zip`
   - macOS: `TachoReader-v<version>-macos.dmg`
   - Linux (x86_64): `TachoReader-v<version>-linux-x86_64.flatpak`
2. **Launch** the application (extract the zip and run `TachoReader.exe` on Windows; open the DMG and drag `TachoReader.app` to Applications on macOS; install and run the Flatpak on Linux — see [Installation](installation.md#linux-flatpak-x86_64)).
3. **Click "Open DDD file"** (or drop a `.ddd` file on the window) and select your `.ddd` file.
4. **Explore** the parsed data in the section tree, open the activity or speed charts, and export to PDF, Excel, CSV, or JSON.

The window opens in English. To use another language, click the language button in
the top bar and choose one from **Language**; see the [GUI Guide](gui_guide.md#languages).

For command-line usage, see the [CLI Guide](cli_guide.md).
