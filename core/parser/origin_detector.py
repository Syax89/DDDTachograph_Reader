"""Content-based origin detection for tachograph files.

The first byte alone (0x76 = VU) is not enough to classify a file. A driver
card image can be wrapped in a single VU ``Card Download`` message (TREP 0x06,
DDP_049 / DDP_050): such a file starts with 0x76 but its
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

from typing import Dict, Iterable, Optional, Tuple

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
    # G2.2 VU containers. 0x7634 is *not* a transfer: DDP_011/DDP_032 prescribe
    # TREP '24'H for detailed speed in every generation. It is kept here only as
    # an observed compatibility tag for origin detection, never as a TREP alias.
    0x7631, 0x7632, 0x7633, 0x7634, 0x7635,
}


# Records that prove tachograph data but belong to neither origin on their own:
# the certificate block (Annex 1B App. 1 EF_Certificate / EF_CA_Certificate and
# their G2/G2.2 copies) sits in card *and* VU images, so it is in neither set
# above. A card whose header was cut away but whose certificate records still
# parse decoded real records — that is not "nothing recognised".
CERTIFICATE_TAGS = {
    0xC100,  # G1 CardCertificate
    0xC101,  # G2/G2.2 CardCertificate
    0xC108,  # G1 CA_Certificate
    0xC109,  # G2/G2.2 CA_Certificate
}


def first_record_tag(results: Dict) -> Optional[int]:
    """Tag of the top-level record that opens the decoded stream.

    ``None`` when nothing was decoded. Nested TLV children share their parent's
    offset, so the shallowest occurrence wins a tie: the record that opens the
    file is the parent one.
    """
    best = None                     # (offset, depth, tag) of the best candidate
    for occs in (results.get("raw_tags") or {}).values():
        for occ in occs or ():
            if not isinstance(occ, dict):
                continue
            try:
                offset = int(str(occ.get("offset", "0x0")), 16)
                tag = int(str(occ.get("tag_id", "0x0")), 16)
            except (TypeError, ValueError):
                continue
            depth = occ.get("depth")
            depth = depth if isinstance(depth, int) else 0
            if best is None or (offset, depth) < best[:2]:
                best = (offset, depth, tag)
    return None if best is None else best[2]


def nonstandard_header(results: Dict) -> Optional[int]:
    """The opening record's tag when it cannot open a card download.

    A card download starts with one of the card file identifiers
    (``core.parser.card_envelope.CARD_FILE_TAGS``: EF_ICC/EF_IC or the generation-2
    identification group, and the certificate records a download may lead with).
    Those records sit below the signed-EF space, so rewriting the header's tag
    bytes leaves the stream framed and every signed EF intact — the verdict stays
    clean and nothing else in the app would ever mention it. That is the fact this
    reports: not a verdict, and not a guess.

    ``None`` unless the bytes really are a card image: a file that decoded no
    tachograph record at all (a text file, a JSON dump, a PDF) has no card header
    to compare with the standard form, and saying that its header "differs from a
    standard download" about such input is a diagnosis of something that is not
    there. ``has_tachograph_content`` is the same test the CLI uses to refuse
    input that carries nothing recognisable.
    """
    from core.parser.card_envelope import CARD_FILE_TAGS

    tag = first_record_tag(results)
    if tag is None or tag in CARD_FILE_TAGS:
        return None
    if not has_tachograph_content(results):
        return None
    return tag


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


def has_tachograph_content(results: Dict) -> bool:
    """Whether the decoded content holds any tachograph-only tag.

    ``CARD_ONLY_TAGS`` / ``VU_ONLY_TAGS`` name EFs that exist nowhere but a card
    or VU image, so observing one is proof the bytes are a tachograph;
    ``CERTIFICATE_TAGS`` are the certificate records they share. A file that
    decoded end to end as "Unknown"/generic tags (a text file, binary noise that
    happens to parse as 0x0001 padding) proves nothing and is not a tachograph
    download.
    """
    return bool(_observed_tags(results)
                & (CARD_ONLY_TAGS | VU_ONLY_TAGS | CERTIFICATE_TAGS))


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
        note = ("Card image extracted from a VU Card Download "
                "(TREP 06, DDP_049/DDP_050) \u2014 valid selective download")
        return ORIGIN_CARD, note, True

    return ORIGIN_VU, "", False
