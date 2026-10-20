# Normative completion — what is spec-verified, what is inferred

This document records one batch of work: completing the two standard structures
that the parser was cutting short, and making every remaining *guessed* field say
out loud that it is a guess. It is deliberately specific about the line between
the two, because "the bytes were all accounted for" is not the same claim as
"the bytes all have a regulatory meaning".

Read it together with [`specs.md`](./specs.md) (where tag specifications and
their verification status live) and [`parsing_pipeline.md`](./parsing_pipeline.md)
(how the walks work).

## 1. The rule this batch implements

1. **A layout that the regulation specifies is decoded from the regulation**, by
   exact offsets, and is never reached through a recovery heuristic.
2. **A layout that only *fits* the samples is not normative.** If no Annex 1B /
   Annex 1C structure describes it, the bytes are preserved and the field kinds
   are labelled as an empirical reading — not presented as a decoded fact.
3. **Guesses are marked where they are made.** A synthesized record carries
   `confidence: low` on the record itself (not only in `metadata`), and the
   section is listed in `metadata.heuristic_fields` with a WARNING when a decode
   route actually switched — a valid download that fell back from nothing is
   never declared, however uncertain the bytes it carries (see §4).
4. **Nothing that was already correct changes.** This batch only *adds* fields
   and confidence metadata; no previously reported value, count or relationship
   was modified.

## 2. Verified source references

All quotations below were read from the consolidated texts in the batch's
`.audit/spec` working directory (not committed):

| Reference | Where | Establishes |
|---|---|---|
| Reg. 3821/85, Annex 1B §2.120 | `annex1b-1360-2002.txt`, printed pp. 86-87 | `VuCardIWRecord` field order (G1) |
| Annex 1B §2.85 | printed p. 79 | `PreviousVehicleInfo ::= SEQUENCE { vehicleRegistrationIdentification, cardWithdrawalTime }` |
| Annex 1B §2.114 | printed p. 84 (p. 86 is §2.120) | `VehicleRegistrationNumber ::= SEQUENCE { codePage INTEGER (0..255), vehicleRegNumber OCTET STRING (SIZE(13)) }` |
| Annex 1B §2.66 | printed p. 73 | `ManualInputFlag ::= INTEGER { noEntry(0), manualEntries(1) }` — "Value assignment: not further specified" |
| Reg. EU 2016/799, Annex 1C §2.177 | L 139/144-145 | `VuCardIWRecord` for generation 2: G1 structure **plus** a 19-byte `fullCardNumberAndGeneration` |
| Annex 1C §2.118 | L 139/126-127 | `PreviousVehicleInfo` — generation 1 structure, and "In addition to generation 1 the following data element is used: `vuGeneration`" |
| Annex 1C §2.167 / §2.93 | L 139/140, L 139/121 | `VehicleRegistrationNumber` (codePage + 13 characters) and `ManualInputFlag` |
| Annex 1B Appendix 1 §2.132 | `annex1b-1360-2002.txt`, printed pp. 89-90 | `VuEventRecord`: `eventType eventPurpose begin end driverBegin coDriverBegin driverEnd coDriverEnd similarEvents` (four card slots, DDP_031) |
| Annex 1B Appendix 1 §2.28 | printed p. 62 | `CardSlotsStatus ::= OCTET STRING (SIZE(1))`, octet aligned `'ccccdddd'B` — `cccc` co-driver slot card type, `dddd` driver slot card type; `0000` none, `0001` driver, `0010` workshop, `0011` control, `0100` company, `0101`..`1111` unassigned |
| Annex 1C §4.5.3.2.x | L 139/59-63 | the §4.5.3.2.x numbering is *card EF* (tachograph application) layout, starting with §4.5.3.2.1 "Application identification" |

Two consequences worth stating explicitly:

* **`Annex 1B §4.5.3.2.1` does not exist.** Annex 1B §4.5.3 is "Stored data
  integrity"; the four-level §4.5.3.2.x numbering belongs to Annex 1C card
  files. A docstring that cited it as the source of the sensor-download layout
  was therefore wrong and has been removed (see §4).
* **Neither regulation defines a "sensor download" payload.** There is no
  official byte map to demonstrate, so the layout kept in the code stays an
  empirical reading, labelled as such.

