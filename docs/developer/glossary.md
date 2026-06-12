# Glossary

## File Formats & Encoding

**DDD** — Digital Driver Data file. The binary download format produced by EU digital tachographs. Contains driver card data, vehicle unit (VU) records, GNSS positions, and security certificate chains.

**STAP** (Secure Tag Application Protocol) — G1 encoding format. Each record has a fixed 5-byte T2L2 header: 2 bytes tag (big-endian), 1 byte data type, 2 bytes length (big-endian), followed by the payload. Used in Annex 1B tachographs.

**BER-TLV** (Basic Encoding Rules — Tag Length Value) — G2/G2.2 encoding format. Variable-length tags and lengths per ASN.1 BER. Tags can span multiple bytes (bit 5 extension), lengths use short form (< 128) or long form (1-3 subsequent bytes). Used in Annex 1C tachographs.

**ASN.1** (Abstract Syntax Notation One) — Formal interface description language used to define the tachograph data model. The schema is in `specs/tachograph.asn`.

**T2L2** — The 5-byte STAP header format: Tag (2 bytes), Type (1 byte, formerly "L/T"), Length (2 bytes). Sometimes referred to as "T1L2" in older documentation.

**RecordArray** — G2 VU data format defined in Annex 1C Appendix 7. A 4-byte header: record count (2 bytes) + record size (2 bytes), followed by fixed-size records.

**TREP** (Transfer Representation) — Encoding used in VU download messages. Activity data in TREP format starts with `0x6864` marker byte sequence.

## Tachograph Generations

**G1 (Generation 1)** — Digital tachograph per Reg. 3821/85 Annex 1B. Uses STAP encoding. First byte of the file is not `0x76`. Tags: `0x0001`-`0x0005`, `0x0501`-`0x0522`, `0x7601`-`0x7605`.

**G2 (Generation 2)** — Smart tachograph per Reg. EU 2016/799 Annex 1C. Uses BER-TLV encoding. Files start with `0x7621` or `0x7622`. Tags include `0x0101`-`0x0201`, `0x0509`-`0x0524`, `0x7621`-`0x7634`.

**G2.2 (Generation 2.2)** — Smart tachograph V2 per Reg. EU 2023/980. Uses BER-TLV encoding. Files start with `0x7631`. Adds GNSS accumulated driving, load/unload operations, trailer registrations, enhanced GNSS places, load sensor data, border crossings.

## Equipment

**VU** (Vehicle Unit) — The tachograph unit installed in the vehicle. Records driver activity, vehicle speed, GNSS positions, and events.

**Driver Card** — Smart card inserted into the VU by the driver. Stores personal identification, driving licence info, activity data (28+ days), events, and faults.

**Company Card** — Smart card used by fleet operators to lock/unlock VU data and download company-specific records.

**Control Card** — Smart card used by enforcement authorities for roadside inspections. Has read access to all VU data.

## Certificate Authorities

**ERCA** (European Root Certificate Authority) — The root of trust for tachograph certificate chains. ERCA certificates are distributed as PEM files in `certs/`.

**MSCA** (Member State Certificate Authority) — National-level CA that issues card and VU certificates. Each EU member state operates its own MSCA. MSCA certificates are signed by ERCA.

**Certificate Chain** — The hierarchy: ERCA (root) → MSCA (intermediate) → Card/VU (leaf). Validated by `SignatureValidator.validate_tacho_chain()` (`signature_validator.py:187`).

## Core Architecture Components

**TachoParser** (`ddd_parser.py`) — Entry point class. Orchestrates the parse pipeline in named phases: structural parse, VU semantic decoding, activity dedup, certificate chain and EF signature verification.

**TachoResult** (`core/models.py:43`) — Main data model dataclass. Contains all parsed data: metadata, driver info, vehicle info, activities, events, faults, locations, raw tags, and G2.2-specific records.

**VuRecordDispatcher** (`core/vu_record_dispatcher.py`) — Walks G2/G2.2 VU downloads as RecordArray sections keyed by recordType (Annex 1C Appendix 7), used for both structural coverage and semantic decoding.

