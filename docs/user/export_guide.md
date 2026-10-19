# Export Guide — Formats and Best Practices

The DDD Tachograph Reader supports four export formats. All exports share the same formatting layer (readable timestamps, humanised column names, full English country names for nations), so the formats present the same facts with the same text. They present them differently, and each section below says how: the workbook additionally types the cells it can type and splits the activity report into a daily and a monthly sheet, while the PDF is a paginated summary and the CSV one text block per section. This guide explains each format, its contents, and when to use it.

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
| **Summary** | File, driver and vehicle facts, the file-state warnings, the row-limit disclosure and an index of every sheet (a clickable link, a one-line description and its row count) |
| **TREP Signatures** | Per-block signature verification details (VU files) |
| **VU Certificates** | Certificates found in the file (VU files) |
| **Daily Activities** | One row per day: date, odometer, Drive/Work/Rest/Available/Unknown/Total |
| **Monthly Activities** | The monthly subtotal rows of the same report, one highlighted row per month |
| **One sheet per data section** | Events, faults, places, GNSS records, calibrations, … |
| **Key/value sheets** | Card application, VU information, sensor identification, IC chip, … |

Every table is rectangular: a wrapped navy header band, a frozen header row, an
auto-filter, hidden gridlines, column widths that leave room for the filter
button, and landscape printing fitted to one page wide with the header repeated
on every page. Rows are striped, descriptions are wrapped above the header, and
the monthly subtotal rows are bold and shaded.

**Typed cells — what a spreadsheet can work with**:

- **Dates and times**: the daily `Date` column is a real date cell, and a timestamp
  column (`Begin`, `End`, `Timestamp`, `Insertion Time`, `Card Expiry`, …) is a
  real date-time cell. Timestamps are UTC and keep their zone in the cell format
  (`2024-11-26 04:28Z`), because Excel has no time zones. A date without a time
  keeps the shape of the text it came from: a `dd/mm/yyyy` value displays
  `dd/mm/yyyy`, an ISO value displays `yyyy-mm-dd`, and the stored value is the
  exact calendar date either way.
- **Only named columns are typed**: the time/date columns are an explicit
  allow-list of the labels the report gives real time and date fields. A column
  whose name merely *ends* like a time is not one: `Card Driver Begin`,
  `Card Driver End`, `Card Codriver Begin` and `Card Codriver End` hold card
  identifiers (registration nation + card number), so they always stay text and
  a date-shaped identifier (`2026-03-04`, `04/03/2026`) keeps its exact
  characters.
- **Numbers**: odometers (`Odometer km`, `Odometer KM`, `Odometer Begin/End`,
  `Distance`) and measured speeds (`Max Speed KMH`, `Average Speed KMH`,
  `Speed Limit`) are numeric cells, so they sort and sum.
- **Durations**: the activity duration columns are numeric durations formatted
  `[h]:mm`, so `09:31` stays a duration and a monthly total of `48:00` keeps
  counting past 24 hours instead of becoming `2.00`.
- **Everything else stays text**: card numbers, licence numbers, VINs, serials,
  registration plates, certificate references, hex material, codes and counters
  keep their exact characters (a leading zero survives, a 16-digit number is not
  rounded to 15), and a sentinel (`N/A`), a placeholder or a malformed value is
  never guessed into a date or a number.
- **Unknown time is a note, not a number**: the Daily Activities `Unknown (h:mm)`
  cell stays numeric and a `Notes` column says what the value is. Unknown time
  just means the record does not attribute those minutes to Drive, Work, Rest or
  Available — it is not by itself a sign of a corrupt file.

**Two activity sheets, one report**: the rows come from the same monthly activity
report the PDF and CSV print, and the arithmetic is the same slot-aware engine.
The Excel workbook splits that report so a filter range only ever holds one kind
of row: `Daily Activities` contains day rows only, `Monthly Activities` the
monthly subtotal rows. Both are subject to the same 50,000-row limit, counted on
the report rows *including* the subtotal rows, so a month whose subtotal row was
cut simply has no row on the monthly sheet — no total is invented for it.

**Limits, stated inside the file**: a section with more report rows than the
50,000-row limit says so on its own sheet ("Row limit: 3 of 7 rows exported …")
and again in the Summary, which names each capped section with its exported and
available row count and points at the JSON export (or the original `.ddd` file)
for the complete data. The disclosure is in the workbook even when the limit
retains no visible row at all. The key/value sheets, the TREP signature list and
the VU certificate list are not row-capped.

The disclosure is meant to be read, so the sheet note is never squeezed into a
narrow table: its merged span is guaranteed at least 60 characters (a one-column
table's last column is widened to reach that) and the row height is computed from
that real width with no line cap, up to Excel's 409.5-point row limit — beyond
which the note is elided from the front, marked with `…`, so the row-limit
statement itself survives. Data rows are never wrapped.

**The Summary index**: every sheet gets an entry. Sections that carry a
description show its first sentence; a section without one (card certificates,
the card-application tables) gets a fallback that says what the sheet is — a
records table or a key/value table, named after the sheet. Entries are wrapped
and the row is sized to its text, so no entry is blank and none is cut at the
column edge.

**A preview, not the parsed structure**: nested values are shown as the same
compact report text the other exports use — not as their full decoded detail —
and coverage/verification statements are the file's own, never a claim the export
produced. Use JSON for the complete decoded structure.

**Best for**:
- Sharing reports with non-technical staff
- Filtering and sorting data by date or activity type
- Pivot-table analysis (typed dates, numbers and durations)

**How to export**:
- GUI: **Export → Excel (.xlsx)**
- CLI: `python app/cli.py file.ddd --excel report.xlsx` (requires `openpyxl`)

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
