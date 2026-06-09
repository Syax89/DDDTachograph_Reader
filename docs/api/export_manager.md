# ExportManager

Excel and CSV export for tachograph parsed data. Produces multi-sheet Excel workbooks and flat CSV files using pandas and openpyxl.

**File:** `export_manager.py`

---

## Class: `ExportManager`

```python
class ExportManager:
    """Exports tachograph data to Excel and CSV formats."""
```

All methods are static. No constructor initialization required.

---

### Method: `export_to_excel(data, filepath)`

```python
@staticmethod
def export_to_excel(data: Dict[str, Any], filepath: str)
```

Exports parsed tachograph data to a multi-sheet Excel file.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `data` | `dict` | Parsed result dict from `TachoParser.parse()` |
| `filepath` | `str` | Output `.xlsx` file path |

**Excel output structure:**

| Sheet Name | Source Data | Contents |
|-----------|-------------|----------|
| `Riepilogo` | `metadata`, `driver`, `vehicle`, `activities` | Summary: filename, analysis date, integrity, driver name, card number, vehicle plate, VIN, total km, total drive hours |
| `Attività Giornaliere` | `daily_summaries` | Daily activity totals (if available) |
| `Infrazioni` | `infractions` | Compliance infraction records |
| `Posizioni GPS` | `locations` or `gps_positions` | GNSS position data (if available) |

**Implementation** (`export_manager.py:7-55`): Uses `pd.ExcelWriter` with `openpyxl` engine. Creates DataFrames from dict data and writes each to a named sheet.

**Dependencies:** `pandas`, `openpyxl`

---

### Method: `export_to_csv(data, filepath)`

```python
@staticmethod
def export_to_csv(data: Dict[str, Any], filepath: str)
```

Exports parsed tachograph data to a flat CSV file with semicolon delimiter.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `data` | `dict` | Parsed result dict from `TachoParser.parse()` |
| `filepath` | `str` | Output `.csv` file path |

**CSV columns:**

| Column | Source | Description |
|--------|--------|-------------|
| `Data` | `day["data"]` | Activity date |
| `Inizio` | `ev["ora"]` | Event start time |
| `Fine` | Next event time or `"23:59"` | Event end time |
| `Durata` | Calculated in minutes | Event duration |
| `Tipo Attività` | `ev["tipo"]` | Activity type (GUIDA/LAVORO/RIPOSO/DISPONIBILE) |
| `Conducente` | `driver.surname + " " + driver.firstname` | Driver full name |
| `Carta` | `driver.card_number` | Tachograph card number |
| `Veicolo` | `vehicle.plate` | Vehicle license plate |

**Format:** UTF-8 with BOM (`utf-8-sig`), semicolon separator (`;`). Suitable for import into accounting/fleet management systems.

**Implementation** (`export_manager.py:58-100`): Iterates activities, flattens events into rows with calculated end times and durations, appends driver/card/vehicle metadata to each row.

---

### Static Helper Methods

#### `_calculate_total_km(activities)`

```python
@staticmethod
def _calculate_total_km(activities: List[Dict]) -> int
```

Sums `km` field across all activity entries. Returns 0 on parse errors.

#### `_calculate_total_hours(daily_summaries)`

```python
@staticmethod
def _calculate_total_hours(daily_summaries: List[Dict]) -> str
```

Sums `Guida Totale` field (HH:MM format) across all daily summaries. Returns formatted string like `"45h 30m"`.

---

## Usage Example

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_manager import ExportManager

# Parse file
parser = TachoParser("driver_card.ddd")
data = parser.parse()

# Add compliance data (optional)
engine = ComplianceEngine()
infractions = engine.analyze(data["activities"])
daily_summaries = engine.get_daily_summary(data["activities"])
data["infractions"] = infractions
data["daily_summaries"] = daily_summaries

# Export to Excel
ExportManager.export_to_excel(data, "output/report.xlsx")

# Export to CSV
ExportManager.export_to_csv(data, "output/activities.csv")

print("Export complete")
```

### Minimal usage (Excel only)

```python
from ddd_parser import TachoParser
from export_manager import ExportManager

parser = TachoParser("file.ddd")
data = parser.parse()
ExportManager.export_to_excel(data, "report.xlsx")
```

### CSV export with compliance data

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_manager import ExportManager

parser = TachoParser("file.ddd")
data = parser.parse()

# Attach compliance for richer export
engine = ComplianceEngine()
data["infractions"] = engine.analyze(data["activities"])
data["daily_summaries"] = engine.get_daily_summary(data["activities"])

ExportManager.export_to_excel(data, "compliance_report.xlsx")
ExportManager.export_to_csv(data, "activities_log.csv")
```

## See Also

- [TachoParser](tacho_parser.md) — Produces the data dict used for export
- [ComplianceEngine](compliance_engine.md) — Provides infractions and daily summaries
- [Export PDF](export_pdf.md) — PDF report generation
- [FleetAnalytics](fleet_analytics.md) — Alternative CSV output for batch processing

## Common Tasks

### Export with full compliance data

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from export_manager import ExportManager

parser = TachoParser("driver_card.ddd")
data = parser.parse()
engine = ComplianceEngine()
data["infractions"] = engine.analyze(data["activities"])
data["daily_summaries"] = engine.get_daily_summary(data["activities"])

ExportManager.export_to_excel(data, "full_report.xlsx")
```

### Batch export multiple files

```python
import os
from ddd_parser import TachoParser
from export_manager import ExportManager

for filename in os.listdir("DDD/"):
    if filename.endswith(".ddd"):
        parser = TachoParser(f"DDD/{filename}")
        data = parser.parse()
        out_name = filename.replace(".ddd", ".xlsx")
        ExportManager.export_to_excel(data, f"output/{out_name}")
        print(f"Exported: {out_name}")
```

### Export activities only (CSV)

```python
parser = TachoParser("file.ddd")
data = parser.parse()
ExportManager.export_to_csv(data, "activities.csv")
print(f"Exported {len(data['activities'])} days to CSV")
```
