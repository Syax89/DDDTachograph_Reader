# Installation Guide

## Windows

1. Go to the [GitHub Releases page](https://github.com/Syax89/ddd-tachograph-reader/releases/latest).
2. Download **`TachoReader-Windows.zip`**.
3. Extract the ZIP file to a folder of your choice.
4. Double-click **`TachoReader.exe`** to launch.

> **Note**: Windows SmartScreen may show a warning because the executable is not code-signed. Click "More info" → "Run anyway" to proceed.

## macOS

1. Go to the [GitHub Releases page](https://github.com/Syax89/ddd-tachograph-reader/releases/latest).
2. Download **`TachoReader-Mac.zip`**.
3. Extract the ZIP file.
4. **Right-click** the `TachoReader` app and select **Open** (this bypasses Gatekeeper on first run).
5. If prompted, confirm you want to open the application.

> **Why right-click?** macOS Gatekeeper blocks unsigned applications. The right-click → Open method allows you to run the app after confirming.

## From Source (Developers)

If you prefer to run the tool from Python source:

```bash
git clone https://github.com/Syax89/ddd-tachograph-reader.git
cd ddd-tachograph-reader
pip install -r requirements.txt
```

### Required Dependencies

| Package | Purpose |
|---------|---------|
| `cryptography` | Digital signature verification (ERCA/MSCA certificate chain) |
| `reportlab` | PDF report generation |
| `pandas` | Data manipulation for fleet analysis |
| `openpyxl` | Excel file export (.xlsx) |
| `requests` | Certificate downloads and geocoding API calls |

The GUI uses Python's built-in `tkinter` — no extra GUI package is required.

**Python 3.9 or later is required.**

### Launching

```bash
# GUI
python gui_tree.py

# CLI
python main.py file.ddd
```

## Verification

After installation, verify everything works:

```bash
python main.py --help
```

Or with the advanced CLI:

```bash
python tacho_cli.py --help
```

The help text should display the available options and example commands without errors.
