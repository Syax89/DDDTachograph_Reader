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


def test_false_trep11_marker_does_not_split_card_download():
    # A 0x76 0x11 byte pair inside card-download payload must NOT be treated as
    # a sensor download unless a genuine 0x76 0x14 trailer follows it. Build a
    # TREP 06 body containing a bare 0x76 0x11 with no trailer: the walk should
    # yield a single CardDownload message reaching EOF (not a bogus TREP 11).
    payload = b"\x05\x00\x0d" + b"\x76\x11\x7a\x01\x7e\x19" + b"\xAB" * 40
    stream = b"\x76\x06" + payload
    messages = list(g1_walker.iter_g1_vu_messages(stream))

    assert [m["trep"] for m in messages] == [0x06]
    assert messages[-1]["end"] == len(stream)


def test_genuine_trep11_with_trailer_is_accepted():
    # A real sensor-only download (Overview + Sensor + Trailer) must still
    # recognise its TREP 0x11 because a genuine 0x76 0x14 trailer follows.
    from tests.unit.real_data import require_real_file
    path = require_real_file("VU_FS137FR_XLRTEH4300G267680_VERIFIED_95537A1054.ddd")
    data = open(path, "rb").read()
    treps = [m["trep"] for m in g1_walker.iter_g1_vu_messages(data)]

    assert 0x11 in treps
    assert 0x14 in treps
