# Changelog

## [Unreleased]

## [2.3.1] - 2026-07-09
### Added
- **Monthly activity report in export**: activities grouped by month, daily columns for Drive/Work/Rest/Available/Unknown hours (HH:MM), daily totals, monthly subtotals
- **Unknown activity column**: ⚠️ warning icon when activity type is not among the standard four codes
- **Section descriptions**: subtitle below every section title in PDF/Excel/CSV explaining what data the section contains (38 descriptions in English)
- **PDF cover page**: stats bar with total Drive/Work/Rest hours, active days, event count
### Changed
- **PDF redesign**: font increased to 8pt (from 6.5), smart column widths, bold monthly total rows, month separator lines, right-aligned numbers, professional styling
- **Each month on its own PDF page** with page breaks between months
- **Compact activity tables** (7pt font, 2px padding) to fit 31 days + totals on one landscape page
- **Section descriptions** moved from inside table to subtitle paragraph under section title
### Fixed
- **Single-change days** (e.g. rest day with card not inserted): now show 24h of that activity instead of 00:00
- **Release workflow**: `core.version` → `core.utils.version` import path

## [2.3.0] - 2026-07-09
### Added
- **Monthly activity report in export**: activities grouped by month, daily columns for Drive/Work/Rest/Available hours (HH:MM), daily totals, monthly subtotals, UTC timezone note, description row per section
- **Auth blob BER-TLV walk**: 0x960F (GNSS auth) and 0x6399 (Load/Unload auth) now walk nested TLV structure; OID sub-tags resolved to curve names
- **Record type 0x29 decode**: co-driver slot ActivityChangeInfo from G2.2 VU arrays (Stoneridge V6006)
- **TREP section names in signature table**: "Section Signatures (TREP)" now shows human-readable names like "Activities" instead of just "0x31"
- **GUI sections**: Calibration VINs in G1 group, Auth blobs (GNSS + Load/Unload) in Security group, Decoder Failures detail
- **`__init__.py` facades**: all 7 packages (`core/`, `core/parser/`, `core/registry/`, `core/crypto/`, `core/utils/`, `app/`) with public API re-exports
- **`--csv` CLI flag**: CSV export exposed alongside JSON/PDF/Excel
- **Sheet name dedup**: collision suffix `_2`, `_3` when two sections produce the same 31-char Excel name
### Changed
- **Export runs on separate thread** with progress bar (no more UI freeze)
- **GUI filter + resize debounce**: 300ms throttle on keystrokes and column resize events
- **`Ctrl+F`**: keyboard shortcut jumps to search bar
- **EC curve OID map**: deduplicated in `constants.py`, covers all 6 curves (brainpool + NIST)
- **Constant dedup**: `_ISO_RE`, `_NOT_AVAILABLE_INTS`, `UNIX_EPOCH_*` moved to shared modules
- **`g2_dispatch.py`**: thin wrappers eliminated, `G2_VU_RECORD_DECODERS` references `vu_dispatcher` directly
- **Timestamp display**: `0` → em-dash (—) for "not available" sentinel
### Fixed
- **`_finish_parse()`**: Open button no longer stays disabled after render errors
- **EC_CURVE_OIDS**: now contains all 6 curves (was missing 4)
- **Tag 0x0206**: `parse_cyclic_buffer_activities` wired as decoder
- **8 registry tags**: corrected from G2.2 → G2 (0x052C-0x0533 are Annex 1C 2016/799, not G2.2)
- **Annex refs**: 3 tags changed from "ASN.1:" → "Annex 1C §..."
- **`parse_g1_identification`**: 44 skipped bytes (issuingAuthorityName, issueDate, validityBegin) now decoded
- **G1 cert warnings**: demoted to DEBUG (expected fallback for G2 files)
- **Dead code**: removed `signatures` key from `TachoResult`, removed `export_manager` from `build.spec`
- **CI**: pip caching on all jobs, removed redundant `pip install pytest`/`pyinstaller`
- **`_iso(0)`**: returns "—" instead of `None` for "never" state (overspeeding control, etc.)
- **GUI Raw Tags section**: removed (confusing — data already in generation groups)

