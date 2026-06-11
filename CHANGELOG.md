# Changelog

## [1.9.0] - 2026-06-11
### Fixed
- **Bug**: event/fault description tables did not follow the normative `EventFaultType` encoding (Annex 1B §2.70 / 1C §2.86: events 0x00-0x2F, equipment faults 0x30-0x3F, card faults 0x40-0x4F) — real codes 0x12/0x15/0x21/0x40 were "Unknown", faults were never matched; range-based group fallbacks added
- **Bug**: card EF Events grouped by `type // 0x20` — events 0x05/0x09/0x0C all labelled "Time overlap"; now described per event code; G1/G2 EF copies deduplicated (real card: 73 → 44 unique events)
- **Bug**: EF Control_activity_data (0x0508) never decoded — the card EF is a single bare 46-byte record (no pointer); alignment-based detection + dedup
- **Bug**: G1 TREP 04 read a non-existent variable "minutes" field — real layout is noOfSpeedBlocks(2) + fixed 64-byte blocks (date + 60 per-second samples); blocks aggregated into driving runs (real VU: 50 garbage blocks → 72 clean runs, max 95 km/h instead of the 200 km/h filter cap)
- **Bug**: G1 TREP 03 ignored the count-prefixed layout (noOfFaults + 82B, noOfEvents + 83B, overspeeding control 9B, noOfOverspeeding + 31B, noOfTimeAdjustments + 98B) — heuristic produced ghost events; real VU now decodes 37 events + 3 faults (was 1 + 4 garbage)
- **Bug**: G1 TREP 05 mislabelled the VU part number as approval number (approval is at offset 108, after partNumber/serial/software/manufacturingDate) and scanned calibrations from a misaligned offset — structured parse now starts at 137 (VuIdentification 116 + SensorPaired 20 + count 1), recovering timestamps and purposes; VU serial, software version/install date, manufacturing date and sensor data now decoded
- **Bug**: calibration vehicle plate included the codePage byte (e.g. "ÿ?????????????") — VehicleRegistrationNumber = codePage(1) + 13 chars
- **Bug**: G2 DriverCardApplicationIdentification (17 bytes) decoded with the G1 layout — `noOfCardPlaceRecords` is 2 bytes in G2; G2 GNSS/specific-condition/vehicle-unit counters now decoded
- **Bug**: G2 TREP02 daily activity list sorted alphabetically on dd/mm/yyyy strings instead of chronologically
- **Bug**: 7 tag-keyed G2 decoders in `g2_decoders.py` used invented/G1-hybrid layouts (VuCardRecord 29B vs normative 45B, VuCardIWRecord 29B vs 131B, VuTimeAdjustmentRecord, VuCompanyLocksRecord 25B vs 99B, sensor records with 8-byte approval vs 16, VuITSConsentRecord 23B vs 20B) — they now delegate to the byte-level layouts confirmed in `vu_record_dispatcher`, so each record type has a single definition
- **Bug**: GUI JSON export crashed on VU files — `BytesEncoder` did not serialize sets (`calibration_vins`); sets now exported as sorted lists
- **Bug**: GUI showed the internal `_key` dedup column in Calibrations/Inserted Drivers; `_`-prefixed keys now hidden
- **Bug**: GUI "Card Issuer" registered both as dict and list section — the list variant rendered bare key names; duplicate removed
- **Bug**: GUI hid card Control Activities (EF 0x0508) because the section lived in the VU-only group; moved to Activity & Usage
- **GUI**: `vu_overview` (card slots, downloadable period, last download), `company_info` and `sensor_gnss_couplings` now displayed; `vu_info` moved to the VU group; column sort understands dd/mm/yyyy dates and space-separated thousands
### Added
- VuCardRecord (0x0E, 45B) fully decoded and emitted as `card_records` (cards seen by the VU: cardAndGen + extended serial + structure version + card number) — layout confirmed on real G2/G2.2 downloads
- SensorExternalGNSSCoupledRecord (0x21, 28B) decoder wired into the VU RecordArray dispatcher
- VuTimeAdjustmentRecord (0x1E, 99B): workshop name/address/card now decoded (was raw tail)
- G1 TREP 01 Overview tail decoding: VuDownloadActivityData (last download time/card/company), company locks (98B records) and control activities (31B records) — previously regex-only; body alignment validated via 17-char VIN + TimeReal fields, rejecting false-positive 0x76 0x01 markers
- G1 TREP 02 deterministic daily-activity decoding (date + odometer + card insert/withdraw records + activity changes + places + specific conditions), replacing the timestamp-scan heuristic (real VU: 0 → 49 places, 22 → 42 daily records, card IW records with driver names)
- G1 TREP 03 overspeeding events (31B records) and time adjustments (98B records), previously dropped
- G1 VU Overview now wired into the raw TREP message walk (`parse_vu_download_messages` skipped TREP 01 entirely on raw G1 downloads: vehicle VIN/plate were never structurally decoded)
- **Bug**: EF Places (0x0506) decoded 0 records — G1 pointer is 1 byte (not 2) and G2 records are 21 bytes (base 10 + GNSSPlaceRecord); entry types corrected to 0/2=begin, 1/3=end (real card: 0 → 112 places, GNSS-enriched from the G2 copy, deduplicated across EF copies)
- **Bug**: EF Card_Download (0x050E) never decoded — the EF is a bare 4-byte TimeReal, the fixed 2-byte header skip made the loop never run
- **Bug**: EF Specific_Conditions (0x0522) G1 copy misaligned — the G1 EF has no header pointer; alignment-based detection + dedup across EF copies
- **Bug**: FullCardNumber decoded off-by-one in `_parse_full_card_number`, `parse_control_activity_data`, calibration workshop card — first byte is cardType (Annex 1B §2.73), not nation; wrong nation and truncated card number
- **Bug**: G1 certificate chain validation used the MSCA signature bytes as RSA modulus — now performs the full ERCA→MSCA→card ISO 9796-2 unwrap with SHA-1 digest verification (loads the JRC EC_PK root); real G1 card now reports "Verified"
- **Bug**: G1 (194-byte) certificates lost when a file also carries G2 certificates — kept separately, G1 chain retried when the G2 chain does not verify
- **Bug**: `parse_g1_vu_overview` crashed with `'list' object has no attribute 'add'` when invoked twice (card_numbers set→list conversion)
- **Bug**: cyclic-buffer activity walk re-read the same header on an invalid record instead of advancing via prev_len
- **Bug**: VU GNSS decoder treated only 0xFFFFFF as no-fix — 0x7FFFFF "unknown position" (Annex 1C §2.76) produced ~8389° coordinates
- **Bug**: `record_array` nation byte mapped via `chr(0x40+n)` instead of the Annex nation table (Italy rendered as "Z")
- **Bug**: registry `record_size` for 0x052D/0x052E/0x0530 misaligned with decoders (33→32, 10→9, 90→87)
- **Test**: mock generator encoded the same wrong EF layouts (2-byte pointers everywhere); aligned to spec
- **Test**: mock certificates now written to a temporary directory — test runs no longer dirty `tests/certs/`

