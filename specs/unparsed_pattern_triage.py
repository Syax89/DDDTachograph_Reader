"""Triage of Unparsed Data patterns across real DDD files.

Groups unparsed occurrences by leading 2-byte signature and surfaces the
biggest hot-spots. This complements `specs/semantic_coverage_audit.py` by
directing the next decoding investments.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Mapping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from specs.semantic_coverage_audit import DDD_DIR, audit_file


def _snippet_hex(data_hex: str, head: int = 16) -> str:
    raw = data_hex.split("...")[0]
    if len(raw) > head * 2:
        return raw[: head * 2]
    return raw


def _pattern_key(occurrence: Mapping[str, Any]) -> str:
    data_hex = occurrence.get("data_hex", "")
    raw = data_hex.split("...")[0]
    if len(raw) >= 4:
        return raw[:4]
    if len(raw) == 2:
        return raw + "--"
    return "empty"


def triage_directory(directory: str = DDD_DIR, top_n: int = 20) -> List[Dict[str, Any]]:
    aggregate: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "count": 0,
        "total_bytes": 0,
        "lengths": [],
        "files": set(),
        "snippets": [],
    })
    for path in sorted(os.listdir(directory)):
        if not path.lower().endswith(".ddd"):
            continue
        metrics = audit_file(os.path.join(directory, path))
        # Re-parse to get the raw occurrences, since audit_file only returns metrics.
        from ddd_parser import TachoParser
        result = TachoParser(os.path.join(directory, path)).parse()
        for tag_name, occurrences in result.get("raw_tags", {}).items():
            if "Unparsed Data" not in tag_name:
                continue
            for occ in occurrences:
                key = _pattern_key(occ)
                entry = aggregate[key]
                entry["count"] += 1
                length = int(occ.get("length", 0) or 0)
                entry["total_bytes"] += length
                entry["lengths"].append(length)
                entry["files"].add(path)
                if len(entry["snippets"]) < 3:
                    entry["snippets"].append({
                        "file": path,
                        "offset": occ.get("offset"),
                        "length": length,
                        "hex_prefix": _snippet_hex(occ.get("data_hex", "")),
                    })
        del metrics
    ranked = sorted(aggregate.items(), key=lambda item: -item[1]["total_bytes"])
    serialized = []
    for key, data in ranked[:top_n]:
        serialized.append({
            "pattern": key,
            "count": data["count"],
            "total_bytes": data["total_bytes"],
            "files": sorted(data["files"]),
            "length_distribution": {
                "min": min(data["lengths"]) if data["lengths"] else 0,
                "max": max(data["lengths"]) if data["lengths"] else 0,
                "avg": round(sum(data["lengths"]) / len(data["lengths"]), 1) if data["lengths"] else 0,
            },
            "sample_occurrences": data["snippets"],
        })
    return serialized


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage Unparsed Data patterns across real DDD files.")
    parser.add_argument("--ddd-dir", default=DDD_DIR)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", help="Write JSON report")
    args = parser.parse_args()

    report = triage_directory(args.ddd_dir, args.top)
    print(f"{'Pattern':<10} {'Count':>6} {'Bytes':>8} {'Files':>6}")
    print("-" * 38)
    for entry in report:
        print(f"0x{entry['pattern']:<8} {entry['count']:>6} {entry['total_bytes']:>8,} {len(entry['files']):>6}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
        print(f"Triage report written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
