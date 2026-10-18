# Contributing to DDD Tachograph Reader

## Development Setup

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
```

## Project Structure
- `core/` — Parser engine (navigator, decoders, registry, models)
- `app/engine.py` — Main entry point
- `app/gui.py` — Desktop application (tkinter: tree view + Excel-style table)
- `tests/` — Test suite
- `scripts/` — Tag specifications and verification docs

## How to Add a New Decoder
1. Add the decoder function in the matching `core/decoders/` module (`card_ef.py`, `card_g22.py`, `cert.py`, `vu_g1.py`, `vu_g2.py`, or `common.py`) and re-export it from `core/decoders/__init__.py`
2. Register it in `core/registry/registry.py` with tag number, name, and metadata
3. Add dispatch in the relevant walker (`core/parser/deterministic.py`, `g1_walker.py`, or `vu_dispatcher.py`)
4. Add tests in `tests/`
5. Update spec documentation in `scripts/`

## UI Translations (gettext)

The GUI is translated with `gettext`. English is the source language: every
user-visible string is wrapped in `_("...")` in `app/gui.py`, and the English
text **is** the msgid, so a missing translation falls back to English instead of
leaving the UI empty.

Scope: English plus 24 EU languages, Norwegian, Icelandic, Russian, Ukrainian,
Belarusian, Turkish, Serbian, Bosnian, Albanian and Macedonian (34 in total).

### Adding or updating a language

1. Register the language in `app/i18n.py` (`LANGUAGES`, native name — the menu
   shows each language in its own script).
2. Add `locale/<code>/LC_MESSAGES/tacho.po`. It must translate every msgid the
   UI uses (singular messages only: no `msgctxt`, no `msgid_plural`), keep the
   `{placeholders}` and their format specs unchanged (`{percent:.2f}` stays
   `{percent:.2f}`), and leave no empty `msgstr`.
3. Compile and commit the binary catalog:

   ```bash
   python3 scripts/compile_translations.py          # writes tacho.mo next to each .po
   python3 scripts/compile_translations.py --check  # what CI runs
   ```

   `--check` fails when a `.mo` does not match its `.po`, when a language is
   missing a catalog, or when an entry is invalid. The compiled `.mo` files are
   what PyInstaller bundles.

### Translation rules

- Write plain strings, never f-strings: `_("Parsing {filename}…").format(...)`.
- UI chrome — menus, messages, section names, table headers, record field names —
  is translated. Section names and record keys go through `app/ui_text.label()`,
  which humanises the raw key and then translates it.
- Values *decoded from the file* (activity names, country names) go through
  `app/ui_text.data_text()`: they stay exactly as the decoder names them unless
  the user ticks **Translate file contents** in the Language menu.
- Never translate free text carried by the file (driver names, plates,
  addresses, company and workshop names), certificate/key data, file formats or
  parser diagnostics; exported reports stay English.
- Machine-assisted translations are welcome as a starting point, but a native
  speaker must review them before they are committed: a mistranslated activity
  label or warning is worse than English.

## Code Conventions
- Google-style docstrings on all public functions/classes
- Specific exception handling (no bare `except: pass`)
- 100% byte coverage on all test .ddd files
- Python 3.10+ compatibility

## Running Tests
```bash
python -m pytest tests/ -v
```

## Coverage Audit
```bash
python3 scripts/coverage_audit.py
```
