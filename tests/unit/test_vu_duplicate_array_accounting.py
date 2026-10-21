"""A repeated RecordArray must not invent dropped records.

``stored`` used to collapse to the *last* ``noOfRecords`` of a record type while
``emitted`` summed every occurrence, so a section carrying two arrays of the same
type (an event/fault section split in two, an activity day downloaded twice)
reported more emitted than stored. The difference went negative, was logged as a
WARNING and — through ``_vu_walk_complete`` — turned a complete download into
"VU download incomplete: truncated/partial". Nothing was dropped.
"""
from core.parser.vu_dispatcher import walk_vu_record_arrays
from tests.unit import vu_synthetic as S


def _walk(data):
    results = {}
    walk_vu_record_arrays(data, results)
    return results


def _report(results):
    return results["metadata"]["vu_section_schema"][0]


def test_a_repeated_array_counts_every_declared_record():
    data = S.section(
        0x32,
        S.record_array(0x09, 5, [b"\x01" * 5, b"\x02" * 5]),
        S.record_array(0x09, 5, [b"\x03" * 5, b"\x04" * 5, b"\x05" * 5]),
        S.signature_record())

    results = _walk(data)
    report = _report(results)
    # every declared record reached the results: nothing is dropped
    assert report["emitted_records"] == {"0x09": 5}
    assert report["stored_records"] == {"0x09": 5}
    assert report["dropped_records"] == {}
    # and no count is negative anywhere
    for table in ("stored_records", "emitted_records", "dropped_records"):
        assert all(value >= 0 for value in report[table].values()), table
    assert len(results["specific_conditions"]) == 5
