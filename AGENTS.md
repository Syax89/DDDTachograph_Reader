# AGENTS.md — DDD Tachograph Reader

## Project overview
Cross-platform (Windows/macOS/Linux) application for parsing, analyzing and visualizing data from digital tachograph files (`.ddd` format). Linux ships as an x86_64 Flatpak bundle (`flatpak/`, app ID `io.github.Syax89.TachoReader`). EU digital tachographs record driver activity, vehicle data, GNSS positions, and security certificate chains.

## Key architecture
- **Entry point**: `app/main.py` (CLI compatibility entry point) → `app/cli.py` / `app/engine.py` (TachoParser) → `core/parser/deterministic.py` (STAP/BER-TLV + VU stream walks, full byte coverage)
- **Decoders**: `core/decoders/` — type-split field decoders: `common.py` (shared helpers), `card_ef.py` (card EFs, multi-gen), `card_g22.py` (G2.2 card tags), `cert.py` (certificates), `vu_g1.py` (G1 VU stream), `vu_g2.py` (G2/G2.2 VU RecordArray dispatch); re-exported via the `__init__.py` facade
- **Parser engine**: `core/parser/` — deterministic.py, record_array.py, vu_dispatcher.py (RecordArray walker), g1_walker.py
- **Crypto**: `core/crypto/` — signature.py (root validator), vu_signature.py (ECDSA TREP + CVC chain), ef_signature.py (card data integrity)
- **Utils**: `core/utils/` — ber_tlv, coverage, encoding, constants, logger, version, report_format, event_codes, tag_defs
- **GUI**: `app/gui.py` — regedit-style tree + table/chart viewer, summary-first load, PDF/Excel/CSV/JSON export
- **Localization**: `app/i18n.py` (34 languages, per-user `settings.json`, `scripts/compile_translations.py`) and `app/ui_text.py` (the single display-text layer: `label()` for chrome, `data_text()` for values decoded from the file, gated by the *Translate file contents* preference). Exports stay English; `locale/<code>/LC_MESSAGES/tacho.po|.mo` holds one catalog per language.
- **Presentation**: `app/theme.py` is the only palette/font source the GUI paints with — `app/gui.py` carries no colour literal.
- **Icons**: `app/icons.py` — the only way the UI asks for an image: `icon(name, size, master)` decodes `assets/icons/png/<size>/<name>.png` (16 px tree rows and inline markers, 20 px toolbar), caches it per Tk interpreter so Tkinter cannot garbage-collect it into a blank row, and returns `None` for a missing file. The emoji the UI used before were drawn by whatever font the OS picked; nothing in `app/gui.py`/`app/cli.py` may carry one again (`tests/unit/test_gui_icons.py`). `assets/icons/README.md` is the designer's note, `assets/icons/svg/` the editable masters (Tk cannot read them; only `png/` is bundled by `build.spec`).
- **CLI**: `app/cli.py` — full-featured CLI; `app/main.py` — compatibility entry point
- **Export**: `app/export.py` — multi-sheet Excel (typed cells, Summary index, Daily/Monthly split, 50 000-row report cap) + CSV (semicolon, UTF-8 BOM, section blocks) + PDF (cover, Technical Appendix, 1 500-row cap per section); JSON is the complete parsed structure written by the callers

## Running tests
```bash
python3 -m pytest tests/ -v
```
Requires: `pip install -r requirements.txt` (pytest, pyinstaller, cryptography, openpyxl, reportlab, tkinterdnd2 — the last one optional, it only adds drag & drop).

Run the app as a module from the repository root (`python -m app.gui`, `python -m app.cli`): invoking `app/gui.py` or `app/cli.py` by path fails, because the package root is then not on the import path.

Tests use `tests/unit/conftest.py`, which resets the DecoderRegistry singleton between tests.

## CI and releases
`.github/workflows/build.yml` builds Windows, macOS and Linux Flatpak on every branch push, PR and manual run (plus `--version`/`--smoke` smoke tests and, on Linux, an installed-Flatpak + Xvfb GUI smoke); the `All platforms verified` job fails unless all three succeeded. `.github/workflows/test.yml` is the separate lint/mypy, translation-catalog check, 3.10/3.12/3.13 pytest and semantic-coverage gate — it is not part of that platform gate. `.github/workflows/release.yml` runs on `v*` tags only (tag must match `core/utils/version.py`), and a single publisher publishes after all three platform packages exist. Details: `docs/developer/testing.md`.

## Spec documentation
All tag specifications are in `scripts/`:
- `g1_complete_structures.md` — G1 tags, record sizes, field offsets, verification status
- `g2_g22_complete_structures.md` — G2/G2.2 tags with Annex 1C references
- `g22_verification_status.md` — G2.2 tag verification status (HIGH/MEDIUM/LOW confidence)
- `tachograph.asn` — Formal ASN.1 schema
- `coverage_audit.py` — Run with `python3 scripts/coverage_audit.py` for file-by-file coverage report
- `semantic_coverage_audit.py` — Semantic coverage audit (unparsed bytes per file)

## Key regulations
- Reg. 3821/85 Annex 1B — G1 tachograph spec
- Reg. EU 2016/799 Annex 1C — G2 smart tachograph spec
- Reg. EU 2023/980 — G2.2 smart tacho V2
- Reg. EU 2021/1228 — G2.2 additional specs

## Coverage guarantee
Every tracked `.ddd` sample in `DDD/` is parsed with full byte coverage. `DeterministicParser._classify_gaps()` sweeps any bytes missed by the structural walk, classifying them as padding or tracked unknown ranges. Shared interval merging via `core/coverage_utils.merge_intervals()`. Coverage audit: `python3 scripts/coverage_audit.py`.
