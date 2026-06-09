# FleetAnalytics

Multi-file fleet batch analysis for DDD tachograph data. Processes multiple `.ddd` files in parallel to produce aggregated driver/vehicle analytics and comparative reports.

**File:** `fleet_analytics.py`

---

## Class: `FleetAnalytics`

```python
class FleetAnalytics:
    """Multi-file fleet analytics engine that processes multiple .ddd files
    and produces aggregated driver/vehicle statistics with comparative reporting."""
```

### Constructor

```python
def __init__(self, folder_path: str)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `folder_path` | `str` | Path to directory containing `.ddd` files |

**Initializes:**
- `self.folder_path` — Source directory
- `self.results` — Empty list for per-file results
- `self.compliance` — `ComplianceEngine` instance for infraction analysis

---

### Method: `process_file(file_path)`

```python
def process_file(self, file_path: str) -> Dict[str, Any]
```

Processes a single `.ddd` file and returns aggregated statistics.

**Parameters:**
- `file_path` — Path to a `.ddd` file

**Returns:** `dict` — Per-file analytics result:

```python
{
    "filename": "driver_card.ddd",
    "status": "OK",
    "driver_name": "Mario Rossi",
    "card_number": "IT0000000000000000",
    "total_km": 1250,
    "total_drive_time_hours": 45.5,
    "last_activity": "15/03/2024",
    "infractions": 3,
    "integrity": "Verified"
}
```

On error:
```python
{
    "filename": "corrupted.ddd",
    "status": "ERROR",
    "error": "Parse failed"
}
```

**Processing steps:**
1. Parses the file via `TachoParser(file_path).parse()`
2. Extracts driver identity (name, card number)
3. Sums total kilometers from activity records
4. Builds a timeline via `ComplianceEngine._build_timeline()` to calculate drive time
5. Runs `ComplianceEngine.analyze()` for infraction count
6. Reads integrity check status from metadata

---

### Method: `run()`

```python
def run(self) -> List[Dict[str, Any]]
```

Processes all `.ddd` files in `folder_path` using a thread pool.

**Returns:** `List[dict]` — Results for all files (same format as `process_file()`).

**Implementation:** Uses `concurrent.futures.ThreadPoolExecutor` with `executor.map()` for parallel processing.

```python
# From fleet_analytics.py:74-81
files = glob.glob(os.path.join(self.folder_path, "*.ddd"))
with ThreadPoolExecutor() as executor:
    self.results = list(executor.map(self.process_file, files))
```

---

### Method: `print_report()`

```python
def print_report(self)
```

Prints a formatted table to stdout:

```
FILENAME                  | DRIVER               | KM       | DRIVE(H) | INF | STATUS
-------------------------------------------------------------------------------
driver_card.ddd           | Mario Rossi          | 1250     | 45.5     | 3   | Verified
```

---

### Method: `save_csv(filename="fleet_report.csv")`

```python
def save_csv(self, filename: str = "fleet_report.csv")
```

Saves results to a CSV file with columns: `Filename`, `Driver`, `Card`, `Total KM`, `Drive Time (h)`, `Last Activity`, `Infractions`, `Status`, `Integrity`.

---

## Aggregated Statistics

The output from `run()` provides per-driver statistics that can be aggregated across the fleet:

| Metric | Source | Description |
|--------|--------|-------------|
| `driver_name` | `driver.surname + " " + driver.firstname` | Full name |
| `card_number` | `driver.card_number` | Tachograph card number |
| `total_km` | Sum of `day["km"]` across all activities | Total kilometers |
| `total_drive_time_hours` | Sum of `GUIDA` durations from timeline | Driving hours |
| `last_activity` | Last event date from timeline | Most recent activity date |
| `infractions` | Count from `ComplianceEngine.analyze()` | Number of EU 561/2006 violations |
| `integrity` | `metadata.integrity_check` | Certificate validation status |

---

## Usage Example

```python
# From fleet_analytics.py:106-111 (CLI usage)
from fleet_analytics import FleetAnalytics

# Process all .ddd files in a directory
analyzer = FleetAnalytics("/path/to/ddd_files")
results = analyzer.run()

# Print summary table
analyzer.print_report()

# Save to CSV
analyzer.save_csv("fleet_report.csv")
```

### Programmatic usage

```python
from fleet_analytics import FleetAnalytics

analyzer = FleetAnalytics("./DDD/")
results = analyzer.run()

# Filter only successful parses
ok = [r for r in results if r["status"] == "OK"]
errors = [r for r in results if r["status"] == "ERROR"]

print(f"Successfully parsed: {len(ok)}, Errors: {len(errors)}")

# Find driver with most infractions
worst = max(ok, key=lambda r: r["infractions"])
print(f"Most infractions: {worst['driver_name']} ({worst['infractions']})")

# Total fleet kilometers
total_km = sum(r["total_km"] for r in ok)
print(f"Fleet total: {total_km} km")

# Total drive hours
total_hours = sum(r["total_drive_time_hours"] for r in ok)
print(f"Total drive time: {total_hours:.1f}h")

# Find files with integrity issues
suspect = [r for r in ok if r["integrity"] not in ("Verified", "Verified (G1)", "Verified (Local Chain)")]
for s in suspect:
    print(f"Warning: {s['filename']} — {s['integrity']}")
```

### Process a single file (not batch)

```python
analyzer = FleetAnalytics("./")  # folder not used for single file
result = analyzer.process_file("/path/to/single.ddd")
print(f"Driver: {result['driver_name']}")
print(f"Drive time: {result['total_drive_time_hours']}h")
print(f"Infractions: {result['infractions']}")
```

## See Also

- [TachoParser](tacho_parser.md) — Per-file parsing used by process_file()
- [ComplianceEngine](compliance_engine.md) — Infraction analysis engine
- [ExportManager](export_manager.md) — Alternative export to Excel/CSV

## Common Tasks

### Rank drivers by drive time

```python
analyzer = FleetAnalytics("./DDD/")
results = analyzer.run()
ranked = sorted([r for r in results if r["status"] == "OK"],
                key=lambda r: r["total_drive_time_hours"], reverse=True)
for i, r in enumerate(ranked[:10], 1):
    print(f"{i}. {r['driver_name']}: {r['total_drive_time_hours']}h")
```

### Filter by infraction count

```python
results = analyzer.run()
with_infractions = [r for r in results if r["status"] == "OK" and r["infractions"] > 0]
print(f"Drivers with infractions: {len(with_infractions)}/{len(results)}")
```

### CLI usage

```bash
python3 fleet_analytics.py /path/to/ddd/files
```
