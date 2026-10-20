"""Decode TREP by TREP: normative first, heuristic only on the failed unit.

The owner's rule: every TREP (G1 message, G2 RecordArray section) is decoded by the
normative decoder; when one fails, the heuristic runs on **that unit's byte range
only** and the next TREP resumes normatively from a verified marker. A file whose
units all decode normatively never uses the heuristic — the existing
"a valid file never uses the heuristic" test keeps that guarantee.
"""
import struct

import pytest

from app.engine import TachoParser
from core.decoders import vu_g1
from core.registry.registry import DecoderRegistry
from tests.unit.real_data import real_ddd_files
from tests.unit.test_g1_vu_semantics import (
    _g1_calibration, _overview_body, _trep03_body, _trep05_body)


def _parse(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


def _units(result):
    return (result["metadata"].get("vu_units") or [])


# ── An intact file has only normative units ──────────────────────────────

def test_every_intact_unit_is_normative():
    files = real_ddd_files()
    if not files:
        pytest.skip("no private corpus available")
    seen = 0
    for path in files:
        DecoderRegistry.reset_instance()
        result = TachoParser(path).parse()
        units = _units(result)
        for unit in units:
            assert unit["path"] == "normative", (path, unit)
            assert unit["offset"] >= 0 and unit["length"] > 0
        assert not result["metadata"].get("heuristic_fields"), path
        seen += len(units)
    assert seen, "no units published"


def test_a_synthetic_intact_stream_publishes_normative_units(tmp_path):
    stream = (b"\x76\x01" + _overview_body() + b"\x00" * 128)
    result = _parse(tmp_path, "one.ddd", stream)
    units = _units(result)
    assert [unit["trep"] for unit in units] == ["0x01"]
    assert units[0]["path"] == "normative"
    assert units[0]["offset"] == 0
    assert not result["metadata"].get("heuristic_fields")


# ── One corrupted middle TREP: only that unit leaves the normative path ──

#: A synthetic signature block: non-fill bytes, so a cut into it is a truncated
#: signature and not indistinguishable from the 0x00/0xFF padding fill.
SIGNATURE = b"\x5a" * 128


def _three_message_stream():
    overview = b"\x76\x01" + _overview_body() + SIGNATURE
    events = b"\x76\x03" + _trep03_body(n_over=(), n_adj=()) + SIGNATURE
    technical = b"\x76\x05" + _trep05_body([_g1_calibration()]) + SIGNATURE
    return overview, events, technical


def test_a_corrupted_middle_unit_does_not_disturb_its_neighbours(tmp_path, monkeypatch):
    overview, events, technical = _three_message_stream()
    intact = _parse(tmp_path, "intact3.ddd", overview + events + technical)

    # Corrupt the middle TREP so its own normative decoder fails.
    from core.parser import g1_walker as walker
    original = walker._parse_trep_03_events_faults

    def broken(body, results, message_offset=None):
        if message_offset is not None and message_offset == len(overview):
            raise ValueError("synthetic middle-unit corruption")
        return original(body, results, message_offset=message_offset)

    monkeypatch.setattr(walker, "_parse_trep_03_events_faults", broken)
    damaged = _parse(tmp_path, "damaged3.ddd", overview + events + technical)

    units = _units(damaged)
    assert [unit["trep"] for unit in units] == ["0x01", "0x03", "0x05"]
    by_trep = {unit["trep"]: unit for unit in units}
    assert by_trep["0x01"]["path"] == "normative"
    assert by_trep["0x05"]["path"] == "normative"
    assert by_trep["0x03"]["path"] in ("heuristic", "unreadable")
    # the neighbours keep the untouched file's records
    assert damaged["vehicle"]["vin"] == intact["vehicle"]["vin"]
    assert len(damaged.get("calibrations") or []) == len(
        intact.get("calibrations") or [])


def test_the_heuristic_never_publishes_outside_the_failed_range(tmp_path, monkeypatch):
    overview, events, technical = _three_message_stream()
    calls = []
    original = vu_g1.parse_vu_download_messages

    def spy(data, results, base_offset=0):
        calls.append((len(data), base_offset))
        return original(data, results, base_offset=base_offset)

    monkeypatch.setattr(vu_g1, "parse_vu_download_messages", spy)
    from core.parser import g1_walker as walker
    original_handler = walker._parse_trep_03_events_faults

    def broken(body, results, message_offset=None):
        if message_offset is not None and message_offset == len(overview):
            raise ValueError("synthetic middle-unit corruption")
        return original_handler(body, results, message_offset=message_offset)

    monkeypatch.setattr(walker, "_parse_trep_03_events_faults", broken)
    _parse(tmp_path, "scoped.ddd", overview + events + technical)
    assert calls, "the failed unit was not handed to the heuristic"
    for size, base in calls:
        # exactly the failed unit (marker included), never the whole stream
        assert size == len(events), (size, len(events))
        assert base == len(overview)


# ── A 0x76 inside data is not a marker ───────────────────────────────────

def test_a_0x76_inside_data_is_not_treated_as_a_marker(tmp_path):
    body = bytearray(_overview_body())
    body[200] = 0x76                       # inside a certificate
    body[201] = 0x01
    stream = b"\x76\x01" + bytes(body) + b"\x00" * 128
    result = _parse(tmp_path, "fake_marker.ddd", stream)
    units = _units(result)
    assert len(units) == 1
    assert units[0]["trep"] == "0x01"
    assert units[0]["path"] == "normative"


# ── A truncated tail stays declared, with no invented unit ──────────────

def test_a_truncated_tail_is_partial_and_publishes_no_phantom_unit(tmp_path):
    overview, _events, _technical = _three_message_stream()
    cut = overview[:-40]
    result = _parse(tmp_path, "tail.ddd", cut)
    assert (result["metadata"].get("trep_report") or {}).get("is_partial") is True
    for unit in _units(result):
        assert unit["offset"] + unit["length"] <= len(cut)


# ── Generation 2: one unit per RecordArray section ───────────────────────

def test_generation_2_publishes_one_normative_unit_per_section(tmp_path):
    from tests.unit import vu_synthetic as S
    stream = (S.section(0x31, S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
                        S.signature_record())
              + S.section(0x24, S.record_array(
                  0x12, 64, [struct.pack(">I", S.BASE_TIME) + bytes(60)]),
                  S.signature_record()))
    result = _parse(tmp_path, "g2units.ddd", stream)
    units = _units(result)
    assert [unit["trep"] for unit in units] == ["0x31", "0x24"]
    assert all(unit["path"] == "normative" for unit in units)
    assert units[0]["offset"] == 0
    assert units[1]["offset"] == units[0]["length"]
    assert not result["metadata"].get("heuristic_fields")


def test_the_units_never_overlap_or_exceed_the_file(tmp_path):
    overview, events, technical = _three_message_stream()
    data = overview + events + technical
    result = _parse(tmp_path, "spans.ddd", data)
    spans = sorted((unit["offset"], unit["offset"] + unit["length"])
                   for unit in _units(result))
    for (start, end), (next_start, _next_end) in zip(spans, spans[1:], strict=False):
        assert end <= next_start, (start, end, next_start)
    assert spans[-1][1] <= len(data)
