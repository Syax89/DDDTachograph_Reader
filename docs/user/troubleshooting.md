# Troubleshooting

---

## "File not recognized" or Parsing Fails

**Symptom**: The application shows an error when loading a file, or the parsed data is empty.

**Possible causes and fixes**:

1. **The file is not a tachograph download**: The reader expects the raw binary download from a card or vehicle unit. Files with other extensions such as `.esm`, `.tgd`, `.c1b`, and `.v1b` are usually the *same* EU download under a different name — open them via **All Files** in the dialog (or rename to `.ddd`). See the [FAQ](faq.md) for the one exception (`.esm` files that wrap or compress the payload).
2. **File is corrupted or partial**: For VU downloads the reader reports TREP completeness and, when data is genuinely missing, shows a **CORRUPTED / PARTIAL FILE** page with what could be recovered. If the whole file fails at the first bytes, try downloading it again from the tachograph or card reader.
3. **Unsupported generation**: If the file uses a future tachograph standard not yet implemented, the parser reports unparsed blocks, tracked as gap ranges in the **Raw / Unparsed Data** section.

---

## Unparsed / Unknown Data

**Symptom**: A file parses successfully but some bytes are reported as unknown.

**What this means**: A few regions could not be interpreted by the parser. They are swept up, classified as padding or tracked unknown ranges, and shown in the **Raw / Unparsed Data** section — never silently dropped.

**What to do**:
- Small unknown regions are usually padding or unused areas; the extracted data is still valid.
- If a large portion is unknown, the file may use a new or proprietary tag format. Open a GitHub issue (without sharing sensitive personal data) so support can be added.

---

## Integrity Warning: Partial Chain or "Missing ERCA"

**Symptom**: The integrity banner appears with a partial-verification or "Missing ERCA" note instead of staying quiet.

**Explanation**: The ERCA (European Root Certificate Authority) certificate needed to complete that file's signature chain is not available, so the chain is only partially anchored. The data is still readable and accurate — only the full cryptographic proof of authenticity is incomplete.