## [2.2.2] - 2026-07-09
### Added
- **Certificate CVC/ECC field-level decoder**: unified `parse_certificate()` with auto-detect (G1 RSA 194-byte vs G2/G2.2 CVC BER-TLV). CAR, CHR, curve OID, public key (x,y), validity dates, signature r/s exposed in `certificates[]`
- **G1 Sensor download decoder** (TREP 0x11 / 0x7611): sensor identification (approval number, nation), date range, 66 daily timestamp records exposed in GUI and export
- **Context-aware `DecoderRegistry`**: `get_decoder(tag, generation=, is_vu=, dtype=, parent_tag=)` with multi-variant support — same FID can have different decoders for card vs VU, generation-specific payloads
- **Tag/FID decoding matrix generator** (`scripts/tag_decoding_matrix.py`): full matrix from `DecoderRegistry.iter_decoders()` with Markdown/JSON output; gate tests ensure every variant has an Annex reference
- **Golden field-level assertions** (`tests/test_golden_fields.py`): 95 tests verifying decoded values (card number, driver name, plate, VIN, activity/event counts, certificates, signature status) across all 19 real files
- **GUI file integrity warning**: popup on file open when coverage < 100%, unknown bytes present, decoder failures, certificate chain issues, EF/TREP signature failures
- **Rich Vehicle summary**: calibration status with expiry warning (❌/⚠️/✅), VU manufacturer/part/software info, active company lock, sensor pairing data
- **Rich Driver summary**: cardholder name, card details, licence, activity statistics, EF verification status
- **Rich Sensor summary**: sensor identification, associated vehicle, date range with actual days, speed/distance parameters
- **Export coverage**: certificates, sensor daily records, dict-style sections (VU Overview, Card Issuer, IC Chip, etc.) in Excel/CSV/PDF
### Changed
- **GUI tree reorganized by generation**: top-level folders "Generation 1 — Annex 1B", "Generation 2 — Annex 1C", "Generation 2.2 — Smart V2"; VU sections filtered for card files; empty folders hidden
- **Column auto-fit**: table columns proportionally resize with window width
- **Nested dict flattening**: Field/Value tables now expand sub-dicts as `Parent › Child` rows instead of compact strings
- **`locations`** (GPS) section added to GUI tree (was missing)
- **G2.2 card EF decoders rewritten**: ASN.1 32-bit signed coordinates (1/10 micro-degree), `CardLoadUnloadRecord` (22 bytes) and `CardBorderCrossingRecord` (19 bytes) with nested `GNSSPlaceAuthRecord`
- **Status bar consistency**: integrity label now matches between File Info panel and top bar via shared `_integrity_label()` method
### Fixed
- **G2/G2.2 CVC certificates** (204-205 bytes) were incorrectly decoded as G1 RSA (194 bytes), producing garbage fields
- **Right panel stale data**: table now clears when switching files
- **`locations`** section missing from GUI tree
- **Sheet name sanitization**: `/`, `:`, `[` etc. replaced with `_` in Excel sheet names
- **Calibration date parsing**: handles both ISO format (G2) and dd/mm/yyyy format (G1)
- **Double separator line** after SENSOR section in vehicle panel
- CLI file argument now correctly loads file on startup

