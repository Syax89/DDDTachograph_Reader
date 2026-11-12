# Command-Line Interface (CLI) Guide

The DDD Tachograph Reader provides `app/cli.py` for command-line parsing, export,
and reporting. `app/main.py` is a compatibility entry point that delegates to the
same CLI. Run both **as modules from the repository root** — calling
`python app/cli.py` by path fails with `ModuleNotFoundError: No module named
'core'`, because the package root is not on the import path:

```bash
python -m app.cli --help
python -m app.main --help   # identical
```

The CLI is meant for scripts and automation: it never opens a window, its output
is always English (the interface language and the *Translate file contents*
preference do not apply here), and it writes nothing except the files you ask
for.

---

## Basic Usage

With a file and no output flag, the CLI prints the compact summary **and** the
JSON. The JSON owns standard output and the summary goes to standard error, so
the parsed structure can be piped straight into another tool while a human
reading the terminal still sees both:

```bash
python -m app.cli file.ddd
python -m app.cli file.ddd | jq '.metadata.integrity_check'
```

### Parse and Display Summary

```bash
python -m app.cli file.ddd --summary
```

The summary shows file metadata (type and generation), signature verification
status, driver and vehicle identity, and per-activity totals (drive / work /
available / rest) computed from the daily activity records. For a vehicle-unit
download it also reports TREP completeness as `OK:` or `Warning:`.

### JSON Output

The default invocation above already prints the JSON after the summary. To keep
the parsed structure on its own, write it to a file:

```bash
python -m app.cli file.ddd --json output.json
```

With `--json` and no filename, an auto-named file is written to the current
directory:

```bash
python -m app.cli file.ddd --json
# Creates: ./file_20261019_143022.json
```

Auto names are second-granular and never overwrite: a second run in the same
second gets a numeric suffix (`file_20261019_143022_1.json`). An explicit path is
used exactly as given — except `-`, which means standard output:

```bash
python -m app.cli file.ddd --json - > result.json
```

The JSON is the **complete parsed output** of the reader — metadata, driver,
vehicle, activities, records, raw tags and verification results — and not a
reversible copy of the original `.ddd` file. Keep the source file for archival.

### Export Formats

**Excel** (multi-sheet workbook, typed cells):

```bash
python -m app.cli file.ddd --excel report.xlsx
```

**PDF** (formatted report with cover and Technical Appendix):

```bash
python -m app.cli file.ddd --pdf report.pdf
```

**CSV** (one semicolon-separated UTF-8 block per section):

```bash
python -m app.cli file.ddd --csv report.csv
```

**GNSS positions for a map** (G2/G2.2 files; generation 1 records no
positions, so its file is empty but valid):

```bash
python -m app.cli file.ddd --gpx route.gpx
python -m app.cli file.ddd --kml route.kml
```

The route (positions recorded every 3 h of accumulated driving) is a track;
the start/end of each daily work period, border crossings and load/unload
operations are waypoints. No driver name or card number is written. GPX/KML
are not part of `--all`; a bare `--gpx`/`--kml` next to `--all` writes into
that directory, and in a batch `--gpx DIR`/`--kml DIR` write one file per input.

**All formats at once** (JSON, PDF, Excel, CSV into a directory):

```bash
python -m app.cli file.ddd --all output_dir/
```

`--all` creates the directory if needed and can be combined with explicit file
names; a bare `--json` / `--pdf` / `--excel` / `--csv` inside `--all` writes the
auto-named file into that directory instead of the current one. If the path
exists and is not a directory, the CLI stops with an error. A bare `--all` uses
`<file>_output/`.

Exports are written as they are generated: if one format fails (for example a
missing `reportlab`), the others are still produced, the failure is reported on
standard error as a `Warning: …` line (for a missing `reportlab`: `Warning: PDF export
requires reportlab (pip install reportlab): …`; other failures read
`Warning: … generation failed: …`), and the process exits non-zero.

### Verbose Output

Use `-v` or `--verbose` for detailed debug logs and full Python tracebacks on errors:

```bash
python -m app.cli file.ddd --verbose --summary
```

### Quiet Output

`-q` / `--quiet` suppresses everything on screen, so only the files are written:

```bash
python -m app.cli file.ddd --pdf report.pdf --quiet
```

`--json -` is the one exception: it explicitly asks for the JSON on standard
output, so `-q --json -` still prints the payload there (and nothing else —
summary, warnings and progress stay silent). Redirect it if only the file
matters: `python -m app.cli file.ddd --json out.json --quiet`.

---

## Complete Option Reference

