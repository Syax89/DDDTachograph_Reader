# Testing Guide

## Running Tests

All tests are run with:

```bash
python -m pytest tests/ -v
```

Generate the synthetic fixtures first to run the mock coverage tests, as CI does:

```bash
python tests/integration/generate_mock_ddd.py
python -m pytest tests/ -v
```

Run a specific test file:

```bash
python -m pytest tests/unit/test_coverage.py -v
```

Run tests matching a pattern:

```bash
python -m pytest tests/ -v -k "test_parse"
```

Run with coverage:

```bash
pip install pytest-cov
python -m pytest tests/ -v --cov=app --cov=core
```

## CI, Builds and Releases

The workflows are the source of truth; this section summarises what they do.
Read the files themselves for step-level detail:

- [`build.yml`](../../.github/workflows/build.yml) — branch/PR/manual builds for Windows, macOS and Linux
- [`test.yml`](../../.github/workflows/test.yml) — lint, tests and the coverage gate
- [`release.yml`](../../.github/workflows/release.yml) — tagged release publication
- [`build-flatpak` action](../../.github/actions/build-flatpak/action.yml) — Linux packaging shared by `build.yml` and `release.yml`

### When CI runs

| Event | What runs |
|---|---|
| Local commit (`git commit`) | Nothing — no remote CI runs on a local commit |
| Push to any branch | `build.yml` + `test.yml` |
| Pull request (any base branch) | `build.yml` + `test.yml` |
| Manual run (*Run workflow*) | `build.yml` and/or `test.yml` |
| Push of a `v*` tag | `release.yml` only |

Tag pushes do not run the branch workflows: their `push` trigger lists branches
only, so `release.yml` owns lint, tests, builds and publication for a release
tag. Merging a pull request is just a branch push, so it re-runs both branch
workflows on the target branch.

### Branch builds (`build.yml`)

Each platform build freezes the app with `build.spec` and smoke-tests the result with
`--version` and `--smoke tests/mock_data/mock_g2_card.ddd`:

| Job | Runner | Verification |
|---|---|---|
| `build` (matrix) | `windows-latest`, `macos-latest` | frozen bundle starts natively (`TachoReader.exe` / `TachoReader.app`) and answers the version and parser smoke commands |
| `build-linux-flatpak` | `ubuntu-24.04` | frozen bundle packaged as a Flatpak, the exported `.flatpak` installed, version + parser smoke inside the sandbox, then a GUI smoke under Xvfb (real X11 window mapped, app terminates cleanly) |
| `all-platforms-verified` | `ubuntu-latest` | aggregate gate over the two jobs above |

The Windows/macOS matrix uses `fail-fast: false`, so one platform failing never
cancels the other. `all-platforms-verified` runs with `if: always()` and
`needs: [build, build-linux-flatpak]`, and fails unless both results are exactly
`success` — a failed, cancelled or skipped build never passes the gate.

That gate covers the platform builds only: the `test.yml` jobs are not in its
`needs`, so a green **All platforms verified** does not by itself mean lint,
tests or the coverage audit passed.

### Automated checks (`test.yml`)

| Job | What it checks |
|---|---|
| `lint` | `ruff check .` and `mypy .` on Python 3.12 |
| `test` (Python 3.10, 3.12, 3.13) | compiled translation catalogs still match their `.po` sources (`compile_translations.py --check`), then `pytest -q` |
| `coverage` | semantic coverage audit against the committed mock baseline, failing on regression |

### Build artifacts vs release assets

A branch, PR or manual run uploads ordinary GitHub Actions artifacts:

| Artifact | Contents |
|---|---|
| `TachoReader-windows-latest` | frozen `dist/TachoReader` folder with `TachoReader.exe` |
| `TachoReader-macos-latest` | the frozen `.app` bundle and build directory |
| `TachoReader-linux-x86_64` | the exported `TachoReader-linux-x86_64.flatpak` |

The Windows/macOS artifacts are raw build output, **not** the packaged zip/dmg
installers — that packaging only happens in `release.yml`. Find them under the
workflow run → **Artifacts** in the Actions tab. Extract the downloaded artifact
ZIP before using its contents; downloading may require a
GitHub login, and artifacts expire, so they are not a permanent download
channel. For installers use the Releases page.

### Releases (`release.yml`)

A `v*` tag runs, in order:

1. `check-version` — the tag without its leading `v` must equal `__version__` in
   [`core/utils/version.py`](../../core/utils/version.py).
2. `lint`, then `test` — Ruff, Mypy and pytest on Python 3.12. Unlike the branch
   test workflow, this path does not run the three-version matrix, a separate
   translation-catalog check or the semantic coverage audit.
3. `build-windows`, `build-macos`, `build-linux-flatpak` — each builds, smoke
   tests and packages its own artifact; none of them publishes.
4. `Publish release` — the only job with `contents: write`. It starts only after
   all three platform jobs succeeded, downloads the three artifacts as a set,
   verifies each exact file exists and is non-empty, and only then creates the
   GitHub release.