## 3. `VuCardIWRecord` — completed in both generations

`VuCardIWRecord` records one card insertion/withdrawal cycle: holder name, full
card number, expiry, insertion time + odometer, card slot, withdrawal time +
odometer, **the previous vehicle the driver used**, and **a manual-input flag**.

Both generations share the whole body; the tail is generation-specific:

| # | Field | G1 offset | G2 offset |
|---|-------|-----------|-----------|
| 1 | `holderSurname` (36) | 0 | 0 |
| 2 | `holderFirstNames` (36) | 36 | 36 |
| 3 | `fullCardNumber` (18) / `fullCardNumberAndGeneration` (19) | 72 | 72 |
| 4 | `cardExpiryDate` (4) | 90 | 91 |
| 5 | `cardInsertionTime` (4) | 94 | 95 |
| 6 | `vehicleOdometerValueAtInsertion` (3) | 98 | 99 |
| 7 | `cardSlotNumber` (1) | 101 | 102 |
| 8 | `cardWithdrawalTime` (4) | 102 | 103 |
| 9 | `vehicleOdometerValueAtWithdrawal` (3) | 106 | 107 |
| 10 | `previousVehicleInfo` (19 / 20) | 109 | 110 |
| 11 | `manualInputFlag` (1) | 128 | 130 |
| | **record size** | **129** | **131** |

Inside `previousVehicleInfo`:

| Field | Relative offset |
|---|---|
| `vehicleRegistrationNation` (NationNumeric, 1) | 0 |
| `vehicleRegistrationNumber.codePage` (1) | 1 |
| `vehicleRegistrationNumber.vehicleRegNumber` (13) | 2 |
| `cardWithdrawalTime` (TimeReal, 4) | 15 |
| `vuGeneration` (1) — **generation 2 only** | 19 |

### What the parser now emits

`core/decoders/vu_g1.py::_parse_trep_02_g1_structured` (G1) and
`core/parser/vu_dispatcher.py::decode_card_iw` (G2) add, per record:

* `previous_vehicle` — `registration_nation`, `registration_nation_code`,
  `registration_code_page`, `registration_plate`, `card_withdrawal_time`,
  `card_withdrawal_timestamp`, and (G2 only) `vu_generation`.
  The plate is decoded through the **declared code page**, so accented letters
  survive (`core/decoders/common.py::decode_coded_text`); an unknown code page
  falls back to latin-1, exactly like the existing string decoder.
* `manual_input_flag` — the **numeric** byte, plus `manual_input_flag_meaning`
  which is `noEntry` only for `0`, `manualEntries` only for `1`, and
  `undefined (not a ManualInputFlag value)` for everything else. The flag is an
  enumeration, not a boolean: `bool(byte)` used to report a reserved value as
  "manual entries", which was a claim the regulation does not support.
* `record_complete` — whether the record has the full normative length.

G1 keeps its existing `manual_input` boolean unchanged for backward
compatibility (the day-detail view reads it); the numeric flag now sits beside
it so the two can never be confused.

**Previous vehicle stays per record.** It describes the vehicle *that driver*
used before this insertion, so it is stored on the IW record. The file-level
`vehicle` mapping (current VIN / plate / nation) is never written from it — a
test pins that a body with two different previous vehicles leaves
`results["vehicle"]` untouched.

### Non-canonical lengths

| G2 record length | Result |
|---|---|
| 131 | Full decode, `confidence: high`, `record_complete: true` |
| < 110 | Not a `VuCardIWRecord` (`None`) — nothing is decoded from a fragment |
| 110…130 | Prefix decoded (unchanged between generations), `confidence: low`, `record_complete: false`, `missing_bytes`, and the bytes that *are* present in the tail in `raw_tail_hex`. The previous-vehicle fields are **not** emitted: a 20-byte structure cannot be proven from fewer bytes |
| > 131 | The 131 normative bytes are decoded, but the record is not a canonical `VuCardIWRecord`: `confidence: low`, `record_complete: false`, and the extension is preserved verbatim in `raw_tail_hex` / `raw_tail_bytes` with no interpretation |

