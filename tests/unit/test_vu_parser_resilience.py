"""Regression tests for malformed VU record recovery."""
import struct

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


# ── B-F3: CardDownload boundary search must not blow up ──────────────────

_CARD_PATTERN = bytes.fromhex("76040000760600000000")


def test_carddownload_boundary_search_scales_polynomially(monkeypatch):
    """A crafted repeated ``76 04 00 00 76 06 00 00 00 00`` payload hung the
    walker (k=24 took 33.9s, k=50 >2min) because every nested TREP 06 restarted
    the boundary search with a fresh memo. Guard by operation count — no wall
    clock — so CI stays deterministic.

    The decisive range is k >= 64. Dropping the single ``ctx=ctx`` argument
    (the reviewer's M1 survivor) restores the pathology at k>=64 — ops 63 -> 2016
    at k=64 and 127 -> 8128 at k=128, ~4.29x per doubling — and the emitted
    message boundaries diverge (66 -> 128 messages). The k=8-vs-k=16 range is
    *blind* to that mutant (15 vs 120 ops both satisfy ``4*small+8``), so the
    shipped check now also bites at k>=64 while keeping the pre-fix exponential
    catch (base was k=8->127, k=16->32767 ops)."""
    real = g1_walker._valid_chain_from
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(g1_walker, "_valid_chain_from", counting)

    def measured(k):
        calls["n"] = 0
        list(g1_walker.iter_g1_vu_messages(_CARD_PATTERN * k))
        return calls["n"]

    # Pre-fix exponential catch (still fails on the base: 32767 > 4*127 + 8).
    small = measured(8)
    mid = measured(16)
    assert mid <= 4 * small + 8, (
        f"_valid_chain_from calls grew super-linearly: k=8 -> {small}, "
        f"k=16 -> {mid}")

    # The bite at k>=64 (where a dropped ``ctx=ctx`` is distinguishable).
    for k in (32, 64, 128):
        ops = measured(k)
        assert ops <= 4 * k + 8, (
            f"_valid_chain_from ops at k={k} grew super-linearly: {ops} "
            f"(limit {4 * k + 8})")


def test_carddownload_is_not_silently_dropped():
    """No silent drop: a valid TREP 06 body must still be followed by the
    genuine TREP 04 that closes it (the readback that proves the cost fix did
    not 'solve' the hang by discarding CardDownload sections)."""
    data = b"\x76\x06" + b"card-payload" + b"\x76\x04\x00\x00"
    messages = list(g1_walker.iter_g1_vu_messages(data))
    assert [m["trep"] for m in messages] == [0x06, 0x04]
    assert messages[0]["body_end"] == len(data) - 4
    assert messages[-1]["end"] == len(data)


# ── D-F1: byte-scan fallback must inspect each section once ──────────────

def test_download_fallback_decodes_card_section_once(monkeypatch):
    """The fallback re-parsed the whole tail once per ``76 06`` (O(k·n):
    4KB→2s, 16KB→34s). It must now decode the CardDownload region once."""
    from core.decoders import vu_g1

    real = vu_g1._parse_trep_06_card_download
    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(vu_g1, "_parse_trep_06_card_download", counting)

    chunk = bytes.fromhex("7606") + b"A" * 10
    vu_g1.parse_vu_download_messages(chunk * 100, {})
    assert calls["n"] <= 2, f"CardDownload re-parsed {calls['n']} times for 100 markers"


# ── XB-F4 / D-F2: lying record count must not lose later sections ────────

def _array(rt, rs, nr, fill=b"\x00"):
    return bytes([rt]) + struct.pack(">HH", rs, nr) + fill * (rs * nr)


def test_lying_record_count_keeps_later_section():
    """An array whose declared rs*nr exceeds EOF used to ``break`` the whole
    walk, silently losing every later section."""
    data = (b"\x76\x31" + _array(0x01, 4, 2)
            + bytes([0x03]) + struct.pack(">HH", 4, 20000)   # claims 80000 bytes
            + b"\x76\x32" + _array(0x01, 4, 2))
    results = {}
    sections = walk_vu_record_arrays(data, results)

    assert [s["trep"] for s in sections] == ["0x31", "0x32"]
    assert results["_vu_walk_complete"] is False


