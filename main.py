"""
DDD Tachograph Reader - CLI Entry Point
"""
import argparse
import json
import sys
import logging
from ddd_parser import TachoParser


def main():
    parser = argparse.ArgumentParser(description="DDD Tachograph File Reader - Structural TLV Parser")
    parser.add_argument("file", help="Percorso del file .ddd da leggere")
    parser.add_argument("-o", "--output", help="Percorso del file JSON di output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Output verboso")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s"
    )

    try:
        ddd = TachoParser(args.file)
        result = ddd.parse()
        
        
    except Exception as e:
        print(f"Errore critico durante il parsing: {e}", file=sys.stderr)
        sys.exit(1)

    if result is None:
        print("Errore: Impossibile leggere il file.", file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(result, indent=4, ensure_ascii=False)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"Dati salvati in {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
