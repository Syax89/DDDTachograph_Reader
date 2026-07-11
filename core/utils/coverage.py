"""Shared coverage utilities: interval merging and coverage metrics."""

from typing import Dict, List, Mapping, Optional, Tuple

KNOWN_PADDING_BYTES = {0x00, 0xFF, 0x55}


def merge_intervals(ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Merge overlapping intervals into a minimal set of disjoint intervals."""
    if not ranges:
        return []
    sorted_ranges = sorted(r for r in ranges if r[0] < r[1])
    if not sorted_ranges:
        return []
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        last = merged[-1]
        if start <= last[1]:
            merged[-1] = (last[0], max(last[1], end))
        else:
            merged.append((start, end))
    return merged


def coverage_pct(covered_bytes: int, total_size: int) -> float:
    """Calculate coverage percentage, handling zero size."""
    if total_size == 0:
        return 0.0
    return round(covered_bytes / total_size * 100, 2)


def coverage_metrics(
    total_size: int, accounted_bytes: int, classifications: Mapping[str, int]
) -> Dict[str, float | int]:
    """Build presentation metrics from non-overlapping byte classifications.

    "accounted" includes every byte assigned a classification, including
    padding and unknown data. Structural identification is deliberately not a
    semantic decoding metric: it counts only known non-padding classifications.
    """
    unknown_bytes = int(classifications.get("Unknown", 0))
    structurally_identified_bytes = sum(
        int(byte_count)
        for classification, byte_count in classifications.items()
        if classification not in {"Unknown", "Unclassified"}
        and not classification.startswith("Padding(")
    )
    return {
        "byte_accounted_bytes": accounted_bytes,
        "byte_accounted_pct": coverage_pct(accounted_bytes, total_size),
        "unknown_bytes": unknown_bytes,
        "unknown_pct": coverage_pct(unknown_bytes, total_size),
        "structurally_identified_bytes": structurally_identified_bytes,
        "structurally_identified_pct": coverage_pct(
            structurally_identified_bytes, total_size
        ),
    }


def is_padding_block(data: bytes) -> Optional[int]:
    """If data is all the same padding byte (0x00, 0xFF, or 0x55), return that byte.
    Returns None if not a padding block or too short."""
    if len(data) < 2:
        return None
    first = data[0]
    if first not in KNOWN_PADDING_BYTES:
        return None
    if all(b == first for b in data):
        return first
    return None
