# Changelog

## [Unreleased]
### Added
- Deterministic parser with CoverageTracker and Decoder Registry
- G2.2 smart tachograph support (GNSS, load/unload, trailer, border crossings)
- Fleet batch analytics and PDF export
- ERCA/MSCA certificate chain validation
- Compliance engine (EU 561/2006)
- Fine calculator (Italian CdS Art. 174)
- CustomTkinter GUI ("Aurora DDD Analytics")
- 100% byte coverage on all 8 test DDD files

### Fixed
- Tag 0x0508 record size corrected (24 → 46 bytes)
- Tags 0x0222, 0x0223 dispatch added
- Multiple BER-TLV and STAP parsing improvements

## [1.0.0] - 2025
### Added
- Initial release
- G1 (Annex 1B) and G2 (Annex 1C) parser
- Driver card and vehicle unit support
- Excel/CSV export
- Basic compliance checks
