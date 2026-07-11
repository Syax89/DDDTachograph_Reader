# DeterministicParser

Deterministic parser that guarantees 100% byte coverage through a schema-driven two-pass architecture. The default parser since TachoParser v5.1.

**File:** `core/parser/deterministic.py`

---

## Class: `CoverageTracker`

```python
class CoverageTracker:
    """Tracks which byte ranges have been covered during parsing."""
```

### Constructor

```python
def __init__(self, total_size: int)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `total_size` | `int` | Total file size in bytes |

### Methods

| Method | Description |
|--------|-------------|
| `mark_covered(start, end)` | Records a byte range as covered |
| `mark_classified(start, end, classification)` | Records a range with a classification label (e.g., `"Tag_0520"`) |
| `mark_padding(start, end, fill_byte)` | Records a padding range with the fill byte value |
| `mark_unknown(start, end, data)` | Records bytes that could not be classified |
| `merge_ranges()` | Merges overlapping covered ranges |
| `get_coverage_pct()` | Returns total coverage percentage (0.0–100.0) |
| `get_uncovered_ranges()` | Returns list of `(start, end)` tuples for uncovered bytes |
| `get_section_report(file_size)` | Returns per-byte-range coverage breakdown |

**Internal state:**
- `covered_ranges` — List of `(start, end)` tuples
- `classifications` — Dict counting bytes per classification label
- `unknown_ranges` — List of `(start, end, data)` for unclassified bytes

---

## Class: `DeterministicParser`

```python
class DeterministicParser:
    """
    Two-pass architecture:
    1. Structural pass: parse every byte through known STAP/BER-TLV
    2. Semantic pass: validate record sizes, checksums, field ranges
    """
```

### Constructor

```python
def __init__(self, parser=None, registry: DecoderRegistry = None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `parser` | `TachoParser` or `None` | `None` | Reference to parent TachoParser for state sharing |
| `registry` | `DecoderRegistry` or `None` | `None` | Decoder registry; creates new default if None |

### Method: `parse()`

```python
def parse(self, raw_data: bytes, is_vu: bool) -> Dict[str, Any]
```

Main entry point. Executes the two-pass deterministic parse.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `raw_data` | `bytes` | Raw file contents (typically from mmap) |
| `is_vu` | `bool` | Whether the file is a vehicle unit download |

**Returns:** `Dict[str, Any]` — Complete parsed result (equivalent to `TachoResult().to_dict()`)

**Two-pass architecture:**

**Pass 1 — Structural:**
1. Creates a `CoverageTracker` for the file size
2. Initializes a fresh `TachoResult` dictionary
3. Detects generation from first 2 bytes
4. Sets top-level mode: `'stap'` for G1, `'ber'` for G2/G2.2
5. Iterates byte-by-byte through the file:
   - Skips padding blocks (0x00, 0xFF, 0x55)
   - Tries STAP (G1) or BER-TLV (G2/G2.2) header reading
   - On success: records the tag, dispatches its decoder, recurses into containers
   - On failure: marks 1 byte as unknown and advances
6. Collects unknown ranges into `raw_tags`

**Pass 2 — Semantic:**
- Record sizes, checksums, and field ranges are validated by individual decoders
- Coverage data is assembled into the `"coverage"` and `"sections"` keys

**Output structure:**
```python
{
    "metadata": {...},
    "driver": {...},
    "vehicle": {...},
    "activities": [...],
    # ... all TachoResult fields ...
    "raw_tags": {
        "Padding": [...],
        "Unparsed Data": [...],
        "0520_G1_Identification": [...],
        # ... etc ...
    },
    "coverage": {
        "total_bytes": 12345,
        "covered_pct": 100.0,
        "classifications": {
            "Tag_0520": 143,
            "Tag_0504": 8192,
            "Padding(0x00)": 512,
            # ...
        },
        "uncovered_ranges": []
    },
    "sections": {
        "Bytes [0x000000, 0x000100)": {"start": "0x000000", "end": "0x000100", "size": 256, "covered": 256, "coverage_pct": 100.0},
        "Bytes [0x000100, 0x00181C)": {...},
        # ... additional contiguous byte ranges ...
    }
}
```

`"sections"` is retained as the API container name. Its entries are neutral
display byte ranges, not inferred semantic file sections.

---

## Design Notes

The parser is **deterministic by construction**: it walks the file sequentially with known structures (STAP/BER-TLV for cards, RecordArray or SID/TREP streams for VU downloads) and every byte ends up classified — as a tag, padding, or an explicitly tracked unknown range. There is no heuristic recovery pass: anything that does not validate is surfaced as "Unparsed Data" rather than guessed. (The earlier heuristic recursive parser, `TagNavigator`, has been removed.)

---

## Usage Example

```python
# Default usage via TachoParser
from app.engine import TachoParser

parser = TachoParser("file.ddd")
data = parser.parse()

# Inspect deterministic coverage
cov = data["coverage"]
print(f"Total: {cov['total_bytes']} bytes, Covered: {cov['covered_pct']}%")
print(f"Classifications: {dict(cov['classifications'])}")

# Section-level breakdown
for section, info in data["sections"].items():
    print(f"{section}: {info['coverage_pct']}% ({info['covered']}/{info['size']})")
```

### Direct usage (standalone)

```python
from core.deterministic_parser import DeterministicParser

with open("file.ddd", "rb") as f:
    raw = f.read()

parser = DeterministicParser()
results = parser.parse(raw, is_vu=(raw[0] == 0x76))
print(results["metadata"]["generation"])
```


## See Also

- [TachoParser](tacho_parser.md) — Main parser that drives DeterministicParser
- [DecoderRegistry](decoder_registry.md) — Registry used for tag dispatch

## Common Tasks

### Check coverage of a file

```python
from app.engine import TachoParser

d = TachoParser("file.ddd").parse()
print(f"Coverage: {d['metadata']['coverage_pct']}%")
for start, end, size in d["coverage"]["uncovered_ranges"]:
    print(f"  Uncovered: {start} - {end} ({size} bytes)")
```

### Check classification breakdown

```python
parser = TachoParser("file.ddd")
data = parser.parse()
classes = data["coverage"]["classifications"]
for label, count in sorted(classes.items(), key=lambda x: -x[1]):
    print(f"  {label}: {count} bytes")
```

### Find uncovered byte ranges

```python
parser = TachoParser("file.ddd")
data = parser.parse()
for start, end, size in data["coverage"]["uncovered_ranges"]:
    print(f"Gap: {start}–{end} ({size} bytes)")
```
