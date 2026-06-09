# GUI Guide — Aurora DDD Analytics

The Aurora DDD Analytics desktop application provides a modern, tabbed interface for exploring and analyzing digital tachograph data. This guide walks through every tab and feature.

---

## Launching the Application

- **Windows**: Double-click `TachoReader.exe`.
- **macOS**: Right-click `TachoReader` → Open.
- **From source**: `python gui_tree.py`.

---

## Sidebar Navigation

The left sidebar contains all navigation controls:

| Control | Action |
|---------|--------|
| **Carica File .ddd** | Opens a file dialog to select a `.ddd` file |
| **BENVENUTO** | Welcome tab with driver/vehicle identity card and KPI dashboard |
| **ESPLORA DATI** | Raw data tree view showing all parsed tags |
| **ATTIVITÀ** | Daily activity breakdown table |
| **INFRAZIONI** | Compliance violations table (hidden for VU files) |
| **FLOTTA** | Multi-file batch analysis |
| **Esporta JSON** | Save results as JSON |
| **Esporta Excel** | Save results as Excel workbook |
| **Esporta CSV** | Save results as CSV |

---

## Welcome Tab (BENVENUTO)

After loading a `.ddd` file, the Welcome tab shows:

### Identity Card
- **Driver files (Carta)**: Driver's full name, card number
- **Vehicle files (VU)**: Vehicle plate, VIN number

### Legal Status Banner
A color-coded banner indicates file integrity:
- **Green**: Certified — digital signature is valid, file has not been tampered with.
- **Yellow**: Not verifiable — ERCA certificates are missing from the system, but extracted data is still readable.
- **Red**: Invalid — the signature check indicates possible tampering.

### KPI Dashboard
Three key performance indicators:
- **Total Distance** (KM)
- **Driving Hours**
- **Integrity Status**

---

## Explore Data Tab (ESPLORA DATI)

This tab displays a hierarchical tree view of every tag parsed from the `.ddd` file, similar to a registry editor.

| Column | Description |
|--------|-------------|
| **Offset** | Hexadecimal position in the file |
| **Tag** | TLV tag identifier (e.g., `F00B`, `F010`) |
| **Descrizione** | Human-readable tag name |
| **Lunghezza** | Data length in bytes |
| **Tipo** | Data type or "Container" for nested structures |

### Tips for Reading the Tree View
- **Folder icons (📂)** represent container structures that hold child tags underneath.
- Click the expand arrow to drill down into nested data.
- Tags marked with **🚫 DATI GREZZI** are unparsed byte ranges (usually empty padding or unknown regions).
- Tags marked with **💤 PADDING** are filler bytes inserted by the tachograph to align data.
- The tree is sorted by physical offset in the file, matching the on-disk layout.

---

## Activities Tab (ATTIVITÀ)

A daily summary table showing time breakdowns:

| Column | Description |
|--------|-------------|
| **Data** | Date (DD/MM/YYYY) |
| **Guida** | Total driving time (HH:MM) |
| **Lavoro** | Total work time (HH:MM) |
| **Pausa/Riposo** | Total rest + availability time (HH:MM) |
| **Infrazioni** | Number of compliance violations for that day |

Use this tab to quickly spot heavy driving days or days with infractions.

---

## Infractions Tab (INFRAZIONI)

> **Note**: This tab is only visible when analyzing a **driver card** file. It is hidden for vehicle unit (VU) files since infractions are tied to individual drivers.

### Infractions Table

| Column | Description |
|--------|-------------|
| **Data** | Date of the violation |
| **Tipo Infrazione** | Violation type code (e.g., `ECCESSO_GUIDA_CONTINUA`) |
| **Severità** | Severity level: **MSI**, **SI**, or **MI** |
| **Descrizione** | Human-readable explanation of the violation |

### Severity Levels
- **MSI** (Most Serious Infringement): Severe violations (>30 min over continuous driving limit, >2h short on daily rest)
- **SI** (Serious Infringement): Significant violations (up to 90 min over driving, up to 2h short on rest)
- **MI** (Minor Infringement): Small excesses (up to 30 min over driving, up to 1h short on rest)

### Fines Estimate
The red banner above the table shows the estimated fine range based on the Italian Highway Code (Art. 174 C.d.S.). Fines are cumulative across all infractions.

For a deeper explanation, see the [Compliance Guide](compliance_guide.md).

---

## Fleet Tab (FLOTTA)

The Fleet tab enables batch analysis of multiple `.ddd` files from a folder.

### Workflow
1. Click **"Seleziona Cartella"** and choose a folder containing `.ddd` files.
2. Click **"Analizza"** to process all files in the folder.
3. Review the results table and KPI summary bar.
4. Export results with **"Esporta CSV"** or **"Esporta PDF"**.

### Results Table

| Column | Description |
|--------|-------------|
| **Conducente** | Driver name |
| **Carta** | Driver card number |
| **KM Totali** | Total distance traveled |
| **Ore Guida** | Total driving hours |
| **Ultima Attività** | Date of last recorded activity |
| **Infrazioni** | Number of violations (color-coded) |
| **Integrità** | Signature verification status |
| **File** | Source filename |

### KPI Summary Bar
- Number of drivers processed
- Total KM across the fleet
- Total driving hours
- Total infractions

---

## Export (Single File)

Three export buttons in the sidebar save the currently loaded file's data:

| Format | Description |
|--------|-------------|
| **JSON** | Full structured output with all parsed fields |
| **Excel** | Multi-sheet workbook (.xlsx) |
| **CSV** | Flat CSV with time ranges |

Click any export button, choose a save location, and the file will be written. For details on each format, see the [Export Guide](export_guide.md).