## [1.7.0] - 2025-06-09
### Added
- GUI Export button with Excel (.xlsx), CSV (.csv), JSON (.json) formats
- `core/coverage_utils.py` — shared `merge_intervals()`, `coverage_pct()`, `is_padding_block()`
- `core/encoding.py` — shared `BytesEncoder` (moved from tacho_cli.py, also used by gui_tree.py and main.py)
- `tests/conftest.py` — `autouse` fixture resetting DecoderRegistry singleton between tests
- Thread-safety lock in `core/logger.py` for concurrent parser instances
- Iteration cap in `deep_scan()` (max 10000 iterations) preventing infinite loops
- Idempotent `parse()` — state fully reset on each call

### Fixed
- **Bug**: STAP empty-tag slots (0x0000, 0xFFFF, 0x5555) used `break` stopping the block → `continue`
- **Bug**: VU `iter_vu_sections` used `break` on invalid RecordArray header → skips record, continues
- **Bug**: `decode_date` timestamp upper bound `< 4102444800` → `<= 4102444800`
- **Bug**: `get_coverage_report()` returned `0.0` for unparsed files → returns `None`
- **Bug**: Padding skip required 2+ identical bytes → now handles single padding bytes
- **Bug**: `read_ber_tlv` and `_try_read_ber_tlv` hardcoded `0x100000` → `MAX_TLV_LENGTH` from constants
- **Bug**: Activity dedup `except (KeyError, ValueError)` too broad → removed, uses `.get()` calls
- **Bug**: Decoder dispatch silent `except Exception` → logs at WARNING level with traceback
- **Bug**: mmap file descriptor leak if `mmap.mmap()` fails → immediate close
- **Bug**: Duplicate range-merging logic in 3 places → single `merge_intervals()` in coverage_utils
- **Bug**: Duplicate padding detection in 2 places → single `is_padding_block()` in coverage_utils
- **Bug**: Italian docstrings in `vu_signature_verifier.py` → translated to English
- **Bug**: `signature_validator.py` crash on cryptography >= 43 (missing `tbs_certificate_bytes`) → safe accessor
- **Test**: Export assertions updated for new comprehensive multi-sheet format
- **Test**: Mock G1 VU coverage minimum raised to 30%, generation test fixed

### Changed
- ExportManager rewritten for full-content export (all sections from TachoResult)
- GUI button labels simplified: "Open DDD file", "Export" (menu: Excel, CSV, JSON)
- `tacho_cli.py` reused shared `BytesEncoder` from `core/encoding.py`
- `main.py` reused shared `BytesEncoder`, removed dead code
- Requirements.txt includes `pytest` as explicit dependency
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