## [2.1.0] - 2026-06-12
### Fixed
- **G2/G2.2 VU detailed speed was invisible**: `VuDetailedSpeedBlock` records (recordType 0x12) were decoded by the RecordArray dispatcher but never folded into `speed_blocks`, so the GUI's "Detailed Speed Blocks" section only appeared for G1 VU files. Real G2/G2.2 VU downloads now expose their per-minute speed blocks (timestamp, min/max/avg km/h, sample count) in the GUI and all exports; padding blocks are skipped. Synthetic regression test added
- Shared logger records are now consistently named `ddd_tacho` — previously the singleton took the name of whichever module called `get_logger` first, producing misleading log origins
### Added
- **GUI "Card Numbers Seen" section** (VU group): driver card numbers captured from G1 VU TREP data were only visible in the JSON export; now rendered as a sortable table. With this, every result key the parser populates has a GUI section
### Changed
- **`core/decoders/__init__.py` (3,061 lines) split into themed modules** behind a re-export facade: `decode_primitives` (shared helpers), `card_decoders` (card EFs), `g22_card_decoders` (Gen 2.2 tags), `cert_decoders` (certificates/keys), `vu_trep_decoders` (VU overview + TREP walkers). All existing imports keep working through the facade
- **`TachoParser.parse()` refactored from a 246-line block into named phases** (`_open_file`, `_run_structural_parse`, `_decode_vu_semantics`, `_dedup_and_sort_activities`, `_validate_certificate_chain`, `_verify_ef_signatures`); behavior unchanged
- Function docstring coverage raised from 65% to 77% (deterministic parser internals, GUI lifecycle, export manager); dead `infractions` branch removed from the CLI summary (nothing ever populated it)
### Documentation
- **User docs rewritten to describe the real application**: the previous `docs/user` documented features that never existed ("Aurora DDD Analytics" branding, an EU 561/2006 compliance engine with fine estimates, Fleet/Infractions GUI tabs, `--geocode`/`--batch` CLI flags). A new FAQ entry clarifies the tool does not evaluate driving-time rules
- **GitHub wiki published** from `docs/user` (Home, Installation, GUI/CLI/Export guides, FAQ, Troubleshooting)
- Developer/API docs purged of the removed legacy parser (`TagNavigator`, `deep_scan`, `use_deterministic`, `_fill_coverage_gaps`): architecture diagrams and `parsing_pipeline.md` rewritten around the deterministic-only flow, `docs/api/tag_navigator.md` deleted, `AGENTS.md` aligned

## [2.0.0] - 2026-06-11
### Added
- **Application icon**: Windows executable (.ico), macOS bundle (.icns) and the Tk window now use the AppIcons artwork
### Fixed (distribution)
- **Windows builds were broken since 1.9.5**: `strip=True` in `build.spec` ran MinGW `strip` on the bundled PE DLLs on the CI runner, corrupting `python311.dll` — the app hung on a modal "Failed to load Python DLL" error at startup. Stripping is now disabled on Windows; the new CI smoke test launches every bundle before publishing to prevent regressions
### Changed
- **English-only project**: the optional Italian translation layer (`core/i18n.py`, `TACHO_LANG`) has been removed; all UI labels and exports are English
- **G1 EF signature verification tightened**: RSASSA-PKCS1-v1_5 with SHA-1 is now the primary, strictly-checked path (confirmed against real cards); the ISO 9796-2 recovery path enforces the exact block layout (`0x6A‖M1‖SHA1‖0xBC`, M1 == data prefix) instead of scanning for the hash at any offset
- Dependencies pinned with compatible-release ranges in `requirements.txt`; Dependabot enabled for pip and GitHub Actions
- CI: Python test matrix moved to 3.10/3.12/3.13 (3.9 is EOL and pytest 9 requires ≥ 3.10); mypy added to the lint job
- CI: PyInstaller bundles are now smoke-tested on both platforms (`--version` and a headless `--smoke` parse of a mock card) before upload
- Release workflow: GitHub release notes are extracted from the matching CHANGELOG section
### Fixed
- **ControlType decoded as a bit mask** ('cvds'B, Annex 1B §2.53 / Annex 1C req. 126): real records (0x40, 0xC0, 0xE0…) now render as "Card downloaded, VU downloaded, Printing…" — the previous enum (0x01=Roadside check…) matched no real value and every label fell back to raw hex
- **CalibrationPurpose labels aligned to the regulation** (Annex 1B §2.8): 0x03 is "installation (current vehicle)" and 0x04 "periodic inspection"; the invented 0x05/0x06/0x0A entries removed
- VU Places / GNSS Accumulated Driving: the "no card in slot" filler record (cardType 0, empty number, generation 0xFF) was rendered as a raw field dump (`present=Yes, card_type=0, …`) in the Card Driver column — now decoded as "card absent" and shown as "—"
- GUI: generation/feature groups with no content (e.g. "G2.2 — Smart V2" on a G1 file) are no longer shown as empty folders

