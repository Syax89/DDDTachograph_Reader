# TagNavigator

Recursive STAP/BER-TLV tag navigator for DDD tachograph files. Handles multi-generation tag dispatch, container recursion, deep scan recovery, and coverage tracking.

**File:** `core/tag_navigator.py`

---

## Class: `TagNavigator`

```python
class TagNavigator:
    """Handles recursive navigation of STAP and BER-TLV structures."""
```

### Constructor

```python
def __init__(self, parser: TachoParser)
```

Takes a reference to the parent `TachoParser` instance. All state (results, tags, file data) is accessed through `self.parser`.

---

## Method: `parse_stap_recursive()`

```python
def parse_stap_recursive(self, start_pos: int, end_pos: int, depth: int = 0, parent_path: str = "", mode: str = 'stap')
```

The main recursive parser. Uses a hybrid approach that tries known formats (STAP or BER-TLV) at each position to maximize coverage.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `start_pos` | `int` | (required) | Start byte offset in the file |
| `end_pos` | `int` | (required) | End byte offset (exclusive) |
| `depth` | `int` | `0` | Recursion depth (max 12) |
| `parent_path` | `str` | `""` | Hierarchical path for raw_tags key |
| `mode` | `str` | `"stap"` | Parse mode: `"stap"` for G1 sequential or `"annex1c"` for BER-TLV sliding window |

**Behavior by mode:**

- **`depth == 0` or `mode == 'stap'`**: Strict sequential STAP block parsing. Reads 5-byte header (`>HBH` = tag + data_type + length), dispatches via `record_and_dispatch()`, then falls back to `_ber_scan_fallback()` for remaining bytes.

- **`mode == 'annex1c'`**: Sliding-window BER-TLV scanning. Tries to read BER-TLV headers, dispatches known tags, records gaps as unparsed. Handles multi-byte tags (bit 5 check for container detection).

**Implementation details** (`core/tag_navigator.py:38-110`):
- Skips repeating padding bytes (0x00, 0xFF, 0x55)
- Enforces max depth of 12 to prevent infinite recursion
- STAP header format: `struct.unpack(">HBH", hdr)` → (tag_id, data_type, length)
- Rejects sentinel tags 0x0000, 0xFFFF, 0x5555

---

## Method: `read_ber_tlv()`

```python
def read_ber_tlv(self, data: bytes, pos: int) -> Tuple[Optional[int], Optional[int], int]
```

Reads a BER-TLV header at the given position. Returns `(tag, length, header_size)` or `(None, None, 0)` on failure.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `data` | `bytes` | The raw file data |
| `pos` | `int` | Position to start reading at |

**Returns:** `Tuple[Optional[int], Optional[int], int]`
- `tag` — Parsed tag ID (may be multi-byte)
- `length` — Payload length in bytes
- `header_size` — Number of bytes consumed by the header

**BER-TLV encoding handled:**
- Single-byte tag (bits 1-5 ≠ 0x1F)
- Multi-byte tag (bit 5 = 1, continuation bit = 0x80)
- Short-form length (< 0x80)
- Long-form length (up to 3 length bytes)
- Rejects 0x00, 0xFF as invalid first bytes
- Rejects lengths > 0x100000 (1 MiB sanity limit)

---

## Method: `record_and_dispatch()`

```python
def record_and_dispatch(self, tag: int, length: int, val: bytes, pos: int, h_size: int, depth: int, parent_path: str, mode: str = 'stap', dtype: Optional[int] = None)
```

The central dispatch hub. Records the raw tag occurrence and invokes the appropriate decoder based on tag ID.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `tag` | `int` | Tag identifier |
| `length` | `int` | Payload length |
| `val` | `bytes` | The payload bytes |
| `pos` | `int` | Absolute byte offset in file |
| `h_size` | `int` | Header size (5 for STAP, variable for BER) |
| `depth` | `int` | Current recursion depth |
| `parent_path` | `str` | Hierarchical path prefix |
| `mode` | `str` | `"stap"` or `"annex1c"` |
| `dtype` | `int` or `None` | Data type byte (STAP only), `None` for BER |

**Dispatch logic** (`core/tag_navigator.py:206-353`):
1. **VU vehicle identification** (special offsets 420 and 442): Decodes VIN, nation, and plate at known positions
2. **Signature blocks** (dtype 1/3/11/15): Recorded but not decoded as leaf data; container recursion still invoked
3. **Card-only tags** (0x0002, 0x0005, 0x0520, 0x0501, 0x0521, 0x0508, 0x050E): Dispatched only when `not is_vu`
4. **VU-only tags** (0x0001): Dispatched only when `is_vu`
5. **Shared tags** (0x0101, 0x0102, 0x0201, 0x0502-0x050C, 0x0522-0x0524, etc.): Dispatched unconditionally
6. **G2 VU RecordArray tags** (0x0509-0x0512, 0x052B-0x0533): Routed to `parse_g2_vu_record()`
7. **G2.2 tags** (0x0525-0x052A, 0x0225-0x0228): Routed to dedicated G2.2 decoders
8. **Certificate sub-tags** (0x5F20, 0x5F24, 0x5F25, 0x5F29, 0x5F4C, 0x5F37, 0x7F49): CER/security decoding
9. **Heuristic detection** for G2 RecordArray in unknown large payloads (>5000 bytes) via `0x6864` magic bytes

