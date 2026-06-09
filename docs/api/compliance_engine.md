# ComplianceEngine

EU 561/2006 driving and rest period compliance analysis. Checks continuous driving limits, daily/weekly rest, bi-weekly driving caps, and produces infraction reports with severity classification.

**File:** `compliance_engine.py`

---

## Class: `ComplianceEngine`

```python
class ComplianceEngine:
    """Implements complex logic for split breaks, 24-hour shift cycles, and infraction severity."""
```

### Severity Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `MSI` | `"MSI"` | Most Serious Infringement |
| `SI` | `"SI"` | Serious Infringement |
| `MI` | `"MI"` | Minor Infringement |

### Constructor

```python
def __init__(self)
```

Initializes an empty `infractions` list.

---

### Method: `analyze(activities)`

```python
def analyze(self, activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]
```

Main analysis entry point. Takes parsed activity records and runs all compliance checks.

**Parameters:**
- `activities` — List of daily activity dicts from `TachoResult.activities`. Each entry:
  ```python
  {
      "data": "DD/MM/YYYY",         # Date string
      "eventi": [                     # Activity changes
          {"tipo": "GUIDA", "ora": "HH:MM", "durata": minutes},
          ...
      ]
  }
  ```

**Returns:** `List[dict]` — List of infraction records.

**Pipeline:**
1. `_build_timeline()` — Converts day-based activities into a flat chronological timeline
2. `_check_driving_and_breaks()` — Continuous driving (4.5h max, split breaks)
3. `_check_daily_rest_cycles()` — 24-hour shift rest (11h regular / 9h reduced)
4. `_check_daily_driving_limit()` — Art. 6.1: 9h/day (extendable to 10h, max 2x/week)
5. `_check_weekly_compliance()` — Weekly rest (45h/24h), compensation, bi-weekly 90h driving cap

---

### EU 561/2006 Rules Checked

| Rule | Source | Limit | Infraction Type |
|------|--------|-------|-----------------|
| Continuous driving | Art. 7 | Max 4h30 (270 min) without break | `ECCESSO_GUIDA_CONTINUA` |
| Split break | Art. 7 | 15 min + 30 min or 45 min continuous | (resets accumulator) |
| Daily driving | Art. 6.1 | 9h, extendable to 10h (2x/week) | `ECCESSO_GUIDA_GIORNALIERA` |
| Weekly extensions | Art. 6.1 | Max 2 extensions to 10h/week | `ECCESSO_ESTENSIONI_GUIDA_SETTIMANALI` |
| Daily rest | Art. 8.2 | 11h (regular) / 9h (reduced) within 24h | `RIPOSO_GIORNALIERO_INSUFFICIENTE` |
| Reduced rests | Art. 8.2 | Max 3 reduced rests between weekly rests | `ECCESSO_RIPOSI_RIDOTTI` |
| Inter-weekly interval | Art. 8.6 | Max 6x24h (144h) between weekly rests | `SUPERAMENTO_6_PERIODI_24H` |
| Weekly rest | Art. 8.6 | 45h (regular) / 24h (reduced) | `MANCATA_COMPENSAZIONE_SETTIMANALE` |
| Weekly driving | Art. 6.2 | 56h/week | `ECCESSO_GUIDA_SETTIMANALE` |
| Bi-weekly driving | Art. 6.3 | 90h in two consecutive weeks | `ECCESSO_GUIDA_BISETTIMANALE` |

### Severity Classification

**Driving excess** (`_get_driving_severity`):

| Excess | Severity |
|--------|----------|
| ≤ 30 min | MI (Minor) |
| 31–90 min | SI (Serious) |
| > 90 min | MSI (Most Serious) |

**Rest shortfall** (`_get_rest_severity`):

| Shortfall | Severity |
|-----------|----------|
| ≤ 60 min | MI (Minor) |
| 61–120 min | SI (Serious) |
| > 120 min | MSI (Most Serious) |

**Daily driving limit:**

| Excess | Severity |
|--------|----------|
| > 10h (600 min) | SI |
| > 11h (660 min) | MSI |

---

### Infraction Output Structure

Each infraction is a dictionary:

```python
{
    "data": "15/03/2024",                          # Date of infraction (DD/MM/YYYY)
    "tipo": "ECCESSO_GUIDA_CONTINUA",              # Infraction type code
    "severita": "SI",                              # MSI, SI, or MI
    "descrizione": "Guida continua di 310 min..."  # Human-readable description (Italian)
}
```

---

### Method: `get_daily_summary(activities)`

