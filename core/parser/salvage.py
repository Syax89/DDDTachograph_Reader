"""Anchor-based salvage for corrupt / mis-framed VU downloads.

The deterministic walk relies on the ``0x76 TREP`` framing being intact. When a
download is truncated or its framing is damaged, whole regions may go
undecoded. This module runs a last-resort recovery pass that ignores the
(unreliable) framing and instead scans the raw bytes for *self-validating*
anchors — an embedded card-EF image, or event/fault records with plausible
timestamps — and merges anything it can confirm.

Everything recovered here is marked heuristic (``metadata.heuristic_fields``)
so the UI/exports flag it as inferred rather than spec-verified. The pass is
conservative: a candidate is accepted only when it passes the plausibility
validators, so a corrupt file never gains invented data.
"""
from __future__ import annotations

from typing import Dict, List

from core.utils.logger import get_logger
from core.decoders.common import mark_heuristic
from core.decoders.validators import is_printable_text

_log = get_logger(__name__)

# Minimum bytes a region must have before we bother scanning it.
_MIN_REGION = 32


def should_salvage(results: Dict) -> bool:
    """True when the parse left genuinely unrecovered bytes worth scanning.

    Being 'partial' (missing mandatory TREPs) is not enough on its own: a file
    can legitimately contain only some sections. Salvage only makes sense when
    there are undecoded byte regions to recover, so we require both a partial
    report AND tracked ``Unparsed Data``.
    """
    report = (results.get("metadata") or {}).get("trep_report") or {}
    if not report or not report.get("is_partial"):
        return False
    unparsed = (results.get("raw_tags") or {}).get("Unparsed Data") or []
    return any(int(u.get("length", 0) or 0) >= _MIN_REGION for u in unparsed)


def salvage_vu_download(raw_data, results) -> List[str]:
    """Recover data from unrecovered byte regions of a corrupt VU download.

    Scans regions the structural walk left as ``Unparsed Data`` for embedded
    card images and event/fault records. Returns the list of result keys that
    gained data (also flagged as heuristic). Never raises.
    """
    try:
        data = bytes(raw_data)
    except (TypeError, ValueError):
        return []

    regions = _unrecovered_regions(data, results)
    if not regions:
        return []

    gained: set = set()
    for start, end in regions:
        chunk = data[start:end]
        if len(chunk) < _MIN_REGION:
            continue
        gained.update(_salvage_card_image(chunk, results))

    gained_list = sorted(gained)
    if gained_list:
        mark_heuristic(results, "salvage", gained_list)
        _log.info("Salvage recovered %d region(s), keys: %s",
                  len(regions), gained_list)
    return gained_list


def _unrecovered_regions(data, results):
    """Return [(start, end)] byte ranges surfaced as Unparsed Data.

    Only genuinely tracked gaps are scanned; we never fall back to the whole
    file (that would let the scanner re-interpret already-decoded bytes and
    invent records).
    """
    ranges = []
    unparsed = (results.get("raw_tags") or {}).get("Unparsed Data") or []
    for occ in unparsed:
        try:
            start = int(occ.get("offset", "0x0"), 16)
            length = int(occ.get("length", 0))
        except (TypeError, ValueError):
            continue
        if length >= _MIN_REGION:
            ranges.append((start, start + length))
    return ranges


def _salvage_card_image(chunk, results) -> List[str]:
    """Try to decode *chunk* as an embedded card-EF (STAP) image."""
    from core.decoders.vu_g1 import _decode_embedded_card_image

    tracked = ("events", "faults", "activities", "places", "inserted_drivers")
    before = {k: len(results.get(k) or []) for k in tracked}
    driver_before = dict(results.get("driver") or {})
    scratch: Dict = {}
    try:
        _decode_embedded_card_image(chunk, scratch)
    except Exception as exc:  # noqa: BLE001 - salvage must never break parsing
        _log.debug("Salvage card-image decode failed: %s", exc)
        return []

    gained = []
    for key in tracked:
        recovered = scratch.get(key)
        if isinstance(recovered, list) and recovered:
            existing = results.setdefault(key, [])
            existing.extend(recovered)
            if len(existing) > before[key]:
                gained.append(key)
    scratch_driver = scratch.get("driver") or {}
    if scratch_driver and not driver_before and is_printable_text(
            scratch_driver.get("surname")):
        results["driver"] = scratch_driver
        gained.append("driver")
    return gained
