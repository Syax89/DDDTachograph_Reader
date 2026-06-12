# Export Guide — Formats and Best Practices

The DDD Tachograph Reader supports four export formats. All exports share the same formatting layer (readable timestamps, humanised column names), so the formats present the same content consistently. This guide explains each format, its contents, and when to use it.

---

## JSON (.json)

**What it contains**: The complete parsed result as a structured JSON object, including metadata, driver info, vehicle info, all activity records, GNSS data, events/faults, signature verification status, and raw tag data.

**Best for**:
- Further data processing in scripts or other applications
- Integration with fleet management systems
- Developers who need the full data structure
- Archival of parsed data for later re-analysis

**How to export**:
- GUI: **Export → JSON (.json)**
- CLI: `python tacho_cli.py file.ddd --json output.json`

**Example structure** (abridged):
```json
{
  "metadata": {
    "filename": "CARD_001.ddd",
    "generation": "G2.2",
    "integrity_check": "Verified",
    "coverage_pct": 100.0
  },
  "driver": {
    "surname": "Rossi",
    "firstname": "Marco",
    "card_number": "IT1234567890"
  },
  "vehicle": { ... },
  "activities": [ ... ],
  "events": [ ... ],
  "signature_verification": { ... }
}
```

---

## Excel (.xlsx)

**What it contains**: A multi-sheet workbook:

| Sheet | Contents |
|-------|----------|
| **Summary** | Overview with file, driver, and vehicle info |
| **TREP Signatures** | Per-block signature verification details (VU files) |
| **VU Certificates** | Certificates found in the file (VU files) |
| **One sheet per data section** | Daily activities, events, faults, places, GNSS records, etc. |

Sheets have styled headers, alternating row stripes, auto-filters, and frozen header rows. Very large sections are truncated at 50,000 rows.

**Best for**:
- Sharing reports with non-technical staff
- Filtering and sorting data by date or activity type
- Pivot-table analysis

**How to export**:
- GUI: **Export → Excel (.xlsx)**
- CLI: `python tacho_cli.py file.ddd --excel report.xlsx`

---

## CSV (.csv)

**What it contains**: All data sections in a single CSV file. Each section gets a title row, its own header, and its rows, separated by a blank line — readable in any spreadsheet application.

**Best for**:
- Import into database systems or other software
- Quick data inspection
- Lightweight format when file size matters

**How to export**:
- GUI: **Export → CSV (.csv)**
- CLI: not available as a flag; use the GUI or call `ExportManager.export_to_csv()` programmatically

---

## PDF (.pdf)

**What it contains**: A formatted report with the file summary (driver/vehicle identity, generation, signature status) followed by the data section tables. Very large sections are truncated at 1,500 rows to keep the document manageable.

**Best for**:
- Reports for audits or record-keeping
- Printed records for physical archives

**How to export**:
- GUI: **Export → PDF (.pdf)**
- CLI: `python tacho_cli.py file.ddd --pdf report.pdf` (requires `reportlab`)

---

## Choosing the Right Format

| Need | Best Format |
|------|------------|
| "I need the raw data for my own scripts" | JSON |
| "My boss wants a spreadsheet to review" | Excel |
| "We need a printable report" | PDF |
| "I'm importing into our ERP system" | CSV |
| "Send me everything" | `--all` (JSON + PDF + Excel) |
