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
| `Riepilogo` | `metadata`, `driver`, `vehicle`, `activities` | Summary: filename, integrity, driver name, card number, vehicle plate, VIN, total km, total drive hours |
| `Attivita Giornaliere` | `daily_summaries` | Daily activity totals (if available) |
| `Posizioni GPS` | `locations` or `gps_positions` | GNSS position data (if available) |

**Implementation** (`export_manager.py:7-55`): Uses `pd.ExcelWriter` with `openpyxl` engine.

**Dependencies:** `pandas`, `openpyxl`

---

## Usage Example

```python
from ddd_parser import TachoParser
from export_manager import ExportManager

parser = TachoParser("file.ddd")
data = parser.parse()

# Export to Excel
ExportManager.export_to_excel(data, "report.xlsx")

# Export to CSV
ExportManager.export_to_csv(data, "activities.csv")
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
```

## See Also

- [TachoParser](tacho_parser.md) — Produces the data dict used for export
