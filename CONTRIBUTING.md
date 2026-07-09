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
