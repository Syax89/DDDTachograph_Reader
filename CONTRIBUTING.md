# Contributing to DDD Tachograph Reader

## Development Setup

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
```

## Project Structure
- `core/` — Parser engine (navigator, decoders, registry, models)
- `ddd_parser.py` — Main entry point
- `gui_tree.py` — Desktop application (tkinter: tree view + Excel-style table)
- `tests/` — Test suite (150+ tests)
- `specs/` — Tag specifications and verification docs

## How to Add a New Decoder
1. Add decoder function in `core/decoders.py` or `core/g2_decoders.py`
2. Register it in `core/decoder_registry.py` with tag number, name, and metadata
3. Add dispatch in `core/tag_navigator.py` `record_and_dispatch()` method
4. Add tests in `tests/`
5. Update spec documentation in `specs/`

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
python3 specs/coverage_audit.py
```
