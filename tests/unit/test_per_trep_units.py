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
from tests.unit import vu_synthetic as S
from tests.unit.real_data import real_ddd_files, require_real_file
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
    for (_start, end), (next_start, _next_end) in zip(spans, spans[1:],
                                                     strict=False):
        assert end <= next_start, (end, next_start)
    assert spans[-1][1] <= len(data)


# ── Every byte belongs to a unit ─────────────────────────────────────────

def _coverage_ok(units, size):
    spans = [(unit["offset"], unit["offset"] + unit["length"]) for unit in units]
    spans.sort()
    assert spans, "no units"
    assert spans[0][0] == 0, spans[0]
    for (_start, end), (next_start, _next_end) in zip(spans, spans[1:],
                                                     strict=False):
        assert end == next_start, (end, next_start)
    assert spans[-1][1] == size, (spans[-1], size)


def test_the_half_truncated_real_file_covers_every_byte(tmp_path):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        raw = handle.read()
    data = raw[:len(raw) // 2]
    result = _parse(tmp_path, "half.ddd", data)
    units = _units(result)
    _coverage_ok(units, len(data))
    assert result["metadata"]["vu_units_cover_file"] is True
    # the normative part is untouched, and the leftover is ONE declared zone
    normative = [unit for unit in units if unit["path"] == "normative"]
    zones = [unit for unit in units if unit["path"] != "normative"]
    assert len(zones) == 1, zones
    assert zones[0]["length"] > 0
    assert zones[0].get("reason")
    assert len(normative) >= 40
    # counts never exceed the intact file's
    intact = _parse(tmp_path, "intact.ddd", raw)
    for key in ("activities", "events", "faults", "places", "card_iw_records",
                "specific_conditions"):
        assert len(result.get(key) or []) <= len(intact.get(key) or []), key
    # the normative part keeps the numbers the walk alone produced
    assert len(result.get("activities") or []) >= 42
    assert len(result.get("faults") or []) >= 3


def test_a_tail_truncated_by_129_bytes_has_one_zone(tmp_path):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        raw = handle.read()
    data = raw[:-129]
    result = _parse(tmp_path, "cut129.ddd", data)
    units = _units(result)
    _coverage_ok(units, len(data))
    zones = [unit for unit in units if unit["path"] != "normative"]
    assert len(zones) == 1, zones
    assert (result["metadata"].get("trep_report") or {}).get("is_partial") is True


def test_generation_2_units_cover_the_file_including_the_header(tmp_path):
    from tests.unit import vu_synthetic as S
    # two junk bytes between two sections: they are their own unit
    stream = (S.section(0x31, S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
                        S.signature_record())
              + b"\xde\xad"
              + S.section(0x24, S.record_array(
                  0x12, 64, [struct.pack(">I", S.BASE_TIME) + bytes(60)]),
                  S.signature_record()))
    result = _parse(tmp_path, "g2cover.ddd", stream)
    units = _units(result)
    _coverage_ok(units, len(stream))
    junk = [unit for unit in units if unit["path"] != "normative"]
    assert len(junk) == 1, units
    assert junk[0]["length"] == 2


def test_an_intact_stream_is_fully_normative(tmp_path):
    overview, events, technical = _three_message_stream()
    data = overview + events + technical
    result = _parse(tmp_path, "full.ddd", data)
    units = _units(result)
    _coverage_ok(units, len(data))
    assert all(unit["path"] == "normative" for unit in units), units


def test_the_decode_units_section_is_rendered_and_translated():
    import glob
    import re
    from core.utils import report_format as rf
    assert "vu_units" in [key for key, _label in rf.EXPORT_SECTIONS]
    assert "Decode units" in [label for key, label in rf.EXPORT_SECTIONS
                              if key == "vu_units"]
    assert rf.section_description("vu_units")
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        msgids = set(re.findall(r'^msgid "(.*)"$',
                                open(path, encoding="utf-8").read(), re.M))
        for label in ("Decode units", "Path"):
            assert label in msgids, (path, label)


# ── Normative partial read of a message truncated at its tail ────────────

def _cut_intact_top_level(result, key):
    return result.get(key) or []


def test_a_message_cut_at_its_tail_keeps_its_complete_records(tmp_path):
    """The last TREP of the real G1 file, cut by 129 bytes.

    Every record before the cut is complete and its size is fixed by Annex 1B, so it is
    decoded by the same handler with normative provenance; only the cut remainder (the
    incomplete final record) is a failed range.
    """
    path = require_real_file("*_3975E02669.ddd")
    with open(path, "rb") as handle:
        raw = handle.read()
    intact = _parse(tmp_path, "intact_speed.ddd", raw)
    cut = _parse(tmp_path, "cut_speed.ddd", raw[:-129])

    units = _units(cut)
    _coverage_ok(units, len(raw) - 129)
    # the last message is split: a normative part and a small failed remainder
    last_normative = [unit for unit in units
                      if unit["trep"] == "0x04" and unit["path"] == "normative"]
    tail = [unit for unit in units if unit["path"] != "normative"]
    assert last_normative, units[-3:]
    assert len(tail) == 1, tail
    assert tail[0]["length"] < 200, tail[0]
    assert "truncation" in (last_normative[-1].get("reason") or "")
    # the records before the cut are the intact file's, record by record
    intact_blocks = intact.get("speed_blocks") or []
    cut_blocks = cut.get("speed_blocks") or []
    assert cut_blocks, "the complete blocks before the cut must be published"
    assert len(cut_blocks) <= len(intact_blocks)
    by_begin = {run.get("timestamp"): run for run in intact_blocks}
    compared = 0
    for mine in cut_blocks:
        reference = by_begin.get(mine.get("timestamp"))
        if reference is None:
            continue
        assert mine.get("max_speed_kmh") == reference.get("max_speed_kmh")
        assert (mine.get("_chart_speeds_kmh") or [])[:10] == (
            reference.get("_chart_speeds_kmh") or [])[:10]
        compared += 1
    assert compared, "no block of the cut file matched the intact one"
    # the file is still partial, with the reason unchanged in meaning
    assert (cut["metadata"].get("trep_report") or {}).get("is_partial") is True


def test_a_generation_1_message_cut_on_a_record_boundary(tmp_path):
    overview, _events, _technical = _three_message_stream()
    # cut the final signature off exactly: the body is complete -> still normative
    data = overview[:-128]
    result = _parse(tmp_path, "boundary.ddd", data)
    units = _units(result)
    _coverage_ok(units, len(data))
    assert units[0]["path"] == "normative"


def test_a_generation_1_message_cut_inside_a_record(tmp_path):
    """A TREP 04 cut mid-record publishes only the complete blocks."""
    blocks = [struct.pack(">I", S.BASE_TIME + 60 * i) + bytes([10 + i] * 60)
              for i in range(3)]
    body = struct.pack(">H", 3) + b"".join(blocks)
    stream = b"\x76\x04" + body[:-30] + SIGNATURE
    result = _parse(tmp_path, "midrecord.ddd", stream)
    units = _units(result)
    _coverage_ok(units, len(stream))
    normative = [unit for unit in units if unit["path"] == "normative"]
    assert normative and normative[0]["trep"] == "0x04"
    # two complete blocks fit in body[:-30]
    samples = sum(len(run.get("_chart_speeds_kmh") or [])
                  for run in (result.get("speed_blocks") or []))
    assert samples >= 120, samples
    assert any(unit["path"] != "normative" for unit in units)


def test_a_generation_1_message_cut_inside_its_header_stays_unreadable(tmp_path):
    stream = b"\x76\x04" + b"\x00\x03" + SIGNATURE[:10]
    result = _parse(tmp_path, "header.ddd", stream)
    units = _units(result)
    _coverage_ok(units, len(stream))
    assert all(unit["path"] != "normative" or unit["trep"] != "0x04"
               for unit in units), units
    assert not (result.get("speed_blocks") or [])


def test_a_generation_2_array_truncated_at_its_tail_keeps_complete_records(tmp_path):
    from tests.unit import vu_synthetic as S
    records = [struct.pack(">I", S.BASE_TIME + 60 * i) + bytes([20 + i] * 60)
               for i in range(3)]
    array = (bytes([0x12]) + struct.pack(">HH", 64, 3) + b"".join(records))
    stream = S.section(0x24, array,
                       S.signature_record())[:-30]
    result = _parse(tmp_path, "g2tail.ddd", stream)
    units = _units(result)
    _coverage_ok(units, len(stream))
    assert result["metadata"]["vu_units_cover_file"] is True
    # the complete blocks of the cut array are published
    samples = sum(len(run.get("_chart_speeds_kmh") or [])
                  for run in (result.get("speed_blocks") or []))
    assert samples >= 120, samples