## [1.9.9] - 2026-06-11
### Added
- **EF card data signature verification** (`core/crypto/ef_signature.py`): every card EF data block is verified against its signature copy with the card public key — G1 RSA (ISO 9796-2 with SHA-1, PKCS#1 v1.5 fallback) and G2 ECDSA (raw r‖s, curve-matched hash). Per-EF report in the GUI ("EF Signatures" under Security & Certificates), exports and summary ("EF card data signatures" row); real cards verify all 9–26 EF signatures
- **ERCA-2 (Gen2) root anchoring**: the EU JRC ERCA Gen2 root certificate (CVC, KID `FD45432001FFFF01`) is bundled in `certs/` and loaded by `SignatureValidator` (CVC-in-PEM wrapping, raw uncompressed EC points 65/97/129/133 bytes for brainpool/NIST 256–521, DER/PEM SPKI). `verify_vu_download` now anchors the MSCA certificate to the root (by CAR, with a try-all fallback for raw keys): real Gen2/2.2 VU downloads report **root-anchored** and "Verified (VU Chain)"
- **G2 CVC chain validation** (`_validate_g2_cvc_chain`): MSCA→Card link verified via the CVC parser (the old path only handled X.509 DER, which tachograph cards don't use)
- **G1 VU chain validation**: the MSCA/VU certificates embedded in TREP 01 Overview now feed `validate_tacho_chain` — real G1 VU files report "Verified"
- **TREP 06 (Card Download)**: activities extracted from the embedded EF 0x0504 cyclic buffer; container 0x7606 registered
- GUI: signature/integrity **status badge** in the header (and window title) summarising chain, EF and TREP verification at a glance
- Calibration purpose and control type human-readable labels (`describe_calibration_purpose`, `describe_control_type`, Annex 1B §2.118 / §2.15a) on calibrations and control activities
### Fixed
- `decode_g2_daily_record`: a record with `sig_len` 0 was sized 112 bytes instead of 48; explicit None handling for absent signature-length bytes
- `iter_vu_sections`: recordType 0x00 headers are rejected (resync instead of decoding junk); Terminator (0x60) arrays with recordSize 0 accepted
- Trailer registrations: unknown coupling codes reported as `UNKNOWN_xx` instead of being folded into "UNCOUPLED"; raw `coupling_code` preserved
- VU_ActivityDailyRecord (0x0206) no longer mis-decoded as a card cyclic buffer
- A failed certificate chain is reported as "Invalid Certificate Chain" (it was masked as "Incomplete Certificates")
- Single trailing padding byte at EOF is classified as padding (was left as unparsed data)
- Lone padding byte handling no longer desyncs the STAP walk (regression guard: `tests/test_deterministic_padding.py`)

## [1.9.5] - 2026-06-11
### Distribution & hygiene
- **Single version source** (`core/utils/version.py`): shown in the GUI title, `tacho-cli --version` / `app/main.py --version`, parse metadata (`app_version`), PDF footer, export summary and the macOS bundle (`CFBundleShortVersionString`); the release workflow refuses tags that don't match it (replaces the stale "Version 5.1" docstring)
- **Legacy parser removed**: the deprecated non-deterministic path (`core/tag_navigator.py`, `use_deterministic=False`, `--legacy`, `validate()`, `scripts/compare_parsers.py`) returned empty results on real files and was dead code; `TachoParser(use_deterministic=False)` now warns and uses the deterministic parser
- **Dead `src/` domain-layer skeleton removed** (never wired to the application)
- **Release workflow unified on `build.spec`**: the inline PyInstaller commands duplicated (and contradicted) the spec — they bundled `src/`, double-packed `core/` as datas and missed the new modules; the spec is now the single bundle definition (verified: local build produces `TachoReader.app` with the right version)
- **Windows build no longer opens a console window** (`console=False` in the spec, matching the old `--noconsole` release flag)
- **CI lint job**: ruff with correctness rules (`ruff.toml`: pyflakes, pycodestyle errors, bugbear) — all findings fixed (unused imports/variables, mutable `hashes.SHA256()` argument defaults)
- pandas dependency dropped (no longer used); reportlab added
### Added
- **PDF export** (GUI menu, `tacho-cli --pdf`, included in `--all`): landscape report with summary page (file/driver/vehicle/integrity/signatures) and one styled table per data section, page footer and truncation notes (reportlab)
- **Deterministic G1 VU walker** (`core/parser/g1_walker.py`): TREP message lengths computed from the Annex 1B §2.2.6 structures (count-prefixed sections) + 128-byte RSA signatures; the walk is self-checking (each message must land on the next `0x76 TREP` marker or EOF). Replaces both the junk STAP coverage walk and the O(n²) byte-scan semantic heuristic on G1 VU files (kept as fallback for non-validating files)
- `ActivityChangeInfo` card-status bit (p) decoded: activity entries now carry `card_inserted`
- Shared export formatting module (`core/utils/report_format.py`): humanised column names, readable timestamps, nested structures (card numbers, GNSS, registrations) rendered as text, internal keys hidden — used by Excel, CSV and PDF
- 100% decoded byte coverage on every real file in `DDD/` (was 95.4% on G1 VU); non-normative `0x76 0x00` download-tool trailers classified explicitly
### Changed
- **Excel export** rewritten on openpyxl: styled frozen headers, autofilter, sized columns, striped rows, summary sheet with driver/vehicle; no more raw JSON dumps in cells (pandas dependency dropped)
- **CSV export** rewritten as readable section blocks (title + per-section header + formatted rows)
### Fixed
- G1 VU days with the card not inserted (18-byte TREP 02 bodies) were dropped by the heuristic wrapper's 50-byte minimum — real G1 VU now reports all 42 downloaded days instead of 22
- **Bug**: `SpecificConditionType` decoded against an invented table (0=Ferry, 1=Train, 2=OutOfScope, 3/4=GNSS blackout) in 4 places — the normative assignment (Annex 1C §2.154) is 0x01/0x02 = Out of scope Begin/End, 0x03/0x04 = Ferry/Train crossing Begin/End, 0x00 = RFU; real out-of-scope periods were reported as train crossings. Single canonical map in `event_fault_codes`
- **Bug**: EF Vehicles_Used decoded the G2 EF copy with an invented 35-byte layout (4-byte odometers) — the normative G2 `CardVehicleRecord` is 48 bytes (G1 fields + VIN, Annex 1C §2.37); the misaligned walk produced ghost sessions (real card: 203 → 200) and the VIN was lost; G1/G2 copies now deduplicated and VIN-enriched, layout chosen by validation scoring
- **Bug**: tag 0x0523 decoded as "G2 VehiclesUsed" — it is EF VehicleUnits_Used (Annex 1C §2.39, 10-byte records: timestamp + manufacturerCode + deviceID + vuSoftwareVersion); now decoded into `vehicle_units` (confirmed on real card: software version "4072", count matches `noOfCardVehicleUnitRecords`)
- **Bug**: tag 0x0524 decoded as a G2 activity cyclic buffer — it is EF GNSS_Places (Annex 1C §2.78, 18-byte `GNSSAccumulatedDrivingRecord`: ts + GNSSPlaceRecord + odometer); real card now yields 336 GNSS positions with odometer (was 0)
- **Bug**: `tacho-cli --all` generated only the JSON and exited with an error — it auto-enabled the unimplemented PDF export whose branch called `sys.exit(1)` before Excel; `--pdf` now warns and continues
- **Bug**: card files always labelled "G1 (Digital)" — generation is now refined after parsing from the EF appendix dtypes (0x02/0x03 = Gen2 copies) and the Gen2v2-only EFs (0x0525-0x052A)
- **Bug**: the deterministic structural pass walked Gen2/2.2 VU downloads as BER-TLV, misreading 0x76 as a 1-byte tag and classifying garbage tags (`Tag_003E`, `Tag_0062`, …) — VU files are now classified along the RecordArray stream (`7621_VU_Overview > 04_MemberStateCertificate`, …); decoded byte coverage on real G2/G2.2 VU files is now 100%
- **Bug**: `iter_vu_sections` resynced 5 bytes at a time on an invalid RecordArray header (could skip a valid array start after junk) and accepted any 0x76 byte as a section marker — resync is now 1 byte and markers require a valid TREP byte
- **Bug**: VU download signature read assumed 64-byte ECDSA signatures — now uses the SignatureRecord size (96/128 bytes for P-384/P-512 curves)
- **Bug**: G2.2 sensor records (0x0532/0x0533) declared 20/24-byte sizes but the decoders required 28 bytes, silently dropping every record — shorter variants now decoded (serial-first/date-last) with `confidence: low`
- **Bug**: `decode_name` (VU dispatcher) dropped bytes ≥ 0x7F — accented characters in workshop/holder names and addresses were silently removed; now decodes via the declared code page
- **Bug**: deterministic decoder dispatch ignored the registry `card_only`/`vu_only` context flags — card decoders ran on VU files and vice versa (the legacy navigator already filtered)
- **Bug**: bare G2 VU records without a RecordArray header landed under generic `g2_XXXX` result keys invisible to GUI/export — now use the same named keys as the array path
- **Bug**: `parse_g1_vehicles_used` rejected the valid special nation codes 0xFD/0xFE/0xFF (EC/EUR/WLD)
- **Bug**: `TachoResult.to_dict` omitted the declared `signed_daily_records` field; `validate()` compared the never-populated `locations` key instead of `places`; `decode_g2_daily_record` caller fallback record size 113 vs decoder 112
- **CLI**: summary now reports Availability separately instead of folding it into Rest
- `vehicle_units` section (EF VehicleUnits_Used) in GUI and Excel export
- Card EF GNSS_Places (G2 18-byte / G2.2 19-byte records with authentication flag) merged into `gnss_ad_records` with dedup
- **Test**: mock G1 card now uses the normative appendix dtypes (0x00 data / 0x01 signature); mock G2/G2.2 cards are flat STAP streams (no VU wrapper) with correct EF usage (0x0504 activities, 0x0505 vehicles, 0x0523 vehicle units, 0x0524 GNSS places)

- **Bug**: `test_vu_dispatcher` and `test_export` checked for the old Italian keys (`eventi`, `data`, `km`, `tipo`) — updated to the English production keys (`changes`, `date`, `odometer_km`, `activity`); golden snapshots regenerated
- **Bug**: G1 VU deterministic walker did not handle TREP 06 (Card Download via VU) — missing from `TREP_NAMES`, body-length table and dispatch dict, causing a fallback to heuristic parsing; TREP 06 body extends to the next `0x76 TREP` marker or EOF

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
- `core/utils/coverage.py` — shared `merge_intervals()`, `coverage_pct()`, `is_padding_block()`
- `core/utils/encoding.py` — shared `BytesEncoder` (moved from app/cli.py, also used by app/gui.py and app/main.py)
- `tests/conftest.py` — `autouse` fixture resetting DecoderRegistry singleton between tests
- Thread-safety lock in `core/utils/logger.py` for concurrent parser instances
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
- **Bug**: `core/crypto/signature.py` crash on cryptography >= 43 (missing `tbs_certificate_bytes`) → safe accessor
- **Test**: Export assertions updated for new comprehensive multi-sheet format
- **Test**: Mock G1 VU coverage minimum raised to 30%, generation test fixed

### Changed
- ExportManager rewritten for full-content export (all sections from TachoResult)
- GUI button labels simplified: "Open DDD file", "Export" (menu: Excel, CSV, JSON)
- `app/cli.py` reused shared `BytesEncoder` from `core/utils/encoding.py`
- `app/main.py` reused shared `BytesEncoder`, removed dead code
- Requirements.txt includes `pytest` as explicit dependency
### Added
- `core/utils/event_codes.py` — 28 event types + 17 fault types per EU Reg. 2016/799 + 2023/980
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
- P0: Non-existent method calls in `app/cli.py` (validate_file, reverse)
- P0: Activity sorting crash on `"N/A"` date strings
- P1: Decoder dispatch fragility in deterministic parser — uses inspect.signature
- P1: Record size ambiguity G1(31) vs G2(35) — validates timestamp
- P1: Timeline gap detection for missing days in activity builder
- P2: Wrong path resolution for all_tacho_tags.json
- P2: Alphabetical time sort replaced with integer tuple
- P2: G1 VU container detection tightened to exact tags
- P2: Negative odometer distance now returns None not 0
- P2: Time format robustness in export_manager
- P2: Centralized magic number constants in core/utils/constants.py
- P2: Logger failure detection made more precise
- P2: Coverage report fallback in deterministic mode
- P2: Redundant hasattr check removed, duplicate main block fixed

### Added
- `core/utils/constants.py` — shared constant definitions
- Robust decoder dispatch via `inspect.signature` in deterministic parser

## [1.0.0] - 2025
### Added
- Initial release
- G1 (Annex 1B) and G2 (Annex 1C) parser
- Driver card and vehicle unit support
- Excel/CSV export
- Basic compliance checks