def test_truncated_g2_download_is_not_reported_complete(tmp_path):
    """A download whose last section declares more bytes than exist must fail
    closed (complete_walk False / partial), never be reported complete."""
    from app.engine import TachoParser

    data = (b"\x76\x31" + _array(0x01, 4, 2)
            + b"\x76\x32" + _array(0x01, 4, 2)
            + b"\x76\x33" + _array(0x01, 4, 2)
            + b"\x76\x35" + bytes([0x01]) + struct.pack(">HH", 4, 300))
    path = tmp_path / "truncated.ddd"
    path.write_bytes(data)

    report = TachoParser(str(path)).parse()["metadata"]["trep_report"]
    assert report["complete_walk"] is False
    assert report["is_partial"] is True


# ── XD-F2: dense stream must be bounded and fail closed ──────────────────

def test_dense_stream_record_cap_fails_closed(monkeypatch):
    """Per-array cap 20000 does not bound the stream. With the global cap the
    walk stops, reports partial, and never allocates unbounded dicts."""
    from core.parser import vu_dispatcher
    from core.utils.constants import RECORD_ARRAY_MAX_RECORDS, VU_MAX_TOTAL_RECORDS

    assert VU_MAX_TOTAL_RECORDS >= RECORD_ARRAY_MAX_RECORDS

    monkeypatch.setattr(vu_dispatcher, "VU_MAX_TOTAL_RECORDS", 100)
    data = b"\x76\x31" + _array(0x01, 1, 20000, b"\x01")

    results = {}
    sections = walk_vu_record_arrays(data, results)
    decoded = sum(sum(s["record_counts"].values()) for s in sections)

    assert results["_vu_walk_complete"] is False
    assert results["_vu_walk_record_cap"] == 100
    assert decoded == 100, f"decoded {decoded} records despite cap of 100"


def test_dense_stream_below_cap_is_complete():
    """Negative sibling: a small, valid stream stays complete (the cap is not a
    blanket 'partial' verdict)."""
    results = {}
    walk_vu_record_arrays(b"\x76\x31" + _array(0x01, 4, 3), results)
    assert results["_vu_walk_complete"] is True


def test_shipped_memory_ceiling_value_is_pinned():
    """Pin the SHIPPED ceiling value, not just the mechanism.

    ``test_dense_stream_record_cap_fails_closed`` monkeypatches the constant to
    100, so it never reads the shipped number: raising it (reviewer's M5,
    500000 -> 10**9) leaves the suite green. Measured justification for 500000:
    the smallest dense input that can reach it is 26 x (5 + 20000) = 520130 B
    (~1 record per input byte) and the worst case is a flat ~5.6 MB tracemalloc
    peak; a decoded 1-byte record costs up to 280.6x its bytes. Expressing it as
    25 x RECORD_ARRAY_MAX_RECORDS keeps both edges moving together.
    """
    from core.utils.constants import RECORD_ARRAY_MAX_RECORDS, VU_MAX_TOTAL_RECORDS

    assert VU_MAX_TOTAL_RECORDS == 500_000
    assert VU_MAX_TOTAL_RECORDS == 25 * RECORD_ARRAY_MAX_RECORDS


# ── D-F3 / D2-008: generation from the leading TRTP marker ───────────────

def test_generation_from_leading_trtp_marker():
    from core.parser.deterministic import DeterministicParser

    def gen(first_two):
        return DeterministicParser()._detect_generation(first_two + b"\x00" * 40)

    # Gen 2.2 TRTP markers per the annex: 00, 31, 32, 33 and 35.
    for trep in (0x00, 0x31, 0x32, 0x33, 0x35):
        assert gen(bytes([0x76, trep])) == "G2.2", f"76 {trep:02X} should be G2.2"
    for trep in (0x21, 0x22, 0x23, 0x24, 0x25):
        assert gen(bytes([0x76, trep])) == "G2", f"76 {trep:02X} should be G2"
    for trep in (0x01, 0x02, 0x03, 0x05, 0x06):
        assert gen(bytes([0x76, trep])) == "G1", f"76 {trep:02X} should be G1"

    # Exactly the annex G2.2 set: no marker the annex does not define (an
    # invented mapping in the generation table) may classify as v2.
    g22 = {b for b in range(0x100) if gen(bytes([0x76, b])) == "G2.2"}
    assert g22 == {0x00, 0x31, 0x32, 0x33, 0x35}


def test_g1_file_with_inner_g2_marker_stays_g1():
    """Generation must come from the leading marker, never a byte pair inside a
    record: a G1 file (76 01) containing 76 32 in its body stays G1."""
    from core.parser.deterministic import DeterministicParser

    data = b"\x76\x01" + b"\x00" * 5 + b"\x76\x32" + b"\x00" * 40
    assert DeterministicParser()._detect_generation(data) == "G1"