In short: a record **shorter** than 131 bytes keeps the old prefix and its
uncovered bytes stay raw (the previous-vehicle block is *not* decoded from a
fragment); a record **longer** than 131 bytes has its 131 standard bytes decoded
— previous vehicle and flag included — and only the extension stays raw. Both
are reported incomplete and `confidence: low`, because neither is a canonical
`VuCardIWRecord`.

Generation 1 records are walked at a fixed 129-byte stride, so they are always
complete by construction.

## 3b. `VuEventRecord` — all four card slots (Gen1)

A `VuEventRecord` (Annex 1B Appendix 1 §2.132; DDP_031 fixes the per-TREP
layout) carries **four** `FullCardNumber` fields, in this order after
`beginTime`/`endTime`: the driver and co-driver cards as they were at the
beginning of the event, then the driver and co-driver cards at its end, followed
by `similarEvents`. The Gen1 emitter
(`core/decoders/vu_g1.py::_parse_trep_03_structured`) copied only
`card_driver_begin`, so three of the four cards the vehicle unit recorded were
lost.

The emitter now copies all four, under the key names the Gen2 emitter already
uses — `card_driver_begin`, `card_codriver_begin`, `card_driver_end`,
`card_codriver_end`. **A Gen1 event table therefore shows three more card
columns** (`Card Codriver Begin`, `Card Driver End`, `Card Codriver End`); those
heads already exist for Gen2 events, so no new *label text* is introduced and no
catalog entry is needed (the corpus-wide column union is unchanged — that is
what the column probe compares, and it is identical to the pre-batch baseline).

In a Gen1 download an empty slot renders with the filler the existing
`card_driver_begin` column already shows — nation `WLD` / "No information
available" — where a Gen2 table shows an em dash. That difference is
**pre-existing and was not changed here**: normalising it would alter a column
the owner already sees today.

On the real corpus this adds exactly the three missing keys to the 112 Gen1
events; the dedup key (`type`, `begin`, `end`, `purpose`) is untouched, and a
test pins that two identical records still collapse to one.

Deliberately **not** changed: the emergency heuristic emitters
(`_parse_trep_03_events_faults_heuristic`, both its record-boundary and its
byte-scan branch) still publish only `card_driver_begin`. Those records are
synthesized from a guessed offset, so filling in four inferred card numbers
would present guesses as data; the omission there is reported, not "fixed".

## 3c. `CardSlotsStatus` — two nibbles, not two bits (Gen1 Overview)

`CardSlotsStatus` (Annex 1B Appendix 1 §2.28) is one octet, octet aligned
`'ccccdddd'B`: the **high nibble is the card type in the co-driver slot**, the
low nibble the type in the **driver** slot. `0000` means no card, `0001` driver,
`0010` workshop, `0011` control, `0100` company card, and `0101`..`1111` are
unassigned.

The decoder used to test bit 0 for the driver slot and bit 1 for the co-driver
slot, which is not that layout: for `0x41` (a card in both slots) it reported the
co-driver slot as *empty*. It now reads the two nibbles
(`core/decoders/vu_g1.py::_card_slot_state`), keeping the published result shape
exactly — the same two keys plus `raw` — and it *extends* the value vocabulary
with a third word, `reserved`, for the unassigned codes `0101`..`1111`. Before,
those codes read as `occupied` or `empty` by accident (whatever bit 0/bit 1
happened to say); now they are reported as unassigned and never guessed into a
card type, because naming the type on screen would be new UI text. On the corpus the two files whose status byte is `0x41` now report
`codriver_slot: occupied`; `driver_slot` did not change anywhere.

## 4. The empirical exception: the TREP 0x11 sensor payload

`core/decoders/vu_g1.py::_parse_sensor_download` recovers a sensor identification
block and per-day speed statistics from a section that some vehicle units emit.
**No regulation describes this payload**, so:

* the false citation of `Annex 1B §4.5.3.2.1` was removed, and the docstrings now
  state plainly that the layout is a manufacturer extension;
* the recovery was **kept** — the values are real data the unit stored, and
  deleting a working recovery would lose evidence, not gain truth;
* everything it produces is labelled: `sensor_info["confidence"] = "low"` and
  every `sensor_daily_records` record `confidence: low`, carried to the JSON
  export;
