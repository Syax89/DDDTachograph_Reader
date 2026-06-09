#!/usr/bin/env python3
"""Semantic coverage audit for DDD parser results.

The parser already tracks all bytes by filling gaps as ``Unparsed Data``.
This module calculates the stricter metric: how many bytes were semantically
decoded instead of merely tracked.
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Mapping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddd_parser import TachoParser


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")
BASELINE_PATH = os.path.join(os.path.dirname(__file__), "semantic_coverage_report.json")
LEGACY_BASELINE_PATH = os.path.join(os.path.dirname(__file__), "coverage_report.json")


def _iter_raw_occurrences(result: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for tag_name, occurrences in result.get("raw_tags", {}).items():
        if not isinstance(occurrences, list):
            continue
        for occurrence in occurrences:
            if isinstance(occurrence, Mapping):
                yield tag_name, occurrence


def sum_occurrence_lengths(result: Mapping[str, Any], name_fragment: str) -> int:
    total = 0
    for tag_name, occurrence in _iter_raw_occurrences(result):
        if name_fragment in tag_name:
            total += int(occurrence.get("length", 0) or 0)
    return total


def semantic_metrics(result: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = result.get("metadata", {})
    file_size = int(metadata.get("file_size_bytes", 0) or 0)
    tracked_coverage = float(metadata.get("coverage_pct", 0) or 0)
    unparsed_bytes = sum_occurrence_lengths(result, "Unparsed Data")
    padding_bytes = sum_occurrence_lengths(result, "Padding")
    decoded_bytes = max(file_size - unparsed_bytes - padding_bytes, 0)
    decoded_coverage = (decoded_bytes / file_size * 100) if file_size else 0.0

    stranded_bytes = 0
    stranded_blocks = 0
    meaningful_unparsed = 0
    meaningful_blocks = 0
    for tag_name, occurrence in _iter_raw_occurrences(result):
        if "Unparsed Data" not in tag_name:
            continue
        length = int(occurrence.get("length", 0) or 0)
        if length == 1:
            stranded_bytes += length
            stranded_blocks += 1
        else:
            meaningful_unparsed += length
            meaningful_blocks += 1
    meaningful_coverage = ((file_size - meaningful_unparsed) / file_size * 100) if file_size else 0.0

    return {
        "generation": metadata.get("generation", "Unknown"),
        "size_bytes": file_size,
        "tracked_byte_coverage": round(tracked_coverage, 3),
        "decoded_byte_coverage": round(decoded_coverage, 3),
        "decoded_bytes": decoded_bytes,
        "unparsed_bytes": unparsed_bytes,
        "padding_bytes": padding_bytes,
        "unparsed_blocks": sum(1 for name, _ in _iter_raw_occurrences(result) if "Unparsed Data" in name),
        "stranded_bytes": stranded_bytes,
        "stranded_blocks": stranded_blocks,
        "meaningful_unparsed_bytes": meaningful_unparsed,
        "meaningful_unparsed_blocks": meaningful_blocks,
        "meaningful_byte_coverage": round(meaningful_coverage, 3),
    }


def list_ddd_files(directory: str = DDD_DIR) -> List[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.lower().endswith(".ddd")
    )


def audit_file(path: str) -> Dict[str, Any]:
    result = TachoParser(path).parse()
    metrics = semantic_metrics(result)
    metrics["filename"] = os.path.basename(path)
    return metrics


def load_baseline(path: str = BASELINE_PATH) -> Dict[str, Any]:
    if not os.path.exists(path) and path == BASELINE_PATH:
        path = LEGACY_BASELINE_PATH
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def compare_to_baseline(metrics: Mapping[str, Mapping[str, Any]], baseline: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    regressions = []
    for filename, current in metrics.items():
        expected = baseline.get(filename)
        if not expected:
            continue
        current_unparsed = int(current.get("unparsed_bytes", 0) or 0)
        baseline_unparsed = int(expected.get("unparsed_bytes", 0) or 0)
        if current_unparsed > baseline_unparsed:
            regressions.append({
                "filename": filename,
                "baseline_unparsed_bytes": baseline_unparsed,
                "current_unparsed_bytes": current_unparsed,
                "increase": current_unparsed - baseline_unparsed,
            })
    return {"regressions": regressions, "passed": not regressions}


def audit_directory(directory: str = DDD_DIR) -> Dict[str, Dict[str, Any]]:
    return {os.path.basename(path): audit_file(path) for path in list_ddd_files(directory)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit decoded-byte coverage for real DDD files.")
    parser.add_argument("--ddd-dir", default=DDD_DIR, help="Directory containing .ddd files")
    parser.add_argument("--baseline", default=BASELINE_PATH, help="semantic coverage baseline path")
    parser.add_argument("--output", help="Write current semantic metrics to this JSON file")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero if unparsed bytes increase")
    args = parser.parse_args()

    metrics = audit_directory(args.ddd_dir)
    baseline = load_baseline(args.baseline)
    comparison = compare_to_baseline(metrics, baseline)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(metrics, handle, indent=2)
            handle.write("\n")

    if args.json:
        print(json.dumps({"files": metrics, "baseline_comparison": comparison}, indent=2))
    else:
        print("Semantic DDD Coverage Audit")
        print(
            f"{'Filename':<52} {'Gen':<16} {'Tracked%':>9} {'Decoded%':>9} "
            f"{'Mean%':>7} {'Unparsed':>10} {'Stranded':>10} {'MeanB':>8}"
        )
        print("-" * 122)
        for filename, info in metrics.items():
            print(
                f"{filename:<52} {info['generation']:<16} "
                f"{info['tracked_byte_coverage']:>8.1f}% "
                f"{info['decoded_byte_coverage']:>8.1f}% "
                f"{info['meaningful_byte_coverage']:>6.1f}% "
                f"{info['unparsed_bytes']:>10,} "
                f"{info['stranded_bytes']:>10,} "
                f"{info['meaningful_unparsed_bytes']:>8,}"
            )
        if comparison["regressions"]:
            print("\nRegressions versus baseline:")
            for item in comparison["regressions"]:
                print(
                    f"- {item['filename']}: +{item['increase']} unparsed bytes "
                    f"({item['baseline_unparsed_bytes']} -> {item['current_unparsed_bytes']})"
                )
        else:
            print("\nNo unparsed-byte regressions versus baseline.")
        if args.output:
            print(f"Semantic report written to: {args.output}")

    return 1 if args.fail_on_regression and not comparison["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
