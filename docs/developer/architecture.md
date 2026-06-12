# Architecture

## Architecture Overview

The DDD Tachograph Reader follows a layered pipeline architecture with four main layers:

1. **Parser layer** — reads raw `.ddd` bytes, detects tachograph generation, walks STAP/BER-TLV structures and VU download streams deterministically, and dispatches field-level decoders
2. **Analysis layer** — validates certificate chains (ERCA/MSCA → Card/VU) and VU download signatures
3. **Export layer** — produces output in JSON, Excel (multi-sheet), CSV, and PDF formats
4. **GUI/CLI layer** — provides a tkinter GUI (`gui_tree.py`) and `tacho_cli.py` command-line interface

### Key Design Patterns

**Registry Pattern** — `DecoderRegistry` (`core/decoder_registry.py:28`) is the single source of truth mapping tag IDs to decoder functions. Each entry carries metadata: container flag, signature block, minimum length, record size, Annex reference, and generation. This enables lookup-by-tag without hardcoded switch statements.

**Strategy Pattern** — `DeterministicParser` (`core/deterministic_parser.py`) selects a walk per file kind:
- Card files: sequential STAP (G1, T2L2 headers) or BER-TLV (G2/G2.2) walk with container recursion
- G2/G2.2 VU downloads: RecordArray stream walk via `core/vu_record_dispatcher.py` (Annex 1C Appendix 7)
- G1 VU downloads: SID/TREP message walk via `core/g1_vu_walker.py` (Annex 1B §2.2.6)

**Pipeline Pattern** — `parse → analyze → export`. `TachoParser.parse()` (`ddd_parser.py`) is a thin orchestrator over named phase methods: `_open_file → _run_structural_parse → _decode_vu_semantics → _dedup_and_sort_activities → _validate_certificate_chain → _verify_ef_signatures → build_generations_tree`.

### Flow Diagram

```mermaid
flowchart TD
    A[".ddd File"] --> B[TachoParser.parse]
    B --> C{Generation + VU/card detection}
    C -->|"Card"| D["DeterministicParser\nSTAP / BER-TLV walk"]
    C -->|"G2/G2.2 VU"| E["RecordArray stream walk\n(vu_record_dispatcher)"]
    C -->|"G1 VU"| F["SID/TREP message walk\n(g1_vu_walker)"]
    D --> G["DecoderRegistry.get_decoder"]
    E --> G
    F --> G
    G --> H["Field-level decoders\n(decoders.py facade → themed modules)"]
    H --> I[TachoResult]
    I --> J["SignatureValidator\n(ERCA→MSCA→Card/VU)"]
    J --> K["EF / TREP signature verification"]
    K --> L["build_generations_tree()\n→ JSON via TachoResult.to_dict()"]
```

## Pipeline Flow (Detailed)

```mermaid
flowchart TD
    subgraph "1. File Loading"
        A["Open .ddd file\n(mmap for large files)"]
        A --> A1["Read first byte\n(0x76 → VU, else card)"]
        A --> A2["Read first 2 bytes\n(0x7631 → G2.2\n0x762x → G2\nelse → G1)"]
    end

    subgraph "2. Structural Parsing (DeterministicParser)"
        A2 --> B1{"VU or card?"}
        B1 -->|"G2/G2.2 VU"| B2["_parse_vu_stream()\nRecordArray sections"]
        B1 -->|"G1 VU"| B3["_parse_g1_vu_stream()\nSID/TREP messages"]
        B1 -->|"Card"| B4["STAP / BER-TLV walk\n_try_read_stap / _try_read_ber_tlv"]
        B4 --> B5["_parse_container()\nrecursive, depth-bounded"]
        B2 --> B6["CoverageTracker\nevery byte classified"]
        B3 --> B6
        B5 --> B6
        B6 --> B7["_classify_gaps()\nPadding / DownloadTrailer / Unknown"]
    end

    subgraph "3. Tag Dispatch"
        B4 --> C1["DecoderRegistry.get_decoder(tag)"]
        C1 --> C2["decoder_fn(payload, results[, tag])\ncard/VU scope filter\nsignature dtypes skipped"]
    end

    subgraph "4. VU Semantic Pass (TachoParser)"
        B2 --> D1["walk_vu_record_arrays()\n+ ECDSA download verification"]
        B3 --> D2["walk_g1_vu()\nheuristic fallback if invalid"]
    end

    subgraph "5. Post-processing"
        C2 --> E1["Activity dedup + sort"]
        D1 --> E1
        D2 --> E1
        E1 --> E2["Certificate chain validation\n+ EF signature verification"]
        E2 --> E3["build_generations_tree()"]
    end
```

## Component Descriptions

### TachoParser (`ddd_parser.py`)

Entry point class. Constructor accepts the file path, records metadata, initializes `SignatureValidator`. `parse()` orchestrates named phases:
1. `_open_file()` — mmap + VU/card detection (first byte `0x76` = VU)
2. `_run_structural_parse()` — `DeterministicParser` walk with full byte coverage
3. `_decode_vu_semantics()` — VU only: RecordArray dispatch + ECDSA verification (G2/G2.2) or TREP walk (G1)
4. `_dedup_and_sort_activities()` — drop duplicate daily blocks, newest-first
5. `_validate_certificate_chain()` — ERCA → MSCA → Card/VU chain
6. `_verify_ef_signatures()` — per-EF data integrity against the card key
7. `build_generations_tree()` — hierarchical per-generation view

