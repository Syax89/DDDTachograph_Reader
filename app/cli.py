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
from core.utils.activity_stats import compute_activity_totals


def main():
    parser = argparse.ArgumentParser(
        description="🚛 DDD Tachograph Reader CLI - Digital Tachograph File Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tacho-cli file.ddd                     # JSON output to screen
  tacho-cli file.ddd --json report.json  # Save JSON
  tacho-cli file.ddd --pdf report.pdf    # Generate PDF report
  tacho-cli file.ddd --excel report.xlsx # Generate Excel
  tacho-cli file.ddd --all output_dir/   # Generate all formats
  tacho-cli file.ddd --summary           # Text summary only
        """
    )
    parser.add_argument("file", help="Path to .ddd file to analyze")
    parser.add_argument("--json", nargs="?", const="auto", metavar="FILE", help="Generate JSON output (optional: file path)")
    parser.add_argument("--pdf", nargs="?", const="auto", metavar="FILE", help="Generate PDF report (optional: file path)")
    parser.add_argument("--excel", nargs="?", const="auto", metavar="FILE", help="Generate Excel report (optional: file path)")
    parser.add_argument("--csv", nargs="?", const="auto", metavar="FILE", help="Generate CSV report (optional: file path)")
    parser.add_argument("--all", nargs="?", const="auto", metavar="DIR", help="Generate all formats in a directory")
    parser.add_argument("--summary", action="store_true", help="Show compact text summary")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
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

    if not os.path.isfile(args.file):
        print(f"❌ File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Parse
    try:
        from app.engine import TachoParser
        ddd = TachoParser(args.file)
        result = ddd.parse()
    except Exception as e:
        print(f"❌ Parsing error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    parse_error = (result.get("metadata") or {}).get("parse_error")
    if parse_error:
        message = (parse_error.get("message", "Unknown parse error")
                   if isinstance(parse_error, dict) else str(parse_error))
        print(f"❌ Parsing error: {message}", file=sys.stderr)
        sys.exit(1)

    # Auto-generate output basename
    basename = os.path.splitext(os.path.basename(args.file))[0]
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

    # --all mode
    if args.all is not None:
        out_dir = args.all if args.all != "auto" else f"{basename}_output"
        if os.path.exists(out_dir) and not os.path.isdir(out_dir):
            print(f"❌ --all output path exists and is not a directory: {out_dir}",
                  file=sys.stderr)
            sys.exit(1)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            print(f"❌ Cannot create output directory {out_dir}: {e}", file=sys.stderr)
            sys.exit(1)
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
            print(f"⚠️ JSON generation error: {e}", file=sys.stderr)
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
            print(f"⚠️ PDF export requires reportlab (pip install reportlab): {e}", file=sys.stderr)
        except Exception as e:
            export_failed = True
            print(f"⚠️ PDF generation error: {e}", file=sys.stderr)
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
            print(f"⚠️ Excel generation error: {e}", file=sys.stderr)
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
            print(f"⚠️ CSV generation error: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Summary
    if args.summary or (not args.json and not args.pdf and not args.excel and not args.csv and not args.quiet):
        print_summary(result)

    # Default: print JSON to stdout if no output flags
    if not args.json and not args.pdf and not args.excel and not args.csv and not args.summary and not args.quiet:
        print(json.dumps(result, indent=2, ensure_ascii=False, cls=BytesEncoder))

    if not args.quiet and generated:
        print("\n📁 Generated files:")
        for fmt, path in generated:
            size = os.path.getsize(path)
            print(f"   {fmt}: {path} ({format_size(size)})")

    if export_failed:
        sys.exit(1)

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


def print_summary(data):
    """Prints a compact summary to screen."""
    meta = data.get("metadata", {})
    driver = data.get("driver", {})
    vehicle = data.get("vehicle", {})
    activities = data.get("activities", [])

    print("=" * 60)
    print("🚛 DDD TACHOGRAPH READER - SUMMARY")
    print("=" * 60)

    # File info — ``metadata.file_type``/``type`` is not populated by any
    # decoder, so the lookup used to fall through to the bogus "N/D" sentinel
    # (XF-F4). Fall back to the decoded source kind instead.
    file_type = meta.get("file_type") or meta.get("type") or ""
    if not _is_present(file_type):
        file_type = "Vehicle Unit" if meta.get("is_vu") else "Driver Card"
    gen = meta.get("generation", "N/D")
    print(f"\n📄 File: {meta.get('filename', 'N/D')} ({file_type}, Gen {gen})")

    # Signature
    print(f"🔐 Integrity: {meta.get('integrity_check', 'N/D')}")

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
        print(f"\n👤 Driver: {identity}")
    if _is_present(card):
        print(f"   Card: {card}")

    # Vehicle
    vin = vehicle.get("vin", "N/A")
    plate = vehicle.get("plate", vehicle.get("registration", "N/A"))
    if _is_present(vin) or _is_present(plate):
        print(f"\n🚗 Vehicle: {plate} (VIN: {vin})")

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
            totals = compute_activity_totals(day_block.get("changes") or [])
            drive_min += totals["DRIVE"]
            work_min += totals["WORK"]
            rest_min += totals["REST"]
            avail_min += totals["AVAILABLE"]
        days = len(dates)

        print(f"\n📊 Activity ({len(activities)} daily blocks, {days} days):")
        print(f"   🟦 Drive:     {drive_min // 60}h {drive_min % 60}m")
        print(f"   🟨 Work:      {work_min // 60}h {work_min % 60}m")
        print(f"   🟧 Available: {avail_min // 60}h {avail_min % 60}m")
        print(f"   🟩 Rest:      {rest_min // 60}h {rest_min % 60}m")

    # TREP completeness (VU only)
    trep_report = meta.get("trep_report")
    if trep_report:
        from core.parser.trep_inventory import format_trep_summary
        summary = format_trep_summary(trep_report)
        if trep_report.get("is_partial"):
            print(f"\n\u26a0\ufe0f  {summary}")
        else:
            print(f"\n\u2705  {summary}")

    print("\n" + "=" * 60)


def format_size(bytes_val):
    for unit in ['B', 'KB', 'MB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} GB"


if __name__ == "__main__":
    main()
