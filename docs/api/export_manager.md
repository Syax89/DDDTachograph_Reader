# ExportManager

Report writers for parsed tachograph data: a multi-sheet Excel workbook, a
paginated PDF report and a section-block CSV. JSON is not produced here — the CLI
and the GUI serialise the parser result themselves (see below).

**File:** `app/export.py`

**Shared report layer:** `core/utils/report_format.py` (`section_tables`,
`summary_rows`, `records_to_table`, `integrity_verdict`, `humanize_key`). Excel,
CSV and PDF render the same sections and the same humanised labels from it, so a
field is called the same thing in every report. The layer also hoists a
`record_type` column that is constant across a section into a one-line note
beside the section description.

---

## Class: `ExportManager`

```python
class ExportManager:
    """Multi-format export of parsed tachograph data."""
```

All methods are static; no constructor is needed. Each takes the result dict
returned by `TachoParser.parse()` and an output path, and writes the file
directly (any `OSError` from the path propagates).

| Method | Output | Optional dependency |
|---|---|---|
| `export_to_excel(data, filepath)` | `.xlsx` | `openpyxl` |
| `export_to_pdf(data, filepath)` | `.pdf` | `reportlab` |
| `export_to_csv(data, filepath)` | `.csv` | none |

The optional dependency is imported inside the method, so the module itself
imports without them: a caller that only needs CSV never pays for `openpyxl` or
`reportlab`.

---

### Method: `export_to_excel(data, filepath)`

```python
@staticmethod
def export_to_excel(data: Dict[str, Any], filepath: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `data` | `dict` | Parsed result dict from `TachoParser.parse()` |
| `filepath` | `str` | Output `.xlsx` file path |

**Sheet layout** (in workbook order):

| Sheet | Source | Contents |
|-------|--------|----------|
| `Summary` | `summary_rows(data)` | One row per summary fact (zeros included), the parse/integrity problem rows tinted, a warnings-and-limits block, and an index of every sheet with its row count and an internal hyperlink |
| `TREP Signatures` | `signature_verification.treps` | Per-block signature verification (VU files) |
| `VU Certificates` | `vu_certificates` | Certificates found in the file (VU files) |
| `Daily Activities` | `activities` via the shared activity report | Day rows only, with a `Notes` column when unattributed time is present |
| `Monthly Activities` | the same report | The monthly subtotal rows, highlighted |
| one sheet per data section | `EXPORT_SECTIONS` | Events, faults, places, calibrations, GNSS, … |
| key/value sheets | `DICT_SECTIONS` | Card application, VU information, sensor identification, IC chip, … |

**Typed cells:** a column is typed only when its meaning is known
(`_EXCEL_TIME_LABELS`, `_EXCEL_NUMBER_LABELS`, and the `(h:mm)` duration
columns); a value is converted only when it matches the canonical shape the
report prints. Everything else — identifiers, codes, `N/A` sentinels, malformed
values — stays text, and a leading `=`, `+`, `-` or `@` is escaped so a
spreadsheet cannot execute it as a formula.

**Row limit:** `_EXCEL_MAX_ROWS` (50 000) report rows per data section, counted
on the shared rows *including* the monthly subtotals and applied before the
daily/monthly split. A capped section discloses the cut on its own sheet and in
the Summary. Key/value sheets, `TREP Signatures` and `VU Certificates` are not
capped.

---

### Method: `export_to_pdf(data, filepath)`

```python
@staticmethod
def export_to_pdf(data: Dict[str, Any], filepath: str) -> None
```

A4 landscape report in three parts: a cover (file/source/generation, generation
time, activity period from the daily records, identity, file state, totals grid),
the operational sections, then a **Technical Appendix** (`_PDF_APPENDIX_SECTIONS`
plus a closing *File & Parse Details* block). A section with more than
`_PDF_WIDE_COLUMNS` (10) visible columns prints as one field/value card per
record. Each list section stops at `_PDF_MAX_ROWS` (1 500) rows and says so on
the page; the cover's totals are computed from every daily record in the input,
so they can exceed the capped tables below them.

Characters the PDF's built-in font cannot draw are replaced with a plain
stand-in (`⚠` → `!`); the report rows themselves keep the original.

---

### Method: `export_to_csv(data, filepath)`

```python
@staticmethod
def export_to_csv(data: Dict[str, Any], filepath: str) -> None
```

One file, UTF-8 with BOM, `;` delimiter, one block per section: a
`=== SECTION NAME ===` marker row, the section description, the header row, the
data rows, a blank separator. No row cap. Nested values are the compact report
text and internal bookkeeping keys are omitted — use the JSON output for the full
decoded structure. Cells that would start with `=`, `+`, `-` or `@` get a
leading apostrophe. The section marker rows (`=== EVENTS ===`) are the exception:
they are written as is, so they read `=== EVENTS ===` in the raw text.

---

## JSON output

JSON is the complete parsed structure, not a report: it is written by
`app/cli.py` and the GUI's JSON export with
`json.dump(..., cls=core.utils.encoding.BytesEncoder)`, which turns `bytes` into
hex strings and sets into sorted lists. It therefore contains every decoded
field, including `raw_tags`, `coverage`, `sections`, `generations` and the
verification results — and it is not a reversible copy of the original `.ddd`
file.

---

## Usage Example

```python
from app.engine import TachoParser
from app.export import ExportManager

data = TachoParser("file.ddd").parse()

ExportManager.export_to_excel(data, "report.xlsx")
ExportManager.export_to_pdf(data, "report.pdf")
ExportManager.export_to_csv(data, "report.csv")
```

### Batch export multiple files

```python
import os

from app.engine import TachoParser
from app.export import ExportManager

os.makedirs("output", exist_ok=True)
for filename in os.listdir("DDD/"):
    if filename.lower().endswith(".ddd"):
        data = TachoParser(os.path.join("DDD", filename)).parse()
        stem = os.path.splitext(filename)[0]
        ExportManager.export_to_excel(data, os.path.join("output", stem + ".xlsx"))
```

## See Also

- [TachoParser](tacho_parser.md) — Produces the data dict used for export
- [../../docs/user/export_guide.md](../user/export_guide.md) — What each format
  contains, its limits and when to use it
