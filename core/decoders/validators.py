"""Plausibility validators used to gate decoder output.

Corrupt or mis-framed downloads can feed the wrong bytes to a decoder, which
then emits physically impossible values (e.g. 25284 km/h) or non-printable
"text". These pure predicates let each decoder sanity-check a result *before*
publishing it: implausible data is dropped rather than shown, and the affected
region is left for the anchor-based salvage pass.

All functions are side-effect free and never raise.
"""
from __future__ import annotations

from typing import Optional

# Physical / regulatory bounds (Annex 1B/1C).
MAX_VEHICLE_SPEED_KMH = 250          # authorised tacho range tops out well below
MAX_ODOMETER_KM = 9_999_999         # OdometerShort is 24-bit (max 16_777_215)
MIN_UNIX_TS = 946_684_800           # 2000-01-01T00:00:00Z
MAX_UNIX_TS = 4_102_444_800         # 2100-01-01T00:00:00Z


def is_plausible_timestamp(ts: Optional[int]) -> bool:
    """True when *ts* is a Unix second count within [2000, 2100)."""
    if ts is None:
        return False
    try:
        return MIN_UNIX_TS <= int(ts) < MAX_UNIX_TS
    except (TypeError, ValueError):
        return False


def is_plausible_speed(kmh: Optional[float]) -> bool:
    """True when *kmh* is within the physical tachograph speed range."""
    if kmh is None:
        return False
    try:
        return 0 <= float(kmh) <= MAX_VEHICLE_SPEED_KMH
    except (TypeError, ValueError):
        return False


def is_plausible_odometer(km: Optional[int]) -> bool:
    """True when *km* is a non-negative odometer value within 24-bit range."""
    if km is None:
        return False
    try:
        return 0 <= int(km) <= MAX_ODOMETER_KM
    except (TypeError, ValueError):
        return False


def is_printable_text(value: Optional[str], min_ratio: float = 0.8) -> bool:
    """True when *value* is mostly printable (control-char ratio below 20%).

    Rejects the "\\x12\\x35\\x1a..." style garbage produced when raw binary is
    decoded as Latin-1/ASCII text.
    """
    if value is None:
        return False
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return True
    printable = sum(1 for ch in stripped if ch.isprintable())
    return (printable / len(stripped)) >= min_ratio


def is_plausible_count(count: Optional[int], max_count: int) -> bool:
    """True when a record count is non-negative and within *max_count*."""
    if count is None:
        return False
    try:
        return 0 <= int(count) <= max_count
    except (TypeError, ValueError):
        return False


def is_plausible_sensor_info(info: dict) -> bool:
    """Sanity-check a decoded G1 sensor identification block.

    A genuine block has plausible speed parameters and a printable approval
    string; the false-marker garbage fails on both counts.
    """
    if not isinstance(info, dict):
        return False
    checks = (
        is_plausible_speed(info.get("param_speed_max_kmh")),
        is_plausible_speed(info.get("param_speed_avg_kmh")),
        is_printable_text(info.get("sensor_approval")),
    )
    return all(checks)


def is_plausible_event_record(event: dict) -> bool:
    """Sanity-check a decoded VU/card event or fault record.

    Requires at least a plausible begin timestamp and, when present, a
    printable vehicle plate — enough to reject records carved from noise.
    """
    if not isinstance(event, dict):
        return False
    begin = event.get("begin") or event.get("begin_time")
    if isinstance(begin, (int, float)) and not is_plausible_timestamp(begin):
        return False
    plate = event.get("vehicle_plate")
    if plate is not None and not is_printable_text(plate):
        return False
    return True