**G1VuWalker** (`core/g1_vu_walker.py`) — Deterministic SID/TREP message walk for G1 VU downloads (Annex 1B §2.2.6), including per-message RSA signatures.

**DecoderRegistry** (`core/decoder_registry.py:28`) — Centralized registry mapping tag IDs to decoder functions. Each entry contains metadata: container flag, record size, annex reference, generation, card/VU scope.

**DeterministicParser** (`core/deterministic_parser.py`) — The structural parser. Guarantees 100% byte coverage through sequential parsing with `CoverageTracker`; routes VU downloads to the dedicated stream walkers.

**CoverageTracker** (`core/deterministic_parser.py:18`) — Tracks covered byte ranges, classifies them (Tag, Padding, Unknown), and produces coverage reports.

## Data Fields & Records

**Activity Data (Cyclic Buffer)** — G1 tag `0x0504`, G2 tag `0x0524`. Stores daily driver activity records (activity changes per minute), odometer readings, and timestamps in a circular buffer format.

**Events Data** — G1 tag `0x0502`. Records security events: card insertion/withdrawal, power interruptions, motion sensor faults, speed violations.

**Faults Data** — G1 tag `0x0503`. Records equipment faults: card communication errors, GNSS receiver faults, display malfunctions.

**Vehicles Used** — G1 tag `0x0505` (31-byte records), G2 tag `0x0523` (35-byte records). Logs of vehicles the driver has used, with odometer readings at start/end and timestamps.

**Places** — G1 tag `0x0506`. Records start/end locations of daily work periods with nation, timestamp, and odometer.

**Calibration Data** — G1 tag `0x050C`. Tachograph calibration records with workshop info, VIN, and timestamps.

**GNSS Accumulated Driving** — G2.2 tag `0x0525`. Records GNSS positions accumulated over driving periods. Contains timestamps, coordinates, and odometer values.

**Load/Unload Operations** — G2.2 tag `0x0526`. Records cargo loading and unloading events with timestamps and vehicle state.

**Trailer Registrations** — G2.2 tag `0x0527`. Records trailers attached to the vehicle with registration numbers and timestamps.

**GNSS Enhanced Places** — G2.2 tag `0x0528`. Enhanced GNSS place records per Annex 1C §2.79c.

**Load Sensor Data** — G2.2 tag `0x0529`. Load sensor readings from vehicles equipped with load sensing devices.

**Border Crossings** — G2.2 tag `0x052A`. Records of international border crossings detected via GNSS, required for cabotage enforcement.

## Regulations

**EU 561/2006** — The main driving and rest time regulation (4.5h continuous driving limit, daily/weekly rest minimums). Background context only: this project parses recorded activities but does **not** evaluate driving-time rules.

## Other Terms

**GNSS** — Global Navigation Satellite System (GPS + Galileo). Used for position recording and border crossing detection.

**ITS** (Intelligent Transport Systems) — G2 VU record type `0x0512`. Records consent data for ITS communication interfaces.

**IW** (Identification Workshop) — Workshops authorized to install, calibrate, and inspect tachographs. Records stored as VuCardIWRecord (`0x050A`).

**SID** (Service Identifier) — Byte marker used in VU download message format. `0x76` = VU download data.

**TACHO_TAGS** — Default tag name dictionary loaded from `core/tag_definitions.py`. Maps tag IDs to human-readable names. Can be extended via `all_tacho_tags.json`.

**DType** — Data type byte in STAP headers. Values: 0=raw, 1=certificate/signature, 3=encrypted, 6=G2 daily activity, 11/15=signature blocks.

**CodePage** — First byte of string fields indicating the character encoding (Annex 1B/1C). Common values: `0x01`=Latin-1, `0x02`=ISO-8859-2, etc.

**TimeReal** — 4-byte Unix timestamp (seconds since 1970-01-01). Used for most tachograph date/time fields.

**Datef** — 4-byte BCD-encoded date (YYMMDD format). Used for certain card fields like birth date.
