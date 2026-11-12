#!/usr/bin/env python3
"""
DDD Tachograph Reader - Full CLI
Analyzes .ddd files and generates reports in JSON, PDF or Excel.
"""
import argparse
import json
import sys
import os
import logging
from datetime import datetime

from core.utils.encoding import BytesEncoder
from core.utils.version import __version__
from core.utils.activity_stats import compute_activity_totals, recorded_until_seconds


def main():
    parser = argparse.ArgumentParser(
        # ``prog`` comes from ``sys.argv[0]`` by default, which made the usage
        # line and ``--version`` depend on the calling script ("cli.py",
        # "main.py"). Name the command the examples below document, and print
        # the reader version the GUI and the guides report (CLI-VERSION).
        prog="tacho-cli",
        description="DDD Tachograph Reader CLI - Digital Tachograph File Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tacho-cli file.ddd                     # JSON output to screen
  tacho-cli file.ddd --json report.json  # Save JSON
  tacho-cli file.ddd --pdf report.pdf    # Generate PDF report
  tacho-cli file.ddd --excel report.xlsx # Generate Excel
  tacho-cli file.ddd --all output_dir/   # Generate all formats
  tacho-cli file.ddd --summary           # Text summary only
  tacho-cli a.ddd b.ddd --all out/       # Batch: every report into out/
  tacho-cli downloads/ -r --excel xlsx/  # Batch: a folder, one workbook per file
        """
    )
    parser.add_argument("file", nargs="+", metavar="PATH",
                        help="Path to a .ddd file, or a directory of .ddd files; "
                             "several paths make a batch")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Also scan subdirectories of a directory argument")
    parser.add_argument("--json", nargs="?", const="auto", metavar="FILE", help="Generate JSON output (optional: file path)")
    parser.add_argument("--pdf", nargs="?", const="auto", metavar="FILE", help="Generate PDF report (optional: file path)")
    parser.add_argument("--excel", nargs="?", const="auto", metavar="FILE", help="Generate Excel report (optional: file path)")
    parser.add_argument("--csv", nargs="?", const="auto", metavar="FILE", help="Generate CSV report (optional: file path)")
    parser.add_argument("--gpx", nargs="?", const="auto", metavar="FILE",
                        help="Export the GNSS positions as GPX (optional: file path)")
    parser.add_argument("--kml", nargs="?", const="auto", metavar="FILE",
                        help="Export the GNSS positions as KML (optional: file path)")
    parser.add_argument("--all", nargs="?", const="auto", metavar="DIR", help="Generate all formats in a directory")
    parser.add_argument("--summary", action="store_true", help="Show compact text summary")
    parser.add_argument("--version", action="version",
                        version=f"TachoReader {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose debug output")
    parser.add_argument("-q", "--quiet", action="store_true", help="No screen output (files only)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s"
    )
    if args.verbose:
        # ``logging.basicConfig`` only configures the *root* logger. The parser
        # logger ``ddd_tacho`` sets ``propagate=False`` and owns a console
        # handler pinned at WARNING (core/utils/logger.py), so ``-v`` used to
        # leave the parser's own diagnostics silent (CLI-VERBOSE-SILENT). Lower
        # that handler too so ``-v`` actually raises parser verbosity.
        from core.utils.logger import enable_debug
        enable_debug()

    # One path that is not a directory is the classic single-file run, whose
    # output stays exactly as before; anything else is a batch.
    if len(args.file) == 1 and not os.path.isdir(args.file[0]):
        rc = _process_file(args, args.file[0])[0]
        if rc:
            sys.exit(rc)
        return
    sys.exit(_run_batch(parser, args))


def _process_file(args, path, batch=False):
    """Parse *path* and write the outputs *args* ask for.

    Returns ``(exit_code, result, errors)``: ``result`` is the parsed dict (or
    ``None`` when nothing parsed) and ``errors`` the messages reported for this
    file. In a *batch* every message names the file, an explicit output path is
    a directory, and standard output never carries the JSON.
    """
    # Work on a copy: the output resolution below rewrites the flags, and a
    # batch reuses the same namespace for every file.
    args = argparse.Namespace(**vars(args))
    where = f"{path}: " if batch else ""
    result = None
    errors = []

    def fail(message):
        print(f"Error: {where}{message}", file=sys.stderr)
        errors.append(message)
        return 1, result, errors

    def warn(message):
        print(f"Warning: {where}{message}", file=sys.stderr)
        errors.append(message)

    if not os.path.isfile(path):
        return fail(f"file not found: {path}" if not batch else "file not found")

    # Parse
    try:
        from app.engine import TachoParser
        ddd = TachoParser(path)
        result = ddd.parse()
    except Exception as e:
        rc = fail(f"parsing failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return rc

    parse_error = (result.get("metadata") or {}).get("parse_error")
    if parse_error:
        message = (parse_error.get("message", "Unknown parse error")
                   if isinstance(parse_error, dict) else str(parse_error))
        return fail(f"parsing failed: {message}")

    if not _has_tachograph_structure(result):
        # No card/VU/certificate record was decoded (CLI-NOT-A-TACHO). The CLI
        # used to announce such a file as a "Driver Card, Gen G1" and exit 0,
        # which a batch script reads as success. The message states the fact —
        # a fragment of a real download can fail to decode too, so "not a
        # tachograph file" claimed more than the parse proved.
        return fail("no tachograph structure was decoded")

    # ``--json -`` is the conventional "write the JSON to standard output". It
    # used to be taken as a file name and created a file literally called "-".
    json_to_stdout = args.json == "-"
    if json_to_stdout:
        args.json = None

    # Standard output belongs to the JSON whenever the JSON goes there; the
    # summary, the generated-file list and any progress text follow it to
    # standard error so ``tacho-cli file.ddd > out.json`` parses (CLI-JSON-STDOUT).
    # A batch never streams JSON: its standard output is the per-file summaries
    # and the batch table.
    stdout_is_json = not batch and (json_to_stdout or (
        not args.json and not args.pdf and not args.excel and not args.csv
        and not args.gpx and not args.kml
        and not args.summary and not args.quiet))
    notice = sys.stderr if stdout_is_json else sys.stdout

    # Auto-generate output basename
    basename = os.path.splitext(os.path.basename(path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def resolve_path(val, ext, default_dir="."):
        """Resolve an output path; ``auto`` picks a non-colliding name.

        Auto names are second-granular, so two runs within the same second
        would otherwise overwrite each other silently (XF-F7); an existing
        name gets a numeric suffix. Explicit paths are returned unchanged —
        the caller chose them.
        """
        if val != "auto":
            return val
        stem = os.path.join(default_dir, f"{basename}_{timestamp}")
        path = f"{stem}.{ext}"
        counter = 1
        while os.path.exists(path):
            path = f"{stem}_{counter}.{ext}"
            counter += 1
        return path

    if batch:
        # In a batch an explicit output FILE names a directory: one auto-named
        # report per input lands in it (``_run_batch`` has created it).
        for attr, ext in _FORMATS:
            target = getattr(args, attr)
            if target not in (None, "auto"):
                setattr(args, attr, resolve_path("auto", ext, target))

    # --all mode
    if args.all is not None:
        out_dir = args.all if args.all != "auto" else f"{basename}_output"
        if os.path.exists(out_dir) and not os.path.isdir(out_dir):
            return fail(f"--all output path exists and is not a directory: {out_dir}")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            return fail(f"cannot create output directory {out_dir}: {e}")
        # A bare ``--json``/``--pdf``/... stores the value "auto"; treat it as
        # unset here so the file is written into the --all directory rather
        # than the current working directory (XF-F7).
        if args.json in (None, "auto"):
            args.json = resolve_path("auto", "json", out_dir)
        if args.pdf in (None, "auto"):
            args.pdf = resolve_path("auto", "pdf", out_dir)
        if args.excel in (None, "auto"):
            args.excel = resolve_path("auto", "xlsx", out_dir)
        if args.csv in (None, "auto"):
            args.csv = resolve_path("auto", "csv", out_dir)
        # GPX/KML stay opt-in, but a bare flag lands in the --all directory.
        for attr in ("gpx", "kml"):
            if getattr(args, attr) == "auto":
                setattr(args, attr, resolve_path("auto", attr, out_dir))

    generated = []
    export_failed = False

    # JSON output
    if args.json:
        json_path = resolve_path(args.json, "json")
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False, cls=BytesEncoder)
            generated.append(("JSON", json_path))
        except Exception as e:
            export_failed = True
            warn(f"JSON generation failed: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # PDF output
    if args.pdf:
        pdf_path = resolve_path(args.pdf, "pdf")
        try:
            from app.export import ExportManager
            ExportManager.export_to_pdf(result, pdf_path)
            generated.append(("PDF", pdf_path))
        except ImportError as e:
            export_failed = True
            warn(f"PDF export requires reportlab (pip install reportlab): {e}")
        except Exception as e:
            export_failed = True
            warn(f"PDF generation failed: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Excel output
    if args.excel:
        excel_path = resolve_path(args.excel, "xlsx")
        try:
            from app.export import ExportManager
            ExportManager.export_to_excel(result, excel_path)
            generated.append(("Excel", excel_path))
        except Exception as e:
            export_failed = True
            warn(f"Excel generation failed: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # CSV output
    if args.csv:
        csv_path = resolve_path(args.csv, "csv")
        try:
            from app.export import ExportManager
            ExportManager.export_to_csv(result, csv_path)
            generated.append(("CSV", csv_path))
        except Exception as e:
            export_failed = True
            warn(f"CSV generation failed: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

    # GNSS positions (GPX / KML). Not part of --all: a map file is asked for.
    for attr, label in (("gpx", "GPX"), ("kml", "KML")):
        target = getattr(args, attr)
        if not target:
            continue
        geo_path = resolve_path(target, attr)
        try:
            from app.geo_export import export_positions
            export_positions(result, geo_path, attr)
            generated.append((label, geo_path))
        except Exception as e:
            export_failed = True
            warn(f"{label} generation failed: {e}")

    # Summary — ``-q`` promises to suppress everything on screen, so it holds
    # back an explicit ``--summary`` too (CLI-QUIET).
    if not args.quiet and (
            args.summary or (not args.json and not args.pdf and not args.excel
                             and not args.csv and not args.gpx and not args.kml)):
        print_summary(result, file=notice)

    # JSON on standard output: the documented default, or an explicit ``--json -``.
    if stdout_is_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, cls=BytesEncoder))

    if not args.quiet and generated:
        print("\nGenerated files:", file=notice)
        for fmt, out_path in generated:
            size = os.path.getsize(out_path)
            print(f"   {fmt}: {out_path} ({format_size(size)})", file=notice)

    return (1 if export_failed else 0), result, errors


# Output flags and the extension of the file each writes.
_FORMATS = (("json", "json"), ("pdf", "pdf"), ("excel", "xlsx"), ("csv", "csv"),
            ("gpx", "gpx"), ("kml", "kml"))


def _collect_inputs(paths, recursive):
    """Expand the PATH arguments into ``[(path, problem)]`` in command-line order.

    A file is kept as given (a missing one is reported by ``_process_file``); a
    directory contributes its ``.ddd`` files (any letter case), sorted, from
    every subdirectory too with *recursive*. A directory holding none yields
    one entry whose *problem* says so. A file reached twice is processed once.
    """
    entries = []
    seen = set()

    def add(path):
        key = os.path.realpath(path)
        if key not in seen:
            seen.add(key)
            entries.append((path, None))

    for path in paths:
        if not os.path.isdir(path):
            add(path)
            continue
        found = []
        if recursive:
            for root, dirs, files in os.walk(path):
                dirs.sort()
                found.extend(os.path.join(root, name) for name in sorted(files)
                             if name.lower().endswith(".ddd"))
        else:
            found = [os.path.join(path, name) for name in sorted(os.listdir(path))
                     if name.lower().endswith(".ddd")
                     and os.path.isfile(os.path.join(path, name))]
        if not found:
            hint = "" if recursive else " (use --recursive to scan subdirectories)"
            entries.append((path, f"no .ddd files found{hint}"))
        for file_path in found:
            add(file_path)
    return entries


def _run_batch(parser, args):
    """Process several inputs; one failing file never stops the others.

    Returns the exit code: ``0`` when every input was processed, ``1`` when any
    input failed (missing, unparsable, no tachograph structure, an export
    failed, or a directory without ``.ddd`` files).
    """
    if args.json == "-":
        parser.error("--json - writes one file's JSON to standard output; "
                     "it needs a single input file")

    # Explicit output targets are directories in a batch: create them once,
    # before any file is parsed, so a bad target fails the run up front.
    targets = [(f"--{attr}", getattr(args, attr)) for attr, _ in _FORMATS]
    targets.append(("--all", args.all))
    for flag, target in targets:
        if target in (None, "auto"):
            continue
        if os.path.exists(target) and not os.path.isdir(target):
            print(f"Error: {flag} needs a directory with several inputs, "
                  f"and {target} exists and is not a directory", file=sys.stderr)
            return 1
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as e:
            print(f"Error: cannot create output directory {target}: {e}", file=sys.stderr)
            return 1

    rows = []
    for path, problem in _collect_inputs(args.file, args.recursive):
        if problem:
            print(f"Error: {path}: {problem}", file=sys.stderr)
            rows.append((path, 1, None, [problem]))
            continue
        rc, result, errors = _process_file(args, path, batch=True)
        rows.append((path, rc, result, errors))

    if not args.quiet:
        _print_batch_table(rows)
    return 1 if any(rc for _, rc, _, _ in rows) else 0


def _activity_days(result):
    """Number of distinct dates carrying a daily activity record."""
    return len({block.get("date") for block in result.get("activities") or []
                if isinstance(block, dict) and block.get("date")})


def _print_batch_table(rows, file=None):
    """Print one line per input: generation, kind, verdict, days and errors."""
    from core.utils.report_format import integrity_verdict
    out = sys.stdout if file is None else file
    header = ("File", "Gen", "Type", "Integrity", "Days", "Errors")
    lines = []
    for path, _rc, result, errors in rows:
        gen = kind = verdict = days = "-"
        if result is not None:
            meta = result.get("metadata") or {}
            if meta.get("parse_error"):
                verdict = integrity_verdict(result)
            elif _has_tachograph_structure(result):
                gen = str(meta.get("generation") or "-")
                kind = "VU" if meta.get("is_vu") else "Card"
                verdict = integrity_verdict(result)
                days = str(_activity_days(result))
        lines.append((path, gen, kind, verdict, days, "; ".join(errors) or "-"))
    widths = [max(len(line[i]) for line in [header, *lines]) for i in range(5)]
    failed = sum(1 for _, rc, _, _ in rows if rc)
    print("\n" + "=" * 60, file=out)
    noun = "input" if len(rows) == 1 else "inputs"
    print(f"BATCH SUMMARY: {len(rows)} {noun}, {len(rows) - failed} OK, {failed} failed",
          file=out)
    print("=" * 60, file=out)
    for line in [header, *lines]:
        cells = [cell.ljust(width) for cell, width in zip(line[:5], widths, strict=True)]
        cells[4] = line[4].rjust(widths[4])
        print("  ".join([*cells, line[5]]), file=out)


def _has_tachograph_structure(result):
    """Whether the parse proved the bytes are a tachograph at all.

    The structural walk classifies every byte it cannot bind as *Unknown*, so a
    text file or binary noise parses "successfully" with no decoded section.
    A tag that only tachograph data carries — a card-only/VU-only EF or one of
    the certificate records both share (``origin_detector``) — is the proof a
    real download has and junk does not. Nothing recognised decoded is reported
    as exactly that; a recognised record means the bytes are a tachograph,
    however little else survived.
    """
    from core.parser.origin_detector import has_tachograph_content
    return has_tachograph_content(result)


# Identity/field sentinels meaning "no value decoded". The CLI must never
# render these as if they were real data (CLI-BOGUS-SENTINELS: F-F5, XF-F4,
# I-F12). Kept in sync with the driver/vehicle defaults in
# ``core/registry/models.py`` and the "N/D" placeholder used for absent
# metadata.
_PLACEHOLDERS = frozenset({"N/A", "N/D", "NONE", "UNKNOWN"})


def _is_present(value):
    """True when *value* is a decoded value, not an absent/sentinel field."""
    if value is None:
        return False
    text = str(value).strip()
    return text != "" and text.upper() not in _PLACEHOLDERS


def print_summary(data, file=None):
    """Prints a compact summary to *file* (standard output by default)."""
    out = sys.stdout if file is None else file
    meta = data.get("metadata", {})
    driver = data.get("driver", {})
    vehicle = data.get("vehicle", {})
    activities = data.get("activities", [])

    print("=" * 60, file=out)
    print("DDD TACHOGRAPH READER - SUMMARY", file=out)
    print("=" * 60, file=out)

    # File info — ``metadata.file_type``/``type`` is not populated by any
    # decoder, so the lookup used to fall through to the bogus "N/D" sentinel
    # (XF-F4). Fall back to the decoded source kind instead.
    file_type = meta.get("file_type") or meta.get("type") or ""
    if not _is_present(file_type):
        file_type = "Vehicle Unit" if meta.get("is_vu") else "Driver Card"
    gen = meta.get("generation", "N/D")
    print(f"\nFile: {meta.get('filename', 'N/D')} ({file_type}, Gen {gen})", file=out)

    # Signature
    print(f"Integrity: {meta.get('integrity_check', 'N/D')}", file=out)
    # A decoder that raised leaves its field out of the result; the export
    # reports already carry a "Decoder failures" row, the summary must too.
    failures = meta.get("decoder_failure_count", 0)
    if isinstance(failures, int) and failures > 0:
        print(f"Warning: {failures} decoder failure(s) during parsing; "
              "some fields may be missing", file=out)

    # Driver — when no card data was decoded the ``driver`` dict carries the
    # truthy sentinel "N/A" in every field (core/registry/models.py), so the
    # old truthiness guard rendered a bogus "Driver: N/A N/A" / "Card: N/A"
    # block. Treat the sentinels as absent, exactly as the vehicle line below
    # already does (F-F5 / XF-F4 / I-F12).
    name = driver.get("name") or driver.get("surname") or ""
    first = driver.get("first_name") or driver.get("firstname") or ""
    card = driver.get("card_number") or ""
    identity = " ".join(p for p in (first, name) if _is_present(p))
    if identity:
        print(f"\nDriver: {identity}", file=out)
    if _is_present(card):
        print(f"   Card: {card}", file=out)

    # Vehicle — one identity field can be absent on its own (two tracked samples
    # carry a plate but no readable VIN), so each is rendered only when decoded
    # instead of leaking the "N/A" sentinel next to the other (CLI-VIN-NA).
    vin = vehicle.get("vin", "N/A")
    plate = vehicle.get("plate", vehicle.get("registration", "N/A"))
    if _is_present(plate):
        suffix = f" (VIN: {vin})" if _is_present(vin) else ""
        print(f"\nVehicle: {plate}{suffix}", file=out)
    elif _is_present(vin):
        print(f"\nVehicle: VIN: {vin}", file=out)

    # Activities summary
    if activities:
        drive_min = 0
        work_min = 0
        rest_min = 0
        avail_min = 0
        dates = set()
        for day_block in activities:
            if not isinstance(day_block, dict):
                continue
            date_val = day_block.get("date", "")
            if date_val:
                dates.add(date_val)
            totals = compute_activity_totals(day_block.get("changes") or [],
                                             recorded_until_seconds(day_block))
            drive_min += totals["DRIVE"]
            work_min += totals["WORK"]
            rest_min += totals["REST"]
            avail_min += totals["AVAILABLE"]
        days = len(dates)

        print(f"\nActivity ({len(activities)} daily blocks, {days} days):", file=out)
        print(f"   Drive:     {drive_min // 60}h {drive_min % 60}m", file=out)
        print(f"   Work:      {work_min // 60}h {work_min % 60}m", file=out)
        print(f"   Available: {avail_min // 60}h {avail_min % 60}m", file=out)
        print(f"   Rest:      {rest_min // 60}h {rest_min % 60}m", file=out)

    # TREP completeness (VU only)
    trep_report = meta.get("trep_report")
    if trep_report:
        from core.parser.trep_inventory import format_trep_summary
        summary = format_trep_summary(trep_report)
        if trep_report.get("is_partial"):
            print(f"\nWarning: {summary}", file=out)
        else:
            print(f"\nOK: {summary}", file=out)

    print("\n" + "=" * 60, file=out)


def format_size(bytes_val):
    for unit in ['B', 'KB', 'MB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} GB"


if __name__ == "__main__":
    main()
