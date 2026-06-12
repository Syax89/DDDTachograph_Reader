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
| **Typical use** | Driver monitoring | Fleet management, vehicle usage analysis |

The application detects the file type automatically and adapts the section tree accordingly (e.g., VU-specific sections such as sensor pairings, company locks, and detailed speed blocks only appear for VU files).

---

### What do G1, G2, and G2.2 mean?

These are the three generations of digital tachographs:

- **G1 (Generation 1)**: The original digital tachograph standard (Annex 1B of Reg. 3821/85). Uses STAP encoding.
- **G2 (Generation 2)**: First-generation Smart Tachograph (Annex 1C, Reg. EU 2016/799). Uses BER-TLV encoding. Adds GNSS recording and remote communication.
- **G2.2 (Generation 2.2)**: Second-generation Smart Tachograph (Reg. EU 2023/980). Adds new fields (border crossings, load/unload operations, trailer registrations) and enhanced security.

The application automatically detects which generation a file belongs to from the file header (`0x7631` = G2.2, `0x7621`/`0x7622` = G2, otherwise G1).

---

### Why are some GNSS positions missing?

GNSS positions are recorded by the tachograph at specific intervals (typically when the vehicle starts, every 3 hours of accumulated driving, and when it stops). Not every minute of driving has a GPS coordinate. Additionally, G1 tachographs do not have GNSS capability at all. Gaps in position data are normal and expected.

---

### What does "byte coverage" mean?

Byte coverage is the percentage of the `.ddd` file that the parser can interpret. A value of **100%** means every byte in the file was successfully decoded (including recognized padding). If coverage is below 100%, some sections of the file could not be parsed (possibly due to a new or undocumented tag format).

All test files in the project achieve 100% coverage.

---

### Does the tool check driving-time rules (EU 561/2006)?

No. The tool is a **parser and integrity validator**: it decodes the recorded activities and verifies the digital signatures, but it does not currently evaluate driving-time or rest-period rules and does not estimate fines. You can export the activity data to JSON or Excel and run your own compliance analysis on it.

---

### Is my data secure?

Yes. All processing is **local** — your `.ddd` files never leave your computer. There is no cloud upload, no telemetry, and no data sharing. Signature verification uses the ERCA root certificates bundled with the application in the `certs/` folder.

---

### How do I report a bug?

Open an issue on the [GitHub repository](https://github.com/Syax89/ddd-tachograph-reader/issues). Please include:
- The operating system you're using
- The `.ddd` file generation (G1, G2, or G2.2)
- A description of what happened vs. what you expected
- Any error messages displayed

---

### What regulations are supported?

- **Reg. 3821/85 (Annex 1B)**: Original digital tachograph specification
- **EU 2016/799 (Annex 1C)**: Smart Tachograph data specification
- **EU 2021/1228** and **EU 2023/980**: Smart Tachograph V2 data specification

---

### Can the tool edit or modify .ddd files?

No. The application is **read-only**. It parses, analyzes, and exports data from `.ddd` files but never modifies them. This ensures the original file remains forensically intact.

---

### Does the tool work on Linux?

The application is developed and tested on Windows and macOS. If you are comfortable running Python scripts, you can use the from-source installation on Linux by running `python gui_tree.py` or the CLI tools. However, Linux is not an officially supported platform for the pre-built executables.
