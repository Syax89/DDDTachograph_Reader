# How to Add a New Decoder

This guide walks through adding support for a new tachograph tag, from spec research to test validation.

## Step 1: Identify the Tag in Specifications

Locate the tag in one of:
- `specs/g1_complete_structures.md` — G1 tags (Annex 1B)
- `specs/g2_g22_complete_structures.md` — G2/G2.2 tags (Annex 1C)
- `specs/tachograph.asn` — Formal ASN.1 schema
- The relevant EU regulation: Annex 1B (Reg. 3821/85), Annex 1C (Reg. EU 2016/799), Reg. EU 2023/980 (G2.2)

Determine:
- **Tag ID** (hex integer, e.g., `0x0534` for a hypothetical new G2.2 tag)
- **Record structure**: field names, byte offsets, data types
- **Container or leaf**: does it contain recursive sub-structures?
- **Generation**: G1, G2, or G2.2
- **Card-only, VU-only, or both**
- **Annex reference** (e.g., "Annex 1C §2.80")

## Step 2: Implement the Decoder Function

Decide where to place the decoder based on generation and card/VU scope:

| Scope | File |
|---|---|
| G1/G2 card EF data | `core/card_decoders.py` |
| G2/G2.2 VU RecordArray records | `core/g2_decoders.py` |
| G2.2 card GNSS/Load/Trailer | `core/g22_card_decoders.py` |
| Certificates / public keys | `core/cert_decoders.py` |
| VU overview / TREP walkers | `core/vu_trep_decoders.py` |
| Shared low-level helpers | `core/decode_primitives.py` |

Add the new function to the re-export list in `core/decoders.py` (the facade through which the registry and all other modules import decoders).

### Decoder Function Signature

There are two signatures depending on how the decoder is dispatched:

**Standard signature** (most decoders):
```python
def parse_new_tag(data: bytes, results: dict) -> None:
    """Decode NewTag (Annex 1C §X.Y).

    Structure:
      field1 (N bytes): description
      field2 (M bytes): description
    Total: N+M bytes
    """
    # Populate results dict
    results["new_tag_field"] = value
```

**Tag-aware signature** (for decoders dispatched with a tag parameter, used by G2.2 certificate subtags and G2 VU records):
```python
def parse_new_tag(data: bytes, results: dict, tag: int) -> None:
    """Decode NewTag (Annex 1C §X.Y)."""
    results.setdefault("some_list", []).append({...})
```

### Helper Utilities (from `core/decode_primitives.py`)

| Function | Purpose |
|---|---|
| `get_nation(code)` | Map numeric nation code to ISO code |
| `decode_string(data, is_id=False)` | Decode binary string, handling CodePage byte |
| `decode_date(data, prefer_datef=False)` | Decode TimeReal (4B unix) or Datef (4B BCD) |

### Example: Hypothetical `VuVehicleAuthorizationRecord` (0x0534)

```python
# In core/g2_decoders.py

def parse_g22_vehicle_authorization(data: bytes, offset: int = 0):
    """Decode a G2.2 VuVehicleAuthorizationRecord (tag 0x0534).

    Structure:
      authorizationType (1 byte): 0=none, 1=standard, 2=extended
      authorizationNumber (8 bytes): ASCII
      validFrom (4 bytes): timeReal
      validUntil (4 bytes): timeReal
      issuingMemberState (1 byte): nation code
    Total: 18 bytes
    """
    if offset + 18 > len(data):
        return None
    rec = data[offset:]

    auth_type = rec[0]
    auth_number = rec[1:9].decode('latin-1', errors='ignore').strip('\x00').strip()
    valid_from_ts = struct.unpack(">I", rec[9:13])[0]
    valid_until_ts = struct.unpack(">I", rec[13:17])[0]
    nation_byte = rec[17]

    from .decoders import get_nation
    from datetime import datetime, timezone

    valid_from = datetime.fromtimestamp(valid_from_ts, tz=timezone.utc).isoformat() \
        if 946684800 <= valid_from_ts <= 4102444800 else "N/A"
    valid_until = datetime.fromtimestamp(valid_until_ts, tz=timezone.utc).isoformat() \
        if 946684800 <= valid_until_ts <= 4102444800 else "N/A"

    return {
        "authorization_type": auth_type,
        "authorization_number": auth_number,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "issuing_member_state": get_nation(nation_byte),
    }
```

## Step 3: Register in DecoderRegistry

Add a `TagDecoder` entry in `core/decoder_registry.py`, inside the `_build()` method (within the `definitions` list):

