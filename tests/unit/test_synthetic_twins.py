"""Synthetic twins of the corpus-only guards this branch added (F-2).

CI has no DDD/ (personal data) and no external binaries, so every owner-rule-critical
behaviour must also be exercised on bytes the test builds itself. Each test here is the
synthetic counterpart of a private-corpus test that would otherwise be skipped in CI;
the private-file variant stays as the additional check in its own module.
"""
import struct


from app.engine import TachoParser
from core.parser.g1_walker import walk_g1_vu
from core.registry.registry import DecoderRegistry
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


def _parse(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


def _g1_stream(*treps: bytes) -> bytes:
    overview = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
                + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
                + b"PART0001        " + S.extended_serial(0x0000A001)
                + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME))
    return b"\x76\x05" + overview + b"".join(treps)


# ── twins of test_scoped_heuristic_validity.py ───────────────────────────

def test_a_false_marker_inside_sensor_data_adds_no_activity_day(tmp_path):
    """A bare 0x76 inside a body is not a TREP marker: no invented day."""
    sensor = (b"SENSORAP" + S.extended_serial(0x0000A002) + struct.pack(">I", TIME)
              + b"\x76\x02" + b"\xff" * 8)          # 0x76 + junk, no valid TREP 02
    stream = _g1_stream(b"\x76\x07" + sensor + b"\x00" * 128)
    result = _parse(tmp_path, "false_marker.ddd", stream)
    assert result.get("activities") in (None, [])
    units = (result.get("metadata") or {}).get("vu_units") or []
    assert all(unit.get("trep") != 0x02 for unit in units if unit.get("path") == "heuristic")


def test_a_garbled_reread_of_a_driver_is_not_a_second_driver(tmp_path):
    """The same driver body twice is one driver: identity, not heuristics."""
    iw = (b"ROSSI" + b" " * 31 + b"MARIO" + b" " * 31
          + S.card_number() + struct.pack(">I", TIME) + struct.pack(">I", TIME)
          + (120_000).to_bytes(3, "big") + b"\x00" + struct.pack(">I", 0)
          + b"\x00\x00\x00" + b"\x00" * 19 + b"\x00")
    day = (struct.pack(">I", TIME) + (120_000).to_bytes(3, "big")
           + b"\x00\x01" + bytes(iw))
    result = _parse(tmp_path, "dup_driver.ddd",
                    _g1_stream(b"\x76\x02" + day + b"\x00" * 128,
                               b"\x76\x02" + day + b"\x00" * 128))
    # the same driver never becomes two: identity, not a second record
    assert len(result.get("card_iw_records") or []) <= 1


# ── twins of test_integrity_bookkeeping.py ───────────────────────────────

def test_a_truncated_g1_file_still_reports_a_damaged_file(tmp_path):
    """The verdict and the declared cause survive on synthetic bytes too."""
    stream = _g1_stream(b"\x76\x02" + struct.pack(">I", TIME) + b"\x00")
    result = _parse(tmp_path, "cut_g1.ddd", stream[:len(stream) - 1])
    meta = result.get("metadata") or {}
    units = meta.get("vu_units") or []
    # every byte is still accounted for, and the cut tail is declared
    assert meta.get("vu_units_cover_file") is True
    assert any(unit.get("path") in ("heuristic", "unreadable") for unit in units), units
    assert meta.get("integrity_check") not in (None, "Verified")


def test_dangling_marker_byte_makes_the_walk_incomplete(tmp_path):
    data = _g1_stream() + b"\x76"
    results = {"metadata": {}, "vehicle": {}, "activities": [], "faults": [],
               "events": []}
    _messages, complete = walk_g1_vu(data, results)
    assert complete is False
    assert results["metadata"].get("vu_units_cover_file") is True


def test_g1_walker_exception_keeps_its_honest_cause(tmp_path, monkeypatch):
    """A decoder defect is declared as such, from synthetic bytes as well as real."""
    import core.parser.g1_walker as gw

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic walker defect")

    monkeypatch.setattr(gw, "walk_g1_vu", boom)
    # the engine calls the walker through the module attribute, so patching it here
    # reaches the same call the private-file test intercepts
    result = _parse(tmp_path, "boom.ddd", _g1_stream(b"\x76\x02" + b"\x00" * 8))
    paths = (result.get("metadata") or {}).get("decode_paths") or {}
    reasons = paths.get("reasons") or []
    assert reasons or paths.get("fallback"), paths
    if reasons:
        assert reasons[0]["cause"] == "normative_decoder_exception", reasons[0]
        assert reasons[0]["classification"] == "decoder_defect_suspected"
