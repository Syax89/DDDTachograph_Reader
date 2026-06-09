# Frequently Asked Questions

---

### What is a .ddd file?

A `.ddd` file is a binary download from a digital tachograph. It contains all recorded data from a specific period: driver identity, vehicle information, daily activity records (driving, work, rest), GNSS (GPS) positions, events, faults, and digital signatures that prove the data has not been tampered with.

There is no standard tool to open `.ddd` files on a normal computer. This application is designed to fill that gap.

---

### What's the difference between driver card and VU files?

| | Driver Card (Carta) | Vehicle Unit (VU) |
|---|---|---|
| **Source** | Downloaded from the driver's personal tachograph card | Downloaded from the tachograph unit installed in the vehicle |
| **Contains** | One driver's activities across multiple vehicles | Activities of all drivers who used that vehicle |
| **Infractions tab** | Visible (compliance is per-driver) | Hidden (multiple drivers on one unit) |
| **Typical use** | Driver monitoring, compliance checking | Fleet management, vehicle usage analysis |

---

### What do G1, G2, and G2.2 mean?

These are the three generations of digital tachographs:

- **G1 (Generation 1)**: The original digital tachograph standard (Annex 1B of Reg. 3821/85). Uses STAP encoding.
- **G2 (Generation 2)**: First-generation Smart Tachograph (Annex 1C, Reg. EU 2016/799). Uses BER-TLV encoding. Adds GNSS recording and remote communication.
- **G2.2 (Generation 2.2)**: Second-generation Smart Tachograph (Reg. EU 2023/980). Adds new fields and enhanced security.

The application automatically detects which generation a file belongs to based on the first 2 bytes (`0x7631` = G2.2, `0x7621`/`0x7622` = G2, other = G1).

---

### Why are some GNSS positions missing?

GNSS positions are recorded by the tachograph at specific intervals (typically when the vehicle starts, every 3 hours, and when it stops). Not every minute of driving has a GPS coordinate. Additionally, some older G1 tachographs do not have GNSS capability at all. Gaps in position data are normal and expected.

---

### What does "byte coverage" mean?

Byte coverage is the percentage of the `.ddd` file that the parser can interpret. A value of **100%** means every byte in the file was successfully decoded. If coverage is below 100%, some sections of the file could not be parsed (possibly due to a new or undocumented tag format).

All test files in the project achieve 100% coverage.

---

### Can I analyze multiple files at once?

Yes. Use the **Fleet tab** in the GUI: select a folder containing `.ddd` files and click "Analizza". The application processes all files and displays a comparative table with key metrics for each driver/vehicle.

From the command line, directory batch processing is available.

---

### Is my data secure?

Yes. All processing is **local** — your `.ddd` files never leave your computer. There is no cloud upload, no telemetry, and no data sharing. The only network requests are optional: downloading ERCA certificates for signature validation and reverse geocoding (if you enable the `--geocode` flag).

---

### How do I report a bug?

Open an issue on the [GitHub repository](https://github.com/Syax89/ddd-tachograph-reader/issues). Please include:
- The operating system you're using
- The `.ddd` file generation (G1, G2, or G2.2)
- A description of what happened vs. what you expected
- Any error messages displayed

---

### What regulations are supported?

- **EU 561/2006**: Driving times, breaks, and rest periods for professional drivers
- **Italian C.d.S. Art. 174**: Fines estimation for tachograph violations
- **EU 2016/799 (Annex 1C)**: Smart Tachograph data specification
- **EU 2023/980**: Smart Tachograph V2 data specification
- **Reg. 3821/85 (Annex 1B)**: Original digital tachograph specification

---

### Can the tool edit or modify .ddd files?

No. The application is **read-only**. It parses, analyzes, and exports data from `.ddd` files but never modifies them. This ensures the original file remains forensically intact.

---

### Why does the infractions tab not appear?

The infractions tab is only shown when a **driver card** file is loaded. Vehicle unit (VU) files contain data from multiple drivers, so compliance analysis per-driver is not performed on VU files.

---

### Does the tool work on Linux?

The application is developed and tested on Windows and macOS. If you are comfortable running Python scripts, you can use the from-source installation on Linux by running `python gui_tree.py` or the CLI tools. However, Linux is not an officially supported platform for the pre-built executables.
