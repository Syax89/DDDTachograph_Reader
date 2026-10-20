"""A stand-alone TREP 06 envelope is the plain card plus two bytes.

Some downloads are relayed *through the vehicle unit*: the file is the VU's
SID 0x76 + TREP 06 header followed by a complete card image (Annex 1B DDP_049/050 —
the relaying VU keeps the two header bytes that DDP_050 strips for a stored card
file). Such a file is not a VU stream and not a "corrupt card": it must decode
exactly like the plain card, with the two envelope bytes accounted for.

Every assertion compares the wrapped parse with the plain parse of the same bytes.
Synthetic cards come from ``tests/integration/generate_mock_ddd.py``; the real
files are addressed by hash glob and skipped when ``DDD/`` is absent.
"""
import os
import tempfile

import pytest

from app.engine import TachoParser
from core.registry.registry import DecoderRegistry
from tests.integration import generate_mock_ddd as mock
from tests.unit.real_data import require_real_file

#: Metadata keys that legitimately differ between a wrapped and a plain parse.
ENVELOPE_METADATA_KEYS = {"filename", "file_name", "file_path", "file_size_bytes",
                          "parsed_at", "origin_note", "envelope",
                          "decoder_validation_warnings"}


def _parse_bytes(tmp_path, name, data):
    path = os.path.join(tmp_path, name)
    with open(path, "wb") as handle:
        handle.write(data)
    DecoderRegistry.reset_instance()
    return TachoParser(path).parse()


def _mock_card(directory, kind):
    path = os.path.join(directory, f"mock_{kind}.ddd")
    {"g1": mock.generate_g1_card, "g2": mock.generate_g2_card}[kind](path)
    with open(path, "rb") as handle:
        return handle.read()


def _payload_without_envelope(result):
    """Result sections that must be identical, minus file/metadata bookkeeping."""
    return {k: v for k, v in result.items() if k not in ("metadata", "coverage")}


def _shift_offsets(value, delta=2):
    """Shift every ``offset`` string in the result (the two envelope bytes)."""
    if isinstance(value, dict):
        return {k: (f"0x{int(v, 16) + delta:08X}" if k == "offset" and isinstance(v, str)
                    else _shift_offsets(v, delta))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_shift_offsets(v, delta) for v in value]
    return value


# ── The envelope is detected and decoded as the plain card ──────────────────

@pytest.mark.parametrize("kind", ["g1", "g2"])
def test_wrapped_card_is_identical_to_the_plain_card(tmp_path, kind):
    card = _mock_card(str(tmp_path), kind)
    plain = _parse_bytes(tmp_path, f"plain-{kind}.ddd", card)
    wrapped = _parse_bytes(tmp_path, f"wrapped-{kind}.ddd", b"\x76\x06" + card)

    assert wrapped["metadata"]["envelope"] == {
        "type": "TREP 06 card download relayed by the VU", "bytes": 2}
    assert wrapped["metadata"]["origin_note"]
    assert wrapped["metadata"]["is_vu"] is False
    assert "trep_report" not in wrapped["metadata"]

    # every offset is shifted by the two envelope bytes; nothing else changes
    assert (_payload_without_envelope(wrapped)
            == _shift_offsets(_payload_without_envelope(plain)))

    for key in ("generation", "integrity_check", "origin"):
        assert wrapped["metadata"][key] == plain["metadata"][key], key
    for key in set(plain["metadata"]) - set(wrapped["metadata"]):
        assert key in ENVELOPE_METADATA_KEYS, key
    assert wrapped["metadata"].get("decode_paths", {}).get("fallback") in (None, [])
    assert (bool(wrapped["metadata"].get("heuristic_fields"))
            == bool(plain["metadata"].get("heuristic_fields")))
    assert (wrapped["metadata"].get("decode_paths", {}).get("fallback_reasons")
            == plain["metadata"].get("decode_paths", {}).get("fallback_reasons"))


def test_wrapped_offsets_are_shifted_by_the_envelope_size(tmp_path):
    card = _mock_card(str(tmp_path), "g2")
    plain = _parse_bytes(tmp_path, "plain-off.ddd", card)
    wrapped = _parse_bytes(tmp_path, "wrapped-off.ddd", b"\x76\x06" + card)
    assert _shift_offsets(plain["raw_tags"]) == wrapped["raw_tags"]
    assert wrapped["coverage"]["total_bytes"] == len(card) + 2
    assert wrapped["coverage"]["covered_pct"] == plain["coverage"]["covered_pct"]


