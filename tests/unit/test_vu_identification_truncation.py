"""A cut VuIdentification says it was cut — it is not a high-confidence record.

``decode_vu_identification`` published ``record_complete: False`` for a short body
but never ``missing_bytes``/low confidence, so the walker's "this payload was cut"
branch (driven by ``missing_bytes``) never fired: a 125-byte record of the canonical
126 was published as complete-looking, with ``confidence: high`` and no
``truncated`` flag — unlike every other fixed-size type, whose short body is
published low + ``missing_bytes`` + the informational note.
"""
from core.parser.vu_dispatcher import decode_vu_record, walk_vu_record_arrays
from tests.unit import vu_synthetic as S
from core.decoders.vu_g1 import TRUNCATED_RECORD_NOTE

#: A canonical generation-2 VuIdentification (126 bytes, Annex 1C §2.145).
BODY = (b"A" * 36 + b"B" * 36 + b"C" * 16 + S.extended_serial(1234)
        + b"\x00" * 12 + b"P" * 16 + b"\x02\x00")


def _walk(record):
    data = S.section(0x35, S.record_array(0x19, len(record), [record]),
                     S.signature_record())
    results = {}
    walk_vu_record_arrays(data, results)
    return results


def test_the_canonical_record_is_complete_and_high():
    assert len(BODY) == 126
    record = decode_vu_record(0x19, BODY, trep=0x35)
    assert record["record_complete"] is True
    assert record["confidence"] == "high"
    assert "missing_bytes" not in record
    published = _walk(BODY)["vu_identifications"][0]
    assert not published.get("truncated")
    assert published["confidence"] == "high"


def test_a_short_record_reports_its_missing_bytes():
    record = decode_vu_record(0x19, BODY[:125], trep=0x35)
    assert record["record_complete"] is False
    assert record["missing_bytes"] == 1
    assert record["confidence"] == "low"


def test_a_short_record_reaches_the_results_flagged_and_with_its_note():
    published = _walk(BODY[:125])["vu_identifications"][0]
    assert published["truncated"] is True
    assert published["note"] == TRUNCATED_RECORD_NOTE
    assert published["record_complete"] is False
    assert published["confidence"] == "low"
    # the fields the remaining bytes still describe are kept, not withheld
    assert published["manufacturer_name"] == "A" * 36
