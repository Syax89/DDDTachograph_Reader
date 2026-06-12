# Testing Guide

## Running Tests

All tests are run with:

```bash
python -m pytest tests/ -v
```

Run a specific test file:

```bash
python -m pytest tests/test_coverage.py -v
```

Run tests matching a pattern:

```bash
python -m pytest tests/ -v -k "test_parse"
```

Run with coverage:

```bash
pip install pytest-cov
python -m pytest tests/ -v --cov=core --cov=ddd_parser
```

## Test Categories

| File | Purpose |
|---|---|
| `tests/test_coverage.py` | Byte coverage verification against reference DDD files |
| `tests/test_deterministic_padding.py` | Padding classification in the deterministic parser |
| `tests/test_export.py` | Export format correctness (Excel, CSV, PDF) |
| `tests/test_fuzz.py` | Fuzzing with random/malformed byte sequences |
| `tests/test_gen22.py` | G2.2 specific tag decoders (GNSS, load/unload, border crossings) |
| `tests/test_golden_snapshot.py` | Golden-file snapshot comparison for real DDD samples |
| `tests/test_validation.py` | Certificate chain validation (ERCA/MSCA) |
| `tests/test_semantic_coverage.py` | Semantic field coverage (do decoders populate all expected fields) |
| `tests/test_real_semantic_coverage.py` | Real-file semantic coverage against DDD/ samples |
| `tests/test_g22_auth_and_triage.py` | G2.2 authentication data and unparsed pattern triage |
| `tests/test_vu_dispatcher.py` | VU RecordArray stream dispatcher |
| `tests/test_vu_signature.py` | VU download ECDSA/CVC signature verification |

Tests that require real `.ddd` samples (the private `DDD/` folder) skip automatically when those files are absent, so the suite passes on a fresh clone.

## Writing New Tests

### Conventions

- Use `pytest` fixtures and assertions
- Test files are prefixed `test_` and function names start with `test_`
- Import decoders directly from `core.decoders` or `core.g2_decoders`
- For full pipeline tests, instantiate `TachoParser` with a test file or mock byte data
- Use `tests/mock_data/` for static test fixtures
- Use `tests/generate_mock_ddd.py` to programmatically build DDD byte sequences

### Test Pattern: Direct Decoder Test

```python
import struct
from core.decoders import parse_g1_vehicles_used

def test_vehicles_used_parsing():
    # Build a minimal G1 VehiclesUsed record
    # Structure: odoStart(3B), odoEnd(3B), firstUse(4B timeReal),
    #            lastUse(4B timeReal), nation(1B), plate(14B string)
    import struct
    from datetime import datetime, timezone

    ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    record = struct.pack(">3B3BIIB14s",
        0, 0, 100,   # odoStart (3 bytes)
        0, 50, 0,    # odoEnd (3 bytes)
        ts,          # firstUse
        ts + 86400,  # lastUse
        0x1A,        # nation: Italy
        b"AB123CD       "  # plate (14 bytes)
    )

    results = {"vehicle_sessions": []}
    parse_g1_vehicles_used(record, results)

    assert len(results["vehicle_sessions"]) > 0
    ses = results["vehicle_sessions"][0]
    assert ses["registration_nation"] == "I"
```

### Test Pattern: Full Pipeline Test

```python
from ddd_parser import TachoParser
import tempfile, os

def test_full_parse_g1():
    from tests.generate_mock_ddd import generate_mock_g1_ddd

    with tempfile.NamedTemporaryFile(suffix='.ddd', delete=False) as f:
        data = generate_mock_g1_ddd()
        f.write(data)
        f.flush()
        path = f.name

    try:
        parser = TachoParser(path)
        results = parser.parse()
        assert results["metadata"]["integrity_check"] != "Error"
        assert results["metadata"]["coverage_pct"] >= 99.0
    finally:
        os.unlink(path)
```

## Mock DDD File Generation (`tests/generate_mock_ddd.py`)

The `generate_mock_ddd.py` script builds synthetic DDD files for all three generations:

```python
# Key helper functions
def stap(tag, dtype, data):
    """Encode STAP: 2B tag(BE) + 1B dtype + 2B len(BE) + data."""
    return struct.pack(">HBH", tag, dtype, len(data)) + data

def act_val(activity, minute):
    """2-byte activityChangeInfo: activity(2b) + minute(11b)."""
    return struct.pack(">H", (activity & 3) << 11 | (minute & 0x7FF))

def ts(y, m, d, h=0, mi=0):
    """Unix timestamp."""
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp())

def datef(y, m, d):
    """4-byte BCD date."""
    return bytes([((y//100)//10<<4)|((y//100)%10), ...])
```

Building blocks include: `build_ef_icc()`, `build_ef_ic()`, `build_driver_id()`, `build_vehicle_id()`, `make_cyclic()`, and generation-specific container builders.

## Fuzzing (`tests/test_fuzz.py`)

The fuzzing test generates random byte sequences to verify parser robustness:

- Tests with completely random bytes
- Tests with structurally valid headers but invalid/malformed payloads
- Tests with boundary conditions (empty files, truncated records, oversized lengths)
- Verifies the parser never crashes or raises unhandled exceptions

## Coverage Targets

- **Byte coverage**: 100% on the reference DDD files in `DDD/` (verified by `specs/coverage_audit.py`)
- **Semantic coverage**: Decoder functions should populate the expected TachoResult fields
- **Error path coverage**: Graceful handling of malformed input, truncated files, empty files

Run the coverage audit:

```bash
python3 specs/coverage_audit.py
```

This produces a per-file breakdown of:
- Total bytes, covered bytes, coverage percentage
- Unparsed blocks with hex snippets
- Pattern grouping of unparsed bytes

## Test Data

- **`DDD/`**: Real-world DDD files from various tachograph models (G1, G2, G2.2). **Not committed** — contains personal data; tests depending on it skip when absent.
- **`tests/mock_data/`**: Static binary test fixtures
- **`tests/generate_mock_data.py`**: Programmatic test data generation; mock certificates for signature validation are written to a temporary directory at test time