The three release assets are `TachoReader-<tag>-windows-x64.zip`,
`TachoReader-<tag>-macos.dmg` and `TachoReader-<tag>-linux-x86_64.flatpak`, with
release notes extracted from a matching `## [version]` section in `CHANGELOG.md`,
or a generic `Release <tag>` note when no matching section is found. The gate runs
before any upload, but the upload itself is a normal non-transactional API call:
these workflows do not make it atomic. They also do not configure branch
protection or required checks.

## Test Categories

| File | Purpose |
|---|---|
| `tests/unit/test_coverage.py` | Byte coverage verification against mock and private DDD files |
| `tests/unit/test_deterministic_padding.py` | Padding classification in the deterministic parser |
| `tests/unit/test_export.py` | Export format correctness (Excel, CSV, PDF) |
| `tests/integration/test_fuzz.py` | Fuzzing with random/malformed byte sequences |
| `tests/unit/test_gen22.py` | G2.2 specific tag decoders (GNSS, load/unload, border crossings) |
| `tests/test_golden_snapshot.py` | Golden-file snapshot comparison for real DDD samples |
| `tests/unit/test_validation.py` | Certificate chain validation (ERCA/MSCA) |
| `tests/integration/test_semantic_coverage.py` | Semantic field coverage (do decoders populate all expected fields) |
| `tests/integration/test_real_semantic_coverage.py` | Real-file semantic coverage against DDD/ samples |
| `tests/unit/test_g22_auth_and_triage.py` | G2.2 authentication data and unparsed pattern triage |
| `tests/integration/test_vu_dispatcher.py` | VU RecordArray stream dispatcher |
| `tests/integration/test_vu_signature.py` | VU download ECDSA/CVC signature verification |

Tests that require real `.ddd` samples (the private `DDD/` folder) skip automatically when those files are absent, so the suite passes on a fresh clone.

### Private Semantic Baseline

`tests/integration/test_real_semantic_coverage.py` also requires the local
`scripts/semantic_coverage_report.json` baseline for the same private corpus.
It is intentionally git-ignored because it contains private fixture filenames.
Regenerate it locally after intentionally accepting a semantic-coverage change:

```bash
python scripts/semantic_coverage_audit.py --output scripts/semantic_coverage_report.json
```

Without a versioned, non-private corpus, this regression baseline cannot run in
public CI and the real-file test skips when either prerequisite is unavailable.

## Writing New Tests

### Conventions

- Use `pytest` fixtures and assertions
- Test files are prefixed `test_` and function names start with `test_`
- Import decoders directly from `core.decoders` or `core.g2_decoders`
- For full pipeline tests, instantiate `TachoParser` with a test file or mock byte data
- Use `tests/mock_data/` for static test fixtures
- Use `tests/integration/generate_mock_ddd.py` to programmatically build DDD byte sequences

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
from app.engine import TachoParser
import tempfile, os

def test_full_parse_g1():
    from tests.integration.generate_mock_ddd import generate_g1_card

    with tempfile.NamedTemporaryFile(suffix='.ddd', delete=False) as f:
        generate_g1_card(f.name)
        path = f.name

    try:
        parser = TachoParser(path)
        results = parser.parse()
        assert results["metadata"]["integrity_check"] != "Error"
        assert results["metadata"]["coverage_pct"] >= 99.0
    finally:
        os.unlink(path)
```

## Mock DDD File Generation (`tests/integration/generate_mock_ddd.py`)

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

Building blocks include: `build_ef_icc()`, `build_ef_ic()`, `build_g1_id()`,
`build_g1_vehicles()`, `make_cyclic()`, and generation-specific container builders.

## Fuzzing (`tests/integration/test_fuzz.py`)

The fuzzing test generates random byte sequences to verify parser robustness:

- Tests with completely random bytes
- Tests with structurally valid headers but invalid/malformed payloads
- Tests with boundary conditions (empty files, truncated records, oversized lengths)
- Verifies the parser never crashes or raises unhandled exceptions

## Coverage Targets

- **Byte coverage**: 100% on the reference DDD files in `DDD/` (verified by `scripts/coverage_audit.py`)
- **Semantic coverage**: Decoder functions should populate the expected TachoResult fields
- **Error path coverage**: Graceful handling of malformed input, truncated files, empty files

Run the coverage audit:

```bash
python3 scripts/coverage_audit.py
```

This produces a per-file breakdown of:
- Total bytes, covered bytes, coverage percentage
- Unparsed blocks with hex snippets
- Pattern grouping of unparsed bytes

## Test Data

- **`DDD/`**: Real-world DDD files from various tachograph models (G1, G2, G2.2). **Not committed** — contains personal data; tests depending on it skip when absent.
- **`tests/mock_data/`**: Generated synthetic fixtures (run `python tests/integration/generate_mock_ddd.py`)
- **`tests/integration/generate_mock_data.py`**: Programmatic test data generation; mock certificates for signature validation are written to a temporary directory at test time
