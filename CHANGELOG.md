# Changelog

## [1.6.0] - 2025-06-09
### Added
- `core/event_fault_codes.py` — 28 event types + 17 fault types per EU Reg. 2016/799 + 2023/980
- `descrizione` field in all event/fault entries with human-readable descriptions
- Missing GUI sections: Company Locks, Overspeeding Events, Control Activities
- Chip IC/ICC info in Security & Certificates section
- Shared `iter_vu_sections()` in vu_record_dispatcher (unified with vu_signature_verifier)
- Leading column support in GUI tables (`descrizione` always first)

### Fixed
- P0: Tag dispatch hardcoded in 4 separate places → now data-driven from DecoderRegistry
- P0: DecoderRegistry reconstructed per-tag → singleton pattern via `instance()`
- P0: Padding skip advanced 1 byte/iter → now skips entire run (perf: 10000x on large pads)
- P1: G2 VU vehicle plate/nation not written to `results["vehicle"]` (records 0x0A/0x0B/0x24)
- P1: Calibration fallback overriding correct plate with garbage `?????????????`
- P1: Overlapping Certificates/Signature section boundaries in coverage reports
- P1: `verify_dispatch_coverage` checked wrong parser registry in deterministic mode
- P1: `walk_vu_record_arrays` fallback duplicated data on partial failure
- P2: Lazy imports in `decoders.py` now cached with proper lazy load pattern
- P2: Duplicate `_iter_sections` in vu_signature_verifier → uses shared `iter_vu_sections`
- P2: Missing `RECORD_ARRAY_MAX_*` imports in vu_record_dispatcher
- P2: Export test assertions updated for English column names

### Changed
- **Full English translation** with EU legislation terminology across all user-facing strings
- Activity types: `RIPOSO→REST`, `GUIDA→DRIVE`, `LAVORO→WORK`, `DISPONIBILITÀ→AVAILABLE`
- GUI: removed `confidence` column, `vu_identifications` as Campo/Valore, VU group hidden for cards
- Excel export sheet names: `Riepilogo→Summary`, `Attività Giornaliere→Daily Activities`

## [1.5.4] - Unreleased
### Removed
- Geocoding engine (reverse geocoding, static maps)
- Compliance engine (EU 561/2006 infractions)
- Fine calculator (Italian CdS Art. 174)
- Related tests and documentation

### Fixed
- P0: Non-existent method calls in `tacho_cli.py` (validate_file, reverse)
- P0: Activity sorting crash on `"N/A"` date strings
- P1: Decoder dispatch fragility in deterministic parser — uses inspect.signature
- P1: Record size ambiguity G1(31) vs G2(35) — validates timestamp
- P1: Timeline gap detection for missing days in activity builder
- P2: Wrong path resolution for all_tacho_tags.json
- P2: Alphabetical time sort replaced with integer tuple
- P2: G1 VU container detection tightened to exact tags
- P2: Negative odometer distance now returns None not 0
- P2: Time format robustness in export_manager
- P2: Centralized magic number constants in core/constants.py
- P2: Logger failure detection made more precise
- P2: Coverage report fallback in deterministic mode
- P2: Redundant hasattr check removed, duplicate main block fixed

### Added
- `core/constants.py` — shared constant definitions
- Robust decoder dispatch via `inspect.signature` in deterministic parser

## [1.0.0] - 2025
### Added
- Initial release
- G1 (Annex 1B) and G2 (Annex 1C) parser
- Driver card and vehicle unit support
- Excel/CSV export
- Basic compliance checks
