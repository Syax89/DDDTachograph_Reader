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

Most GUI tests skip in the headless `test` job. On Python 3.12 a final leg installs
the `fonts-dejavu-core` family and re-runs the GUI modules under `xvfb-run`, so the
summary-fit sweep, the toolbar icons, the busy bar, the pane layout, the day-detail
keyboard paths and the integrity badge are exercised with a real display. The font
step is `continue-on-error`: a missing family is reported by the fit sweep itself
rather than by an unrelated apt failure.

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
| `tests/unit/test_export_excel_layout.py` | Workbook sheets, typed cells, protected identifiers, row-limit disclosure |
| `tests/unit/test_export_pdf_layout.py` | PDF cover, appendix, wide-record cards and the row cap |
| `tests/unit/test_i18n.py` | Translator, settings, PO/MO tooling and the language menu |
| `tests/unit/test_ui_text.py` | The display-text layer (`label()` / `data_text()`) and the translate-data preference |
| `tests/unit/test_gui_layout.py` | Pane widths, autohiding scrollbars, summary block order |
| `tests/unit/test_gui_summary_default.py` | The summary panel a file opens on, measured in DejaVu Sans |
| `tests/unit/test_gui_icons.py`, `test_gui_icon_scale.py` | Icon set lookups, the display-scale mapping and the no-emoji rule |
| `tests/unit/test_gui_accessibility.py` | Keyboard paths, contrast, monospace day log, elided verdict |
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
- Import decoders from `core.decoders` (the facade re-exporting every decoder module)
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


## Running every gate locally (mock data first)

`tests/mock_data/` is generated from `tests/integration/generate_mock_ddd.py` and is
git-ignored: a gate run without it silently *skips* every mock-dependent test (about 65
tests), which is how a GUI regression once reached CI while the local run looked green.
`scripts/run_gates.sh` therefore generates the mocks first and then runs, printing every
real exit: headless pytest, `xvfb-run` pytest, ruff, mypy, the translation-catalog
check, the corpus semantic-coverage audit, the **mock** semantic-coverage audit in the
CI form (`--ddd-dir tests/mock_data --baseline scripts/mock_semantic_baseline.json`),
and `git diff --check`.

Expected skip counts with the mocks present: 315 headless (Tk tests need a display and
run under xvfb) and 2 under xvfb (the git-ignored corpus semantic baseline and the
missing golden snapshots for the private fixtures). A skipped *mock* test is a defect.

### The tree column fit is O(distinct characters), not O(nodes)

