"""Shared BER-TLV tag/length header parser.

Used by both the legacy TagNavigator and the DeterministicParser to avoid
duplicate implementations of the same BER-TLV reading logic.

BER-TLV encoding (ISO 7816-4, Annex 1C):
  Tag:   1+ bytes (multi-byte if bits 5-1 of first byte are all 1)
  Length: 1–4 bytes (short form: 0x00–0x7F; long form: 0x81–0x83 + N bytes)
"""
import struct
from .constants import MAX_TLV_LENGTH


def read_ber_tlv_header(data, pos=0):
    """Read a BER-TLV tag and length from *data* starting at *pos*.

    Returns:
        (tag, length, header_size) on success
        (None, None, 0) on failure (invalid/corrupt data)

    Does NOT read the payload — callers slice data[pos+header_size : pos+header_size+length].
    """
    n = len(data)
    if pos >= n:
        return None, None, 0

    try:
        start = pos
        b0 = data[pos]
        pos += 1

        if b0 in (0x00, 0xFF):
            return None, None, 0

        tag = b0
        if (b0 & 0x1F) == 0x1F:   # multi-byte tag
            while pos < n:
                b = data[pos]
                pos += 1
                tag = (tag << 8) | b
                if not (b & 0x80):
                    break
            else:
                return None, None, 0

        if pos >= n:
            return None, None, 0

        lb = data[pos]
        pos += 1

        if lb < 0x80:
            length = lb
        else:
            nb = lb & 0x7F
            if nb == 0 or nb > 3 or pos + nb > n:
                return None, None, 0
            length = int.from_bytes(data[pos:pos + nb], 'big')
            pos += nb

        if length > MAX_TLV_LENGTH:
            return None, None, 0

        if start + (pos - start) + length > n:
            return None, None, 0

        return tag, length, pos - start

    except (IndexError, ValueError, TypeError, struct.error):
        return None, None, 0
