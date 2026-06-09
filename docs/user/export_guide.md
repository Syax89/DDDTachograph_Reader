# Export Guide — Formats and Best Practices

Aurora DDD Analytics supports four export formats. This guide explains each format, its contents, and when to use it.

---

## JSON (.json)

**What it contains**: The complete parsed result as a structured JSON object, including metadata, driver info, vehicle info, all activity records with GNSS positions, infractions, signature validation status, and raw tag data.

**Best for**:
- Further data processing in scripts or other applications
- Integration with fleet management systems
- Developers who need the full data structure
- Archival of parsed data for later re-analysis

**How to export**:
- GUI: Click **"Esporta JSON"** in the sidebar
- CLI: `python tacho_cli.py file.ddd --json output.json`

**Example structure**:
```json
{
  "metadata": {
    "filename": "CARD_001.ddd",
    "type": "Driver Card",
    "generation": "2.2",
    "integrity_check": "VERIFIED"
  },
  "driver": {
    "surname": "Rossi",
    "firstname": "Marco",
    "card_number": "IT1234567890"
  },
  "vehicle": { ... },
  "activities": [ ... ],
  "infractions": [ ... ],
  "signature_status": { ... }
}
```

---

## Excel (.xlsx)

**What it contains**: A multi-sheet workbook with separate tabs for different data categories.

| Sheet | Contents |
|-------|----------|
| **Summary** | Overview with driver info, vehicle info, totals |
| **Daily Activities** | Day-by-day breakdown of driving, work, rest times |
| **Infractions** | All detected violations with severity and fines |
| **GPS Positions** | GNSS coordinate records with timestamps |

**Best for**:
- Fleet managers who need to share reports with non-technical staff
- Integration with spreadsheet-based workflows
- Filtering and sorting data by date, activity type, or severity
- Combined with pivot tables for custom analysis

**How to export**:
- GUI: Click **"Esporta Excel"** in the sidebar
- CLI: `python tacho_cli.py file.ddd --excel report.xlsx`

---

## CSV (.csv)

**What it contains**: A flat CSV file with time ranges and activity data in tabular form. Each row represents a time period with its activity type, duration, and associated metadata.

**Best for**:
- Import into database systems or accounting software
- Quick data inspection in any spreadsheet application
- Lightweight format when file size matters
- Fleet tab batch export (see [GUI Guide](gui_guide.md#fleet-tab-flotta))

**How to export**:
- GUI: Click **"Esporta CSV"** in the sidebar
- CLI: Not directly via `tacho_cli.py`; use the GUI or `ExportManager.export_to_csv()` programmatically

---

## PDF (.pdf)

**What it contains**: A formatted professional report (A4 portrait) with:
- Cover page with driver and vehicle information
- Activity timeline visualization with color-coded time bars
- Compliance summary with infraction counts and fine estimates
- Daily activity tables
- Signature validation status

**Best for**:
- Official reports for transport authorities or compliance audits
- Driver debriefing and performance reviews
- Printed records for physical archives
- Fleet analysis summary (landscape A4, color-coded by driver)

**How to export**:
- CLI: `python tacho_cli.py file.ddd --pdf report.pdf`
- Fleet PDF: From the Fleet tab, click **"Esporta PDF"**

---

## Choosing the Right Format

| Need | Best Format |
|------|------------|
| "I need the raw data for my own scripts" | JSON |
| "My boss wants a spreadsheet to review" | Excel |
| "We need an official printed report" | PDF |
| "I'm importing into our ERP system" | CSV |
| "Send me everything" | `--all` (JSON + PDF + Excel) |

---

## Batch Export

From the Fleet tab, you can export aggregated fleet results:

- **CSV**: All drivers in a single CSV with key metrics
- **PDF**: Professional fleet report with per-driver sections
