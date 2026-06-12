# TachoParser

Main parser entry point for `.ddd` digital tachograph files. Orchestrates generation detection (G1/G2/G2.2), the deterministic structural parse, VU semantic decoding, and post-processing (dedup, certificate and EF signature verification).

**File:** `ddd_parser.py`

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
| `use_deterministic` | `bool` | `True` | Deprecated. The legacy parser has been removed; passing `False` emits a `DeprecationWarning` and the deterministic parser is used regardless |

**Instance attributes set on init:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `file_path` | `str` | Source file path |
| `file_size` | `int` | File size in bytes |
| `raw_data` | `mmap` or `None` | Memory-mapped file data (set during `parse()`) |
| `validator` | `SignatureValidator` | Certificate chain validator instance |
| `card_public_key` | key object or `None` | Card public key after successful chain validation |
| `msca_cert_raw` | `bytes` or `None` | Raw MSCA certificate bytes |
| `card_cert_raw` | `bytes` or `None` | Raw card certificate bytes |
| `validation_status` | `str` | Certificate chain validation result |
| `is_vu` | `bool` | True if file starts with `0x76` (vehicle unit data) |
| `results` | `dict` | Parsed data (TachoResult.to_dict()) |

### Method: `parse()`

```python
def parse(self) -> dict
```

Parses the `.ddd` file and returns the complete result dictionary.

**Returns:** `dict` — A `TachoResult.to_dict()` with all parsed fields.

**Pipeline phases (named methods, in order):**

1. `_open_file()` — memory-maps the file and detects VU vs card (first byte `0x76` = VU)
2. `_run_structural_parse()` — `DeterministicParser.parse()`: STAP/BER-TLV or VU stream walk with full byte coverage
3. `_decode_vu_semantics()` — VU only: G2/G2.2 RecordArray dispatch + ECDSA download verification, or G1 TREP walk (heuristic fallback if invalid)
4. `_dedup_and_sort_activities()` — drops duplicate daily blocks, sorts newest-first
5. `_validate_certificate_chain()` — ERCA → MSCA → Card/VU chain via `SignatureValidator`
6. `_verify_ef_signatures()` — per-EF data integrity against the card public key
7. `build_generations_tree()` — hierarchical per-generation view

### Method: `get_coverage_report()`

```python
def get_coverage_report(self) -> float
```

Returns the percentage of bytes assigned to identified fields.

**Returns:** `float` — Coverage percentage (0.0–100.0), rounded to 2 decimal places.

### Properties and Detection Logic

**Generation detection** (`DeterministicParser._detect_generation()`): reads the first 2 bytes:
- `b'\x76\x31'` → `"G2.2 (Smart V2)"`
- `b'\x76\x21'` or `b'\x76\x22'` → `"G2 (Smart)"`
- Otherwise → `"G1 (Digital)"` (card files are refined after parsing via `_refine_card_generation()`)

**VU detection**: First byte == `0x76` → `is_vu = True`.

## Usage Example

```python
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

## See Also

- [TachoResult](models.md) — Data structure returned by parse()
- [DeterministicParser](deterministic_parser.md) — Structural parser
- [ExportManager](export_manager.md) — Export results to Excel/CSV/PDF

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
    print(f"Date: {day['date']}, Changes: {len(day.get('changes', []))}")
```

### Run coverage audit

```python
parser = TachoParser("my_tacho.ddd")
data = parser.parse()
coverage = data["metadata"]["coverage_pct"]
print(f"Byte coverage: {coverage}%")
```
