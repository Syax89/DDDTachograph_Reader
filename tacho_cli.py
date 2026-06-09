#!/usr/bin/env python3
"""
DDD Tachograph Reader - Full CLI
Analizza file .ddd e genera report in JSON, PDF o Excel.
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
        description="🚛 DDD Tachograph Reader CLI - Analizzatore file tachigrafo digitale",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi:
  tacho-cli file.ddd                     # Output JSON a schermo
  tacho-cli file.ddd --json report.json  # Salva JSON
  tacho-cli file.ddd --pdf report.pdf    # Genera PDF
  tacho-cli file.ddd --excel report.xlsx # Genera Excel
  tacho-cli file.ddd --all output_dir/   # Genera tutti i formati
  tacho-cli file.ddd --summary           # Solo riepilogo testuale
        """
    )
    parser.add_argument("file", help="Percorso del file .ddd da analizzare")
    parser.add_argument("--json", nargs="?", const="auto", metavar="FILE", help="Genera output JSON (opzionale: percorso file)")
    parser.add_argument("--pdf", nargs="?", const="auto", metavar="FILE", help="Genera report PDF (opzionale: percorso file)")
    parser.add_argument("--excel", nargs="?", const="auto", metavar="FILE", help="Genera report Excel (opzionale: percorso file)")
    parser.add_argument("--all", nargs="?", const="auto", metavar="DIR", help="Genera tutti i formati in una directory")
    parser.add_argument("--summary", action="store_true", help="Mostra riepilogo testuale compatto")
    parser.add_argument("--legacy", action="store_true", help="Usa il parser legacy (non deterministico) per retrocompatibilita'")
    parser.add_argument("-v", "--verbose", action="store_true", help="Output verboso di debug")
    parser.add_argument("-q", "--quiet", action="store_true", help="Nessun output a schermo (solo file)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s"
    )

    if not os.path.isfile(args.file):
        print(f"❌ File non trovato: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Parse
    try:
        from ddd_parser import TachoParser
        ddd = TachoParser(args.file, use_deterministic=not args.legacy)
        result = ddd.parse()
    except Exception as e:
        print(f"❌ Errore parsing: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    if result is None:
        print("❌ Impossibile leggere il file.", file=sys.stderr)
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
        print("⚠️ PDF export non disponibile in questa versione.", file=sys.stderr)

    # Excel output
    if args.excel:
        excel_path = resolve_path(args.excel, "xlsx")
        try:
            from export_manager import ExportManager
            ExportManager.export_to_excel(result, excel_path)
            generated.append(("Excel", excel_path))
        except Exception as e:
            print(f"⚠️ Errore generazione Excel: {e}", file=sys.stderr)
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
        print(f"\n📁 File generati:")
        for fmt, path in generated:
            size = os.path.getsize(path)
            print(f"   {fmt}: {path} ({format_size(size)})")


def print_summary(data):
    """Stampa un riepilogo compatto a schermo."""
    meta = data.get("metadata", {})
    driver = data.get("driver", {})
    vehicle = data.get("vehicle", {})
    activities = data.get("activities", [])
    infractions = data.get("infractions", [])
    sig = data.get("signature_verification", {})

    print("=" * 60)
    print("🚛 DDD TACHOGRAPH READER - RIEPILOGO")
    print("=" * 60)

    # File info
    file_type = meta.get("file_type", meta.get("type", "N/D"))
    gen = meta.get("generation", "N/D")
    print(f"\n📄 File: {meta.get('filename', 'N/D')} ({file_type}, Gen {gen})")

    # Signature
    if sig:
        status = sig.get("status", sig.get("overall", "N/D"))
        print(f"🔐 Integrità: {status}")

    # Driver
    name = driver.get("name", driver.get("surname", ""))
    first = driver.get("first_name", driver.get("firstname", ""))
    card = driver.get("card_number", "N/D")
    if name or first:
        print(f"\n👤 Conducente: {first} {name}".strip())
    if card != "N/D":
        print(f"   Carta: {card}")

    # Vehicle
    vin = vehicle.get("vin", "N/D")
    plate = vehicle.get("plate", vehicle.get("registration", "N/D"))
    if vin != "N/D" or plate != "N/D":
        print(f"\n🚗 Veicolo: {plate} (VIN: {vin})")

    # Activities summary
    if activities:
        total_drive = sum(a.get("duration_min", 0) for a in activities if a.get("type") == "GUIDA")
        total_work = sum(a.get("duration_min", 0) for a in activities if a.get("type") == "LAVORO")
        total_rest = sum(a.get("duration_min", 0) for a in activities if a.get("type") in ("RIPOSO", "DISPONIBILITA"))
        days = len(set(a.get("date", "") for a in activities if a.get("date")))

        print(f"\n📊 Attività ({len(activities)} record, {days} giorni):")
        print(f"   🟦 Guida:  {total_drive // 60}h {total_drive % 60}m")
        print(f"   🟨 Lavoro: {total_work // 60}h {total_work % 60}m")
        print(f"   🟩 Riposo: {total_rest // 60}h {total_rest % 60}m")

    # Infractions
    if infractions:
        total_fines = sum(i.get("fine_eur", 0) for i in infractions)
        print(f"\n⚠️ Infrazioni: {len(infractions)} (Sanzioni stimate: €{total_fines:,.0f})")
        for inf in infractions[:5]:
            print(f"   • {inf.get('description', inf.get('type', 'N/D'))}")
        if len(infractions) > 5:
            print(f"   ... e altre {len(infractions) - 5}")

    print("\n" + "=" * 60)


def format_size(bytes_val):
    for unit in ['B', 'KB', 'MB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} GB"


if __name__ == "__main__":
    main()