**What to do**: The application ships with the ERCA root certificates in the `certs/` folder. If a certificate generation is missing, you can download it from the EU Joint Research Centre ([dtc.jrc.ec.europa.eu](https://dtc.jrc.ec.europa.eu/)) and place it in `certs/` — see `certs/README.txt` for the expected file names.

## Integrity Warning: "Invalid Certificate Chain"

**Symptom**: The integrity banner shows a red failure.

**Explanation**: The signature check was performed but failed. This could indicate file tampering or a corrupted download.

**What to do**: If you trust the source of the file, download it again from the card/unit and re-check. If the failure persists, treat the file's authenticity as unverified. Click the integrity banner for the full breakdown (TREP completeness, chain result, EF signatures).

---

## GUI Won't Start

**Symptom**: Running `python -m app.gui` produces an error or the window doesn't appear.

**Common fixes**:

1. **Missing dependencies**: Install all dependencies at once:
   ```bash
   pip install -r requirements.txt
   ```

2. **Wrong Python version**: The GUI requires Python 3.10 or later. Check your version:
   ```bash
   python --version
   ```

3. **macOS tkinter issues**: On macOS, the built-in Python may lack tkinter support. Install it via Homebrew:
   ```bash
   brew install python-tk
   ```
4. **Wrong invocation**: `python app/gui.py` fails with `ModuleNotFoundError: No module named 'app'` because the package root is not on the import path. Run it as a module from the repository root: `python -m app.gui`.

---

## The Window Seemed Frozen While Opening a File (macOS)

**Symptom**: after choosing a file in the macOS file dialog the window stops
responding for several seconds — the progress bar sits still and clicks do
nothing — and then the file appears.

**What changed**: opening a file no longer lets the render pump the Tk event loop
on macOS. The window repaints with idle tasks only and moves the busy bar itself,
the parse starts only after the system file dialog has closed, the garbage
collector is paused while a file is parsed and drawn, and the tree column is
fitted from a handful of measurements instead of one per node. Linux and Windows
never had this behaviour and are unchanged.

**If it still happens**: the reader now notices a real stall by itself, and there
are two ways to capture more.

1. **`~/ddd-reader-stall-report.txt`** — written by the application on its own
   when the main thread stays in the same place for three seconds, once per
   session, and its path is printed to standard error. It holds the platform, the
   Python and Tk versions, the stack the window was stuck in and the last recorded
   load steps — no file names, paths, card numbers or driver data — and a normal
   session writes no report at all. A system dialog waiting for you and Tk's own
   event loop are not treated as stalls. Attach it to an issue.
2. **`DDD_TRACE_LOAD=1`** writes a live trace of each open to
   `~/ddd-reader-load-trace.txt`: the extension, size, generation and record
   counts of each stage, never contents, names or directories. Start the
   application from the Terminal so the variable reaches it:

   ```bash
   DDD_TRACE_LOAD=1 /Applications/TachoReader.app/Contents/MacOS/TachoReader
   ```

   Open two files in a row and send that file back with the stall report.

`DDD_PUMP_MODE=events` puts the old event-pumping render back for one run, which
is how to confirm that the pump is the cause; `DDD_PUMP_MODE=idle` restores the
default on macOS. It is a support switch, not a setting to keep.

---

## Drag & Drop Does Nothing

**Symptom**: You drop a `.ddd` file on the window and nothing happens, and the empty
pane has no "or drop it here" hint.

**Explanation**: drag & drop comes from the optional `tkinterdnd2` package and the
`tkdnd` binary it ships with. When either is missing, the application starts
normally with drag & drop silently disabled — the hint is not shown, and nothing
else changes.

**Fix**: install the package when running from source
(`pip install -r requirements.txt` installs it) and restart. The packaged builds
include it. Opening files through **Open DDD file** or the recent-files list always
works.

---

## The Language Did Not Change

**Symptom**: You picked a language and the window still shows the old one, or the
tick jumped back.

**Explanation**: switching language restarts the application window in the new
language and reopens the file you were viewing. The switch is refused — and the
menu returns to the active language — while a file is being parsed, drawn or
exported, so that no work is lost. The same happens if the per-user settings file
cannot be written; a warning is shown.

**Fix**: wait until the file is on screen (or the export has finished) and choose
the language again. If the warning reappears, check that the settings file is
writable: `%APPDATA%\TachoReader\settings.json` on Windows,
`~/Library/Application Support/TachoReader/settings.json` on macOS,
`~/.config/TachoReader/settings.json` on Linux (`$XDG_CONFIG_HOME/TachoReader/settings.json` when `XDG_CONFIG_HOME` is set).

Note that **Translate file contents**, the tick under the language list, does not
restart anything — it re-renders the open file in place, so it changes the cells
immediately rather than the window's own text.

---

## Recent Files Is Empty or a File Disappeared

**Symptom**: The empty pane shows no **Recent files**, or a file you used
yesterday is missing from the list.

**Explanation**: the list holds the last 8 files that were parsed **successfully**
and only shows the ones that still exist. A file on an unplugged USB stick or a
deleted download is hidden without being forgotten, so it reappears once the
drive is mounted again; a file that failed to parse is never added.

**Fix**: reopen the file from its current location; it will be recorded again.
The history lives in the same per-user `settings.json` as the language.

---

## "ImportError: No module named X"

**Symptom**: A Python import error when running from source.

**Fix**: Install the missing package or reinstall all dependencies:

```bash
pip install -r requirements.txt
```

Note that `reportlab` is only needed for PDF export and `openpyxl` only for Excel export — parsing and JSON output work without them. The GUI still starts without `tkinterdnd2`; it just has no drag & drop.

A `ModuleNotFoundError: No module named 'core'` (or `'app'`) means the entry point
was called by path instead of as a module: run `python -m app.cli file.ddd` or
`python -m app.gui` from the repository root.

---

## "Export Unavailable" When Saving a PDF or Excel File

**Symptom**: The Export menu shows a warning instead of asking where to save.

**Explanation**: PDF export needs `reportlab` and Excel export needs `openpyxl`.
When one of them is missing (typically in a source checkout), that format is
unavailable and the dialog says so; CSV and JSON keep working.

**Fix**: `pip install -r requirements.txt`, or install the single package
(`pip install reportlab` / `pip install openpyxl`). The packaged Windows, macOS and
Linux builds include both.

---

## Performance Tips for Large Files

Large `.ddd` files (90+ days of data, or vehicle unit files with detailed speed blocks) may take longer to process:

1. **Use the CLI for batch processing**: The command-line interface is faster than the GUI for processing many files in a shell loop.
2. **Export to JSON first, then analyze**: Parse the file once with JSON output, then use the JSON for repeated analysis instead of re-parsing the binary `.ddd`.
3. **The GUI stays responsive**: the progress bar in the status bar keeps moving while a file loads, and the window is not frozen while it is drawn. If the window really does freeze on macOS while a file opens, see [The Window Seemed Frozen While Opening a File](#the-window-seemed-frozen-while-opening-a-file-macos) — the reader writes a report you can send.

---

## Still Having Issues?

If none of the above resolves your problem:

1. Run with verbose logging to capture detailed error information:
   ```bash
   python -m app.cli file.ddd --verbose --summary
   ```
2. Check the [FAQ](faq.md) for other common questions.
3. Open a [GitHub issue](https://github.com/Syax89/DDDTachograph_Reader/issues) with the verbose output and a description of your environment (OS, Python version, file generation).
