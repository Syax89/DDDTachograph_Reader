# TachoResult — Data Models

Data models for tachograph parsing results. Defines `TachoResult`, `DriverInfo`, `VehicleInfo`, and related dataclasses used throughout the pipeline.

**File:** `core/models.py`

---

## `TachoResult` dataclass

The central result container for all parsed tachograph data.

```python
@dataclass
class TachoResult:
    metadata: Dict[str, Any]
    driver: Dict[str, Any]
    vehicle: Dict[str, Any]
    activities: List[Dict[str, Any]]
    vehicle_sessions: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    faults: List[Dict[str, Any]]
    locations: List[Dict[str, Any]]
    places: List[Dict[str, Any]]
    calibrations: List[Dict[str, Any]]
    raw_tags: Dict[str, List[Dict[str, Any]]]
    signatures: List[Dict[str, Any]]
    gnss_ad_records: List[Dict[str, Any]]
    load_unload_records: List[Dict[str, Any]]
    trailer_registrations: List[Dict[str, Any]]
    gnss_places: List[Dict[str, Any]]
    load_sensor_data: List[Dict[str, Any]]
    border_crossings: List[Dict[str, Any]]
    signed_daily_records: List[Dict[str, Any]]
```

### Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metadata` | `dict` | See below | File metadata (filename, generation, coverage, etc.) |
| `driver` | `dict` | See below | Driver identification data |
| `vehicle` | `dict` | See below | Vehicle identification (VIN, plate) |
| `activities` | `List[dict]` | `[]` | Daily activity records with events |
| `vehicle_sessions` | `List[dict]` | `[]` | Vehicle usage history (VehiclesUsed) |
| `events` | `List[dict]` | `[]` | Events data (0x0502) |
| `faults` | `List[dict]` | `[]` | Faults data (0x0503) |
| `locations` | `List[dict]` | `[]` | GNSS location entries |
| `places` | `List[dict]` | `[]` | Place records (0x0506) |
| `calibrations` | `List[dict]` | `[]` | Calibration records |
| `raw_tags` | `Dict[str, List[dict]]` | `{}` | Raw tag occurrences with offsets, hex data |
| `signatures` | `List[dict]` | `[]` | Digital signature data |
| `gnss_ad_records` | `List[dict]` | `[]` | G2.2 GNSS accumulated driving (0x0525) |
| `load_unload_records` | `List[dict]` | `[]` | G2.2 load/unload operations (0x0526) |
| `trailer_registrations` | `List[dict]` | `[]` | G2.2 trailer registrations (0x0527) |
| `gnss_places` | `List[dict]` | `[]` | G2.2 GNSS enhanced places (0x0528) |
| `load_sensor_data` | `List[dict]` | `[]` | G2.2 load sensor data (0x0529) |
| `border_crossings` | `List[dict]` | `[]` | G2.2 border crossing records (0x052A) |
| `signed_daily_records` | `List[dict]` | `[]` | G2.2 signed daily records |

### `metadata` default fields

```python
{
    "filename": "N/A",
    "generation": "Unknown",
    "parsed_at": datetime.now().isoformat(),
    "integrity_check": "Pending",
    "file_size_bytes": 0,
    "coverage_pct": 0.0
}
```

### `driver` default fields

```python
{
    "card_number": "N/A",
    "surname": "N/A",
    "firstname": "N/A",
    "birth_date": "N/A",
    "expiry_date": "N/A",
    "issuing_nation": "N/A",
    "preferred_language": "N/A",
    "licence_number": "N/A",
    "licence_issuing_nation": "N/A"
}
```

### `vehicle` default fields

```python
{
    "vin": "N/A",
    "plate": "N/A",
    "registration_nation": "N/A"
}
```

### Method: `to_dict()`

```python
def to_dict(self, tags: Dict[int, str] = None) -> Dict[str, Any]
```

Converts the result to a dictionary. If `tags` is provided, also builds a hierarchical generations tree.

**Parameters:**
- `tags` — Tag ID → name mapping (e.g., `TACHO_TAGS`)

**Returns:** `dict` — Complete result dictionary with all fields.

---

## `DriverInfo` dataclass

```python
@dataclass
class DriverInfo:
    card_number: str = "N/A"
    surname: str = "N/A"
    firstname: str = "N/A"
    birth_date: str = "N/A"
    expiry_date: str = "N/A"
    issuing_nation: str = "N/A"
    preferred_language: str = "N/A"
    licence_number: str = "N/A"
    licence_issuing_nation: str = "N/A"
```

---

## `VehicleInfo` dataclass

```python
@dataclass
class VehicleInfo:
    vin: str = "N/A"
    plate: str = "N/A"
    registration_nation: str = "N/A"
```

---

## `ActivityRecord`, `EventRecord`, `FaultRecord`

These are represented as **dictionaries** (not formal dataclasses) within the `TachoResult` lists:

**ActivityRecord** (per-day entry in `activities`):
```python
{
    "data": "DD/MM/YYYY",         # Date string
    "driver": "DRIVER_NAME",       # Driver identifier (optional)
    "km": 123,                     # Kilometers driven
    "km_start": "0000000 km",     # Odometer at start
    "km_end": "0000123 km",       # Odometer at end
    "daily_counter": 1,           # Day counter
    "eventi": [                   # List of activity changes within the day
        {
            "tipo": "GUIDA",      # Activity type (GUIDA/RIPOSO/LAVORO/DISPONIBILE)
            "ora": "08:30",       # Start time (HH:MM)
            "durata": 45          # Duration in minutes
        },
        ...
    ]
}
```

