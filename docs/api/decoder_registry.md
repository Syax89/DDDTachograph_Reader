# DecoderRegistry

Centralized decoder registry with tag → decoder mapping, priorities, and validation rules. The single source of truth for all known tag definitions in a schema-driven architecture.

**File:** `core/decoder_registry.py`

---

## Class: `TagDecoder`

```python
@dataclass
class TagDecoder:
    tag: int
    name: str
    decoder_fn: Optional[Callable] = None
    container: bool = False
    min_length: int = 0
    max_length: int = 0x100000
    record_size: Optional[int] = None
    annex_ref: str = ""
    generation: str = "all"
    card_only: bool = False
    vu_only: bool = False
    signature_block: bool = False
    priority: int = 0
```

| Field | Type | Description |
|-------|------|-------------|
| `tag` | `int` | Tag identifier (e.g., `0x0520`) |
| `name` | `str` | Human-readable name (e.g., `"G1_Identification"`) |
| `decoder_fn` | `Optional[Callable]` | Function to decode this tag's payload |
| `container` | `bool` | Whether the tag contains nested sub-tags |
| `min_length` | `int` | Minimum expected payload length (0 = no minimum) |
| `max_length` | `int` | Maximum allowed payload length |
| `record_size` | `Optional[int]` | Fixed record size for multi-record arrays |
| `annex_ref` | `str` | EU regulation reference (e.g., `"Annex 1B §2.15"`) |
| `generation` | `str` | `"G1"`, `"G2"`, `"G2.2"`, or `"all"` |
| `card_only` | `bool` | Only applies to driver card data |
| `vu_only` | `bool` | Only applies to vehicle unit data |
| `signature_block` | `bool` | Contains cryptographic signature data |
| `priority` | `int` | Dispatch priority (higher = preferred) |

---

## Class: `DecoderRegistry`

```python
class DecoderRegistry:
    """Central registry of all known tag decoders with spec references."""
```

### Constructor

```python
def __init__(self)
```

Builds the full registry of ~80+ tag decoders via `_build()`. Each decoder is registered by tag ID and classified as container/signature as appropriate.

**Registered tag categories** (from `core/decoder_registry.py:40-471`):

| Category | Tag Range | Count | Description |
|----------|-----------|-------|-------------|
| G1 & G2 Common | 0x0001–0x0005, 0x0100–0x0102, 0x0201, 0x2020 | ~10 | VU/Card identification shared across generations |
| G1 Card Data | 0x0501–0x0508, 0x050C–0x050E, 0x0520–0x0524 | ~18 | Card-specific data (activities, events, faults, etc.) |
| G2 VU Records | 0x0509–0x0512 | ~4 | Vehicle unit record arrays |
| G2.2 GNSS/Load/Trailer | 0x0525–0x052A, 0x0225–0x0228 | ~10 | G2.2 specific data types |
| G2.2 VU Records | 0x052B–0x0533 | ~9 | G2.2 vehicle unit records |
| G1 VU Containers | 0x7601–0x7605 | ~5 | G1 vehicle unit data containers |
| G2 VU Containers | 0x7621–0x7624, 0x7D21, 0xAD21 | ~6 | G2 vehicle unit data containers |
| G2.2 Containers | 0x7631–0x7634, 0x7F21, 0x7F4E | ~6 | G2.2 vehicle unit containers |
| Certificate Tags | 0xC100–0xC102, 0xC108–0xC10A, 0x0103–0x0104 | ~8 | Card/MSCA/ERCA certificate blocks |
| Certificate Sub-tags | 0x42, 0x4208, 0x5F20, 0x5F24, 0x5F25, 0x5F29, 0x5F37, 0x5F4C, 0x7F49, 0x960F, 0x6399 | ~12 | BER-TLV certificate internals |

---

### Method: `get_decoder(tag)`

```python
def get_decoder(self, tag: int) -> Optional[TagDecoder]
```

Look up a decoder by tag ID.

**Parameters:**
- `tag` — Integer tag identifier

**Returns:** `TagDecoder` if found, `None` otherwise.

```python
reg = DecoderRegistry()
dec = reg.get_decoder(0x0520)
print(dec.name)         # "G1_Identification"
print(dec.annex_ref)    # "Annex 1B §2.15+§2.17"
print(dec.generation)   # "G1"
print(dec.card_only)    # True
```

---

### Method: `is_container(tag)`

```python
def is_container(self, tag: int) -> bool
```

Checks if a tag is known to contain nested sub-tags.

**Returns:** `True` if the tag is registered as a container OR matches the `0x7600` mask.

```python
reg = DecoderRegistry()
reg.is_container(0x7622)   # True  — G2_VU_Activities
reg.is_container(0x0526)   # True  — G22_LoadUnloadOperations
reg.is_container(0x0520)   # False — G1_Identification (leaf)
reg.is_container(0x7601)   # True  — matches 0x7600 mask
```

---

### Method: `is_signature(tag)`

