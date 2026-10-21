"""A tail-cut RecordArray reports its shortfall — not a false note per record.

When an array declares more records than the bytes hold, the walker publishes
``floor(available / recordSize)`` records, and every one of them is COMPLETE: the
cut falls after the last whole record, not inside it. It used to mark that last
record ``truncated: true`` with the visible note "This record was cut off in the
file", while the records the file really does not contain (and their bytes) were
reported nowhere.

The shortfall is the array's, so it is reported per array in ``vu_integrity``
(status ``array_truncated``, with the declared/present counts and the missing
bytes) and no complete record carries the note.
"""
from core.decoders.vu_g1 import TRUNCATED_RECORD_NOTE
from core.parser.vu_dispatcher import walk_vu_record_arrays
from tests.unit import vu_synthetic as S

SIZE = 5


def _cut_array(declared, present):
    header = bytes([0x09]) + SIZE.to_bytes(2, "big") + declared.to_bytes(2, "big")
    return header + b"".join(bytes([index + 1]) * SIZE for index in range(present))


def _walk(declared, present, tail=b""):
    data = S.section(0x32, _cut_array(declared, present), tail)
    results = {}
    walk_vu_record_arrays(data, results)
    return results


def test_the_complete_records_of_a_cut_array_carry_no_note():
    results = _walk(declared=5, present=3)
    records = results["specific_conditions"]
    assert len(records) == 3
    for record in records:
        assert record["record_complete"] is True
        assert not record.get("truncated")
        assert "note" not in record or record["note"] != TRUNCATED_RECORD_NOTE


def test_the_array_shortfall_is_reported_with_its_counts_and_bytes():
    results = _walk(declared=5, present=3)
    findings = [finding for finding in results["metadata"]["vu_integrity"]
                if finding.get("status") == "array_truncated"
                and finding.get("record_type") == "0x09"]
    assert len(findings) == 1, results["metadata"]["vu_integrity"]
    finding = findings[0]
    assert finding["declared_records"] == 5
    assert finding["present_records"] == 3
    # two records of five bytes are not in the file
    assert finding["missing_bytes"] == 2 * SIZE
    assert "0x09" in finding["detail"]


def test_the_cut_download_still_fails_closed_as_partial():
    assert _walk(declared=5, present=3)["_vu_walk_complete"] is False


def test_an_intact_array_reports_no_shortfall():
    results = _walk(declared=3, present=3, tail=S.signature_record())
    assert not [finding for finding in results["metadata"].get("vu_integrity") or []
                if finding.get("status") == "array_truncated"]
