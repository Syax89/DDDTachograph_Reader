"""Stand-alone TREP 06 envelope: SID 0x76 + TREP 06 followed by a card image.

A selective download relayed **through the vehicle unit** keeps the transfer header
that a card stored by other tooling does not (DDP_050 strips
``76 06`` when the card image is written to a file). Such a file is the plain card
plus two bytes, so it must be decoded by the plain card pipeline — not as a VU
stream, and never reported as a corrupt card.

The envelope is recognised by walking the payload with the card's own STAP framing
(tag(2) + dtype(1) + length(2), ``FFFF`` reserved, never longer than the remaining
bytes). It is accepted only when that walk is clean: at least one element, every
element a known card file, and the stream ends exactly at EOF or before the short
``76 00`` trailer some download tools append. Anything else is *not* an envelope.
"""
import struct

from core.utils.logger import get_logger

_log = get_logger(__name__)

SID = 0x76
TREP_CARD_DOWNLOAD = 0x06

#: Card file tags that may open a card image (Annex 1B/1C Appendix 1 file
#: identifiers). The first element of a card download is one of these.
CARD_FILE_TAGS = frozenset({
    0x0002, 0x0005,                                     # EF_ICC, EF_IC
    0x0101, 0x0102, 0x0103, 0x0104, 0x0105,             # G2 identification group
    0x0201, 0x0202, 0x0203,                             # G2 cardholder/licence
    0x0501, 0x0502, 0x0503, 0x0504, 0x0505, 0x0506,     # universal application EFs
    0x0507, 0x0508, 0x0509, 0x050A, 0x050B, 0x050C,
    0x050D, 0x050E, 0x050F, 0x0510, 0x0511, 0x0512,
    0x0513, 0x0514, 0x0515, 0x0516, 0x0517,
    0x0520, 0x0521, 0x0522, 0x0523, 0x0524, 0x0525,     # generation-specific copies
    0x0526, 0x0527, 0x0528, 0x0529, 0x052A, 0x052B,
    0x052C, 0x052D, 0x052E, 0x052F, 0x0530, 0x0531,
    0x0532, 0x0533, 0x0540,
    0xC100, 0xC108, 0x7F21, 0x7F4E,                     # certificates
    0x2020, 0x2200,                                     # image / manufacturer notes
})

#: The card's STAP header is five bytes; ``FFFF`` is the reserved length.
STAP_HEADER_SIZE = 5
STAP_RESERVED_LENGTH = 0xFFFF


def _is_download_trailer(data, pos):
    """True when ``data[pos:]`` is the short ``76 00`` trailer tools append."""
    tail = data[pos:]
    return (2 <= len(tail) <= 8 and tail[0] == SID and tail[1] == 0x00)


def card_image_extent(payload):
    """Walk *payload* as a card STAP stream.

    Returns ``(end, element_count)``: ``end`` is the offset just past the last
    complete element (``0`` when the first bytes are not an element).
    """
    pos = 0
    count = 0
    n = len(payload)
    while pos + STAP_HEADER_SIZE <= n:
        tag, dtype, length = struct.unpack(">HBH", payload[pos:pos + STAP_HEADER_SIZE])
        if tag in (0x0000, STAP_RESERVED_LENGTH, 0x5555):
            break
        if tag >> 8 == SID:
            # A card file identifier is never 0x76xx: that pair opens a VU TREP
            # section (a second `76 06` card region, or the next transfer), so the
            # card stream ends here.
            break
        if dtype > 0x0F:
            break
        if length == STAP_RESERVED_LENGTH:
            break
        if pos + STAP_HEADER_SIZE + length > n:
            break
        pos += STAP_HEADER_SIZE + length
        count += 1
    return pos, count


def trep06_envelope(raw_data):
    """Detect the stand-alone ``76 06`` card envelope.

    Returns ``{"bytes": 2, "payload": memoryview/bytes, "card_bytes": int}`` when
    the file is exactly one clean card image behind the transfer header, else
    ``None``. The check is structural: no field value (date, name, card number)
    takes part in it.
    """
    try:
        head = bytes(raw_data[:2])
    except (TypeError, ValueError):
        return None
    if len(head) < 2 or head[0] != SID or head[1] != TREP_CARD_DOWNLOAD:
        return None
    payload = raw_data[2:]
    end, count = card_image_extent(payload)
    if not count:
        return None
    # The first element must be a card file: a random 0x76 06 pair inside another
    # format cannot start with a known file identifier.
    tag = struct.unpack(">H", bytes(payload[:2]))[0]
    if tag not in CARD_FILE_TAGS:
        return None
    # The stream must cover the rest of the file, optionally plus a trailer.
    if end != len(payload) and not _is_download_trailer(payload, end):
        return None
    _log.debug("TREP 06 card envelope: %d element(s), %d card bytes",
               count, end)
    return {"bytes": 2, "card_bytes": end, "elements": count}


def trep06_card_regions(raw_data):
    """Every complete ``76 06`` + card region, when they cover the whole file.

    A file may hold more than one relayed card (a tool that saves several card
    downloads back to back). Each region is bounded by its own STAP framing, so
    every one of them is recognised and none can swallow its neighbour. Returns a
    list of ``(offset_of_card_bytes, card_bytes)`` or ``[]``; the file counts only
    when the regions cover it completely (nothing else in it).
    """
    try:
        data = bytes(raw_data)
    except (TypeError, ValueError):
        return []
    regions = []
    pos = 0
    while pos + 2 <= len(data):
        if data[pos] != SID or data[pos + 1] != TREP_CARD_DOWNLOAD:
            return []
        start = pos + 2
        end, elements = card_image_extent(data[start:])
        tag = struct.unpack(">H", data[start:start + 2])[0] if elements else None
        if not elements or tag not in CARD_FILE_TAGS:
            return []
        regions.append((start, end))
        pos = start + end
    return regions if len(regions) > 1 else []