def test_g2_card_keeps_its_generation_behind_the_envelope(tmp_path):
    card = _mock_card(str(tmp_path), "g2")
    wrapped = _parse_bytes(tmp_path, "wrapped-g2-gen.ddd", b"\x76\x06" + card)
    plain = _parse_bytes(tmp_path, "plain-g2-gen.ddd", card)
    assert plain["metadata"]["generation"].startswith("G2")
    assert wrapped["metadata"]["generation"] == plain["metadata"]["generation"]
    assert len(wrapped["generations"]) == len(plain["generations"])


def test_trailing_download_trailer_is_tolerated(tmp_path):
    card = _mock_card(str(tmp_path), "g1")
    plain = _parse_bytes(tmp_path, "plain-tr.ddd", card)
    wrapped = _parse_bytes(tmp_path, "wrapped-tr.ddd", b"\x76\x06" + card + b"\x76\x00")
    assert wrapped["metadata"]["envelope"]["bytes"] == 2
    assert wrapped["metadata"]["integrity_check"] == plain["metadata"]["integrity_check"]


# ── Things that are NOT an envelope go to the VU path ─────────────────────

def test_envelope_with_a_cut_card_is_not_treated_as_a_card(tmp_path):
    card = _mock_card(str(tmp_path), "g1")
    # cut inside the last element: the TLV chain does not close
    cut = b"\x76\x06" + card[:-20]
    result = _parse_bytes(tmp_path, "cut.ddd", cut)
    assert "envelope" not in result["metadata"]
    # the VU path owns it: the card region does not close, which is an integrity
    # finding (never silently complete) and never claims the card was verified
    findings = result["metadata"].get("vu_integrity") or []
    assert any(f["status"] == "card_envelope_incomplete" for f in findings), findings
    assert result.get("_vu_walk_complete") is not True
    assert "Verified" not in result["metadata"]["integrity_check"]


def test_envelope_followed_by_garbage_is_not_a_card(tmp_path):
    card = _mock_card(str(tmp_path), "g1")
    result = _parse_bytes(tmp_path, "garbage.ddd", b"\x76\x06" + card + b"\xde\xad\xbe\xef")
    assert "envelope" not in result["metadata"]


def test_76_06_without_a_card_is_not_an_envelope(tmp_path):
    result = _parse_bytes(tmp_path, "junk.ddd", b"\x76\x06" + b"\x00" * 40)
    assert "envelope" not in result["metadata"]


# ── Reporting parity in every damage case (F1b) ──────────────────────────

def _verdicts(result):
    ef = result.get("ef_signature_verification") or {}
    return (result["metadata"]["integrity_check"], ef.get("verified"),
            ef.get("failed"), bool(result["metadata"].get("heuristic_fields")))


def _assert_same_verdict(wrapped, plain):
    assert _verdicts(wrapped) == _verdicts(plain), (_verdicts(wrapped),
                                                    _verdicts(plain))


@pytest.mark.parametrize("case", ["flipped", "cut-tail"])
def test_synthetic_damage_reports_the_same_verdict_wrapped_and_plain(tmp_path, case):
    """A wrapped file is never MORE or LESS trusted than its plain twin."""
    card = _mock_card(str(tmp_path), "g1")
    damaged = bytearray(card)
    if case == "flipped":
        damaged[5 + 8] ^= 0xFF          # inside the first EF's value
    else:
        # cut *inside* the last element: not a clean image, so the file stays on
        # the VU path and the reason is reported
        damaged = bytes(damaged[:-70])
        wrapped = _parse_bytes(tmp_path, f"w-{case}.ddd", b"\x76\x06" + damaged)
        plain = _parse_bytes(tmp_path, f"p-{case}.ddd", damaged)
        assert "envelope" not in wrapped["metadata"]
        findings = wrapped["metadata"].get("vu_integrity") or []
        assert any(f["status"] == "card_envelope_incomplete" for f in findings)
        assert "Verified" not in wrapped["metadata"]["integrity_check"]
        return
    damaged = bytes(damaged)
    plain = _parse_bytes(tmp_path, f"p-{case}.ddd", damaged)
    wrapped = _parse_bytes(tmp_path, f"w-{case}.ddd", b"\x76\x06" + damaged)
    _assert_same_verdict(wrapped, plain)


# ── Real files ───────────────────────────────────────────────────────────

