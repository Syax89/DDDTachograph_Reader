# Export Guide — Formats and Best Practices

The DDD Tachograph Reader supports four export formats. All exports share the same formatting layer (readable timestamps, humanised column names, full English country names for nations), so the formats present the same content consistently. This guide explains each format, its contents, and when to use it.

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
- CLI: `python app/cli.py file.ddd --json output.json`

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
- CLI: `python app/cli.py file.ddd --excel report.xlsx`

---

## CSV (.csv)

**What it contains**: All data sections in a single CSV file. Each section gets a title row, its own header, and its rows, separated by a blank line — readable in any spreadsheet application.

**Best for**:
- Import into database systems or other software
- Quick data inspection
- Lightweight format when file size matters

**How to export**:
- GUI: **Export → CSV (.csv)**
- CLI: `python app/cli.py file.ddd --csv report.csv`

---

## PDF (.pdf)

**What it contains**: an A4 landscape report in three parts.

1. **Cover** — file name, source and generation, when the report was generated,
   the activity period, the identity facts the file carries, the file state, and
   a compact totals grid. The activity period is derived from the daily activity
   records in the file only (day dates are UTC); it is not a statement about the
   download's full retention period. The file state shows the integrity verdict,
   download completeness and every partial-parse warning the parser recorded —
   missing mandatory sections, discarded sections, recovered data, decoder
   failures. The totals grid lists Drive, Work, Rest, Available, Unknown and
   Total plus days with activity, events and faults.
2. **Operational sections** — **Daily Activities** month by month (each month on
   its own page, `h:mm` durations, bold shaded monthly subtotals, headers
   repeated when a table continues), followed by the remaining record sections
   in their usual order.
3. **Technical Appendix** — signature checks, certificates, calibrations and
   workshops, vehicle-unit/sensor/card identification, and the file-level parse
   details (file size, byte coverage, reader version).

**Reading the report**:

- Durations are always `h:mm`: `00:00` means no time in that bucket, `07:15` is
  7 h 15 min, `48:00` is two full days.
- A leading `!` marks time the file leaves unattributed. Unknown time is not by
  itself a sign of a corrupt file: it is time the record does not attribute to
  Drive, Work, Rest or Available (minutes before the day's first status entry, an
  unrecognised status code, or a card slot with no activity).
- Drive and Work are summed across the two card slots; Rest, Available and
  Unknown are kept at the maximum across slots. A day with two drivers (crew)
  can therefore show more than `24:00` in total.
- Each day is summed with the same slot-aware engine the monthly table uses, so
  per-day figures match. The cover totals cover **every** daily record in the
  input, while the printed tables stop at the row limit: past it the Daily
  Activities table is a subset and the cover is the complete figure.
- Records wider than ten columns (calibrations, certificates, power
  interruptions, VU identifications) are printed as one field/value card per
  record — "Record 2 of 7" — so no field is squeezed into an unreadable column.
  A record long enough to need two pages repeats its record number and header.
- A list-based section is cut at 1,500 rows and says so on the page, naming the
  rows exported and pointing at the JSON export (Excel has its own limit). That
  applies to the daily activities table and to every record table (events,
  places, detailed speed, …). The monthly subtotal rows are rows of the same cap,
  so a long month can be cut before its subtotal — its heading then says it is a
  partial month instead of showing an empty month name, and a capped section
  whose retained rows carry no displayable value still discloses the cut without
  printing an empty grid. Dictionary sections (card application, VU
  information, sensor identification, …) and the special TREP / VU-certificate
  lists are not capped and keep their existing behaviour.
- The PDF is a **summary**: nested structures are flattened into readable text
  (an absent card slot as `—`, a certificate as a truncated digest). Use JSON for
  the complete decoded structure, or Excel to work with the rows.

**Best for**:
- Reports for audits or record-keeping
- Printed records for physical archives

**How to export**:
- GUI: **Export → PDF (.pdf)**
- CLI: `python app/cli.py file.ddd --pdf report.pdf` (requires `reportlab`)

---

## Choosing the Right Format

| Need | Best Format |
|------|------------|
| "I need the raw data for my own scripts" | JSON |
| "My boss wants a spreadsheet to review" | Excel |
| "We need a printable report" | PDF |
| "I'm importing into our ERP system" | CSV |
| "Send me everything" | `--all` (JSON + PDF + Excel + CSV) |