* it is **not** declared as a heuristic fallback: no
  `metadata.heuristic_fields` entry and no WARNING. A valid, intact download did
  not fall back from anything here — TRTP `11`..`1F` are manufacturer-specific,
  so there is no normative layout that could have failed. The low-confidence
  marker carries the uncertainty; the "values were recovered heuristically"
  banner would be a false alarm on a healthy file;
* the original payload is still available untouched through `raw_tags`.

`tests/unit/test_vu_event_fault_conformance.py::TestPrivateCorpus` therefore stays
strict — `metadata.heuristic_fields` is empty and `decode_paths.fallback` is false
for **all 19** real files — and the sensor test in
`tests/unit/test_vu_g1_heuristic_labelling.py` asserts the low-confidence labels,
the absence of the metadata entry and the absence of a WARNING together.

## 5. Inferred records are now labelled at the record

Gen1 has a deterministic walk per TREP and, behind it, emergency scans for
non-standard or damaged downloads. The scans stay — they are the only thing that
recovers a driver from a malformed day — but every record they synthesize now
carries `confidence: low` where it is appended:

| Section | Synthesis | `metadata.heuristic_fields` key |
|---|---|---|
| `activities`, `inserted_drivers` | TREP 02 timestamp scan | `vu_activities_TREP02` |
| `events`, `faults`, `inserted_drivers` | TREP 03 record-boundary / byte scan | `vu_events_faults_TREP03` |
| `calibrations` | TREP 05 VIN-scan reconstruction | `vu_technical_TREP05` |
| `card_downloads`, `inserted_drivers` | TREP 06 pattern scan | `vu_card_download_TREP06` |
| `sensor_info`, `sensor_daily_records` | TREP 0x11 empirical payload | `vu_sensor_download` |

Two behaviours deserve a note:

* **The TREP 03 wrapper measures the driver too.** It used to compare only
  `events` and `faults`, so a scan that recovered a card holder and nothing else
  changed the results silently: no `heuristic_fields` entry, no WARNING. A
  driver-only gain is now declared and logged like any other.
* **The deterministic paths are unchanged and unlabelled.** A record decoded by
  the Annex 1B/1C layout carries no `confidence` key at all, so the absence of
  the marker keeps meaning "read from the standard". Negative tests assert this
  for TREP 02, 03, 05 and 06.

## 6. Proprietary and unsupported content stays raw

This batch did not add any new interpretation of manufacturer-specific data.
Where a record type or a byte range has no Annex 1C meaning, the existing rules
still hold and are worth restating:

* record types above `0x24` (RFU / manufacturer-specific) are reported with
  `normative: false` (`core/parser/vu_dispatcher.py::is_normative_record_type`);
* unknown trailing bytes are surfaced as hex (`raw_hex`, `raw_tail_hex`,
  `payload_hex`) instead of being decoded;
* `raw_tags` keeps the original bytes of every container;
* the sensor payload above is the worked example: decoded values *and* the raw
  payload, both labelled for what they are.

## 7. What the coverage audits do **not** claim

`scripts/coverage_audit.py` and `scripts/semantic_coverage_audit.py` answer
"were these bytes accounted for / semantically decoded?", not "is this
interpretation correct?". A file can reach 100 % tracked coverage while sections
of it are read by an empirical heuristic. Therefore:

* **100 % coverage is not a normative statement.** It never was, and this batch
  does not claim "all bytes are normative". The normative claim is made per
  structure, with its Annex reference, and only where the reference exists.
* The semantic audit cannot see *meaning*: a field name invented by a heuristic
  counts as decoded, which is why the record-level `confidence` marker and
  `metadata.heuristic_fields` — not coverage numbers — are the signal a consumer
  should use to separate fact from inference.
* Coverage also cannot see a *dropped* field: the old `VuCardIWRecord` walk read
  the whole record, so the bytes were "covered", while the previous-vehicle tail
  was silently discarded. Checking an offset table against the regulation is
  what catches that class of defect, which is what §3 does.

## 8. Scope of this batch

Implemented:

* `VuCardIWRecord` tails, both generations (offsets, code page, numeric flag,
  completeness/confidence markers).
* `confidence: low` at every Gen1 heuristic append site, and TREP 03 driver-only
  gain detection.
* Removal of the false sensor citation; labelling of the empirical sensor
  payload.
