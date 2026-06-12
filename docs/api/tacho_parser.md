# TachoParser

Main parser entry point for `.ddd` digital tachograph files. Handles generation detection (G1/G2/G2.2), deterministic or legacy parsing, post-processing (dedup, forensic validation), and coverage gap filling.

**File:** `ddd_parser.py:26`

## Class: `TachoParser`

```python
class TachoParser:
    """Professional analysis engine for Tachograph files (.DDD)."""
```

### Constructor

```python
def __init__(self, file_path: str, use_deterministic: bool = True)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | `str` | (required) | Path to the `.ddd` file to parse |
| `use_deterministic` | `bool` | `True` | Use `DeterministicParser` (two-pass) or legacy `TagNavigator` |

**Instance attributes set on init:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `file_path` | `str` | Source file path |
| `file_size` | `int` | File size in bytes |
| `raw_data` | `mmap` or `None` | Memory-mapped file data (set during `parse()`) |
| `validator` | `SignatureValidator` | Certificate chain validator instance |
| `bytes_covered` | `int` | Running count of bytes assigned to tags |
| `card_public_key` | `bytes` or `None` | Extracted card public key after validation |
| `msca_cert_raw` | `bytes` or `None` | Raw MSCA certificate bytes |
| `card_cert_raw` | `bytes` or `None` | Raw card certificate bytes |
| `validation_status` | `str` | Certificate chain validation result |
| `is_vu` | `bool` | True if file starts with `0x76` (vehicle unit data) |
| `use_deterministic` | `bool` | Parser mode flag |
| `results` | `dict` | Parsed data (TachoResult.to_dict()) |
| `navigator` | `TagNavigator` | Legacy recursive parser (used in legacy mode) |

### Method: `parse()`

```python
def parse(self) -> dict
```

Parses the `.ddd` file and returns the complete result dictionary.

**Returns:** `dict` — A `TachoResult.to_dict()` with all parsed fields.

**Pipeline steps (in order):**

1. **Validation**: Checks file existence and non-zero size
2. **Memory map**: Opens file with `mmap` for random access
3. **Generation detection**: Reads first 1-2 bytes to detect VU (0x76) and generation
4. **Parsing mode**: 
   - *Deterministic* (`use_deterministic=True`): Delegates to `DeterministicParser.parse()`
   - *Legacy* (`use_deterministic=False`): Calls `TagNavigator.parse_stap_recursive()` + `deep_scan()`
5. **VU download messages**: If `is_vu`, parses SID 0x76 + TREP messages via `decoders.parse_vu_download_messages()`
6. **Coverage**: `_fill_coverage_gaps()` guarantees 100% byte coverage (legacy) or reads coverage from deterministic parser
7. **Post-processing**: Activity deduplication and date-based sorting
8. **Forensic validation**: Certificate chain validation via `SignatureValidator.validate_tacho_chain()`
9. **Generations tree**: Builds hierarchical view via `build_generations_tree()`

### Method: `get_coverage_report()`

```python
def get_coverage_report(self) -> float
```

Returns the percentage of bytes assigned to identified fields.

**Returns:** `float` — Coverage percentage (0.0–100.0), rounded to 2 decimal places.

### Properties and Detection Logic

**Generation detection** happens in two paths:

- **Deterministic parser** (`core/deterministic_parser.py:188`): Reads first 2 bytes:
  - `b'\x76\x31'` → `"G2.2 (Smart V2)"`
  - `b'\x76\x21'` or `b'\x76\x22'` → `"G2 (Smart)"`
  - Otherwise → `"G1 (Digital)"`

- **Legacy parser** (`ddd_parser.py:141-147`): Same logic, inline.

**VU detection**: First byte == `0x76` → `is_vu = True`.

**Parser selection**: Controlled by `use_deterministic` constructor parameter. The deterministic parser (`core/deterministic_parser.py`) provides 100% coverage by design; the legacy parser (`TagNavigator`) relies on `_fill_coverage_gaps()` to achieve the same.

## Usage Example

```python
# From ddd_parser.py:216
import sys
import json
from ddd_parser import TachoParser

parser = TachoParser("/path/to/file.ddd")
results = parser.parse()

# Access parsed data
print(results["metadata"]["generation"])       # e.g. "G2.2 (Smart V2)"
print(results["metadata"]["integrity_check"])  # e.g. "Verified"
print(results["driver"]["surname"])            # e.g. "ROSSI"
print(results["vehicle"]["plate"])             # e.g. "AA000BB"
print(len(results["activities"]))              # Number of daily activity records

# Check coverage
pct = parser.get_coverage_report()
print(f"Coverage: {pct}%")

# Certificate validation status
print(parser.validation_status)  # "Verified", "Verified (Local Chain)", or "Invalid Certificate Chain"
```

### Using non-deterministic (legacy) mode

```python
parser = TachoParser("/path/to/file.ddd", use_deterministic=False)
results = parser.parse()
```

## See Also

- [TachoResult](models.md) — Data structure returned by parse()
- [ExportManager](export_manager.md) — Export results to Excel/CSV

## See Also

- [TachoResult](models.md) — Output data model
- [DeterministicParser](deterministic_parser.md) — Two-pass parser used by default
- [TagNavigator](tag_navigator.md) — Legacy recursive parser

## Common Tasks

### Parse a single file and check integrity

```python
from ddd_parser import TachoParser

parser = TachoParser("my_tacho.ddd")
data = parser.parse()
status = data["metadata"]["integrity_check"]
print(f"File integrity: {status}")
```

### Extract driver and vehicle info

```python
parser = TachoParser("my_tacho.ddd")
data = parser.parse()
driver = data["driver"]
vehicle = data["vehicle"]
print(f"{driver['firstname']} {driver['surname']}, Card: {driver['card_number']}")
print(f"Vehicle: {vehicle['plate']} (VIN: {vehicle['vin']})")
```

### Count activities by type

```python
parser = TachoParser("my_tacho.ddd")
data = parser.parse()
for day in data["activities"][:5]:
    print(f"Date: {day['data']}, Events: {len(day.get('eventi', []))}")
```

### Run coverage audit

```python
parser = TachoParser("my_tacho.ddd")
data = parser.parse()
coverage = data["metadata"]["coverage_pct"]
print(f"Byte coverage: {coverage}%")
```