### DecoderRegistry (`core/decoder_registry.py:28`)

Centralized tag → decoder mapping. Holds a `Dict[int, TagDecoder]` with entries for all known tags. Each `TagDecoder` dataclass contains:

| Field | Description |
|---|---|
| `tag` | Tag ID (integer) |
| `name` | Human-readable name |
| `decoder_fn` | Callable decoder function, or None for container-only |
| `container` | Whether inner data should be parsed recursively |
| `min_length` | Minimum payload length |
| `max_length` | Maximum payload length |
| `record_size` | Fixed record size for RecordArray decoding |
| `annex_ref` | Specification reference (e.g., "Annex 1B §2.15") |
| `generation` | "G1", "G2", "G2.2", or "all" |
| `card_only` / `vu_only` | Card/VU-specific |
| `signature_block` | Marked for signature validation |
| `priority` | Dispatch priority (higher = sooner) |

Key methods: `get_decoder(tag)`, `is_container(tag)`, `is_signature(tag)`, `get_by_generation(gen)`, `get_unhandled_tags(seen_tags)`.

### DeterministicParser (`core/deterministic_parser.py:105`)

Schema-driven two-pass parser (migration target). Architecture:
1. **Structural pass**: Sequentially parses the file using `_try_read_stap()` or `_try_read_ber_tlv()`, dispatching through `DecoderRegistry.get_decoder()` and recursing into containers
2. **Semantic pass**: (reserved for future) Validates record sizes, checksums, and field ranges

Uses `CoverageTracker` (`core/deterministic_parser.py:18`) to track exact byte ranges covered, with classifications (Tag, Padding, Unknown). Guarantees 100% coverage by construction.

### Decoders (`core/decoders.py` facade + themed modules)

Field-level byte decoders, split by scope. `core/decoders.py` is a facade that re-exports every decoder, so the registry and other modules import from a single place:

| Module | Contents |
|---|---|
| `core/decode_primitives.py` | Shared helpers: nations, code-page strings, dates, activity values, cyclic activity buffers |
| `core/card_decoders.py` | Card EFs: ICC/IC, identification, licence, events/faults, places, vehicles used, calibrations, control activities, company data |
| `core/g22_card_decoders.py` | G2.2 tags: GNSS accumulated driving, load/unload, trailers, enhanced places, load sensor, border crossings |
| `core/cert_decoders.py` | Certificates: G1 RSA profiles, signatures, public keys, G2.2 CVC profiles and auth sub-tags |
| `core/vu_trep_decoders.py` | VU download messages: overview, TREP 02–06 walkers, G2/G2.2 VU RecordArray dispatch |

`g2_decoders.py` (~567 lines) handles G2/G2.2 VU RecordArray records:
- `parse_g2_card_record()` (0x0509): 29-byte card records
- `parse_g2_card_iw_record()` (0x050A): 29-byte insertion/withdrawal records
- `parse_g2_vu_record()`: Generic dispatcher for all G2/G2.2 VU record types using RecordArray format

### Models (`core/models.py`)

`TachoResult` dataclass hierarchy:

```
TachoResult
├── metadata: filename, generation, parsed_at, integrity_check, file_size_bytes, coverage_pct
├── driver: card_number, surname, firstname, birth_date, expiry_date, issuing_nation, ...
├── vehicle: vin, plate, registration_nation
├── activities: List[Dict] — daily driver activities
├── vehicle_sessions: List[Dict] — vehicles used over time
├── events: List[Dict] — recorded events
├── faults: List[Dict] — recorded faults
├── locations: List[Dict] — GNSS positions
├── places: List[Dict] — recorded places
├── calibrations: List[Dict] — calibration records
├── raw_tags: Dict[str, List[Dict]] — raw tag occurrences
├── signatures: List[Dict]
├── gnss_ad_records: List[Dict] — G2.2 GNSS accumulated driving
├── load_unload_records: List[Dict]
├── trailer_registrations: List[Dict]
├── gnss_places: List[Dict]
├── load_sensor_data: List[Dict]
├── border_crossings: List[Dict]
└── signed_daily_records: List[Dict]
```

`build_generations_tree()` (line 113) organizes results into a hierarchical view: `{Generation 1: {...}, Generation 2: {...}, Generation 2.2: {...}}`.

### SignatureValidator (`signature_validator.py:10`)

Validates digital certificate chains. Supports RSA (G1/G2) and ECDSA (G2). Hierarchy:
- **ERCA** (European Root Certificate Authority) — root certificates in `certs/`
- **MSCA** (Member State Certificate Authority) — intermediate certificates
- **Card/VU** — leaf certificates signed by MSCA

### Export Layer

- **ExportManager** (`export_manager.py:5`): Multi-sheet Excel (Riepilogo, Attività Giornaliere) and CSV export

### GUI Layer

- **gui_tree.py**: Desktop application (tkinter/ttk). Regedit-style section tree on the left, Excel-style data table on the right (sortable columns, text filter). Data-driven: sections are derived from the parser output.
- **tacho_cli.py** (`tacho_cli.py:14`): CLI with `--json`, `--excel`, `--all`, `--summary` flags
