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

**What this means**: Some bytes in the file could not be interpreted by the parser. These are tracked as gap ranges.

**What to do**:
- If coverage is above 95%, the missing bytes are likely padding or unused regions and the extracted data is still valid.
- If coverage is significantly below 100%, the file may use a new or proprietary tag format. Report the file to the project (without sharing sensitive personal data) so support can be added.

---

## "Certificate validation failed" or "Incomplete Certificates"

**Symptom**: The integrity status shows "Incomplete Certificates" or "Not Verified" instead of "Verified".

**Explanation**:
- **Incomplete Certificates**: The ERCA (European Root Certificate Authority) certificates needed to validate the digital signature are not installed on your computer. The data is still readable and accurate — only the cryptographic proof of authenticity is unavailable.
- **Not Verified / Tampered**: The signature check was performed but failed. This could indicate file tampering, but can also happen with older cards using deprecated certificate formats.

**What to do**:
- For "Incomplete Certificates": Try running with an internet connection — the application can download the required certificates automatically.
- For "Not Verified": If you trust the source of the file, the data is likely still valid. If you suspect tampering, contact the driver or download the file again from the card/unit.

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

3. **macOS tkinter issues**: On macOS, the built-in Python may lack tkinter support. Install Python via Homebrew:
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

The full dependency list is:

| Package | pip install command |
|---------|-------------------|
| cryptography | `pip install cryptography` |
| reportlab | `pip install reportlab` |
| pandas | `pip install pandas` |
| openpyxl | `pip install openpyxl` |
| requests | `pip install requests` |

---

## Performance Tips for Large Files

Large `.ddd` files (90+ days of data, or vehicle unit files with many drivers) may take longer to process. Here are tips for better performance:

1. **Use the CLI for batch processing**: The command-line interface is faster than the GUI for processing multiple files. Use `tacho_cli.py` for automated workflows.
2. **Disable reverse geocoding**: The `--geocode` flag makes a network request for each GNSS position, which adds significant time. Use it only when you need location names.
3. **Close other applications**: Parsing and compliance analysis are CPU-intensive. Close heavy applications if you notice slowdowns.
4. **Export to JSON first, then analyze**: Parse the file once with JSON output, then use the JSON for repeated analysis instead of re-parsing the binary `.ddd`.
5. **For fleet analysis**: The Fleet tab processes files in a background thread so the GUI remains responsive, but large folders (50+ files) may take several minutes. Monitor the progress bar.

---

## Still Having Issues?

If none of the above resolves your problem:

1. Run with verbose logging to capture detailed error information:
   ```bash
   python tacho_cli.py file.ddd --verbose --summary
   ```
2. Check the [FAQ](faq.md) for other common questions.
3. Open a [GitHub issue](https://github.com/Syax89/ddd-tachograph-reader/issues) with the verbose output and a description of your environment (OS, Python version, file generation).