* `VuEventRecord`: the three missing Gen1 card slots (§3b).
* `CardSlotsStatus`: the two nibbles read as specified (§3c).
* Regression tests: `tests/unit/test_vu_card_iw_record_tail.py`,
  `tests/unit/test_vu_card_iw_reporting_surface.py`,
  `tests/unit/test_vu_g1_heuristic_labelling.py`,
  `tests/unit/test_vu_g1_event_slots_and_card_status.py`.

### The new fields are in the model and the JSON — and hidden from the tables

The `VuCardIWRecord` tail fields (`previous_vehicle`, `manual_input_flag`,
`manual_input_flag_meaning`, `record_bytes`, `record_complete`, `missing_bytes`,
`raw_tail_bytes`) are decoded data: they live on the record, appear in the JSON
export and are available to any consumer. They are **deliberately not** table or
report columns. The owner's rule is that the on-screen layout is preserved
exactly, and every new visible head would first need a translated label in all
33 locale catalogs — which nobody has produced. So the keys are listed in both
hidden-key sets (`core/utils/report_format.HIDDEN_KEYS`, `app/gui.HIDDEN_KEYS`),
exactly like `confidence`, `raw_hex` and the event/fault conformance bookkeeping,
and `tests/unit/test_vu_card_iw_reporting_surface.py` asserts that
`visible_columns()` of a record carrying them equals `visible_columns()` of the
same record without them.

Showing these fields is a *separate owner decision*: it needs 33 catalog entries
first, and it is not made here.

### Not done / deferred (recorded, not implemented)

* **Seal + serial subfield splitting** in the G2/G2.2 calibration extension
  (Annex 1C §2.71 `SealDataVu` / §2.72 `SealRecord` are currently read as raw
  hex, not as `equipmentType` + `extendedSealIdentifier` per seal).
* **`SensorPaired` (recordType 0x07)** — the G1 `SensorPaired` body is surfaced
  with a name and size but without a field-level decode.
* **The Gen1 calibration record dropped by the VIN / L-constant gates**: one
  sample declares 15 `VuCalibrationRecord`s and the parser emits 14, because
  `_decode_cal_record` rejects a record whose VIN or `lTyreCircumference` fails
  its plausibility gate. Tightening or relaxing that gate is a separate
  decision about a real value, so it was left alone.
* **Card-type names from `CardSlotsStatus`** (`0001` driver … `0100` company) —
  kept as `empty`/`occupied`/`reserved` on purpose (§3c): naming them would add
  user-visible text.
* **The workshop-card type of the Gen1 calibration** — the record's workshop
  `FullCardNumber` type byte is decoded but not interpreted into a card-type
  name.
* **The `Annex 1B §2.2.6.6` citation for TREP 06** — the TREP 06 body is an
  embedded card image rather than a structure the Annex lays out field by field,
  so that reference should be re-checked before it is relied on again.
* A full field-by-field conformance verdict for every VU record type — the
  per-record `normative` verdict remains limited to Gen2 events and faults.
* A decoding of the sensor payload at a documented layout (none exists).
* **`decode_coded_text` inherits `decode_string`'s code-page table**, which has no
  KOI8-R/KOI8-U (codes `80`/`85`), and it strips a trailing `0xFF` byte that
  could in principle be a legal character. Both are shared with the pre-existing
  string decoder and were not changed here.
* **The Gen1 `manual_input` boolean** (kept for the day-detail view) is still
  `true` for the reserved flag values; the faithful fields are the numeric
  `manual_input_flag` and `manual_input_flag_meaning`.
* **`scripts/tachograph.asn` and `scripts/g2_g22_complete_structures.md`** still
  describe a different `VuCardIWRecord` layout and were not touched by this
  batch — read §3 above, not those files, for the decoded layout.
* **The Gen1 empty-slot filler in event card columns** (nation `WLD` / "No
  information available" instead of Gen2's em dash): pre-existing, left alone
  because normalising it would change a column the owner sees today.

No user-facing prose was added in any of this: locale catalogs are untouched.
The one place where the UI *content* changed is `CardSlotsStatus`: the same two
keys are now read from the nibbles the regulation specifies (corrected values),
and the value vocabulary gained the third word `reserved` for the unassigned
codes `0101`..`1111` — codes that previously read as `occupied`/`empty` by
accident.