**EventRecord** (entry in `events`):
```python
{
    "type": "GnssFault",          # Event type string
    "start": "DD/MM/YYYY HH:MM", # Start timestamp
    "end": "DD/MM/YYYY HH:MM",   # End timestamp
    "vehicle": "AA000BB"          # Vehicle plate at time of event
}
```

**FaultRecord** (entry in `faults`): Same structure as EventRecord.

---

## `build_generations_tree()`

```python
def build_generations_tree(results: Dict[str, Any], tags: Dict[int, str]) -> Dict[str, Any]
```

Builds a hierarchical view of decoded data grouped by generation and clean tag name. Strips generation prefixes (`G22_`, `G2_`, `G1_`, `VU_`, `EF_`) from tag names.

**Parameters:**
- `results` — The full result dictionary (from `TachoParser.parse()`)
- `tags` — Tag ID → name mapping (from `TACHO_TAGS`)

**Returns:** `dict` — Tree with top-level keys `"Generation 1"`, `"Generation 2"`, `"Generation 2.2"`, each containing decoded data and `_RawTags` sub-tree.

**Implementation** (`core/models.py:113-341`): Maps result fields to their corresponding tag IDs (e.g., `driver` → `0x0520 Identification`, `activities` → `0x0504 DriverActivityData`, etc.) and organizes raw tags by generation prefix.

### Output structure

```python
{
    "Generation 1": {
        "Identification": {...},           # 0x0520
        "DrivingLicenceInfo": {...},       # 0x0521
        "EventsData": [...],               # 0x0502
        "FaultsData": [...],               # 0x0503
        "DriverActivityData": [...],       # 0x0504
        "VehiclesUsed": [...],             # 0x0505
        "CurrentUsage": [...],             # 0x0507
        "CalibrationData": [...],          # 0x050C
        "VehicleIdentification": {...},    # 0x0001
        "VU_TechnicalInfo": {...},
        "_RawTags": {...}
    },
    "Generation 2": {
        "CardIccIdentification": {...},    # 0x0101
        "CardIdentification": {...},       # 0x0102
        "DriverCardHolderIdentification": {...},  # 0x0201
        "VehiclesUsed": [...],             # 0x0523
        "_RawTags": {...}
    },
    "Generation 2.2": {
        "GNSSAccumulatedDriving": [...],   # 0x0525
        "LoadUnloadOperations": [...],     # 0x0526
        "TrailerRegistrations": [...],     # 0x0527
        "GNSSEnhancedPlaces": [...],       # 0x0528
        "LoadSensorData": [...],           # 0x0529
        "BorderCrossings": [...],          # 0x052A
        "_RawTags": {...}
    }
}
```

---

## Usage Example

```python
# From core/models.py usage pattern (seen in ddd_parser.py:203)
from ddd_parser import TachoParser
from core.models import build_generations_tree, TachoResult

parser = TachoParser("my_tacho.ddd")
data = parser.parse()

# Access parsed fields
print(data["metadata"]["filename"])         # "my_tacho.ddd"
print(data["metadata"]["generation"])       # "G2.2 (Smart V2)"
print(data["metadata"]["integrity_check"])  # "Verified"
print(data["driver"]["surname"])            # "ROSSI"
print(data["driver"]["card_number"])        # "IT0000000000000000"
print(data["vehicle"]["plate"])             # "AA000BB"
print(data["vehicle"]["vin"])              # "VIN12345678901234"

# Iterate activities
for day in data["activities"][:3]:
    print(f"Date: {day['data']}, KM: {day.get('km', 0)}")
    for ev in day.get("eventi", []):
        print(f"  {ev['ora']} - {ev['tipo']} ({ev['durata']}min)")

# Access G2.2-specific data
for gnss in data["gnss_ad_records"]:
    print(f"GNSS AD: {gnss}")
for border in data["border_crossings"]:
    print(f"Border crossing: {border}")

# Access raw tags by key
for key, occurrences in data["raw_tags"].items():
    print(f"{key}: {len(occurrences)} occurrence(s)")
    for occ in occurrences[:2]:
        print(f"  offset={occ['offset']}, tag={occ['tag_id']}, length={occ['length']}")

# Build and explore generations tree
from core.tag_definitions import TACHO_TAGS
tree = build_generations_tree(data, TACHO_TAGS)
for gen_name, gen_data in tree.items():
    print(f"\n{gen_name}:")
    for section, content in gen_data.items():
        if section == "_RawTags":
            print(f"  Raw tags: {len(content)} groups")
        else:
            print(f"  {section}: {type(content).__name__}")

# Using the dataclass directly
result = TachoResult()
result.metadata["filename"] = "example.ddd"
data = result.to_dict()
```

## See Also

- [TachoParser](tacho_parser.md) — Main parser that produces TachoResult
- [ExportManager](export_manager.md) — Exports TachoResult to Excel/CSV/PDF

## Common Tasks

### Extract driver identity

```python
parser = TachoParser("file.ddd")
data = parser.parse()
d = data["driver"]
print(f"{d['firstname']} {d['surname']}")
print(f"Born: {d['birth_date']}, Card expires: {d['expiry_date']}")
print(f"Licence: {d['licence_number']} ({d['licence_issuing_nation']})")
```

### Count G2.2 records

```python
parser = TachoParser("file.ddd")
data = parser.parse()
print(f"GNSS AD records: {len(data['gnss_ad_records'])}")
print(f"Load/Unload: {len(data['load_unload_records'])}")
print(f"Trailers: {len(data['trailer_registrations'])}")
print(f"Border crossings: {len(data['border_crossings'])}")
```
