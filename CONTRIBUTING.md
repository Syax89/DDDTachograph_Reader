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
- `tests/` — Test suite (150+ tests)
- `scripts/` — Tag specifications and verification docs

## How to Add a New Decoder
1. Add decoder function in `core/decoders/__init__.py` or `core/decoders/g2_dispatch.py`
2. Register it in `core/registry/registry.py` with tag number, name, and metadata
3. Add dispatch in `core/tag_navigator.py` `record_and_dispatch()` method
4. Add tests in `tests/`
5. Update spec documentation in `scripts/`

## Code Conventions
- Google-style docstrings on all public functions/classes
- Specific exception handling (no bare `except: pass`)
- 100% byte coverage on all test .ddd files
- Python 3.9+ compatibility

## Running Tests
```bash
/usr/local/bin/python3.9 -m pytest tests/ -v
```

## Coverage Audit
```bash
python3 scripts/coverage_audit.py
```
