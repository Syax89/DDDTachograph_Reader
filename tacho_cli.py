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


class _BytesEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


def main():
    parser = argparse.ArgumentParser(
        description="🚛 DDD Tachograph Reader CLI - Digital Tachograph File Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tacho-cli file.ddd                     # JSON output to screen
  tacho-cli file.ddd --json report.json  # Save JSON
  tacho-cli file.ddd --pdf report.pdf    # Generate PDF
  tacho-cli file.ddd --excel report.xlsx # Generate Excel
  tacho-cli file.ddd --all output_dir/   # Generate all formats
  tacho-cli file.ddd --summary           # Text summary only
        """
    )
    parser.add_argument("file", help="Path to .ddd file to analyze")
    parser.add_argument("--json", nargs="?", const="auto", metavar="FILE", help="Generate JSON output (optional: file path)")
    parser.add_argument("--pdf", nargs="?", const="auto", metavar="FILE", help="Generate PDF report (optional: file path)")
    parser.add_argument("--excel", nargs="?", const="auto", metavar="FILE", help="Generate Excel report (optional: file path)")
    parser.add_argument("--all", nargs="?", const="auto", metavar="DIR", help="Generate all formats in a directory")
    parser.add_argument("--summary", action="store_true", help="Show compact text summary")
    parser.add_argument("--legacy", action="store_true", help="Use legacy (non-deterministic) parser for backward compatibility")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose debug output")
    parser.add_argument("-q", "--quiet", action="store_true", help="No screen output (files only)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s"
    )

    if not os.path.isfile(args.file):
        print(f"❌ File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Parse
    try:
        from ddd_parser import TachoParser
        ddd = TachoParser(args.file, use_deterministic=not args.legacy)
        result = ddd.parse()
    except Exception as e:
        print(f"❌ Parsing error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    if result is None:
        print("❌ Cannot read the file.", file=sys.stderr)
        sys.exit(1)

    # Auto-generate output basename
    basename = os.path.splitext(os.path.basename(args.file))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def resolve_path(val, ext, default_dir="."):
        if val == "auto":
            return os.path.join(default_dir, f"{basename}_{timestamp}.{ext}")
        return val

    # --all mode
    if args.all is not None:
        out_dir = args.all if args.all != "auto" else f"{basename}_output"
        os.makedirs(out_dir, exist_ok=True)
        if args.json is None:
            args.json = resolve_path("auto", "json", out_dir)
        if args.pdf is None:
            args.pdf = resolve_path("auto", "pdf", out_dir)
        if args.excel is None:
            args.excel = resolve_path("auto", "xlsx", out_dir)

    generated = []

    # JSON output
    if args.json:
        json_path = resolve_path(args.json, "json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, cls=_BytesEncoder)
        generated.append(("JSON", json_path))

    # PDF output
    if args.pdf:
        print("⚠️ PDF export not available in this version.", file=sys.stderr)

    # Excel output
    if args.excel:
        excel_path = resolve_path(args.excel, "xlsx")
        try:
            from export_manager import ExportManager
            ExportManager.export_to_excel(result, excel_path)
            generated.append(("Excel", excel_path))
        except Exception as e:
            print(f"⚠️ Excel generation error: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()

    # Summary
    if args.summary or (not args.json and not args.pdf and not args.excel and not args.quiet):
        print_summary(result)

    # Default: print JSON to stdout if no output flags
    if not args.json and not args.pdf and not args.excel and not args.summary and not args.quiet:
        pass  # summary already printed above

    if not args.quiet and generated:
        print(f"\n📁 Generated files:")
        for fmt, path in generated:
            size = os.path.getsize(path)
            print(f"   {fmt}: {path} ({format_size(size)})")


def print_summary(data):
    """Prints a compact summary to screen."""
    meta = data.get("metadata", {})
    driver = data.get("driver", {})
    vehicle = data.get("vehicle", {})
    activities = data.get("activities", [])
    infractions = data.get("infractions", [])
    sig = data.get("signature_verification", {})

    print("=" * 60)
    print("🚛 DDD TACHOGRAPH READER - SUMMARY")
    print("=" * 60)

    # File info
    file_type = meta.get("file_type", meta.get("type", "N/D"))
    gen = meta.get("generation", "N/D")
    print(f"\n📄 File: {meta.get('filename', 'N/D')} ({file_type}, Gen {gen})")

    # Signature
    if sig:
        status = sig.get("status", sig.get("overall", "N/D"))
        print(f"🔐 Integrity: {status}")

    # Driver
    name = driver.get("name", driver.get("surname", ""))
    first = driver.get("first_name", driver.get("firstname", ""))
    card = driver.get("card_number", "N/D")
    if name or first:
        print(f"\n👤 Driver: {first} {name}".strip())
    if card != "N/D":
        print(f"   Card: {card}")

    # Vehicle
    vin = vehicle.get("vin", "N/D")
    plate = vehicle.get("plate", vehicle.get("registration", "N/D"))
    if vin != "N/D" or plate != "N/D":
        print(f"\n🚗 Vehicle: {plate} (VIN: {vin})")

    # Activities summary
    if activities:
        total_drive = sum(a.get("duration_min", 0) for a in activities if a.get("type") == "DRIVE")
        total_work = sum(a.get("duration_min", 0) for a in activities if a.get("type") == "WORK")
        total_rest = sum(a.get("duration_min", 0) for a in activities if a.get("type") in ("REST", "AVAILABLE"))
        days = len(set(a.get("date", "") for a in activities if a.get("date")))

        print(f"\n📊 Activity ({len(activities)} records, {days} days):")
        print(f"   🟦 Drive:  {total_drive // 60}h {total_drive % 60}m")
        print(f"   🟨 Work:   {total_work // 60}h {total_work % 60}m")
        print(f"   🟩 Rest:   {total_rest // 60}h {total_rest % 60}m")

    # Infractions
    if infractions:
        total_fines = sum(i.get("fine_eur", 0) for i in infractions)
        print(f"\n⚠️ Infringements: {len(infractions)} (Estimated penalties: €{total_fines:,.0f})")
        for inf in infractions[:5]:
            print(f"   • {inf.get('description', inf.get('type', 'N/D'))}")
        if len(infractions) > 5:
            print(f"   ... and {len(infractions) - 5} more")

    print("\n" + "=" * 60)


def format_size(bytes_val):
    for unit in ['B', 'KB', 'MB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} GB"


if __name__ == "__main__":
    main()
