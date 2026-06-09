# PDF Exporter

Single-driver PDF report generation using ReportLab. Creates detailed compliance reports with timeline visualization, infraction summaries, fines estimates, and raw tag data exploration.

**File:** `export_pdf.py`

**Dependencies:** `reportlab`, `fines_calculator`

---

## Module Function: `generate_pdf(json_data, output_path)`

```python
def generate_pdf(json_data: Dict[str, Any], output_path: str)
```

Main entry point for PDF report generation. Takes parsed tachograph data in JSON/dict format and produces a multi-section A4 PDF.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `json_data` | `dict` | Parsed tachograph result (from `TachoParser.parse()` or loaded from JSON) |
| `output_path` | `str` | Output `.pdf` file path |

**PDF sections (in order):**

1. **Title** — "Report Analisi Tachigrafo Digitale (v1.2.0)"
2. **Driver Identity** — Table with surname, firstname, birth date, card expiry, issuing nation, card number
3. **Summary & Fines** — Violation count and estimated sanctions (Art. 174 CdS) via `FinesCalculator`
4. **Legal Validation** — Certificate integrity status with color-coded box (green = verified, red = unverified)
5. **Timeline Visualization** — 24-hour timeline blocks for up to 7 days, with colored activity segments:
   - Blue (`#3498db`) — Driving (GUIDA)
   - Grey (`#95a5a6`) — Work (LAVORO)
   - Green (`#2ecc71`) — Rest (RIPOSO)
   - Yellow (`#f1c40f`) — Availability (DISPONIBILITÀ)
6. **Infractions Detail** — Table with date, severity (color-coded), type, estimated fine range, description
7. **Forensic Log** — Events and faults table (first 30 entries)
8. **Raw Tags Explorer** — Raw tag data table (first 150 entries) with tag ID, name, length, offset

**Expected keys in `json_data`:**

| Key | Required | Description |
|-----|----------|-------------|
| `metadata` | Yes | File metadata (includes `integrity_check`) |
| `driver` | Yes | Driver identity fields |
| `vehicle` | Yes | Vehicle identification |
| `activities` | Yes | Daily activity records with `eventi` |
| `infractions` | No | Compliance infractions (from `ComplianceEngine`) |
| `events` | No | Event records (0x0502) |
| `faults` | No | Fault records (0x0503) |
| `raw_tags` | No | Raw tag occurrences (for data explorer) |

---

## Module Function: `draw_timeline(drawing, events, infractions_dates, current_date)`

```python
def draw_timeline(drawing: Drawing, events: List[Dict], infractions_dates: List[str], current_date: str)
```

Draws a 24-hour timeline with colored activity blocks onto a ReportLab `Drawing`.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drawing` | `Drawing` | ReportLab drawing object (160mm × 15mm) |
| `events` | `List[Dict]` | Events for a single day, each with `ora`, `tipo`, `durata` |
| `infractions_dates` | `List[str]` | Dates with infractions (DD/MM/YYYY) |
| `current_date` | `str` | Current day date string |

**Visual elements:**
- Background fill (whitesmoke)
- Time markers every 3 hours
- Colored rectangles proportional to activity duration
- Infraction markers on days with violations

---

## CLI Usage

```bash
python3 export_pdf.py input.json output.pdf
```

Reads parsed tachograph data from a JSON file and generates a PDF report.

**Implementation** (`export_pdf.py:284-300`):
```python
if __name__ == "__main__":
    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        data = json.load(f)
    generate_pdf(data, sys.argv[2])
```

---

## Usage Example

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_pdf import generate_pdf
import json

# Parse file
parser = TachoParser("driver_card.ddd")
data = parser.parse()

# Add compliance data
engine = ComplianceEngine()
infractions = engine.analyze(data["activities"])
data["infractions"] = infractions

# Generate PDF
generate_pdf(data, "output/driver_report.pdf")
print("PDF generated: output/driver_report.pdf")
```

### Save intermediate JSON and generate PDF

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_pdf import generate_pdf
import json

parser = TachoParser("driver_card.ddd")
data = parser.parse()
engine = ComplianceEngine()
data["infractions"] = engine.analyze(data["activities"])

# Save JSON for later use or CLI
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

generate_pdf(data, "report.pdf")
```

### PDF with all sections populated

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_pdf import generate_pdf

parser = TachoParser("driver_card.ddd")
data = parser.parse()
engine = ComplianceEngine()

# Enrich data for all PDF sections
data["infractions"] = engine.analyze(data["activities"])
# events, faults, raw_tags are already populated by TachoParser

generate_pdf(data, "full_report.pdf")
```

## See Also

- [TachoParser](tacho_parser.md) — Produces the data dict for PDF generation
- [ComplianceEngine](compliance_engine.md) — Provides infractions for the PDF
- [ExportManager](export_manager.md) — Alternative Excel/CSV export
- [FleetAnalytics](fleet_analytics.md) — Batch processing (not per-driver PDF)

## Common Tasks

### Generate PDF for a single driver

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_pdf import generate_pdf

parser = TachoParser("driver.ddd")
data = parser.parse()
data["infractions"] = ComplianceEngine().analyze(data["activities"])
generate_pdf(data, "driver_report.pdf")
```

### Batch generate PDFs for all drivers

```python
import os
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_pdf import generate_pdf

for filename in os.listdir("DDD/"):
    if filename.endswith(".ddd"):
        parser = TachoParser(f"DDD/{filename}")
        data = parser.parse()
        data["infractions"] = ComplianceEngine().analyze(data["activities"])
        out_name = filename.replace(".ddd", ".pdf")
        generate_pdf(data, f"reports/{out_name}")
        print(f"Generated: {out_name}")
```
