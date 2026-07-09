"""Shared coverage utilities: interval merging, percentage calculation."""

from typing import List, Optional, Tuple

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
