"""
DDD Tachograph Reader - CLI Entry Point
"""
import argparse
import json
import sys
import logging
from ddd_parser import TachoParser
from core.encoding import BytesEncoder


def main():
    parser = argparse.ArgumentParser(description="DDD Tachograph File Reader - Structural TLV Parser")
    parser.add_argument("file", help="Path to .ddd file to read")
    parser.add_argument("-o", "--output", help="Path to output JSON file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s"
    )

    try:
        ddd = TachoParser(args.file)
        result = ddd.parse()
    except Exception as e:
        print(f"Critical parsing error: {e}", file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(result, indent=4, ensure_ascii=False, cls=BytesEncoder)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"Data saved to {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