```python
def is_signature(self, tag: int) -> bool
```

Checks if a tag is a signature/certificate block.

```python
reg = DecoderRegistry()
reg.is_signature(0xC100)   # True
reg.is_signature(0xC109)   # True
reg.is_signature(0x0520)   # False
```

---

### Method: `get_by_generation(gen)`

```python
def get_by_generation(self, generation: str) -> List[TagDecoder]
```

Returns all decoders for a specific generation. Includes decoders with `generation == "all"`.

**Parameters:**
- `generation` — `"G1"`, `"G2"`, or `"G2.2"`

```python
reg = DecoderRegistry()
g1_decs = reg.get_by_generation("G1")
g2_decs = reg.get_by_generation("G2")
g22_decs = reg.get_by_generation("G2.2")
print(f"G1: {len(g1_decs)}, G2: {len(g2_decs)}, G2.2: {len(g22_decs)}")
```

---

### Method: `get_all_tags()`

```python
def get_all_tags(self) -> List[int]
```

Returns all registered tag IDs in sorted order.

---

### Method: `get_unhandled_tags(seen_tags)`

```python
def get_unhandled_tags(self, seen_tags: set) -> List[TagDecoder]
```

Returns tag decoders in the registry that were not dispatched. Useful for coverage auditing.

---

### Method: `get_spec_ref(tag)`

```python
def get_spec_ref(self, tag: int) -> str
```

Returns the Annex reference string for a tag.

---

### Method: `get_containers()`

```python
def get_containers(self) -> List[TagDecoder]
```

Returns all registered container tag decoders.

---

### Method: `get_prioritized()`

```python
def get_prioritized(self) -> List[TagDecoder]
```

Returns all decoders sorted by priority descending, then by tag ascending.

---

### Magic Methods

```python
len(registry)      # Returns number of registered decoders
tag in registry    # Returns True if tag is registered
```

---

## Registering a New Decoder

To add a new tag decoder, add a `TagDecoder` entry to the `definitions` list in `_build()`:

```python
# Example: Adding a custom tag decoder
TagDecoder(
    0x9999,                          # Tag ID
    "CustomData",                    # Name
    my_custom_decoder_function,      # Decoder function
    annex_ref="Custom Spec §1.0",    # Specification reference
    generation="G2.2",               # Generation
    card_only=False,                 # Applicability
    vu_only=True,
    container=False,
    min_length=16,
    record_size=32
)
```

The decoder function signature must match one of these patterns:

```python
# Standard decoder (payload, results)
def my_decoder(payload: bytes, results: dict):
    results["my_field"] = parse_my_data(payload)

# Tag-aware decoder (payload, results, tag)
def my_decoder(payload: bytes, results: dict, tag: int):
    if tag == 0x0509:
        results["vu_card_record"] = parse_card(payload)
    elif tag == 0x050A:
        results["vu_iw_record"] = parse_iw(payload)
```

## Usage Example

```python
from core.decoder_registry import DecoderRegistry, TagDecoder

# Create registry (built on init)
reg = DecoderRegistry()

# Lookup
dec = reg.get_decoder(0x0525)
if dec:
    print(f"Tag: {dec.name}")
    print(f"Generation: {dec.generation}")
    print(f"Container: {dec.container}")
    print(f"Annex: {dec.annex_ref}")
    print(f"Has decoder: {dec.decoder_fn is not None}")

# Check properties
print(f"Total registered tags: {len(reg)}")
print(f"Containers: {len(reg.get_containers())}")
print(f"Signature tags: {sum(1 for t in reg.get_all_tags() if reg.is_signature(t))}")

# Generation filtering
g22_tags = reg.get_by_generation("G2.2")
for dec in g22_tags:
    print(f"{dec.tag:04X} {dec.name:40s} {dec.annex_ref}")

# Membership test
print(0x0520 in reg)  # True
print(0x9999 in reg)  # False

# All known tag IDs
all_ids = reg.get_all_tags()
print(f"Known tags: {len(all_ids)}")
```

## See Also

- [DeterministicParser](deterministic_parser.md) — Uses DecoderRegistry in its two-pass architecture
- [TachoParser](tacho_parser.md) — Main parser using the registry

## Common Tasks

### List all tags without decoders

```python
reg = DecoderRegistry()
for tag_id in reg.get_all_tags():
    dec = reg.get_decoder(tag_id)
    if dec and dec.decoder_fn is None:
        print(f"{tag_id:04X}: {dec.name} — container, no leaf decoder")
```

### Find all container tags

```python
reg = DecoderRegistry()
containers = reg.get_containers()
for c in containers:
    print(f"{c.tag:04X} {c.name:40s} gen={c.generation}")
```

### Check if a tag needs recursion

```python
reg = DecoderRegistry()
tag = 0x7622
if reg.is_container(tag):
    dec = reg.get_decoder(tag)
    print(f"Container: {dec.name}, must recurse into payload")
```
