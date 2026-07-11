"""Compatibility adapter for isolated G2/G2.2 VU RecordArray tag payloads.

Full VU TREP streams are owned by :mod:`core.parser.vu_dispatcher`. This
public adapter remains for registry callers that provide one BER-TLV payload;
it unwraps that RecordArray and uses the dispatcher's canonical semantics.
"""

import struct

from core.utils.logger import get_logger

_log = get_logger(__name__)


def parse_g2_vu_record(val, results, tag):
    """Dispatch G2/G2.2 VU records to appropriate decoders.

    Handles tags 0x0509-0x0512 (G2 VU records) and 0x052B-0x0533 (G2.2 VU records).
    The raw value may be a RecordArray or a single record.
    """
    from core.parser.record_array import RecordArrayParser as _RAP
    from core.parser import vu_dispatcher as _vd

    try:
        result_key = _vd.VU_TAG_RESULT_KEYS.get(tag)
        if result_key is None:
            return

        hdr = _RAP.parse_header(val, 0)
        if hdr and hdr["record_size"] > 0 and hdr["no_of_records"] > 0:
            records = []
            for _idx, rec, _ in _RAP.iter_records(val, 0):
                decoded = _vd.decode_vu_tag_record(tag, rec)
                if decoded:
                    records.append(decoded)
            if records:
                results.setdefault(result_key, []).extend(records)
        else:
            # Bare record without a RecordArray header remains supported.
            decoded = _vd.decode_vu_tag_record(tag, val)
            if decoded:
                results.setdefault(result_key, []).append(decoded)
    except (struct.error, IndexError, ValueError, KeyError, AttributeError) as exc:
        _log.debug("G2 VU record parse failed for tag 0x%04X: %s", tag, exc)
