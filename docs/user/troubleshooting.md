# Troubleshooting

---

## "File not recognized" or Parsing Fails

**Symptom**: The application shows an error when loading a file, or the parsed data is empty.

**Possible causes and fixes**:

1. **The file is not a .ddd file**: Verify the file extension is `.ddd`. Files with other extensions (`.esm`, `.tgd`, `.c1b`, `.v1b`) are different formats and cannot be opened.
2. **File is corrupted**: Try downloading the file again from the tachograph or card reader. A corrupted file will fail at the first bytes of decoding.
3. **Unsupported generation**: If the file uses a future tachograph standard not yet implemented, the parser will report unparsed blocks. Check the byte coverage percentage — anything below 100% may indicate an unsupported format.

---

## "Coverage below 100%"

**Symptom**: A file parses successfully but shows less than 100% byte coverage.

**What this means**: Some bytes in the file could not be interpreted by the parser. These are tracked as gap ranges and shown in the **Raw Tags** section.

**What to do**:
- If coverage is above 95%, the missing bytes are likely padding or unused regions and the extracted data is still valid.
- If coverage is significantly below 100%, the file may use a new or proprietary tag format. Open a GitHub issue (without sharing sensitive personal data) so support can be added.

---

## Integrity shows "Incomplete" or "Missing ERCA"

**Symptom**: The integrity status shows yellow ("Incomplete" / "Missing ERCA") instead of green ("Verified").

**Explanation**: The ERCA (European Root Certificate Authority) certificate needed to validate that file's signature chain is not available. The data is still readable and accurate — only the cryptographic proof of authenticity is incomplete.

**What to do**: The application ships with the ERCA root certificates in the `certs/` folder. If a certificate generation is missing, you can download it from the EU Joint Research Centre ([dtc.jrc.ec.europa.eu](https://dtc.jrc.ec.europa.eu/)) and place it in `certs/` — see `certs/README.txt` for the expected file names.

## Integrity shows "Invalid Certificate Chain"

**Symptom**: The integrity status is red.

**Explanation**: The signature check was performed but failed. This could indicate file tampering or a corrupted download.

**What to do**: If you trust the source of the file, download it again from the card/unit and re-check. If the failure persists, treat the file's authenticity as unverified.

---

## GUI Won't Start

**Symptom**: Running `python gui_tree.py` produces an error or the window doesn't appear.

**Common fixes**:

1. **Missing dependencies**: Install all dependencies at once:
   ```bash
   pip install -r requirements.txt
   ```

2. **Wrong Python version**: The GUI requires Python 3.9 or later. Check your version:
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
   python tacho_cli.py file.ddd --verbose --summary
   ```
2. Check the [FAQ](faq.md) for other common questions.
3. Open a [GitHub issue](https://github.com/Syax89/ddd-tachograph-reader/issues) with the verbose output and a description of your environment (OS, Python version, file generation).