```python
TagDecoder(0x0534, "VuVehicleAuthorizationRecord",
           decoders.parse_g22_vehicle_authorization,  # or g2_decoders.
           annex_ref="Reg. EU 2023/980", generation="G2.2",
           vu_only=True, record_size=18),
```

Key fields:
- `container=True` if the tag contains recursive sub-structures
- `record_size=N` for fixed-size records (enables RecordArray slicing)
- `signature_block=True` if the payload is a certificate
- `priority=N` for dispatch ordering (higher = sooner)

### Import the decoder

If the decoder lives in `core/g2_decoders.py`, make sure to import it at the top of the `_build()` method:

```python
from . import g2_decoders

# Then reference as g2_decoders.parse_g22_vehicle_authorization
```

## Step 4: Add Dispatch in TagNavigator.record_and_dispatch()

Add a dispatch entry in `core/tag_navigator.py`, in the `record_and_dispatch()` method (around lines 294-346 where other G2.2 dispatchers live):

```python
elif tag == 0x0534:
    decoders.parse_g22_vehicle_authorization(val, self.parser.results)
```

If the tag is a container, also add it to the `CONTAINER_TAGS` set in `dispatch_container_if_needed()` (line 525):

```python
CONTAINER_TAGS = {
    # ... existing entries ...
    0x0534,  # Add here if container
}
```

### In DeterministicParser

The `DeterministicParser._dispatch_decoder()` method (`core/deterministic_parser.py:351`) automatically dispatches via `DecoderRegistry.get_decoder(tag).decoder_fn()`, so no manual dispatch entry is needed for the deterministic path — as long as the decoder is registered in `DecoderRegistry` with a valid `decoder_fn`.

If the decoder uses the 3-argument signature `(data, results, tag)`, add it to the tag-aware dispatch list in `_dispatch_decoder()`:

```python
elif tag == 0x0534:
    dec.decoder_fn(payload, self.results, tag)
```

## Step 5: Add Tests

Create test cases in `tests/`:

```python
# In tests/test_new_decoder.py or append to an existing test file

def test_parse_vehicle_authorization():
    """Verify parsing of VuVehicleAuthorizationRecord."""
    import struct
    from datetime import datetime, timezone
    from core.g2_decoders import parse_g22_vehicle_authorization

    ts = int(datetime(2025, 6, 15, tzinfo=timezone.utc).timestamp())
    ts_end = int(datetime(2026, 6, 15, tzinfo=timezone.utc).timestamp())

    record = struct.pack(">B8sIIB",
        1,                          # authorizationType: standard
        b"AUTH1234",                # authorizationNumber (8 bytes)
        ts,                         # validFrom
        ts_end,                     # validUntil
        0x1A,                       # issuingMemberState: Italy
    )

    result = parse_g22_vehicle_authorization(record)

    assert result is not None
    assert result["authorization_type"] == 1
    assert result["authorization_number"] == "AUTH1234"
    assert result["issuing_member_state"] == "I"
    assert "2025-06-15" in result["valid_from"]
    assert "2026-06-15" in result["valid_until"]
```

Run the tests:

```bash
/usr/local/bin/python3.9 -m pytest tests/ -v -k test_parse_vehicle_authorization
```

## Step 6: Update Spec Documentation

Add the tag to the appropriate spec file:

1. **`specs/g2_g22_complete_structures.md`** — Add a new entry in the tag table with:
   - Tag ID, name, record size, fields, offsets, Annex reference, verification confidence level

2. **`specs/g22_verification_status.md`** — Add to the appropriate confidence section (HIGH/MEDIUM/LOW) based on how well the structure is confirmed by public specifications

## Step 7: Run Coverage Audit

Verify that the new decoder doesn't break existing coverage:

```bash
python3 specs/coverage_audit.py
```

All 8 DDD files in `DDD/` should maintain **100% byte coverage** (or very near it). If coverage drops, inspect the audit output for new unparsed ranges.

## Summary Checklist

- [ ] Tag identified in spec with byte-level structure
- [ ] Decoder function implemented with proper signature
- [ ] Registered in `DecoderRegistry` with annex_ref, generation, record_size
- [ ] Dispatch added in `TagNavigator.record_and_dispatch()` (and `_dispatch_decoder()` if needed)
- [ ] Container tag added to `CONTAINER_TAGS` if applicable
- [ ] Tests written and passing
- [ ] Spec documentation updated
- [ ] Coverage audit confirms no regression
