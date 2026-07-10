"""Content-based origin detection for tachograph files.

The first byte alone (0x76 = VU) is not enough to classify a file. A driver
card image can be wrapped in a single VU ``Card Download`` message (TREP 0x06,
Annex 1B §2.2.6.6 / Annex 1C Appendix 7): such a file starts with 0x76 but its
payload is a plain card-EF image, not a VU download.

This module confirms the origin from the decoded content:

  * ``driver_card``  — a card image (no 0x76 header), or a card image wrapped
    in a stand-alone TREP 0x06 (the latter noted as VU-wrapped).
  * ``vehicle_unit`` — a genuine VU download (Overview + activity/technical
    TREPs), optionally including a TREP 0x06 card copy alongside other TREPs.

A stand-alone TREP 0x06 is a valid, spec-defined selective download of just the
card copy — it is NOT a corrupt/partial VU download and must not be flagged as
such.
"""
from __future__ import annotations

from typing import Dict, Iterable, Tuple

ORIGIN_CARD = "driver_card"
ORIGIN_VU = "vehicle_unit"

# EF tags that only ever appear in a driver-card application (Annex 1B/1C).
# Their presence proves the payload is a card image.
CARD_ONLY_TAGS = {
    0x0002,  # EF_ICC (card system file)
    0x0005,  # EF_IC (card system file)
    0x0501,  # DriverCardApplicationIdentification
    0x0520,  # G1 CardIdentification + DriverCardHolderIdentification
    0x0201,  # G2 DriverCardHolderIdentification
    0x0521,  # CardDrivingLicenceInformation
}

# Tags/containers that only appear in a VU download.
VU_ONLY_TAGS = {
    0x7601, 0x7602, 0x7603, 0x7604, 0x7605,          # G1 VU containers
    0x7621, 0x7622, 0x7623, 0x7624, 0x7625,          # G2 VU containers
    0x7631, 0x7632, 0x7633, 0x7634, 0x7635,          # G2.2 VU containers
}


def _observed_tags(results: Dict) -> set:
    tags = set()
    for occs in (results.get("raw_tags") or {}).values():
        for occ in occs:
            if not isinstance(occ, dict):
                continue
            try:
                tags.add(int(occ.get("tag_id", "0x0"), 16))
            except (TypeError, ValueError):
                continue
    return tags


def detect_origin(
    header_is_vu: bool,
    results: Dict,
    vu_treps: Iterable[int] = (),
) -> Tuple[str, str, bool]:
    """Determine a file's true origin from its decoded content.

    ``header_is_vu`` — whether the first byte was 0x76 (initial guess).
    ``results``      — the structural parse results (for observed tags).
    ``vu_treps``     — TREP markers seen by the VU walk (G1) if any.

    Returns ``(origin, note, is_vu_wrapped_card)``:
      * origin — ORIGIN_CARD or ORIGIN_VU
      * note   — human-readable explanation ("" when unremarkable)
      * is_vu_wrapped_card — True for a card image wrapped in a TREP 0x06
    """
    if not header_is_vu:
        return ORIGIN_CARD, "", False

    treps = set(vu_treps)
    tags = _observed_tags(results)

    has_card_only = bool(tags & CARD_ONLY_TAGS)
    has_vu_only = bool(tags & VU_ONLY_TAGS)
    other_treps = treps - {0x06}

    # A stand-alone TREP 0x06 (no other VU section) carrying card EFs is a
    # selective "card download" — a card image, not a VU download.
    if 0x06 in treps and not other_treps and has_card_only and not has_vu_only:
        note = ("Driver card image extracted from a VU Card Download "
                "(TREP 06, Annex 1B \u00a72.2.6.6) \u2014 valid selective download")
        return ORIGIN_CARD, note, True

    return ORIGIN_VU, "", False
