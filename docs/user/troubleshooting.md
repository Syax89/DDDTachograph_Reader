# Troubleshooting

---

## "File not recognized" or Parsing Fails

**Symptom**: The application shows an error when loading a file, or the parsed data is empty.

**Possible causes and fixes**:

1. **The file is not a tachograph download**: The reader expects the raw binary download from a card or vehicle unit. Files with other extensions such as `.esm`, `.tgd`, `.c1b`, and `.v1b` are usually the *same* EU download under a different name — open them via **All Files** in the dialog (or rename to `.ddd`). See the [FAQ](faq.md) for the one exception (`.esm` files that wrap or compress the payload).
2. **File is corrupted or partial**: For VU downloads the reader reports TREP completeness and, when data is genuinely missing, shows a **CORRUPTED / PARTIAL FILE** page with what could be recovered. If the whole file fails at the first bytes, try downloading it again from the tachograph or card reader.
3. **Unsupported generation**: If the file uses a future tachograph standard not yet implemented, the parser reports unparsed blocks, tracked as gap ranges in the **Raw Tags** section.

---

## Unparsed / Unknown Data

**Symptom**: A file parses successfully but some bytes are reported as unknown.

**What this means**: A few regions could not be interpreted by the parser. They are swept up, classified as padding or tracked unknown ranges, and shown in the **Raw Tags** section — never silently dropped.

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

**Symptom**: Running `python app/gui.py` produces an error or the window doesn't appear.

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

---

## "ImportError: No module named X"

**Symptom**: A Python import error when running from source.

**Fix**: Install the missing package or reinstall all dependencies:

```bash
pip install -r requirements.txt
```

Note that `reportlab` is only needed for PDF export and `openpyxl` only for Excel export — parsing and JSON output work without them.

---

## Performance Tips for Large Files

Large `.ddd` files (90+ days of data, or vehicle unit files with detailed speed blocks) may take longer to process:

1. **Use the CLI for batch processing**: The command-line interface is faster than the GUI for processing many files in a shell loop.
2. **Export to JSON first, then analyze**: Parse the file once with JSON output, then use the JSON for repeated analysis instead of re-parsing the binary `.ddd`.
3. **The GUI stays responsive**: Parsing runs in a background thread; the progress bar in the status bar shows when work is in progress.

---

## Still Having Issues?

If none of the above resolves your problem:

1. Run with verbose logging to capture detailed error information:
   ```bash
   python app/cli.py file.ddd --verbose --summary
   ```
2. Check the [FAQ](faq.md) for other common questions.
3. Open a [GitHub issue](https://github.com/Syax89/DDDTachograph_Reader/issues) with the verbose output and a description of your environment (OS, Python version, file generation).
