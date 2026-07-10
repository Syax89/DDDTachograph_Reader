"""Regression tests for malformed VU record recovery."""
from core.parser import g1_walker
from core.parser.vu_dispatcher import walk_vu_record_arrays


def test_zero_activity_date_does_not_abort_vu_dispatch():
    # 0x06 TimeReal record with a zero timestamp in an Activities TREP.
    data = b"\x76\x32\x06\x00\x04\x00\x01\x00\x00\x00\x00"
    results = {"vehicle": {"vin": "N/A", "plate": "N/A", "registration_nation": "N/A"}}

    sections = walk_vu_record_arrays(data, results)

    assert sections[0]["section"] == "Activities"
    assert results["vu_record_arrays"] == sections


def test_g1_decoder_exception_marks_walk_incomplete(monkeypatch):
    body = b"A" * 491 + b"\x00\x00"

    def fail(_body, _results):
        raise RuntimeError("decoder failure")

    monkeypatch.setattr(g1_walker, "parse_g1_vu_overview", fail)

    _messages, complete = g1_walker.walk_g1_vu(b"\x76\x01" + body, {})

    assert complete is False