| Flag | Argument | Description |
|------|----------|-------------|
| *(positional)* | `PATH …` | One or more `.ddd` files or directories (required); more than one, or any directory, makes a [batch](#batch-processing) |
| `-r`, `--recursive` | — | In a batch, also scan the subdirectories of a directory argument |
| `--json` | `[FILE]` | Generate JSON output (optional output path) |
| `--pdf` | `[FILE]` | Generate PDF report (optional output path; needs `reportlab`) |
| `--excel` | `[FILE]` | Generate Excel report (optional output path; needs `openpyxl`) |
| `--csv` | `[FILE]` | Generate CSV report (optional output path) |
| `--gpx` | `[FILE]` | Export the GNSS positions as GPX (optional output path) |
| `--kml` | `[FILE]` | Export the GNSS positions as KML (optional output path) |
| `--all` | `[DIR]` | Generate all four formats into a directory (in a batch: every file's reports into that one directory) |
| `--summary` | — | Show the compact text summary on screen |
| `--version` | — | Print the reader version (`TachoReader 2.9.1`) |
| `-v`, `--verbose` | — | Verbose debug output |
| `-q`, `--quiet` | — | Suppress all screen output (files only); `--json -` still writes the JSON to standard output |

**Exit codes:** `0` on success; `1` when the file is missing, cannot be parsed,
carries no decodable tachograph structure (`Error: no tachograph structure was
decoded` — no card, VU or certificate record could be decoded from it), or an
export failed; `2` for a usage error (unknown flag, missing file argument,
`--json -` with several inputs). In a batch, `0` means every input was processed
and `1` that at least one failed — the others were still processed.

---

## Batch Processing

Give several paths, or a directory, and the CLI processes them all in one run:

```bash
python -m app.cli DDD/ --summary                   # every .ddd in DDD/
python -m app.cli DDD/ --recursive --all reports/   # sub-folders too, all formats
python -m app.cli a.ddd b.ddd "c d.ddd" --excel xlsx/
```

**Which files.** A file argument is processed as given. A directory contributes
the `.ddd` files directly inside it (the extension in any letter case: `.ddd`,
`.DDD`), in name order; `-r` / `--recursive` adds those in its subdirectories.
Other files are ignored. A file reached twice (a file and its own folder) is
processed once. A directory holding no `.ddd` file is reported as an error.

**When it is a batch.** More than one path, or any directory — even one that
holds a single file — is a batch. A single file path is the classic run
described above, unchanged.

**Where the outputs go.** In a batch an output argument names a **directory**,
created if needed, and every input gets its own auto-named file in it
(`<file>_<timestamp>.<ext>`, with a numeric suffix rather than an overwrite when
two inputs share a name):

| Flag in a batch | Writes |
|-----------------|--------|
| `--json DIR` / `--pdf DIR` / `--excel DIR` / `--csv DIR` | one file per input into `DIR` |
| bare `--json` / `--pdf` / `--excel` / `--csv` | one auto-named file per input in the current directory |
| `--all DIR` | all four formats of every input into `DIR` |
| bare `--all` | one `<file>_output/` directory per input, as for a single file |
| `--json -` | refused (exit `2`): standard output cannot hold several JSON documents |

If an output path exists and is not a directory, the run stops with exit `1`
before any file is parsed.

**What is printed.** A batch never writes JSON to standard output. Each input
prints its summary when `--summary` is given or when no output flag is, then its
list of generated files; errors and warnings go to standard error and name the
file (`Error: DDD/x.ddd: no tachograph structure was decoded`). The run ends
with a table of every input:

```
============================================================
BATCH SUMMARY: 3 inputs, 2 OK, 1 failed
============================================================
File            Gen              Type  Integrity   Days  Errors
DDD/card.ddd    G1 (Digital)     Card  verified     242  -
DDD/vu.ddd      G2.2 (Smart V2)  VU    partial       31  -
DDD/broken.ddd  -                -     -              -  no tachograph structure was decoded
```

*Integrity* is the canonical verdict — `verified`, `partial`, `unverified` or
`corrupt` — the same classification the window's integrity badge uses; *Days*
counts the distinct days with activity records. `-q` holds back the summaries,
the file lists and the table; errors still reach standard error.

**Errors.** One bad input never stops the batch: it is reported, gets its row in
the table, and the next input is processed. The exit code is `1` if any input
failed (missing, unparsable, not a tachograph download, an export failed, or an
empty directory), `0` otherwise.

Files are processed one after another in a single process; there is no parallel
mode.

---

## Integrating with Scripts

The default invocation puts the JSON on standard output and the human summary on
standard error, so a script can pipe the default output directly. It can equally
ask for a JSON file and parse that:

```bash
python -m app.cli file.ddd --json result.json --quiet

jq '.driver' result.json
jq '.metadata.integrity_check' result.json
jq '.activities[].date' result.json
jq '.metadata.coverage_pct' result.json
```

`--quiet` keeps standard output empty, so a loop's log stays readable and nothing
is lost if the caller redirects it.
