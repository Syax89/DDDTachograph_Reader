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

### Driving and Rest Times (Regulation (EC) No 561/2006)

`--rules` adds an **indicative** check of a driver card's recorded activity
against the driving-time, break and rest rules of Regulation (EC) No 561/2006:

```bash
python -m app.cli card.ddd --rules              # text report on screen
python -m app.cli card.ddd --rules --json -     # JSON, with the report under "regulation_561"
```

On its own, `--rules` prints only the report (add `--summary` for the summary
too). With `--json` the report is added to the JSON under the key
`regulation_561` — only when `--rules` is given, so the default JSON keeps its
shape. The report lists *findings*, each with the rule, its article, the period
(UTC), the measured value, the limit and an explanation, plus a per-rule count
of what was assessed.

What is checked — the days are joined into one continuous UTC timeline, so
periods running over midnight are measured as a whole:

| Rule | Article | Limit |
|------|---------|-------|
| Break after driving | 7 | 4 h 30 driving, then 45 min — or 15 min followed by 30 min — of rest |
| Daily driving | 6(1) | 9 h between two daily rests, 10 h at most twice per fixed week |
| Weekly / fortnightly driving | 6(2), 6(3) | 56 h per Monday–Sunday week, 90 h in two consecutive weeks |
| Daily rest | 8(1)–(2) | 11 h (or 3 h + 9 h, or reduced 9 h) within 24 h of the previous rest |
| Reduced daily rests | 8(4) | at most three between two weekly rests |
| Weekly rest | 8(6) | starts within six 24-hour periods of the previous one; two per two weeks, one of them ≥ 45 h |

Only *Rest* counts as a break or rest: *Work* and *Availability* do not. A
finding is either an **infringement** or **indeterminate**. Periods the card did
not record (card not inserted, missing days, the time after the download) can
never produce an infringement: when a result depends on whether such a period
was rest, it is indeterminate. Periods recorded in crew mode make break and
daily results indeterminate too, because the multi-manning rules are not
modelled; nor are reduced-weekly-rest compensation, ferry/train interruptions,
derogations and exemptions (the report lists them under *Not modelled*).

Vehicle-unit downloads are not analysed: a vehicle unit records per vehicle and
card slot, not per driver, so the report only says so. Analyse the driver card.

> **The result is indicative, not a legal determination.** It reflects only
> the recorded data and a subset of the Regulation; use it to find periods
> worth a closer look, not to decide whether a driver broke the law.

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
| *(positional)* | `FILE` | Path to the `.ddd` file to analyse (required) |
| `--json` | `[FILE]` | Generate JSON output (optional output path) |
| `--pdf` | `[FILE]` | Generate PDF report (optional output path; needs `reportlab`) |
| `--excel` | `[FILE]` | Generate Excel report (optional output path; needs `openpyxl`) |
| `--csv` | `[FILE]` | Generate CSV report (optional output path) |
| `--all` | `[DIR]` | Generate all four formats into a directory |
| `--summary` | — | Show the compact text summary on screen |
| `--rules` | — | Indicative Regulation (EC) No 561/2006 driving/rest-time analysis (driver cards); added to `--json` as `regulation_561` |
| `--version` | — | Print the reader version (`TachoReader 2.9.1`) |
| `-v`, `--verbose` | — | Verbose debug output |
| `-q`, `--quiet` | — | Suppress all screen output (files only); `--json -` still writes the JSON to standard output |

**Exit codes:** `0` on success; `1` when the file is missing, cannot be parsed,
carries no decodable tachograph structure (`Error: no tachograph structure was
decoded` — no card, VU or certificate record could be decoded from it), or an
export failed; `2` for a usage error (unknown flag, missing file argument).

---

## Batch Processing

The CLI processes one file per invocation. To process a directory, loop in the shell:

```bash
for f in DDD/*.ddd; do
  python -m app.cli "$f" --json --quiet
done
```

Quote `"$f"`: tachograph download names often contain spaces.

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