---

## Method: `dispatch_container_if_needed()`

```python
def dispatch_container_if_needed(self, tag: int, length: int, val: bytes, pos: int, h_size: int, depth: int, parent_path: str, mode: str, dtype: Optional[int])
```

Determines if a tag is a container and recursively parses its inner data.

**Container detection rules** (`core/tag_navigator.py:524-573`):
1. **Explicit container set**: Tags 0x7621-0x7624, 0x7631-0x7634, 0x7601-0x7604, 0x7F21, 0x7D21, 0xAD21, 0x7F4E, 0x7F60, 0x7F61, plus G2.2 container tags (0x0525-0x052A, 0x0225-0x0228)
2. **0x7600 mask**: Any tag matching `(tag & 0xFF00) == 0x7600`
3. **BER-TLV bit 5**: In `annex1c` mode, multi-byte tags with first-byte bit 5 set
4. **No-recurse exceptions**: Tags 0x7F49, 0x5F37, 0x42, 0x4208 are excluded even if they match container patterns

**Container handling by type:**
- **G1 VU containers** (0x7601-0x7604): Parse G1 overview data via `parse_g1_vu_overview()`, then recurse with STAP mode
- **G2/G2.2 Activities** (0x7622, 0x7632): Detect G2 RecordArray format (`0x6864` magic), then recurse with annex1c mode
- **Other containers**: Recurse with annex1c mode (or stap if `mode == 'stap'`)

---

## Method: `deep_scan()`

```python
def deep_scan(self)
```

Final pass to find meaningful tags inside large unparsed blocks. Uses a sliding window to find any known tag ID in the raw data.

**Algorithm** (`core/tag_navigator.py:161-204`):
1. Identifies all `raw_tags` entries containing "Unparsed Data" with length > 10 bytes
2. For each unparsed block, scans byte-by-byte trying:
   - **STAP parsing**: Reads 5-byte header; checks tag ∈ known_tags, dtype validity, and length bounds
   - **BER-TLV parsing**: Reads BER header; checks tag ∈ known_tags and bounds
3. On match, recursively calls `parse_stap_recursive()` with `depth + 1` and a `DEEP_` path prefix

---

## Method: `record_unparsed()`

```python
def record_unparsed(self, start: int, end: int, depth: int, parent_path: str)
```

Records a byte range that could not be decoded. Classifies as "Padding" if contents are all the same byte (for ranges > 8 bytes), otherwise as "Unparsed Data".

---

## Method: `get_section_report()`

```python
def get_section_report(self) -> Dict[str, Any]
```

Generates a coverage report broken down by file sections: Header (0–256), Driver Data, Vehicle Data, Certificates, Signature/Tail. Returns per-section coverage percentages.

---

## Method: `parse_annex1c()`

```python
def parse_annex1c(self, start_pos: int, end_pos: int, depth: int, parent_path: str)
```

Redirects to `parse_stap_recursive()` with `mode='annex1c'`. Legacy compatibility wrapper.

---

## Usage Example

```python
# TagNavigator is instantiated automatically by TachoParser
from ddd_parser import TachoParser

parser = TachoParser("file.ddd", use_deterministic=False)
# parser.navigator is a TagNavigator instance

# After parse(), inspect coverage
data = parser.parse()

# Get section-level coverage
cov = parser.navigator.get_section_report()
for section, info in cov.items():
    print(f"{section}: {info['coverage_pct']}% ({info['covered']}/{info['size']} bytes)")

# Raw tags are populated with navigation path info
for key, occs in data["raw_tags"].items():
    print(f"{key}: {len(occs)} occurrences")
```

## See Also

- [TachoParser](tacho_parser.md) — Parent parser that owns the TagNavigator
- [DeterministicParser](deterministic_parser.md) — Alternative two-pass parser (default)
- [DecoderRegistry](decoder_registry.md) — Tag-to-decoder mapping used by dispatch

## Common Tasks

### Inspect raw tag structure

```python
parser = TachoParser("file.ddd", use_deterministic=False)
data = parser.parse()

for key, occs in data["raw_tags"].items():
    depth = occs[0].get("depth", 0) if occs else 0
    indent = "  " * depth
    total_len = sum(o["length"] for o in occs)
    print(f"{indent}{key}: {len(occs)}x, {total_len} bytes")
```

### Check tag dispatch correctness

```python
parser = TachoParser("file.ddd", use_deterministic=False)
data = parser.parse()

# Tags tracked at top level
top_level = {k.split(" > ")[-1] for k in data["raw_tags"]}
print(f"Top-level tags: {len(top_level)}")
```
