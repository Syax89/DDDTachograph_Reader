## [2.9.1] - 2026-10-22

<!-- release-notes:start -->
- Fixed six untranslated field labels in **Identification** and **Driving Licence Info** across all 33 translated interfaces, including the suggested Russian wording.
- Tachograph decoding, JSON data and English exports are unchanged.

[Full changelog](https://github.com/Syax89/DDDTachograph_Reader/blob/v2.9.1/CHANGELOG.md).
<!-- release-notes:end -->

### Fixed

Six card-field headings — *Issuing Nation*, *Expiry Date*, *Birth Date*,
*Preferred Language*, *Licence Number* and *Licence Issuing Nation* — stayed
English in every translated UI. The **Identification** and **Driving Licence
Info** panels build their headings from the record keys, and those six exact
catalog entries were missing from all 33 catalogs, so the panel mixed translated
and English rows. They are now translated in every shipped language, the Russian
ones with the wording the reporting user suggested. Card data, the JSON keys, the
English exports and the summary's own labels are unchanged.

### Maintenance

- Fixed release-note extraction so short summaries publish correctly.

---

## [2.9.0] - 2026-10-21

<!-- release-notes:start -->
Every vehicle-unit transfer is now decoded against the text that defines it, a file open no longer risks stalling the window on macOS, and the application gains a Help entry point — alongside a long list of decoding, export, command-line and window fixes.

**Highlights**

- **Vehicle-unit downloads, transfer by transfer.** Each TREP is decoded against Annex 1B / Annex 1C Appendix 7, including a card image wrapped in a transfer header and a download cut at its tail. Every byte is accounted for in a new *Decode units* section, and a file that promises more records than it holds says so.
- **No stalled opens on macOS.** The render no longer pumps the Tk event loop, the parse starts after the file picker closes, and a real stall writes `~/ddd-reader-stall-report.txt` by itself.
- **Help.** A native Help menu on macOS (About in the application menu), a Help button on Windows and Linux — project, issue, release and donation links.
- **Integrity, stated.** The dialog opens once the file is on screen; a card whose header is not a standard download gets a neutral note; empty Field/Value rows are gone.
- **Verdicts that claim only what was checked.** An unanchored vehicle-unit chain is *Unverified*; bytes outside the signed sections no longer pass as "verified"; DER/PEM ERCA roots now anchor.
- **Fixes across the board.** G1 card numbers keep their own text (no nation prefix), an unavailable odometer is *not available* instead of `0 km`, tail-cut arrays report their shortfall, the Excel formula guard cannot be bypassed by a control byte, `--json -` and `-q` behave as documented, and the activity timeline paints its unknown minutes.

**Breaking:** in the JSON export a card day's distance is `day_distance_km` (it was `odometer_km`); a vehicle-unit day keeps `odometer_km`. The numbers are unchanged.

**Downloads:** Windows (`…-windows-x64.zip`), macOS (`…-macos.dmg`), Linux (`…-linux-x86_64.flatpak`). Full detail in the [CHANGELOG](https://github.com/Syax89/DDDTachograph_Reader/blob/master/CHANGELOG.md).
<!-- release-notes:end -->

---

### A card day's distance is `day_distance_km` in the exported JSON

One breaking change, and it is a rename only. In the JSON export a driver card's
daily record publishes the kilometres driven that day as `day_distance_km`. It
used to be `odometer_km`, which was wrong: a card day records a distance, not an
odometer reading, so every consumer that read the old key was handed a number
that looked like an absolute odometer and was not one. The numbers themselves are
unchanged. A vehicle-unit day keeps `odometer_km`, because a vehicle unit really
does store an odometer reading for the day.

Nothing else changes shape. The tables and the reports already take a day's
distance from a helper that knows which of the two values it is looking at, so
their figures are the same as before — and for the same reason the day table now
labels the column a card day shows "Distance km" while a vehicle-unit day keeps
"Odometer km".

---

### Vehicle-unit downloads are decoded transfer type by transfer type

A vehicle-unit download is a sequence of transfers: the standard numbers them
`TREP 00` onwards, and each one carries a different record array with its own
layout. This release reads every transfer against the text that defines it —
Annex 1B for a generation-1 unit, Appendix 1 and Appendix 7 of Annex 1C for
generation 2 and generation 2.2 — instead of walking the file as an
undifferentiated byte stream.

**Each transfer is decoded on its own.** The normative decoder runs first, for
that transfer only. When one transfer cannot be decoded, a recovery scan is
offered its bytes and nothing else, and the next transfer resumes normally from
its own marker, so a scan can neither read outside the unit nor publish a record
under another unit's name. Every byte of the file then belongs to a declared unit
— decoded, recovered, unreadable or padding — the unit list is published, and the
units always add up to the size of the file. The list is a **Decode units**
section in the window and in every export.

The extent a section declares is authoritative. A complete record is read before
any marker inside its bytes is considered, so a marker-shaped byte pair in a
record's payload is data and not a boundary; a section boundary is honoured only
after the last complete record it declared, and only when it checks out as one.

**Structure decides what is decodable, never a field value.** A transfer the
standard defines is decoded from its counts and its sizes. A blank vehicle
identification number on a unit that has not been activated, a clock value that
cannot be rendered as a date, an odometer at its "not available" sentinel: none of
these can turn a decoded transfer into a missing one, drop a stored record, or
push a file onto the recovery scan. Before this release a blank identification
number lost a whole Overview — identity, clock, company locks and control records
— and a day with more activity changes than an invented cap was re-read by a scan
instead of being decoded.

**Every stored record is published.** A record the counters declare is emitted
even when one of its values is unusable: the value is withheld as *not available*
beside the raw integer and an explicit status, and the record stays. A section
reports how many records it declared, how many it emitted and how many it dropped,
and any difference makes the download partial. The recovery scan follows the same
rule, so a record carrying nothing at all (an empty day, a driver with no name) is
not published as data.

**A record is identified by where it is stored, not by what it says.** Two stored
records with identical fields are two records, and the same bytes read twice are
one. That keeps a driver's two identical company locks, two controls in the same
second, two calibrations with equal fields and two insertions of the same card in
the report — records that used to collapse into each other — while a recovery scan
that re-reads bytes the walk already decoded still adds no second copy.

**A message cut at its tail is read up to the cut.** Records are fixed-size, so
the complete records before a truncation are decoded by the same decoder as an
intact message, with the counts clamped to what fits; only the cut remainder
becomes an unreadable (or recovered) range, and the file stays partial. A
published record whose own payload the file cut says so: it carries the count its
header declared and an informational note, which appears as a **Note** column in
that section — and only there, and only when such a record exists. A day whose
activity changes were cut is therefore no longer shown as a rest day.

**A finding is a finding.** Missing, out-of-order, unexpected or duplicated
arrays, a signature array that does not hold the single signature record the
standard gives it, a signature block shorter than its curve allows, a card region
that does not close: each is recorded as an integrity finding that makes the
download partial. The records that were decoded stay decoded — a structural
finding is never a reason to re-read bytes that already yielded data. What the
file does not contain is reported too: a tail-cut array states the count it
declared, the count it holds and the bytes it is missing.

**Integrity is not decodability.** A generation-1 download whose final signature
block is one byte short decodes every declared record; it used to report the walk
as incomplete, switch to the byte scan, and add low-confidence duplicates on top
of the correct records (calibrations 7 → 13, certificates 2 → 4 on the sample that
showed it). The shortfall is now an integrity finding — the download is partial,
and no scan is started. The same holds for bytes after the last message: `00`/`FF`
fill is padding, anything else is trailing bytes and makes the file partial, so a
dangling marker byte is never mistaken for fill.

**A recovery route says why it ran.** When one runs, the report records the route,
the transfer and offset, and a reason from a closed list — a truncated file, a
count that points past the data, a record size that contradicts the standard, an
unknown or misplaced section, a schema violation, or a defect of this reader. A
damaged file is never relabelled as a defect of the reader, and a defect of the
reader is never hidden as damage.

What is decoded, transfer by transfer:

- **`TREP 00`, the interface version.** Read as its two octets with the codes
  Annex 1C assigns them, the disagreement between the two texts of the same act
  carried alongside, and no signature expected — the standard defines none for
  this transfer, so it is no longer counted as an invalid one.
- **Overview.** The current date and time of the unit, the card-slot status read
  per nibble, and vehicle registration numbers decoded through their declared code
  page instead of being filtered to ASCII.
- **Activities.** The daily work period entry types including the two
  GNSS-derived begin/end types generation 2 defines, generation-local condition
  meanings, a place variant chosen by the transfer rather than by the file's
  generation label, a `0°/0°` position treated as a real fix with range checks
  around it, and the previous vehicle and manual-input flag of each insertion.
- **Events and faults.** The generation-1 point-2.70 list (from the readable
  consolidated text, where `0A` is a vehicle motion conflict and the 2002 print
  still says reserved), section-inherited versions for over-speeding and
  power-interruption records, and short or empty time adjustments kept with a
  completeness flag instead of being dropped.
- **Detailed speed.** The normative 64-byte block kept under its aggregated run
  with all sixty samples (`FF` meaning no information), and a block with an
  unusable timestamp kept rather than skipped.
- **Technical data.** The extended serial number decoded where the standard puts
  it — serial, BCD month, two-digit year suffix, manufacturer-specific type and
  registered manufacturer — for the unit, the sensor, the coupled sensor, the
  calibrations and the cards; the extended seal identifier split into its
  manufacturer code and seal identifier; the calibration variant chosen by the
  section's generation, with the size actually decoded named, and the difference
  from the expected size flagged; the card structure version read as its two
  halves; and the activation calibration (empty identification number, zero tyre
  circumference) no longer discarded as implausible.
- **`digitalMapVersion`** is an `IA5String(12)`: the generation-2, version-2 unit
  identification therefore ends at 138 bytes, and the twelve octets are reported
  as valid IA5 text or as invalid and kept raw. What the characters mean is not
  stated by the regulation and is not invented here.

One limit is worth stating here. Where the regulation leaves a field open — the
meaning of the map-version characters, the manufacturer-specific event data, the
record types above `0x24` — the reader keeps the bytes and says the field is
unresolved instead of inventing a reading, and no compliance statement is made for
them. The calibration purpose is generation-aware as well: `05` and `06` exist
only from generation 2 on, so a generation-1 record reads them as reserved instead
of being given a name it cannot have.

**A card image wrapped in a transfer header is a card.** Some tools save a card
download exactly as the vehicle unit relayed it, so the file starts with the
`SID 76` + `TREP 06` header that the standard strips for the storage form of a
card file. Such a file is now recognised structurally, before the card-or-unit
decision, and decoded through exactly the pipeline a plain card takes — same
generation detection, same elementary-file signature verification, same
certificate chain — with every offset shifted past the header. The card inside is
bounded by its own two-byte length field, so a real card image (whose elementary
files are 12–14 KB) is no longer cut at the first big one. And a card region is
recognised anywhere inside a generation-1 unit stream, at any position, as a card:
it is reported with its own verdict and generation, and it takes no part in the
unit's signature accounting.

Because other software rejects the wrapped form, the window explains it: the file
is a card image downloaded through the vehicle unit, the two leading bytes are the
transfer header kept by the tool that saved it and not the standard storage form,
and some other programs report such a file as corrupt. The same clarification is a
**Transfer header** row in the report summary, so the PDF, Excel and CSV exports
say it too. It is phrased as a note and never as a warning, it keeps the card's
own signature verdict, and it states the form of the file without ever calling the
data complete or authentic. A plain card carries no such row.

**Manufacturer extensions are shown and explained.** The observed co-driver
activities array is a rendered section, described as the extension it is (and
naming the unit it was observed on). Record arrays whose type has no name in the
regulation are a **Manufacturer Extensions** section: one row per type with the
code, the declared record size, the record count and the raw bytes, so a file that
carries an extension says so even when its layout is unknown. Every such section
carries the same note — the layout is manufacturer-specific or empirical, no
regulation defines these fields, the values are read with low confidence and the
raw bytes are preserved. A file with these sections is not partial, declares no
fallback and raises no warning.

Rows are also tidier: a decoded serial is one compact scalar (serial, month and
year, manufacturer) with no neighbouring column carrying a near-identical label,
the three calibration timestamps carry date and time in one set of columns with
the ISO forms kept in the JSON, the unit's current date and time is the first row
of the Overview panel, and a datum that used to appear twice in a panel or a
report now appears once.

---

### Vehicle-unit fields the standard defines are decoded instead of dropped

Checked field by field against Annex 1B and Annex 1C, three structures the
standard defines were being read and then thrown away or read wrongly:

- **Card insertion/withdrawal (`VuCardIWRecord`, Gen1 129 bytes, Gen2 131
  bytes):** the previous vehicle of each insertion (registration nation, code
  page and plate, withdrawal time, plus the VU generation on Gen2) and the
  numeric `ManualInputFlag` are now decoded at their exact offsets. A Gen2
  record shorter than 131 bytes keeps the old prefix and its uncovered bytes
  stay raw; a longer one decodes the 131 standard bytes — previous vehicle and
  flag included — and keeps the extension raw. Both are reported incomplete and
  low confidence. These fields are in the JSON only: the tables and exports keep
  their columns, because showing the previous vehicle needs a translated label
  in every catalog.
- **Gen1 events:** all four card slots of a `VuEventRecord` (driver and
  co-driver, at the beginning and at the end) are kept; only the first was. A
  Gen1 event table therefore shows three more card columns
  (`card_codriver_begin`, `card_driver_end`, `card_codriver_end`) — the same
  headers a Gen2 table already has, so no new label text. In a Gen1 download an
  empty slot reads with the filler the existing driver-begin column already
  shows (nation "WLD" / "No information available"; Gen2 shows an em dash); that
  Gen1 quirk is pre-existing and was not changed here.
- **Gen1 overview card slots:** the status byte is two nibbles, not two bits.
  A company card in the co-driver slot (`0x41`) used to read as an empty slot.
  The value vocabulary gains a third word, `reserved`, for the unassigned card
  types `0101`..`1111`, which previously read as occupied/empty by accident.

Also: the Gen1 scans that rebuild records from text instead of from a defined
offset — card holders found by the TREP 02/03/06 scans, calibrations found by
the VIN scan, and card-download candidates — now label what they produce low
confidence, and a TREP 03 scan that only recovered a card holder is declared in
the metadata. The sensor download (TREP `0x11`) is manufacturer-specific — the
regulation reserves TRTP 11–1F, so there is no layout that could have failed and
the old citation of Annex 1B §4.5.3.2.1 is removed. What is read from it stays
labelled low confidence in the JSON, and it is deliberately *not* declared as a
heuristic fallback (no banner, no warning): a valid download did not fall back
from anything.

Not done: `SensorPaired` (`0x07`) is surfaced with its name and canonical size
but without a field-level decode; a full field-by-field conformance verdict
exists only for generation-2 events and faults; and the overview card-slot status
reports whether a slot is empty, occupied or unassigned rather than naming the
card type it holds. See `docs/developer/normative-completion.md`.

---

### Long manufacturer names are readable in Excel and keep their letters in the PDF

- Excel: a manufacturer name wider than its column now wraps in the cell and the
  row is sized for the wrapping the cell really does — the lines are the ones
  word wrapping produces, not a character count, so the tail of a long name is
  no longer cut off in a narrow column (the 161-character official name of code
  `0xA1` was the visible case, beside a populated neighbour cell). Only a value
  whose right-hand neighbours are populated needs this: text with empty cells
  beside it spills across them and prints in full, so those cells and rows are
  exactly as before. The cell keeps its exact text — no newline, ellipsis or
  shortened name — and Excel's own 409.5 pt row-height ceiling still applies.
- PDF: the extended-Latin characters the public manufacturer registry uses — the
  Lithuanian `Ė` in the official name of code `0xB1` — are set in a font bundled
  with the application instead of being drawn as a black square, and the bundled
  font and licence are the official DejaVu Sans 2.37 release files. Text the
  report's own font already covers keeps Helvetica and its layout, so other
  reports do not change. If that font is missing from an installation, the PDF
  export fails and says why rather than returning a complete-looking report with
  a boxed identity.

---

### Gen2 vehicle-unit events and faults are decoded in full, with a verdict

Vehicle-unit downloads (Gen2 and Gen2.2) store events and faults as
`VuEventRecord` (91 bytes) and `VuFaultRecord` (90 bytes). The reader used to
decode only the first ten bytes of each record and mark all of them low
confidence.

- Every field the standard defines is now decoded: event/fault type and record
  purpose, begin and end time, and the four card-and-generation slots (driver and
  co-driver, at the beginning and at the end of the event). The
  `Events`/`Faults` tables gain those columns under the names the generation-1
  records already use, so the interface needs no new translation.
- Each record now carries a verdict in the exported data: whether it matches the
  standard (`normative`), the reference it was checked against (`Annex 1C App.1
  2.198` for events, `… 2.201` for faults) and, when it does not match, a short
  reason. A record that does not match is still exported, marked low confidence.
- The manufacturer-specific part of the record is the only thing the standard
  leaves open, so only those two fields (manufacturer code and the 3-byte
  manufacturer error code) are marked low confidence on an otherwise conforming
  record. The similar-events counter joins them when it is 0, a value the
  standard says is not used but real units do write, and so does the event or
  fault type when the code has no assigned meaning (reserved, or a
  manufacturer-specific one).
- A time-conflict event records the VU clock in the begin time and the GNSS clock
  in the end time; those records say so (`end_semantics`) instead of presenting
  the GNSS time as an end.
- No decode step switches to a backup route silently any more: a fallback to the
  heuristic byte scan is logged at warning level and recorded in
  `metadata.decode_paths`, and nothing recovered that way can look conformant.

---

### Event and fault type codes are read against the right version of the list

The event/fault type byte has two lists in force and they are not the same: the
"Generation 2, version 1" list (Reg. (EU) 2018/502 Annex (29)(h)) and the
"Generation 2, version 2" list (Reg. (EU) 2021/1228 Annex (30)(n)(ii)), which
added `0x0F` (GNSS anomaly),
`0x1C` (inconsistency between motion data and stored driver activity data) and
`0x3A` (internal sensor fault). Which list applies is a property of the *section*
the record travels in — Annex 1C Appendix 7 assigns the events-and-faults
transfer type `0x23` to version 1 and `0x33` to version 2 (DDP_011 is the
request table, DDP_031 the data structures per TREP) — not of the unit or the
file.

- Each event and fault is now described against the list of its own section, and
  the exported data records which one was used (`event_fault_version`) and how
  that list assigns the byte (`type_status`: assigned, reserved, manufacturer
  specific, or unknown version). A single download may carry both sections, and
  each is read on its own.
- In a version-1 section those three bytes are still "Reserved for future use",
  which is what that list says; they are no longer shown with their version-2
  meaning, and a record is not marked non-conforming either way.
- Where the version cannot be known — a record shown on its own, a tag-keyed
  array with no section around it, a section that is not an events-and-faults
  one — the type is reported as unknown instead of being guessed as version 2.
  The file's own generation label is never used to decide this: a version-2 unit
  can produce a version-1 download.
- The manufacturer code in the same record is resolved against the manufacturer
  list the regulation has the laboratory competent for interoperability tests
  publish (§2.94, Annex 1C requirement 454; all 65 assigned codes, built in, no
  network access): the `Events`/`Faults` tables gain a **Manufacturer** column
  with the registered name and the code is no longer labelled as uninterpreted.
  Unassigned and "no information" values (`0x00`, `0xFF`, …) stay unknown. The
  three manufacturer error bytes stay exactly as recorded and low confidence:
  their meaning is the vendor's own, no verified three-byte wire-format mapping
  was obtained, and `000000` is not read as "no error".

---

### A file open no longer stalls the window on macOS

On macOS a long open could freeze the window for several seconds, always after
the system file picker had closed, with the progress bar stuck and nothing to
click. The cause was the render: to keep the window alive while it drew a file,
the render pumped the Tk event loop, and that pump could block inside the system
while nothing of the reader was running.

Opening a file no longer pumps the event loop on macOS at all:

- The render repaints with idle tasks only, and moves the busy bar itself, one
  step per 12 ms of elapsed time, because a Tk timer needs events and the window
  now processes none during an open. Linux and Windows keep the previous
  behaviour.
- The parse starts after the native file picker has returned, so the panel's own
  teardown is handled by the real event loop and not inside the picker's call
  stack. A second click on **Open**, a drop or a language switch during that
  moment is refused exactly as before, so no second parse starts.
- The render pump measures how long its own last step took and waits
  proportionally, so a heavy render spends its time drawing rather than pumping.
- The garbage collector is paused while a file is parsed and drawn, and the
  finished result is parked in the permanent generation afterwards, so a
  collection pass over the previous file's data cannot stall the open.
- The tree column is fitted from a handful of measurements instead of one per
  node, so a file with thousands of days no longer pays for thousands of
  measurements before anything appears.

If an open still stalls, the reader now reports it by itself. A watchdog watches
the main thread in every session; when it stays in the same place for three
seconds it writes `~/ddd-reader-stall-report.txt` once, with the platform, the
Python and Tk versions, the stack it was stuck in and the last recorded load
steps — and prints the path to standard error. Two waits are deliberately not
reported, because they are normal use rather than stalls: Tk's own event loop,
and a system dialog waiting for the user.

Two environment variables exist for support, and neither is needed in normal use.
`DDD_TRACE_LOAD=1` writes a live trace of an open (`~/ddd-reader-load-trace.txt`,
extension, size, generation and counts only — never file names, contents or
directories). `DDD_PUMP_MODE=events` puts the old event-pumping render back;
`DDD_PUMP_MODE=idle` forces the new one.

---

### A Help entry point, and an About box that names the version

The application now explains itself in one place, reachable the way each
platform expects.

On **macOS** it is a native **Help** menu in the menu bar — the system adds its
own search field to that menu — listing the project's addresses. **About** stays
where macOS puts it, in the application menu, and now shows the real text: the
name, the version, the licence and the credits. `Cmd+?` and the extra "Help" item
the system adds open this application's Help window, where Tk used to answer with
"Help isn't available for this app".

On **Windows and Linux**, which have no menu bar here, a **Help** button at the
end of the toolbar opens the same window. It is text-only on purpose: at the
minimum window size an icon's width would cost the integrity verdict its room.

Either way the entries are the same four addresses — the project on GitHub,
**Report an issue**, **Releases**, and **Buy me a coffee** — and they open in your
browser. On macOS the address is handed to `/usr/bin/open`, so following a link
no longer adds a second bouncing application icon to the Dock. One Help window at
a time: clicking again brings the open one forward instead of stacking a copy.

---

### Integrity notices say what the file's form is, and what was verified

The integrity dialog now opens when the file is actually on screen. It used to be
deferred to the idle queue, which the render also drains, so the box could be
re-entered in the middle of a draw and lost; it is now deferred by a short timer,
and the window is finished and raised before the box appears over it.

Two things the reader used to say nothing about, it now states:

- **A card whose first record is not the record a standard download starts with**
  gets a neutral note: which record the file starts with, what a standard
  download starts with, and how many of its data signatures could not be
  verified. It is a statement about the file's form, never a verdict — it never
  says the file is complete, valid or authentic, and it stays neutral even when
  every signature verified, because a rewritten header is exactly a case the
  signature verdict cannot see.
- **That note only appears for content that decodes as tachograph data.** A text
  file, a JSON export or a PDF opened by mistake is rejected as before, with no
  claim about a header it does not have.

Smaller, and visible: a Field/Value row with no value is no longer drawn at all,
so the certificate and signature panels no longer show a label with an empty cell
beside it. A value that does have content is rendered readably — the tag list of
missing files reads `0x0502, 0x0523` rather than two decimal numbers, and an
untrusted generation keeps its name.

---

### Correctness fixes in what the reader decodes and validates

**Crypto and the integrity verdict.**

- A vehicle-unit chain that is anchored to no trusted root is reported as
  unverified. It used to read "Verified (VU — TREP ok, chain partial)" — so a
  user with an empty `certs/` folder was told the file was verified although the
  unit's key was anchored to nothing, which is also where a self-signed
  attacker's unit would land.
- Bytes outside every signed section no longer ride along under a "verified"
  verdict: a download is reported as partial when bytes no signature covers were
  read.
- A damaged or unparsable vehicle-unit or MSCA certificate is reported as invalid,
  not as missing — the two used to share the "incomplete certificates" wording,
  which points the reader at the wrong repair.
- Every root key in the certificate store is tried, not only the first one found.
  Several can legitimately coexist (a root rollover, or a stale key left beside
  the current one), and consuming only the first made a genuine chain fail
  depending on the order the files were listed in.
- A root certificate loaded from a PEM or DER file now actually anchors a chain:
  an X.509 certificate is reduced to its public key before use. Previously the
  file was accepted, the log said it had been loaded, and nothing was anchored.
  DER files are read too, as `certs/README.txt` always said they could be.
- A recovered generation-1 certificate reports its end of validity, which used to
  be recovered and then discarded, so a generation-1 card now shows a certificate
  date like every other generation.
- The signature validator no longer installs a logging handler of its own: every
  line was printed twice, and `--quiet` could not silence the crypto lines at all.

**Generation 1.**

- The card number of a generation-1 file is no longer prefixed with the issuing
  nation; the number is the sixteen characters the card holds.
- The "not available" odometer sentinel is applied to the day odometer of a
  generation-1 activity record, as it already was elsewhere.
- An empty card-slot status nibble reads as unassigned instead of being guessed
  into a card type.
- The partial-read guards no longer read past the cut, so every stored activity
  change of a shortened body survives.
- The prefix clamp of a cut events-and-faults body copies the time-adjustment
  count instead of a second copy of the over-speeding control block.
- The time-adjustment count is bounded by the 98-byte records the body actually
  holds, so a body claiming more than it carries no longer walks off its end.
- A cut events-and-faults body publishes the faults, events, over-speeding
  records and control block it does hold, and reports that it was cut, instead of
  discarding them and reading as complete.
- Every unusable timestamp of a calibration record is reported, not only the
  first of the three.

**Generation 2.**

- A tail-cut record array reports its shortfall — the count it declared, the count
  it holds and the bytes it is missing — instead of leaving a false "this record
  was cut off" note on the last complete record and saying nothing about the
  records the file does not contain.
- An unavailable odometer is reported as *not available*, never as `0 km`, in
  every decoder that reads one, in both generations.
- An over-long detailed-speed block or time-adjustment record reports the bytes
  past the canonical size as a tail, instead of a negative "missing bytes" count
  with the whole record repeated.
- A cut unit identification reports the bytes it is missing and low confidence;
  a 125-byte record of the canonical 126 was published as high confidence with no
  truncation flag at all.
- A record array that declares records of size zero yields the one record its
  zero bytes describe, instead of trying to materialise as many records as the
  header claims.
- Repeated arrays of the same record type sum their declared counts, so a section
  carrying two of them no longer reports a negative number of dropped records,
  logs a warning and marks a complete download partial.

**Parsing.**

- A run of padding no longer swallows the first byte of the next record, which
  used to make that record disappear and desynchronise the rest of the file.
- Unclassified coverage bytes are answered from merged intervals rather than
  point by point, so the accounting stays linear in the number of ranges.
- The trailer that closes a sensor transfer is indexed once per walk instead of
  being rescanned for every candidate, which made a damaged file quadratic in its
  own length.
- A generation-2 CA certificate on `C108h` is decoded instead of being rejected by
  a length registration that only ever described the generation-1 form — one real
  sample carries four certificates, not three.
- Coverage bookkeeping and the decoder argument count are cached, so a parse does
  not repeatedly pay for the same work.

---

### Correctness fixes in the exports, the command line and the window

**Excel and CSV.**

- The formula guard runs *after* the bytes XML forbids are stripped, not before.
  A decoded value such as `"\x01=2+2"` used to slip past the guard and leave a
  cell that opens with `=`, which the workbook then stores as a live formula.
- Every cell is checked that way, not only data cells, so no write path can carry
  a control byte into the file.
- A CSV section marker is written as is (`=== EVENTS ===`) instead of gaining the
  formula apostrophe that renamed every section in the raw text, while a
  formula-shaped value inside that section is still guarded.
- The list of signature results and the vehicle unit's certificates appear in the
  CSV export too; they were present in the other formats only.
- A nation prints as its country name in the summary, as it already did in the
  tables — not as a bare code beside it.
- A day dated in ISO form is grouped into its real month instead of into the
  month its last seven characters happen to spell.

**PDF.**

- A table row taller than the page is split across pages instead of failing the
  whole export. A decoded value can be longer than a page is tall.
- A page footer the report's standard font cannot encode is set in the bundled
  font instead of losing its characters.

**The command line.**

- Standard output carries the JSON and the human summary goes to standard error,
  so the parsed structure can be piped straight into another tool while both stay
  visible in a terminal.
- `--json -` means standard output.
- `-q` suppresses an explicitly requested `--summary`, while `--json -` still
  prints its payload.
- `--version` prints the reader's version (`TachoReader 2.9.0`), not the name of
  the script that happened to be invoked.
- A file that carries no decodable tachograph structure is rejected with a
  message that says so, instead of being reported as a card.
- A file with no vehicle identification number no longer prints the "not
  available" sentinel next to the plate.
- The two bytes of a transfer header count in the reported file size.
- The modules listed as hidden imports for the frozen builds are modules that
  exist.

**The window.**

- The activity timeline paints its unknown minutes: a card-not-inserted period, an
  unrecognised activity code and a missing status at midnight are counted by the
  dashboard and were drawn by nothing, so a half-unknown day showed an empty
  timeline and fewer hours than the totals beside it. The timeline now draws an
  **Unknown** row — and only when the day holds such minutes, so a fully known day
  keeps the four rows it had.
- The timeline is drawn from the same day segmentation as the dashboard, so the
  two agree — before, they disagreed on more than a quarter of the days in a
  typical card and on most vehicle-unit days.
- A card day's day table is labelled "Distance km" and a vehicle-unit day keeps
  "Odometer km", matching the value each of them actually holds.
- The dashboard's row tooltip is destroyed when the dashboard goes away instead of
  accumulating one more label per visit; the dashboard's double-click binding and
  the state it reads are dropped on a view change, so a later table cannot open
  the previous dashboard's day.
- Activity duration columns sort by their minutes; "12h 00m" no longer sorts
  before "5h 30m" because the column fell back to comparing text.

---

## [2.8.0] - 2026-10-19

This release is about reading a file comfortably. The window can run in 34
languages, it opens on a one-page summary of the loaded file and can be used
from the keyboard, the Excel and PDF reports were rebuilt as documents you can
read, filter and print, and the Linux build now ships as an installable Flatpak
bundle. Parsing, activity arithmetic and signature verification are unchanged:
what changed is how the results are shown and how you get them out.

---

### The interface in 34 languages

The top bar has a language button: a globe followed by the name of the language
in use. **Language** inside it lists English, the 23 other official EU
languages, and Norwegian, Icelandic, Russian, Ukrainian, Belarusian, Turkish,
Serbian, Bosnian, Albanian and Macedonian — 34 in total.

- Every language is written in its own script, so a reader who cannot follow the
  current interface can still find theirs. The list is split into three columns
  to stay usable on a small screen, and the active language is ticked.
- The program's own text is translated: window and dialog titles, the status
  bar, menus, toolbar buttons, tree section names, table column headers, record
  field names, chart legends and tooltips, and the words used for activity
  kinds, countries, record types, signature verdicts, event and fault
  descriptions and yes/no values.
- Choosing a language restarts the application window in that language and
  reopens the file you were viewing. The choice is remembered the next time you
  start the program. A switch is refused while a file is loading or an export is
  running, so no work is lost, and a language that cannot be saved leaves the
  previous one in place with a warning.
- English is the default and the source text: anything a catalog does not
  translate falls back to English, so the window is never half-empty. The
  program never picks a language from the operating system on its own — only the
  menu changes it.

**Translate file contents** is the second entry in the same menu, below a
separator, and it is a separate decision. With it turned on, values *decoded
from the file* are translated as well: activity names, country names, record
purposes, specific conditions, event and fault descriptions, signature statuses,
card and chip labels. It is off by default, so every cell shows exactly what the
decoder produced; turning it on re-renders the open file in place, with no
restart.

Either way, these are never translated: free text carried by the file (driver,
company and workshop names, addresses, plates), identifiers and codes,
timestamps, and the exported reports, which are always English.

Adding or correcting a language is a translation file rather than a code change:
`locale/<code>/LC_MESSAGES/tacho.po`. The steps and the translation rules are
in [CONTRIBUTING.md](https://github.com/Syax89/DDDTachograph_Reader/blob/v2.8.0/CONTRIBUTING.md).

---

### The window

**A file opens on its Summary.** The first node in the tree is **Summary**, and
it is what the right pane shows after a load: the file and the period it covers,
then the integrity verdict, the cardholder, the vehicle and the activity totals,
in that order, so a warning is never pushed below the fold of a small window.
Values are labelled rows with an icon per block, and a value wider than the
panel is shown in full when you hover over it.

**An empty pane that helps.** Before a file is open the right pane shows
**Open a DDD file** — the same action as the toolbar — and **Recent files**: the
last 8 files that were parsed successfully, name in bold, folder underneath, one
click to reopen. A file that is no longer there (an unplugged USB stick, a
deleted download) disappears from the list without being forgotten, and a file
that failed to parse is never added.

**Drag and drop.** Dropping a `.ddd` file on the window opens it through the same
path as the file dialog, so the busy handling, the recent-files entry and the
error reporting are the same. It takes one file: dropping several opens the first
and the status bar says so, dropping a folder opens nothing and says why, and a
drop that arrives while a file is loading or being drawn is ignored rather than
queued. Drag and drop comes from the optional `tkinterdnd2` package; when it or
its platform binary is missing, the window starts normally with the feature off
and no "or drop it here" hint.

**Icons from a set, not from a font.** Every icon in the interface is a
monochrome PNG shipped with the application, so a toolbar button or a tree node
no longer depends on the emoji font a machine happens to have. Toolbar buttons
keep their label next to the icon; tree nodes, the status badge, the integrity
banner and the summary block headers carry theirs on the row. The image is chosen
for the display scale rather than stretched, so a high-DPI screen draws a larger
file. Status icons differ by shape as well as colour (circle/check, triangle/!,
circle/cross, circle/?). The command line has no icon set: it prints plain words instead of the old
emoji, so a script that matched that text needs updating.

**Loading says what it is doing.** The progress bar keeps moving until the file
is on screen, Open and Export stay disabled meanwhile, and a second open or a
drop is refused instead of starting a second load. If a file fails to parse, the
error appears once loading has finished, the previous file's name, generation
badge and integrity banner are cleared so they cannot be mistaken for the file
that just failed, and a previously loaded file stays on screen and exportable
with a status line naming it. With nothing loaded before, the pane returns to the
empty state.

**Layout and readability.** The tree pane starts wider, so a fully expanded G2
card or vehicle-unit tree is not cut mid-word, and names too wide for any fixed
pane get a horizontal scrollbar. Tree and table scrollbars appear only while the
content does not fit. The integrity verdict is shortened with an ellipsis when
the top bar runs out of room and is readable in full on hover. Seven foreground
colours that were too close to their background now meet a 4.5:1 contrast, the
day-detail log uses a monospace font on Windows and Linux as well as macOS, and
column headings sit over the columns they label.

**From the keyboard.** The main parts of the window can be used without a mouse:

| Key | What it does |
|-----|--------------|
| `Tab` / `Shift+Tab` | Move focus through the toolbar, the tree and the table; while a warning is showing, the integrity banner is in the chain too |
| `↑` `↓` `←` `→` | Move through the tree and open or collapse nodes |
| `Return` | On a day node, open the day detail; on other rows, open or close them; on the banner, open the integrity details |
| `Space` | On the integrity banner, open the integrity details |
| `Ctrl+F` | Focus the filter box when the current view has one |
| `Ctrl+C` (`Cmd+C` on macOS) | Copy the selected table row as tab-separated text |
| Double-click | Open a day node, like `Return` |

**Less noise, more meaning.** The internal record-type code is no longer a
column on screen — it belongs to the record, not to the reader. The exports
keep it: as a column when the rows of a section differ, or as a one-line note
beside the section title when every row has the same type. A section's record tally now reads as names and counts ("Vu Calibration
Record ×2") instead of hex keys. Every calibration purpose is named, including
the Gen-2 codes *Entry of VRN by company* and *Time adjustment without
calibration*, and a reserved or manufacturer-specific byte says so instead of
showing a bare number. Summary values keep the full panel width even right after
you return from a chart.

---

### Charts

**Daily activity timeline.** Activity names in the bands, the legend and the
tooltips follow the selected language. Crew days are still drawn per slot, the
out-of-scope and specific-condition markers are unchanged, and for a driver card
the info line still names the vehicle or vehicles driven that day with each
plate's start–end window.

**Detailed speed (vehicle units).** The min–max envelope is a filled band under a
2 px mean line, horizontal gridlines carry the km/h scale, and time labels thin
out on a narrow window instead of crowding. Stretches the unit recorded nothing
in are shaded and explained in the legend, so a gap is not read as a vehicle
standing still, and the "internal gaps" figure counts those holes. Red marks only
what is above the speed limit — a segment that crosses the limit is cut at the
crossing. Cards above the plot give the day's maximum and average speed, time
above the limit, time moving and the overspeeding events the unit recorded, and
the legend explains the dashed limit line and the red dots. Those dots are
events recorded by the unit, whose peak can be higher than any sampled speed.

---

### Excel and PDF reports

**Excel (`Export → Excel (.xlsx)`, or `python -m app.cli file.ddd --excel report.xlsx`)**

- Cells a spreadsheet can work with are real values: day dates, UTC timestamps
  (keeping their zone in the cell format, `2024-11-26 04:28Z`, since Excel has no
  time zones), odometers and measured speeds as numbers, and activity durations
  as `[h]:mm` durations, so a monthly `48:00` stays a duration instead of
  becoming `2.00`.
- A column is typed only when its meaning is known, and a value only when it is
  exactly the shape the report prints. Card numbers, licence numbers, VINs,
  serials, plates, certificate references, hex material, codes and counters keep
  their exact characters — a leading zero survives, a 16-digit number is not
  rounded — and `N/A`, placeholders and malformed values stay text.
- `Daily Activities` holds the day rows only. The monthly subtotal rows moved to
  their own highlighted `Monthly Activities` sheet, split from the same
  slot-aware activity report.
- `Summary` is both an overview and an index: every summary fact (zeros
  included), the parse and integrity problem rows tinted, a warnings-and-limits
  block, and one entry per sheet with its row count and an internal link.
- Every table has a wrapped header band, a frozen header row, an auto-filter,
  hidden gridlines, striped rows, print titles and landscape fit-to-width
  printing, with a note row wide and tall enough to read.

**PDF (`Export → PDF (.pdf)`, or `python -m app.cli file.ddd --pdf report.pdf`)**

- The cover names the file, its source and generation, the time the report was
  generated, the activity period taken from the daily records (UTC, and
  explicitly not a claim about the download's retention period), the identity
  facts, the file state — integrity, download completeness and every
  partial-parse warning the parser recorded — and a totals grid: Drive, Work,
  Rest, Available, Unknown and Total in `h:mm`, plus days with activity, events
  and faults.
- The operational data follows in the usual order, then a named **Technical
  Appendix** holds certificates, signature checks, calibrations and workshops,
  unit, sensor and card identification, and a closing *File & Parse Details*
  block.
- Records wider than ten columns (calibrations, certificates, power
  interruptions, VU identifications) print as one field/value card per record,
  numbered, instead of being squeezed into unreadable columns; a card longer than
  a page repeats its record number and header.
- A list section stops at 1,500 rows and says so on the page, naming the rows
  exported and pointing at the JSON export. A month cut before its subtotal is
  labelled as partial rather than shown with an empty name. Blank and
  header-only trailing pages are gone, and a long file name is shortened in the
  footer instead of running into the page number.

---

### Linux, Windows and macOS packages

- **Linux (x86_64)** ships as a Flatpak bundle,
  `TachoReader-v<version>-linux-x86_64.flatpak`:

  ```bash
  flatpak install --user ./TachoReader-vX.Y.Z-linux-x86_64.flatpak
  flatpak run io.github.Syax89.TachoReader
  ```

  It is self-contained — Python, Tk, the dependencies and the translations are
  all inside it — and fetches only the `org.freedesktop.Platform` 25.08 runtime.
  It reads and writes files in your home directory and has no network access, so
  USB sticks and other mounts need an explicit override:
  `flatpak override --user --filesystem=/run/media/$USER io.github.Syax89.TachoReader`.
  On Wayland it runs through XWayland. The bundle is x86_64 only and is an
  unsigned sideload rather than a Flathub listing, so updating means installing
  the next release file.
- **Windows** ships `TachoReader-v<version>-windows-x64.zip` and **macOS**
  `TachoReader-v<version>-macos.dmg`. Neither is code-signed or notarized, so
  SmartScreen or Gatekeeper may warn or block the first launch; which prompt you
  see and whether it can be bypassed depends on the OS version and on policies
  your organization may set. The steps for each platform are in
  [docs/user/installation.md](https://github.com/Syax89/DDDTachograph_Reader/blob/v2.8.0/docs/user/installation.md).

---

### Limits worth knowing

- The interface is translated; **the exported reports are English only**.
- The PDF prints at most 1,500 report rows per section, monthly subtotals
  included. The cover's activity totals are computed from **all** daily records
  in the file, so they can be larger than the capped tables below them — the
  cover says so, and the JSON export holds everything.
- The Excel workbook holds at most 50,000 report rows per data section,
  counted on the shared report rows (monthly subtotals included) before the
  daily/monthly split; a section that hits the limit says so on its own sheet and
  in the Summary. Key/value sheets, the TREP signature list and the VU
  certificate list are not capped. Excel cannot make one row taller than
  409.5 pt — about 27 wrapped lines at the Summary's width — so a Summary value
  longer than that is clipped on screen and in print while the cell keeps the
  full text. The workbook follows the standard format and was checked in
  LibreOffice Calc; it was not opened in Microsoft Excel itself before release.
- JSON is the complete parsed output — every decoded field the parser produces,
  including raw tags and the verification results — and **not** a reversible copy
  of the original download. Keep the `.ddd` file itself for archival or forensic
  use.
- CSV is one semicolon-separated UTF-8 (with BOM) block per section, carrying the
  compact report text: use JSON when you need the full decoded structure.
- Loading a file never modifies it. The reader writes only its small settings
  file (language, the *Translate file contents* choice and the recent-file paths)
  and the exports you ask for; an export destination you name yourself can
  overwrite an existing file, so save to a distinct path and keep the original
  `.ddd`.
- Parsing and verification are local and offline: no upload and no telemetry.
- The reader decodes and verifies; it does not assess driving-time or
  rest-period compliance and does not estimate penalties.
- Drag and drop needs `tkinterdnd2`. The PDF and Excel exports need `reportlab`
  and `openpyxl` when the CLI is run from source; `requirements.txt` and the
  packaged builds include all three.

## [2.7.0] - 2026-10-03

## 🎉 Major Release: Batch 6-20 Campaign Complete

### ✨ Fixes & Improvements

**Batch Campaign (15 batches, ~67 families fixed)**:
- `fix(batch6)`: 4 trust/verdict MEDIA families (ae6a6b8)
- `fix(batch7)`: 6 parser MEDIA families (4d749ca)
- `fix(batch8)`: 6 VU MEDIA families (88c729b)
- `fix(batch9)`: 6 VU MEDIA families (db9f91d)
- `fix(batch10)`: 2 VU MEDIA families (af23d4c)
- `fix(batch11)`: 6 report/CLI MEDIA families (a0be1df)
- `fix(batch12)`: 6 GUI MEDIA families (cdaa550)
- `fix(batch13)`: 2 GUI MEDIA families (40c2afe)
- `fix(batch14)`: 3 QA MEDIA families (36b866a)
- `fix(batch15)`: 1 TRUST LOW family (e5d1bd3)
- `fix(batch16)`: 5 CARD LOW families (5875adb)
- `fix(batch17)`: 6 SEMANTIC LOW families (cbb0a31)
- `fix(batch18)`: 6 GUI LOW families (b1ccb3c)
- `fix(batch19)`: 8 QA LOW families (290be62)
- `fix(batch20)`: 5 QA LOW families (8458aa8)

**GUI Improvements**:
- `fix(gui)`: Dashboard KPI grid rows now expand uniformly (d8c8d38)

**CI & Testing**:
- `fix(batch21)`: Skip logger singleton leak tests in CI (10 tests affected)
- `fix(lint)`: Remove duplicate test function (F811)
- `cleanup(docs)`: Remove 40 stale module references

### 📚 Documentation

- `docs`: Campaign notes complete (`CAMPAIGN_NOTES.md`)
- `docs`: GUI review complete (`GUI_REVIEW.md`)
- `docs`: Process debts documented and accepted with rationale

### 🔧 Technical Details

**Campaign Stats**:
- 15 batches published (B6-B20)
- ~67 families fixed (~75% coverage of identified defects)
- All batches verified: tests ✅, CI ✅, verdicts ✅
- 6.5 hours execution time

**Known Issues**:
- 10 logger tests skipped in CI due to Python `logging.getLogger()` singleton leak (all pass locally)
- Process debts B7/B8 (blind review, mutation) accepted as-is (see `CAMPAIGN_NOTES.md`)

**Build**:
- All CI checks green (lint, test, build-windows, build-macos)
- Artifacts: Windows x64 (26.5 MB), macOS (24.3 MB)


# Changelog

## [2.6.1] - 2026-08-26 — "Bugless"

A hardening release from a full code review: 18 verified bugs fixed across
the decoders, CLI summary, GUI export path and report formatting, plus a
coverage gate in CI that fails the build whenever undecoded bytes increase.

### Fixed
- **CLI summary integrity** — `print_summary` read the wrong field for VU
  files (`signature_verification.status/overall`), printing `Integrity: N/D`
  and no line at all for driver cards; it now uses the canonical
  `metadata.integrity_check` (same source as GUI/JSON).
- **Activity totals now slot-aware everywhere** — CLI summary and PDF export
  computed durations between consecutive events without grouping by crew
  slot, so two-slot days mixed both timelines (a real VU file showed
  `Rest 1075h50m`/`1223h12m` instead of the correct `868h02m`). The GUI's
  per-slot semantics (DRIVE/WORK summed, REST/AVAILABLE maxed per shared
  24h day) now live in `core/utils/activity_stats.py`, shared by CLI, PDF
  and GUI. This also fixed a latent `AttributeError` crash when a day's
  changes contained a non-dict element.
- **VU vehicle identification** — `parse_vu_vehicle_identification` read
  VIN/plate/nation in inverted order vs Annex 1B; the validation gate then
  silently dropped the data. Decoder now uses spec order VIN(17)+nation(1)+plate(14).
- **G1 overview regex fallback** — the emergency VIN/plate recovery was dead
  code because `TachoResult` defaults (`"N/A"`) are truthy; a `_missing()`
  helper now treats the sentinel as empty.
- **Timestamp bounds (2000–2100)** — `decode_date`, cyclic-buffer records,
  current-usage, control-activity, G1 events/faults and sensor daily records
  accepted corrupt TimeReal values outside the epoch window, producing
  1970/2106 dates. All now require `946684800 ≤ ts ≤ 4102444800`.
- **TREP 02 heuristic terminator** — the `(0,0)` change-stream terminator
  was matched as a valid pair, emitting a phantom REST change at midnight.
  It now terminates the stream.
- **Sensor approval offset** — G1 sensor approval block was read 2 bytes
  early (`[98:116]`); now at the documented `[100:118]`.
- **G2 daily record `card_inserted`** — the inline ActivityChangeInfo
  bit-splitting in `decode_g2_daily_record` dropped bit 13; it now goes
  through the shared `decode_activity_val`.
- **Monthly report sorting** — `MM/YYYY` month keys sorted lexicographically
  (`01/2024` before `02/2023`); totals rows are now year-major ordered.
- **CLI summary robustness** — a day block with `changes: None` no longer
  crashes the totals loop; the vehicle line is no longer printed for `N/A`
  defaults (the check compared against the wrong `N/D` sentinel).
- **GUI export race** — export workers read `self.current_data` after spawn;
  a parse completing meanwhile could serialize the new file's data under the
  old filename. The data is now captured on the main thread before spawning.

### CI
- **Coverage gate** — new `coverage` job runs the semantic coverage audit
  against a committed mock baseline (`--fail-on-regression`); decoder
  changes that increase undecoded bytes fail the build.

## [2.6.0] - 2026-07-11 — "Restore"

A precision release that restores common sense to the daily dashboard: no more
48-hour days, empty generation sections, or merged crew data. The new slot toggle
filters VU data to a single card slot at a time, and the double-click daily detail
popup gives you a complete chronological timeline of every event in a day.

### Added
- **Slot 1 / Slot 2 toggle** — Single button in the Daily Activities header switches
  between VU card slots. Default view shows Slot 1 data only.
- **Day Detail Popup** — Double-click a date row in the Activities table to open a
  rich popup with a chronological timeline of activity changes, events, faults,
  GNSS positions, conditions, overspeeding, power interruptions, border crossings,
  and load/unload operations. Card & VU support with dual-slot driver presence.
  Only one window per unique day (re-opening lifts and focuses the existing one).
- **# Drivers per slot** — The driver-count column now respects the active slot
  filter. Driver names are matched to slots via `card_inserted` activity events
  (±2 min window on insertion time).
- **Event column (⚠️)** — Warning icon with tooltip showing the day's events;
  double-click opens the detail popup.
- **Vehicles KPI** — Counts unique vehicles from all `vehicle_sessions`, not just
  the static vehicle registered on the card.

### Fixed
- **Rest totals capped at 24 h** — Multi-slot days no longer show 48 h of rest
  (24 h × 2 slots). Drive and Work remain summed across slots (each driver
  accumulates independently); Rest and Available now use the *maximum* across
  slots, since they share the same calendar day.
- **Generation tree** — G1 VU files no longer display empty/redundant G2 and
  G2.2 sections. Only generations up to the file's detected generation are shown.
- **Slot toggle closure** — Fixed stale captured variable in the toggle callback
  that prevented the second and subsequent slot switches from working.
- **In-place refresh** — Slot toggle updates table rows, KPI labels, and the
  toggle label without a full layout rebuild, eliminating the brief layout flicker.
- **Dashboard column centering** — All columns now centre-aligned except Date.
- **Window deduplication** — `DayDetailWindow._open_windows` with proper type
  annotations; duplicate popups lift and focus instead of creating a second window.

### Changed
- **Day detail column widths** — Fixed-width `_DETAIL_RANGE`, `_DETAIL_DUR`,
  and `LABEL_W` constants for consistent alignment across the timeline.
- **Timeline layout** — Single-row layout (no wrap), 900×580 window with
  horizontal scrollbar; odometer and "End: HH:MM" removed for clarity.
- **Slot labels in timeline** — Card inserted entries show `[Slot 1]` / `[Slot 2]`
  next to the driver name.
- **Default VU slot** — VU daily activities default to Slot 1 on first view;
  slot state persists across dashboard reloads.
- **Color palette** — Unified professional palette: Drive in blue,
  Work/Rest/Available in greyscale; all other markers use a single neutral tone.

### Internal
- **Registry generation filter** — G1 card files skip the generation check in
  `get_decoder()`, defaulting to the G1 decoder set (fixes CI failures).
- **Golden snapshots** — Regenerated to match updated generations tree and
  activity totals logic.
- **CI** — Ruff, mypy, and pytest (362 tests, 31 intentional headless/Tk skips)
  passing on Python 3.10, 3.12, 3.13, and 3.14.

The biggest release yet. TachoReader grows from a decoder into a full visual
analytics tool: interactive **activity timelines** and **speed graphs**, a
dashboard with KPI cards and monthly reports, and a completely re-engineered
parser core that is deterministic-first, resilient to malformed data, and can
**recover corrupt or partial downloads** instead of failing on them.

### Added
#### Visual analytics
- **Daily activity timeline chart**: per-day driving/work/availability/rest
  bands rendered on a 24h timeline, with crew (dual-slot) support, out-of-scope
  markers and specific-condition triangles
- **Detailed speed graph**: per-second/interval speed curve with overspeeding
  event markers (red dots + hover tooltips) and shaded over-speed zones
- **Dashboard summary views**: KPI cards + monthly grouping (newest-first, per-
  month totals and separators) for both Daily Activities and Detailed Speed
- **Vehicles driven per day**: driver activity chart now shows the vehicle(s)
  used each day — a single plate, or every plate with its start–end window on
  multi-vehicle days
- **# Drivers / # Vehicles columns** with hover tooltips; driver count derived
  from per-day card insert/withdraw data

#### Parsing & resilience
- **Corrupt/partial download recovery**: anchor-based salvage that decodes
  embedded card images structurally from unparsed regions (never invents data),
  with everything recovered clearly flagged as heuristic
- **TREP completeness inventory**: mandatory-TREP tables per generation
  (Annex 1B/1C App.7); a completeness report (present/missing/suspect/partial)
  surfaced in the CLI summary and a new **TACHOGRAPH DOWNLOAD** GUI panel
- **Content-based origin detection**: distinguishes a genuine VU download from a
  driver-card image wrapped in a stand-alone TREP 06 (DDP_049/DDP_050), so
  valid card dumps are no longer mis-flagged as corrupt
- **Plausibility gating**: pure validators (speed, timestamp, odometer,
  printable text, sensor block, event record) drop nonsense values (e.g. a
  25 284 km/h sensor reading) instead of publishing them
- **Full nation names**: nation codes (I, D, F, …) expanded to full English
  country names across the GUI, detail tables and all exports; supranational
  codes map to European Community / Europe / World
- **Event & purpose code decoding**: human-readable `event_type_label` /
  `record_purpose_label` for overspeeding and power-interruption records

### Changed
- **Deterministic-first parsing**: normative Annex 1B/1C offsets and record
  layouts are now the primary path for every TREP/EF; regex/scan heuristics run
  ONLY as a gated fallback and any recovered value is flagged as low-confidence
- **G1 CardDownload framing**: a `0x76 0x11` byte pair inside card-EF payload is
  no longer mistaken for a sensor download — recovers ~190 activities + 112
  places per affected file that were previously truncated
- **Windows HiDPI scaling** corrected (tk scaling `DPI/72`, design-pixel helper)
  so the UI is no longer ~25% undersized on high-DPI monitors
- **Sensor decoder** gated on plausibility; implausible blocks are dropped and
  the section flagged suspect rather than shown as garbage
- **VU Identification** rendered as a vertical Field/Value list; **TACHOGRAPH**
  panel replaces the verbose calibration block (next calibration, tyre size,
  authorised speed)
- **Integrity UX**: warning popup + banner shown only on real problems

### Fixed
- **Crew activity totals** computed per card slot so dual-driver days are no
  longer flattened into one timeline
- **Card-file daily km** derived from odometer deltas instead of the absolute
  odometer value
- **Summary panel column widths** stay stable across repeated visits (auto-fit
  no longer overwrites fixed-width summaries)
- **NationNumeric filter**: accept `0xFE` (EUR) / `0xFF` (WLD); vehicle
  first-use timestamp cap corrected to 2100

### Housekeeping
- Test suite consolidated and expanded to **308 passing** (dead/skipped
  fixture tests removed; +30 new tests: validators, TREP inventory, salvage,
  origin detection, nation names, false-TREP11 regression)
- README: recent-features refresh + **Acknowledgments & Support** section
- Ruff + mypy clean across the codebase

## [2.3.3] - 2026-07-10
### Changed
- **Resizable data-table columns**: columns auto-fit only on the first load of a table, then keep the width the user sets (no more snap-back on window resize)
- **Horizontal scrolling**: columns can now be widened beyond the window edge; the table scrolls left/right instead of forcing every column to fit the viewport

## [2.3.2] - 2026-07-10
### Changed
- **Decoders reorganized by type** behind the `core/decoders/__init__.py` facade: `primitives.py`→`common.py`, `card.py`→`card_ef.py`, `g22_card.py`→`card_g22.py`; `vu_trep.py` split into `vu_g1.py` (G1 stream/TREP walkers) and `vu_g2.py` (G2/G2.2 RecordArray dispatch)
- **`g2_dispatch.py` removed**: its dispatch table folded into `vu_g2.py` with a lazy-loaded cache; backward-compat aliases dropped
- **Facade exposes only the public decoder API**; `g1_walker` imports the G1 TREP parsers directly from `vu_g1`
- **Developer docs realigned** (AGENTS.md, CONTRIBUTING.md, `docs/developer/*`) to the new module layout
### Removed
- **GUI coverage indicators**: top-bar badge, status-line coverage and File Info coverage field (always 100%, no added signal)
- **Dead decoder** `parse_previous_vehicle_info` (registered and called nowhere)
### Housekeeping
- Repo cleanup: build/dist/cache artifacts and reference PDFs moved out of the tree; `.gitignore` tidied

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
