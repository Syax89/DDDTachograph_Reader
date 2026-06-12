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
| `--version` | Print the program version |

Example with output file:

```bash
python main.py file.ddd -o result.json -v
```

---

## Advanced CLI — tacho_cli.py

The advanced CLI (`tacho_cli.py`) adds export formats and an on-screen summary.

### Parse and Display Summary

```bash
python tacho_cli.py file.ddd --summary
```

The summary shows file metadata (type and generation), signature verification status, driver and vehicle identity, and per-activity totals (drive / work / available / rest) computed from the daily activity records.

### JSON Output

Save results as a structured JSON file:

```bash
python tacho_cli.py file.ddd --json output.json
```

If no filename is given, an auto-named file is created:

```bash
python tacho_cli.py file.ddd --json
# Creates: file_20260612_143022.json
```

With no flags at all, the JSON is printed to standard output.

### Export Formats

**Excel** (multi-sheet workbook):

```bash
python tacho_cli.py file.ddd --excel report.xlsx
```

**PDF** (formatted report):

```bash
python tacho_cli.py file.ddd --pdf report.pdf
```

**All formats at once** (JSON, PDF, Excel into a directory):

```bash
python tacho_cli.py file.ddd --all output_dir/
```

### Verbose Output

Use `-v` or `--verbose` for detailed debug logs and full Python tracebacks on errors:

```bash
python tacho_cli.py file.ddd --verbose --summary
```

---

## Complete Option Reference

| Flag | Argument | Description |
|------|----------|-------------|
| `--json` | `[FILE]` | Generate JSON output (optional output path) |
| `--pdf` | `[FILE]` | Generate PDF report (optional output path) |
| `--excel` | `[FILE]` | Generate Excel report (optional output path) |
| `--all` | `[DIR]` | Generate all formats into a directory |
| `--summary` | — | Show compact text summary on screen |
| `--version` | — | Print the program version |
| `-v`, `--verbose` | — | Verbose debug output |
| `-q`, `--quiet` | — | Suppress all screen output (files only) |

---

## Batch Processing

The CLI processes one file per invocation. To process a directory, loop in the shell:

```bash
for f in DDD/*.ddd; do
  python tacho_cli.py "$f" --json --quiet
done
```

---

## Integrating with Scripts

Since `main.py` outputs pure JSON, it integrates easily with other tools:

```bash
# Pipe to jq for filtering
python main.py file.ddd | jq '.driver'

# Check the signature verification result
python main.py file.ddd | jq '.metadata.integrity_check'

# Extract all activity dates
python main.py file.ddd | jq '.activities[].date'
```
