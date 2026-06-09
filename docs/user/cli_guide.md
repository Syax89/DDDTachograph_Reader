# Command-Line Interface (CLI) Guide

The DDD Tachograph Reader provides two command-line entry points: a simple parser (`main.py`) and an advanced CLI (`tacho_cli.py`) with export and reporting options.

---

## Basic Usage — main.py

The simplest invocation parses a file and prints JSON to standard output:

```bash
python main.py file.ddd
```

**Options**:

| Flag | Description |
|------|-------------|
| `-o FILE`, `--output FILE` | Save JSON output to a file instead of printing to screen |
| `-v`, `--verbose` | Enable debug logging |

Example with output file:

```bash
python main.py file.ddd -o result.json -v
```

The JSON result already includes compliance infractions (added automatically by the compliance engine).

---

## Advanced CLI — tacho_cli.py

The advanced CLI (`tacho_cli.py`) adds export formats, summarization, geocoding, and batch processing.

### Parse and Display Summary

```bash
python tacho_cli.py file.ddd --summary
```

Output:

```
============================================================
🚛 DDD TACHOGRAPH READER - RIEPILOGO
============================================================

📄 File: CARD_001.ddd (Driver Card, Gen 2.2)
🔐 Integrità: VERIFIED

👤 Conducente: Marco Rossi
   Carta: IT1234567890

📊 Attività (342 record, 15 giorni):
   🟦 Guida:  65h 42m
   🟨 Lavoro: 22h 15m
   🟩 Riposo: 131h 3m

⚠️ Infrazioni: 2 (Sanzioni stimate: € 668 − 1,336)
   • Guida continua di 295 min supera il limite di 4.5h.
   • Entro il turno di 24h, il riposo massimo è di 510 min (minimo 9h).

============================================================
```

### JSON Output

Save results as a structured JSON file:

```bash
python tacho_cli.py file.ddd --json output.json
```

If no filename is given, an auto-named file is created:

```bash
python tacho_cli.py file.ddd --json
# Creates: file_20240609_143022.json
```

### Compliance Report

Add `--compliance` flag: the compliance engine runs automatically. Use `--json` or `--summary` to view the results.

### Export Formats

**Excel** (multi-sheet workbook):

```bash
python tacho_cli.py file.ddd --excel report.xlsx
```

**PDF** (professional report with timeline visualization):

```bash
python tacho_cli.py file.ddd --pdf report.pdf
```

**All formats at once** (JSON, PDF, Excel):

```bash
python tacho_cli.py file.ddd --all output_dir/
```

### Reverse Geocoding

Enable reverse geocoding to add city/town names to GNSS positions:

```bash
python tacho_cli.py file.ddd --geocode --json
```

This enriches each activity record with a `location` field containing the nearest city.

### Verbose Output

Use `-v` or `--verbose` for detailed debug logs and full Python tracebacks on errors:

```bash
python tacho_cli.py file.ddd --verbose --summary
```

### Batch Mode

Process all `.ddd` files in a directory:

```bash
python tacho_cli.py DDD/ --batch
```

Each file in the directory is parsed, and results are saved individually.

---

## Complete Option Reference

| Flag | Argument | Description |
|------|----------|-------------|
| `--json` | `[FILE]` | Generate JSON output (optional output path) |
| `--pdf` | `[FILE]` | Generate PDF report (optional output path) |
| `--excel` | `[FILE]` | Generate Excel report (optional output path) |
| `--all` | `[DIR]` | Generate all formats into a directory |
| `--summary` | — | Show compact text summary on screen |
| `--geocode` | — | Enable reverse geocoding of GNSS coordinates |
| `-v`, `--verbose` | — | Verbose debug output |
| `-q`, `--quiet` | — | Suppress all screen output (files only) |

---

## Integrating with Scripts

Since `main.py` outputs pure JSON, it integrates easily with other tools:

```bash
# Pipe to jq for filtering
python main.py file.ddd | jq '.driver'

# Count infractions
python main.py file.ddd | jq '.infractions | length'

# Extract all activity dates
python main.py file.ddd | jq '.activities[].data'
```
