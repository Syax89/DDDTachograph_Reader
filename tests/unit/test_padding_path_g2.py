"""D-01 on the RecordArray walker: fill after the last section is padding.

The same tolerance the G1 walk applies (0x00/0xFF fill is padding, declared as a unit
so every byte is accounted for, and NOT a finding). Other trailing bytes stay a
finding: the unit is unreadable and the file is partial.
"""
import pytest

from core.parser.vu_dispatcher import walk_vu_record_arrays
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


def _stream():
    return S.section(0x31, S.record_array(0x0A, 17, [b"A" * 17]), S.signature_record())


def _walk(data):
    results = {"metadata": {}, "vehicle": {"vin": "N/A"}}
    walk_vu_record_arrays(data, results)
    return results


@pytest.mark.parametrize("fill", [b"\x00", b"\xff"])
@pytest.mark.parametrize("length", [1, 4, 128])
def test_fill_is_a_padding_unit(fill, length):
    results = _walk(_stream() + fill * length)
    units = results.get("vu_units") or []
    assert units[-1]["path"] == "padding", units[-1]
    assert units[-1]["length"] == length
    assert results["metadata"]["vu_units_cover_file"] is True
    assert not [f for f in (results["metadata"].get("vu_integrity") or [])
                if f.get("status") == "trailing_bytes"]


def test_other_fill_is_a_finding():
    results = _walk(_stream() + b"\xde\xad")
    units = results.get("vu_units") or []
    assert units[-1]["path"] in ("heuristic", "unreadable"), units[-1]
    assert any(f.get("status") in ("trailing_bytes", "array_truncated")
               for f in (results["metadata"].get("vu_integrity") or []))


def test_units_are_exposed_at_the_top_level():
    results = _walk(_stream())
    assert results.get("vu_units"), "every surface reads the top-level list"
    assert results["vu_units"] is results["metadata"]["vu_units"]
    assert sum(u["length"] for u in results["vu_units"]) == len(_stream())