`_fit_tree_column` (in `app/gui.py`) must equal the old per-node algorithm exactly while
measuring a handful of labels: `tests/unit/test_gui_tree_fit_perf.py` keeps the old
implementation verbatim as the reference and compares pixel widths on the mocks, five
scripts, a 5000-day tree and the real files; a 5000-node tree must need ≤ 200 `measure`
calls. If you change how the tree is populated, update
`tests/unit/tree_snapshot_mocks.json` (mocks only — never commit a real file's labels).

### Stall report (always on, no env var)

An in-memory ring (`load_trace._ring`, `maxlen` 400) records every trace event whether or not
`DDD_TRACE_LOAD` is set, and a watchdog thread (`load_trace._watch`, started by the first
event — `header()` at window construction —, one sample every 0.5 s via
`sys._current_frames()`) watches the main thread in every session. A main-thread stack that
stays identical for 7 samples (6 intervals = 3 s) writes, **once per process**:

* `~/ddd-reader-stall-report.txt` — UTF-8, mode `0o600`, overwritten: a `# platform=` /
  `# python=` / `# frozen=` / `# tk=` header, the `stall` line (frozen seconds, and the
  `module.function:line` stack), then the ring oldest-first. The path is printed to stderr.
* the same `stall` line continues to go to `~/ddd-reader-load-trace.txt` when
  `DDD_TRACE_LOAD=1`.

Two waits are **not** stalls, because a user experiences them as normal use:
tkinter's own loop (innermost frame `mainloop` in a file ending `tkinter/__init__.py`) and
the native file picker (`commondialog.show` anywhere up the stack). A normal session writes
no report file at all.

Privacy: the report never carries a file name, a directory, a card number, a plate, a VIN, a
driver name or dialog text. The ring lines are the same `key=value` fields the load trace
already restricts to extension/size/generation/counts, and `load_trace.dialog()` writes a
dialog title only when it is one of three fixed msgids (`title=other` otherwise).

A sampler belongs to the module generation that started it (`load_trace._GEN`): a reload —
tests only — retires the previous samplers, so two samplers never report side by side.
`load_trace.STALL_REPORT` switches the *file* off; `tests/conftest.py` does that for the
whole suite (a slow test is not a user-facing stall, and no test may write to the real home
directory), and `tests/unit/test_stall_report.py` turns it back on against a temporary
`HOME`. `tests/test_load_trace_watchdog.py` covers the live file.

#### The sampler does not run under pytest (`load_trace.WATCHDOG`)

An earlier revision kept the sampler running in the test suite too. A full
`xvfb-run -a .venv/bin/python -X faulthandler -m pytest tests -q` then aborted after eleven
tests with `Fatal Python error: Aborted` (exit 134). Faulthandler named the thread:

```
Current thread 0x00007f8786eff6c0 (most recent call first):
  Garbage-collecting
  File ".../core/utils/load_trace.py", line 195 in _watch
  File "/usr/lib/python3.13/threading.py", line 994 in run
```

— the sampler, **inside a garbage-collection pass**, i.e. exactly the
`Tcl_AsyncDelete: async handler deleted by the wrong thread` abort: a pass runs on whichever
thread trips the threshold, the suite creates and drops Tk roots in a loop, and a Tk object
(`PhotoImage`/`Variable`/interpreter `__del__`) finalized on the sampler's thread calls Tcl
from a thread that does not own the interpreter. The crash above happened **with** a
`gc.disable()`-while-allocating guard in place, because the allocation that *enters* the
guard is itself enough to trip the collection: the guard was racy by construction, so it was
removed (`app/gui.py:_gc_pause` is untouched again), rather than kept on a hypothesis.

The remedy is the one that matches the cause: `load_trace.WATCHDOG` is
`"pytest" not in sys.modules`, so the app (and a frozen build) always samples while a test
session never does. A test that needs a sampler asks for it — `load_trace.WATCHDOG = True`
(what `tests/test_load_trace_watchdog.py` does after its `importlib.reload`) or by starting
`load_trace._watch` in a thread (what `tests/unit/test_stall_report.py` does). Support can
force either way with `DDD_STALL_WATCHDOG=0|1` (`load_trace.sampler_allowed()`). The ring
buffer keeps recording under pytest, so a test can still assert what was traced.

The sampled read itself is defensive: `sys._current_frames()` is fetched inside a
`try/except` and a missing frame simply counts as idle, so a failing sample can never take
the app down. Residue worth knowing: any thread can still be the one that collects (the
parse worker allocates megabytes), which is pre-existing and not something the sampler
introduced.

### Event pumping on macOS

Symptom: on Aqua (Tk 8.6.13, frozen) one `self.update()` in `_pump_render` — reached from
`_parse_done` — blocked 17–20 s inside Tk, always after the native file picker had closed
(a third open), with no frame of ours on the stack. Hypothesis (unproven): `update()` enters
a native event-tracking wait and returns only on the next event. The fix therefore does not
depend on *why* Tk waits: on macOS a file open processes **no events at all**.

* `_PUMP_USES_EVENTS` (`app/gui.py:156`, `sys.platform != "darwin"`, monkeypatchable;
  `DDD_PUMP_MODE=events|idle` overrides it for support) picks the mode.
* In the idle mode `_pump_render` calls `update_idletasks()` instead of `update()`, and
  steps the indeterminate busy bar by hand, because Tk timers need events: one step per
  12 ms of wall time since the previous pump (`ttk::progressbar::start 12` = `step 1`
  every 12 ms), capped at 8 steps per pump. `progress.start(12)`, the adaptive throttle,
  `force=True`, `_RenderAbandoned` and the swallowed widget-less-double failure are
  unchanged. Linux and Windows keep the old `update()` path.
* `_open_file` (`app/gui.py:4296`) no longer starts the parse inside the picker's call
  stack: it schedules `_start_parse(path)` with `self.after(150, ...)`, so the *real*
  mainloop handles the panel's teardown first. `_open_pending` is set across the picker and
  the 150 ms, so a second click on Open starts neither a second picker nor a second parse
  (`_start_parse` refuses again while `_parsing`/`_rendering`). The `askopenfilename`
  arguments are untouched. Drop and recent-files clicks do not come out of a native panel
  and still start directly.

Audit — every event-pumping call in `app/` (`grep -n "\.update()\|wait_window\|
wait_visibility\|mainloop(" app/*.py`; there is no `wait_window`, no `wait_visibility` and
no nested `mainloop`, in `app/`, `core/` or `app/export.py`):

| Where | What for | Can it run during/after an open? |
| --- | --- | --- |
| `app/gui.py:4440` `_pump_render` `self.update()` | keeps the window and the busy bar alive while a render holds the main thread | **yes — this was the 17–20 s stall.** Idle mode calls `update_idletasks()` (`:4447`) and steps the bar by hand |
| `app/gui.py:1046` `DataTable.show` `_flush(self.tv)` (was `self.tv.update()`) | settle the geometry before `_sync_xscroll` | yes: it runs from `<<TreeviewSelect>>`, i.e. right after a render. Layout needs idle tasks only, so `_flush` (`:164`) = `update_idletasks()` on macOS |
| `app/gui.py:6075` `_show_dashboard` `_flush(self.table.tv)` (was `tv.update()`) | same, for the dashboard table | yes, same path (the auto-selected node can be a dashboard) |
| `app/gui.py:3476` `__init__` (Windows title bar), `:4535` / `:4612` (busy bar before an export worker), `:5253` / `:7128` (tooltips), `:1044`, `:6073`, `:7074` (`tv.update_idletasks()`) | `update_idletasks()` only | no events are processed, so they cannot enter a native wait: left as they are |
| `app/gui.py:7763` `app.mainloop()` in `main` | the one real loop | not nested: the language switch returns from it and builds a new window |
| `app/gui.py:4317` `after(150, …)`, `:4719` `after_idle(selection_set)`, `:4350` `after(50, _poll_parse_queue)` | deferred callbacks | run by the real loop, never by a pump |

Rules for new code: nothing reachable from `_open_file`, `_parse_done`, `_on_tree_select`
or `_show_dashboard` may call `update()` — use `_flush()`/`update_idletasks()` — and no
parse may be started from inside a native panel's call stack (use `after`).

Note on the comment in `_parse_done` ("Rendering's table sizing update() pumps the loop"):
the call it means is the `_flush` row above, which is idle-only on macOS now.

### Load trace for a slow open (`DDD_TRACE_LOAD=1`)

Live file is opt-in (the in-memory ring and the stall report above are always on): `DDD_TRACE_LOAD=1` appends per-stage timings to `~/ddd-reader-load-trace.txt` (extension, size, generation and counts only — never contents, names or the file's directory). On macOS run `DDD_TRACE_LOAD=1 /Applications/<app>/Contents/MacOS/<binary>` from Terminal (or `open --env DDD_TRACE_LOAD=1 /Applications/<app>.app`), open two files in a row and send back `~/ddd-reader-load-trace.txt`; the lines say `open number=N`, the tree delete of the previous file and the render-pump totals. Code: `core/utils/load_trace.py`, test: `tests/unit/test_load_trace.py`.
