# DDD Tachograph Reader — API Reference

## Core Parser
- [TachoParser](tacho_parser.md) — Main parser entry point
- [TachoResult](models.md) — Parsed result data model
- [TagNavigator](tag_navigator.md) — STAP/BER-TLV recursive navigator
- [DecoderRegistry](decoder_registry.md) — Centralized tag-to-decoder mapping
- [DeterministicParser](deterministic_parser.md) — Schema-driven two-pass parser

## Analysis
- [ComplianceEngine](compliance_engine.md) — EU 561/2006 compliance checks
- [SignatureValidator](signature_validator.md) — Certificate chain validation
- [FleetAnalytics](fleet_analytics.md) — Multi-file batch analysis

## Export
- [ExportManager](export_manager.md) — Excel/CSV export
- [Export PDF](export_pdf.md) — PDF report generation