```python
def get_daily_summary(self, activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]
```

Generates daily summaries for GUI display. Returns per-day totals for driving, work, rest, and infraction count.

**Parameters:**
- `activities` — Same format as `analyze()`

**Returns:** `List[dict]` — Daily summaries:
```python
[
    {
        "Data": "15/03/2024",
        "Guida Totale": "07:45",       # HH:MM format
        "Lavoro Totale": "01:30",
        "Riposo Totale": "09:00",
        "Infrazioni": 2
    },
    ...
]
```

---

### Method: `get_report()`

```python
def get_report(self) -> List[Dict[str, Any]]
```

Returns the internal infractions list after analysis. Shortcut for accessing results.

---

### Internal Methods

| Method | Description |
|--------|-------------|
| `_build_timeline(activities)` | Converts day-based events to flat chronological timeline with calculated durations |
| `_merge_timeline(timeline)` | Merges consecutive events of the same type (≤60s gap) |
| `_check_driving_and_breaks(timeline)` | Split break logic: 45 min or 15+30 min pattern |
| `_check_daily_rest_cycles(timeline)` | 24-hour shift rest analysis; tracks reduced rest count |
| `_check_daily_driving_limit(timeline)` | Per-shift driving limits (9h/10h) with weekly extension tracking |
| `_check_weekly_compliance(timeline)` | Weekly rest intervals, compensation deadlines, bi-weekly driving cap |
| `_get_driving_severity(excess_min)` | Severity class for continuous driving excess |
| `_get_rest_severity(shortfall_min)` | Severity class for rest period shortfall |

---

## Usage Example

```python
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine

# Parse file
parser = TachoParser("driver_card.ddd")
data = parser.parse()

# Analyze compliance
engine = ComplianceEngine()
infractions = engine.analyze(data["activities"])

# Print results
print(f"Infractions found: {len(infractions)}")
for inf in infractions:
    sev_map = {"MSI": "MOST SERIOUS", "SI": "SERIOUS", "MI": "MINOR"}
    print(f"  [{sev_map.get(inf['severita'], inf['severita'])}] {inf['data']}: {inf['tipo']}")
    print(f"    {inf['descrizione']}")

# Get daily summary
daily = engine.get_daily_summary(data["activities"])
for day in daily:
    print(f"{day['Data']}: Drive={day['Guida Totale']}, Work={day['Lavoro Totale']}, Rest={day['Riposo Totale']}, Inf={day['Infrazioni']}")
```

### Using from FleetAnalytics (real codebase pattern)

```python
# From fleet_analytics.py:33-53
from fleet_analytics import FleetAnalytics

analyzer = FleetAnalytics("/path/to/DDD_folder")
result = analyzer.process_file("/path/to/file.ddd")
print(f"Driver: {result['driver_name']}")
print(f"Drive time: {result['total_drive_time_hours']}h")
print(f"Infractions: {result['infractions']}")
```

## See Also

- [TachoParser](tacho_parser.md) — Produces activities data for analysis
- [TachoResult](models.md) — Activity data model
- [FleetAnalytics](fleet_analytics.md) — Batch analysis using ComplianceEngine
- [Export PDF](export_pdf.md) — PDF reports with compliance data

## Common Tasks

### Count infractions by severity

```python
engine = ComplianceEngine()
infractions = engine.analyze(data["activities"])
counts = {"MSI": 0, "SI": 0, "MI": 0}
for inf in infractions:
    counts[inf["severita"]] += 1
print(f"MSI: {counts['MSI']}, SI: {counts['SI']}, MI: {counts['MI']}")
```

### Find days with most infractions

```python
daily = engine.get_daily_summary(data["activities"])
worst = sorted(daily, key=lambda d: d["Infrazioni"], reverse=True)[:5]
for day in worst:
    print(f"{day['Data']}: {day['Infrazioni']} infractions")
```

### Check driving hours per day

```python
daily = engine.get_daily_summary(data["activities"])
for day in daily:
    if day["Infrazioni"] > 0:
        print(f"  *** {day['Data']}: Drive={day['Guida Totale']} — {day['Infrazioni']} infractions")
```

### Filter specific infraction types

```python
engine = ComplianceEngine()
infractions = engine.analyze(data["activities"])
driving = [i for i in infractions if "GUIDA" in i["tipo"]]
rest = [i for i in infractions if "RIPOSO" in i["tipo"] or "REST" in i["tipo"].upper()]
print(f"Driving infractions: {len(driving)}, Rest infractions: {len(rest)}")
```
