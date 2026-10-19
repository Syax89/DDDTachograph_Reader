# GUI Guide — Tacho Explorer

The desktop application (**Tacho Explorer**, `app/gui.py`) provides a two-pane explorer for digital tachograph data: a regedit-style section tree on the left and, on the right, either an Excel-style data table or an interactive chart.

---

## Launching the Application

- **Windows**: Double-click `TachoReader.exe`.
- **macOS**: Right-click `TachoReader` → Open.
- **From source**: `python -m app.gui` from the repository root (running
  `python app/gui.py` by path fails: the package root is not on the import path).
- **With a file already open**: `python -m app.gui path/to/file.ddd`.

The packaged builds also answer `--version` (on Linux:
`flatpak run io.github.Syax89.TachoReader --version`).

---

## Product Tour

![Product tour](https://raw.githubusercontent.com/Syax89/DDDTachograph_Reader/master/docs/screenshots/product-tour.gif)

*Activity dashboard · daily activity timeline · speed dashboard · detailed speed graph. Preview uses anonymized test data. The captures show the chart views; where the window chrome differs from a capture, the text below describes the current build.*

---

## Top Bar

| Control | Action |
|---------|--------|
| **Open DDD file** | Opens a file dialog to select a `.ddd` file |
| **Export** | Drop-down menu: PDF (.pdf), Excel (.xlsx), CSV (.csv), JSON (.json) |
| **Language** (globe) | Shows the active language; opens the language menu (see [Languages](#languages)) |
| File label | Name of the currently loaded file |
| Integrity status | Quiet while the file verifies cleanly; the verdict (or a warning) otherwise, readable in full on hover |
| Integrity banner | Warning shown only when there is a problem — click it (or Tab to it and press Return/Space) for full details |
| Generation badge | Detected generation (G1, G2, G2.2) and file type (Card / VU) |

A file is parsed while the window stays responsive: a progress bar appears in
the status bar and keeps moving until the file is on screen. Open and Export are
disabled for the duration; a second open, a drop or a language switch during a
load is refused rather than queued.

If a file fails to parse, the error appears once loading has finished, the
previous file's name, generation badge and integrity banner are cleared so they
cannot be attributed to the file that just failed, and — if a file was loaded
before — its data stays on screen and exportable, with a status line naming it.
With nothing loaded before, the pane returns to the empty state.

### Before a File Is Open

The right pane starts on an empty state rather than a blank table: a large
**Open a DDD file** heading with the same open action as the top bar, and below
it **Recent files** — the last 8 files that were parsed successfully, each with
its name in bold and its folder underneath. Clicking one reopens it. Entries
whose file is no longer there (an unplugged USB stick, a deleted download) are
hidden until it comes back; a file that fails to parse is never added.

When drag & drop is available, a muted **or drop it here** line sits under the
button: dropping a file on the window opens it exactly like the dialog does
(folders and files that no longer exist open nothing and the status bar says
so; dropping several files opens the first one). If the optional
`tkinterdnd2` package or its platform binary is missing, the hint is not shown
and everything else works unchanged.

### Summary — the view a file opens on

A loaded file opens on **Summary**, the first node in the tree. It is a
single page of labelled rows, in this order:

| Block | What it shows |
|-------|---------------|
| **File** | File name and the period the records cover |
| **Integrity** | The verdict, download completeness and any recovered-data note |
| **Cardholder** | Driver or cardholder identity (driver-card files) |
| **Vehicle** | Plate, VIN, registration nation and tachograph facts (VU files) |
| **Totals** | Drive, Work, Rest, Available, Unknown and Total in `h:mm`, plus days with activity |

The block order is deliberate: a warning can never sit below the fold of a small
window. Section headers carry an icon, and a value wider than the panel is
revealed in full when you hover over it — translated integrity verdicts are long,
and they are never silently cut.

### Integrity Status

The integrity banner stays quiet when a file verifies cleanly. It only appears when there is something worth your attention, and clicking it opens a details popup covering:

- **TREP completeness** — which mandatory download sections are present, missing, or suspect.
- **Cryptographic validation** — the signature chain result (ERCA → MSCA → Card/VU) and, for cards, EF signature verification.
- **Recovered data** — anything reconstructed by best-effort salvage of a partial/corrupted download.

Possible signature outcomes include **Verified**, partial variants (e.g. *Verified (Local Chain)*, *Verified (VU Chain)*, *Missing ERCA*), an **Invalid Certificate Chain** failure, or a **Parse error**. A partial or missing chain means the data is still readable — only the cryptographic proof is incomplete.

---

## Section Tree (Left Pane)

The tree organizes all parsed data into sections. Clicking a section shows its records (as a table or chart) on the right. Every node carries an icon drawn from the monochrome PNG set shipped with the application, so the picture does not depend on the fonts a machine happens to have; a long list of sections can be told apart at a glance. Typical top-level sections:

| Section | Contents |
|---------|----------|
| **Summary** | The view a file opens on (always the first node): file name and the period it covers, driver and/or vehicle, activity totals, and integrity |
| **File Info** | File name, origin (Driver Card / Vehicle Unit, including "from VU download"), generation, integrity, decoder failures |
| **Driver / Cardholder** | Card holder identity (driver card files) |
| **Vehicle** | VIN, plate, registration nation, tachograph (next calibration, tyre size, authorised speed) |
| **Activity & Usage** | Daily activities (day-by-day hierarchy with charts), vehicles used, events, faults, places, calibrations, control activities, and more |
| **G2.2 — Smart V2** | GNSS accumulated driving, GNSS places, border crossings, load/unload records, load sensor, trailers |
| **Vehicle Unit (VU)** | VU identification, sensor pairings, card insertions/withdrawals, time adjustments, company locks, downloads, power interruptions, overspeeding control, ITS consents, detailed speed |
| **Security & Certificates** | Certificates and signature verification details |
| **Raw Tags** | Every raw tag occurrence, for low-level inspection |

Sections only appear when the loaded file actually contains that kind of data — a G1 driver card will not show the G2.2 or VU groups.

Nation fields (registration, issuing, sensor) are shown with their **full country name** (e.g. *Italy*, *Germany*) rather than the raw code; with **Translate file contents** ticked the name appears in the interface language, otherwise in English.

---

## Daily Activities

Selecting the **Daily Activities** parent node opens an **activity dashboard**: KPI cards (total drive/work/rest hours, active days) plus a table grouped by month with per-month totals.

Expanding the node lists one entry per day. Selecting a day opens the **activity timeline chart**:

- A 24-hour timeline with coloured bands for **Drive**, **Work**, **Available**, and **Rest/Break**.
- Activity names — in the bands, the legend and the tooltips — follow the selected interface language.
- Crew (dual-slot) days are drawn per slot, so two drivers recording at once are not flattened together; the day detail can be switched between slots.
- Out-of-scope periods and specific-condition markers appear as triangles.
- For **driver-card** files, the info line shows the **vehicle(s) driven that day** — a single plate, or every plate with its start–end window when the driver changed vehicle during the day.

Each day also keeps a raw-record child table (time, activity type, card slot, crew status, odometer, daily counter).

![Activity dashboard](https://raw.githubusercontent.com/Syax89/DDDTachograph_Reader/master/docs/screenshots/01_activity_dashboard.png)

![Daily activity timeline](https://raw.githubusercontent.com/Syax89/DDDTachograph_Reader/master/docs/screenshots/02_activity_timeline.png)

---

## Detailed Speed (VU files)

Selecting **Detailed Speed** opens a **speed dashboard** (KPI cards + per-day statistics). Expanding it lists each day; selecting a day opens the **speed graph**:

- The min–max speed envelope as a filled band under a 2 px mean line, with
  horizontal gridlines carrying the km/h scale. The plot opens on the hours the
  day actually has samples in; zooming still reaches the full day.
- **Overspeeding events** flagged as red dots with hover details. Red marks only
  what is above the limit — a segment that crosses the limit is cut at the
  crossing.
- The authorised speed limit (from the most recent calibration, otherwise the
  default) drawn as a dashed reference line.
- Stretches the unit recorded nothing in are shaded and explained in the legend,
  so a gap is not mistaken for a vehicle standing still; the "internal gaps"
  figure counts those holes.
- Above the plot, cards show the day's maximum and average speed, time above the
  limit, time moving, and the number of overspeeding events the unit recorded.
  Those events are recorded by the unit and their peak can be higher than any
  sampled speed.
- Time labels thin out on a narrow window instead of crowding.

![Speed dashboard](https://raw.githubusercontent.com/Syax89/DDDTachograph_Reader/master/docs/screenshots/03_speed_dashboard.png)

![Detailed speed graph](https://raw.githubusercontent.com/Syax89/DDDTachograph_Reader/master/docs/screenshots/04_speed_graph.png)

---

## Download Completeness & Corrupted Files

For **VU downloads**, a **TACHOGRAPH DOWNLOAD** panel reports completeness against the mandatory TREP sections for that generation (present / missing / suspect, plus a completeness percentage).

If a VU download is genuinely partial or corrupted, a **CORRUPTED / PARTIAL FILE** page is shown and auto-selected. It lists the completeness, sections present, missing mandatory sections, sections whose data was discarded as implausible, and any data recovered by best-effort salvage.

Note that a driver-card image wrapped inside a stand-alone VU download is **not** treated as corrupt — the reader detects it from its content and shows it as a normal driver card (File Info marks the origin as *Driver Card (from VU download)*).

---

## Data Table (Right Pane)

For non-chart sections the right pane shows a sortable grid:

- **Sort**: click any column header to sort; click again to reverse.
- **Filter**: type in the filter box (the magnifier on its left) to show only matching rows, or press `Ctrl+F` to jump to it.
- **Resizable columns**: columns auto-fit on first load, then keep the width you set; you can widen a column past the window edge and scroll horizontally. The scrollbars appear only while the content does not fit.
- **Copy**: select a row and press `Ctrl+C` (`Cmd+C` on macOS) to copy it to the clipboard as tab-separated text.
- **Record count**: shown next to the section title.

Values are formatted for readability: timestamps as `YYYY-MM-DD HH:MM`, coordinates with 5 decimals, nations as full country names, and the tachograph "not available" sentinel values shown as an em-dash or empty. The internal record-type code is not shown as a column — it is part of the record, not something to read on screen, and the exports keep it. Calibration purposes are named, including *Entry of VRN by company* and *Time adjustment without calibration* for Gen-2 files; a reserved or manufacturer-specific code says so instead of showing a bare number.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Tab` / `Shift+Tab` | Move focus between the toolbar, the tree, the table and — while a warning is showing — the integrity banner |
| `↑` `↓` `←` `→` | Move through the section tree, opening and collapsing nodes |
| `Return` | On a day node: open the day detail; on other nodes: open or collapse the row; on the integrity banner: open the details |
| `Space` | On the integrity banner: open the details |
| `Ctrl+F` | Focus the filter box (views that have one) |
| `Ctrl+C` / `Cmd+C` | Copy the selected table row as tab-separated text |
| Double-click | Open a day node, like `Return` |

---

## Languages

The application ships in 34 languages: English, the 23 other official EU
languages, and Norwegian, Icelandic, Russian, Ukrainian, Belarusian, Turkish,
Serbian, Bosnian, Albanian and Macedonian.

1. Click the **language button** in the top bar — it shows the current language
   in its own script.
2. Choose **Language** and pick one. Every language is listed in its own
   language, in three columns; the tick marks the current one.
3. The window restarts in the new language and **reopens the file that was
   showing**. The choice is saved in the per-user settings file and remembered the
   next time you start the program.

English is the default and the source language: anything a translation is missing
falls back to English, so the window is never half-empty, and the program never
picks a language from the operating system on its own. Switching is refused
while a file is being parsed, rendered or exported.

**Translate file contents** — the second entry in the same menu, under a
separator — decides whether the values *decoded from the file* are translated
too: activity names, country names, record purposes, specific conditions, event
and fault descriptions, signature statuses, card and chip labels. It is off by
default, so every cell shows exactly what the decoder produced; tick it and the
window re-renders in place, without a restart. Either way, these are never
translated: free text carried by the file (driver, company and workshop names,
addresses, plates), identifiers and codes, timestamps, and the exported reports,
which are always English.

See [CONTRIBUTING.md](../../CONTRIBUTING.md) to add or improve a language.

---

## Export

The **Export** menu saves the currently loaded file's data:

| Format | Description |
|--------|-------------|
| **PDF** | A4 landscape report: cover with identity, file state and activity totals, the operational sections, then a Technical Appendix (signature material, certificates, calibrations, unit identification, parse details). Wide records print as field/value cards; a list section is capped at 1,500 rows and says so |
| **Excel** | Multi-sheet workbook (.xlsx) with typed cells (dates, timestamps, numbers, durations), a Summary sheet that indexes every sheet, and the activity report split into `Daily Activities` and `Monthly Activities` |
| **CSV** | All sections in one semicolon-separated UTF-8 file, separated by titled blocks — one text block per section |
| **JSON** | The complete parsed structure with all decoded fields (not a byte copy of the original file) |

Exports are always written in English, whatever the interface language, and a
progress bar shows while the file is being written. Click a format, choose a save
location, and the file is produced; the previously loaded file stays exportable
even after a failed re-open. For details on each format — including the row
limits, the typed-cell rules and what each format is best at — see the
[Export Guide](export_guide.md).
