"""Crafted inputs must not keep the parser busy for seconds.

* G1: a stream of repeated ``76 02`` markers made ~24 000 activity records, and
  ``_append_once`` scanned the whole list for each one (quadratic: 200 kB took
  ~10 s).
* G2: a stream of empty ``76 21`` sections costs ~30 µs a section in every pass
  (1.6 MB took ~30 s); more sections than any real download holds is refused.
* Cards: zero-length STAP elements cost ~2 µs a byte; a card is capped at 1 MB.
"""
import time

import pytest

from app import engine
from app.engine import MAX_CARD_FILE_BYTES, MAX_VU_SECTIONS, TachoParser
from core.decoders import vu_g1


def _parse(tmp_path, data, name="x.ddd"):
    path = tmp_path / name
    path.write_bytes(data)
    return TachoParser(str(path)).parse()


def _code(result):
    return ((result.get("metadata") or {}).get("parse_error") or {}).get("code")


def test_append_once_is_not_quadratic():
    target = []
    started = time.perf_counter()
    for index in range(20000):
        assert vu_g1._append_once(target, {"n": index}, "msg:0", index)
    assert time.perf_counter() - started < 2.0
    # still de-duplicates, also after another code path touched the list
    assert not vu_g1._append_once(target, {"n": 0}, "msg:0", 0)
    target.append({"_key": "msg:9#x"})
    assert not vu_g1._append_once(target, {}, "msg:9", "x")
    target.pop()
    target.pop()
    assert vu_g1._append_once(target, {"n": 19999}, "msg:0", 19999)


def test_g1_marker_stream_parses_quickly(tmp_path):
    started = time.perf_counter()
    result = _parse(tmp_path, b"\x76\x02" * 2000)        # under the section cap
    assert time.perf_counter() - started < 5.0
    assert result.get("metadata")


@pytest.mark.parametrize("marker", [b"\x76\x21", b"\x76\x32", b"\x76\x02"])
def test_implausible_section_count_is_refused_fast(tmp_path, marker):
    started = time.perf_counter()
    result = _parse(tmp_path, marker * (MAX_VU_SECTIONS + 50))
    assert time.perf_counter() - started < 2.0
    assert _code(result) == "too_many_sections"


def test_the_section_cap_leaves_room_for_real_downloads():
    # a year of daily activity sections plus the fixed ones
    assert MAX_VU_SECTIONS > 400


def test_oversized_card_is_refused(tmp_path):
    result = _parse(tmp_path, b"\x05\x01\x00\x00\x00" * (MAX_CARD_FILE_BYTES // 5 + 1))
    assert _code(result) == "file_too_large"


def test_card_under_the_cap_still_parses(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "MAX_CARD_FILE_BYTES", 64)
    result = _parse(tmp_path, b"\x00" * 32)
    assert _code(result) != "file_too_large"