def _real_pairs():
    """The four real VU-relayed cards, addressed by hash glob."""
    try:
        wrapped = require_real_file("*_D47C4D98DF.ddd")
        others = [require_real_file(p) for p in
                  ("*_06C93F5620.ddd", "*_81E64B117F.ddd", "*_D527C92A52.ddd")]
    except Exception:                                  # DDD/ absent
        return []
    return [wrapped] + others


def _real_plain_card():
    """One real plain card (G1) for the damage-parity checks, or None."""
    try:
        return require_real_file("*_E58D0A65D9.ddd")
    except Exception:
        return None


@pytest.mark.parametrize("case", ["flipped", "cut-inside-tlv", "no-signature"])
def test_real_card_damage_reports_the_same_verdict_wrapped_and_plain(tmp_path, case):
    path = _real_plain_card()
    if not path:
        pytest.skip("no private corpus available")
    with open(path, "rb") as handle:
        card = handle.read()
    if card.startswith(b"\x76"):
        pytest.skip("not a plain card")
    healthy_plain = _parse_bytes(tmp_path, "healthy-plain.ddd", card)
    healthy_wrapped = _parse_bytes(tmp_path, "healthy-wrapped.ddd", b"\x76\x06" + card)
    _assert_same_verdict(healthy_wrapped, healthy_plain)
    # the healthy card is genuinely verified, so the damage has something to break
    assert "Verified" in healthy_plain["metadata"]["integrity_check"]

    damaged = bytearray(card)
    if case == "flipped":
        # flip a byte inside the value of the FIRST signed EF (the per-tag walk
        # gives its offset, so the damage lands in real data, not in padding)
        first = healthy_plain["ef_signature_verification"]["ef_results"][0]
        offset = next(
            occ["offset"] for occs in healthy_plain["raw_tags"].values()
            for occ in occs
            if occ.get("tag_id", "").lower().endswith(first["tag"][2:].lower())
            and occ.get("data_type", "").lower() not in ("signature",))
        start = int(offset, 16) + 5
        damaged[start] ^= 0xFF
    if case == "cut-inside-tlv":
        damaged = bytes(damaged[:-40])
        plain = _parse_bytes(tmp_path, "real-p-cut.ddd", damaged)
        wrapped = _parse_bytes(tmp_path, "real-w-cut.ddd", b"\x76\x06" + damaged)
        # not a clean envelope: it goes to the VU path, and the reason is reported
        assert "envelope" not in wrapped["metadata"]
        findings = wrapped["metadata"].get("vu_integrity") or []
        assert any(f["status"] == "card_envelope_incomplete" for f in findings), findings
        assert "Verified" not in wrapped["metadata"]["integrity_check"]
        return
    # drop the final element cleanly (the last signature): the chain still closes,
    # so this IS an envelope and must report exactly what the plain card reports
    from core.parser.card_envelope import card_image_extent
    body = bytes(damaged)
    end, _count = card_image_extent(body)
    last = 0
    pos = 0
    import struct as _struct
    while pos < end:
        tag, dtype, length = _struct.unpack(">HBH", body[pos:pos + 5])
        last = pos
        pos += 5 + length
    damaged = body[:last]
    plain = _parse_bytes(tmp_path, f"real-p-{case}.ddd", damaged)
    wrapped = _parse_bytes(tmp_path, f"real-w-{case}.ddd", b"\x76\x06" + damaged)
    assert wrapped["metadata"]["envelope"]["bytes"] == 2
    _assert_same_verdict(wrapped, plain)
    assert "Verified" not in wrapped["metadata"]["integrity_check"], case


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_real_wrapped_card_equals_its_unwrapped_twin(tmp_path, index):
    files = _real_pairs()
    if not files:
        pytest.skip("no private corpus available")
    with open(files[index], "rb") as handle:
        raw = handle.read()
    if not raw.startswith(b"\x76\x06"):
        pytest.skip("not a wrapped card")
    card = raw[2:]
    plain = _parse_bytes(tmp_path, "real-plain.ddd", card)
    wrapped = _parse_bytes(tmp_path, "real-wrapped.ddd", raw)

    assert wrapped["metadata"]["envelope"]["bytes"] == 2
    assert wrapped["metadata"]["generation"] == plain["metadata"]["generation"]
    assert wrapped["metadata"]["integrity_check"] == plain["metadata"]["integrity_check"]
    for key in ("generations", "ef_signature_verification", "gnss_ad_records"):
        assert len(wrapped.get(key) or []) == len(plain.get(key) or []), key
    assert (_payload_without_envelope(wrapped)
            == _shift_offsets(_payload_without_envelope(plain)))
