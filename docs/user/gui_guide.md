# GUI Guide — Tacho Explorer

The desktop application (**Tacho Explorer**, `gui_tree.py`) provides a two-pane explorer for digital tachograph data: a regedit-style section tree on the left and an Excel-style data table on the right.

---

## Launching the Application

- **Windows**: Double-click `TachoReader.exe`.
- **macOS**: Right-click `TachoReader` → Open.
- **From source**: `python gui_tree.py`.

---

## Top Bar

| Control | Action |
|---------|--------|
| **📂 Open DDD file** | Opens a file dialog to select a `.ddd` file |
| **📤 Export** | Drop-down menu: PDF (.pdf), Excel (.xlsx), CSV (.csv), JSON (.json) |
| File label | Name of the currently loaded file |
| Integrity status | Color-coded signature verification result (see below) |
| Generation badge | Detected generation (G1, G2, G2.2) and file type (Card / VU) |
| Coverage badge | Percentage of file bytes successfully decoded |

Parsing runs in a background thread — a progress bar appears in the status bar while a file is loading, and the window stays responsive.

### Integrity Status Colors

- **Green — Verified**: the digital signature chain is valid; the file has not been tampered with.
- **Yellow — Incomplete / Missing ERCA**: the European root certificates needed to complete the chain are not available. The extracted data is still readable; only the cryptographic proof is incomplete.
- **Red — Invalid Certificate Chain**: the signature check failed. This may indicate tampering or a corrupted download.

---

## Section Tree (Left Pane)

The tree organizes all parsed data into sections. Clicking a section shows its records as a table on the right. Top-level sections:

| Section | Contents |
|---------|----------|
| **Overview** | File name, origin (Driver Card / Vehicle Unit), generation, integrity, coverage |
| **👤 Driver / Cardholder** | Card holder identity (driver card files) |
| **🚚 Vehicle** | VIN, plate, registration nation (VU files) |
| **📊 Activity & Usage** | Daily activities (day-by-day hierarchy), vehicles used, events, faults, places, calibrations, control activities, and more |
| **🛰️ G2.2 — Smart V2** | GNSS accumulated driving, GNSS places, border crossings, load/unload records, load sensor, trailers |
| **🚚 Vehicle Unit (VU)** | VU identification, sensor pairings, card insertions/withdrawals, time adjustments, company locks, downloads, power interruptions, overspeeding control, ITS consents, detailed speed blocks |
| **🔐 Security & Certificates** | Certificates and signature verification details |
| **🧩 Raw Tags** | Every raw tag occurrence, for low-level inspection |

Sections only appear when the loaded file actually contains that kind of data — a G1 driver card will not show the G2.2 or VU groups.

### Daily Activities

The **Daily Activities** section expands into one node per day. Each day's table lists the individual activity changes: time, activity type (Drive, Work, Available, Rest/Break), card slot, and crew status, together with the date, odometer reading, and daily counter.

---

## Data Table (Right Pane)

The right pane shows the selected section as a sortable grid:

- **Sort**: click any column header to sort; click again to reverse.
- **Filter**: type in the 🔎 filter box to show only matching rows.
- **Record count**: shown next to the section title.

Values are formatted for readability: timestamps as `YYYY-MM-DD HH:MM`, coordinates with 5 decimals, and the tachograph "not available" sentinel values are shown as empty.

---

## Export

The **Export** menu saves the currently loaded file's data:

| Format | Description |
|--------|-------------|
| **PDF** | Formatted report with summary and section tables |
| **Excel** | Multi-sheet workbook (.xlsx), one sheet per data section |
| **CSV** | All sections in a single CSV, separated by titled blocks |
| **JSON** | Full structured output with all parsed fields |

Click a format, choose a save location, and the file is written. For details on each format, see the [Export Guide](export_guide.md).
