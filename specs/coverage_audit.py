#!/usr/bin/env python3
"""Coverage Audit: parse all DDD files and report coverage / unparsed bytes."""
import os
import sys
import json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddd_parser import TachoParser

DDD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "DDD")


def hex_snippet(data: bytes, max_len: int = 32) -> str:
    if len(data) <= max_len:
        return data.hex()
    return data[:max_len].hex() + "..."


def group_unparsed_by_pattern(unparsed_list):
    groups = defaultdict(list)
    for rec in unparsed_list:
        raw = bytes.fromhex(rec["data_hex"].split("...")[0])
        if len(raw) >= 2:
            key = raw[:2].hex()
        elif len(raw) == 1:
            key = f"{raw[0]:02X}--"
        else:
            key = "empty"
        groups[key].append(rec)
    return groups


def main():
    print("=" * 80)
    print("DDD FILE COVERAGE AUDIT")
    print("=" * 80)

    ddd_files = sorted([
        os.path.join(DDD_DIR, f)
        for f in os.listdir(DDD_DIR)
        if f.lower().endswith(".ddd")
    ])

    if not ddd_files:
        print("No DDD files found in", DDD_DIR)
        return

    report = {}
    global_unparsed_patterns = defaultdict(list)

    for filepath in ddd_files:
        fname = os.path.basename(filepath)
        fsize = os.path.getsize(filepath)
        print(f"\n{'─' * 80}")
        print(f"File: {fname}")
        print(f"Size: {fsize:,} bytes")

        try:
            parser = TachoParser(filepath)
            result = parser.parse()
        except Exception as e:
            print(f"  ERROR parsing: {e}")
            continue

        coverage = result["metadata"].get("coverage_pct", 0)
        gen = result["metadata"].get("generation", "Unknown")
        print(f"  Generation: {gen}")
        print(f"  Coverage:   {coverage}%")

        unparsed = []
        for key, occs in result.get("raw_tags", {}).items():
            if "Unparsed Data" in key:
                for occ in occs:
                    unparsed.append(occ)
                    global_unparsed_patterns[fname].append(occ)

        if unparsed:
            print(f"  Unparsed Blocks: {len(unparsed)}")
            total_unparsed = sum(o["length"] for o in unparsed)
            print(f"  Unparsed Bytes:  {total_unparsed:,} ({100*total_unparsed/fsize:.1f}% of file)")
            for i, occ in enumerate(unparsed[:50]):
                snippet = hex_snippet(bytes.fromhex(occ["data_hex"].split("...")[0]))
                print(f"    [{i}] Offset={occ['offset']}, Len={occ['length']}, "
                      f"Hex={snippet}")
            if len(unparsed) > 50:
                print(f"    ... and {len(unparsed) - 50} more blocks")
        else:
            print("  Unparsed Blocks: 0 (complete coverage!)")

        report[fname] = {
            "generation": gen,
            "size_bytes": fsize,
            "coverage_pct": coverage,
            "unparsed_blocks": len(unparsed),
            "unparsed_bytes": sum(o["length"] for o in unparsed),
        }

    print(f"\n{'=' * 80}")
    print("SUMMARY TABLE")
    print(f"{'=' * 80}")
    print(f"{'Filename':<50} {'Gen':<14} {'Size':>10} {'Cov%':>7} {'Unparsed':>10}")
    print(f"{'─' * 95}")
    for fname, info in sorted(report.items()):
        print(f"{fname:<50} {info['generation']:<14} {info['size_bytes']:>10,} "
              f"{info['coverage_pct']:>6.1f}% {info['unparsed_bytes']:>10,}")
    print(f"{'─' * 95}")

    total_size = sum(r["size_bytes"] for r in report.values())
    total_unparsed = sum(r["unparsed_bytes"] for r in report.values())
    avg_cov = (sum(r["coverage_pct"] for r in report.values()) / len(report)) if report else 0
    print(f"{'TOTAL/AVG':<50} {'':<14} {total_size:>10,} {avg_cov:>6.1f}% {total_unparsed:>10,}")

    print(f"\n{'=' * 80}")
    print("UNPARSED PATTERNS BY FILE")
    print(f"{'=' * 80}")
    for fname, occs in global_unparsed_patterns.items():
        patterns = group_unparsed_by_pattern(occs)
        print(f"\n  {fname}:")
        for pkey, pitems in sorted(patterns.items(), key=lambda x: -sum(i["length"] for i in x[1])):
            total = sum(i["length"] for i in pitems)
            print(f"    Pattern 0x{pkey}: {len(pitems)} blocks, {total:,} bytes total")
            for item in pitems[:3]:
                print(f"      Offset={item['offset']}, Len={item['length']}")

    print(f"\n{'=' * 80}")
    print("UNPARSED PATTERNS ACROSS ALL FILES (cross-file similarity)")
    print(f"{'=' * 80}")

    all_unparsed = []
    for fname, occs in global_unparsed_patterns.items():
        for occ in occs:
            all_unparsed.append(occ)
    cross_patterns = group_unparsed_by_pattern(all_unparsed)
    for pkey, pitems in sorted(cross_patterns.items(), key=lambda x: -sum(i["length"] for i in x[1]))[:30]:
        total = sum(i["length"] for i in pitems)
        files = set()
        for item in pitems:
            for fname, occs2 in global_unparsed_patterns.items():
                if item in occs2:
                    files.add(fname)
        print(f"  Pattern 0x{pkey}: {len(pitems)} blocks, {total:,} bytes across {len(files)} files")
        if len(pitems) <= 3:
            for item in pitems:
                snippet = hex_snippet(bytes.fromhex(item["data_hex"].split("...")[0]))
                print(f"    Offset={item['offset']}, Len={item['length']}, Hex={snippet}")

    report_path = os.path.join(os.path.dirname(__file__), "coverage_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nDetailed report written to: {report_path}")


if __name__ == "__main__":
    main()
