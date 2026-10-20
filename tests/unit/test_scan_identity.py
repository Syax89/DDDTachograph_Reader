"""The byte-scan recovery must key records by the offset it found them at.

The deterministic walk names a record ``msg:<body offset>#<index>``. The recovery
scan re-reads the same bytes, so it must use the *same* identity namespace: a re-read
collides with the walk's record (and is dropped), while a body the scan finds at a
different offset stays a distinct stored record. Before this fix the scan passed no
offset at all, fell back to a content hash and therefore published a second copy of
every record the walk already had.
"""
from app.engine import TachoParser
from core.decoders import vu_g1
from core.registry.registry import DecoderRegistry
from tests.unit.real_data import require_real_file
from core.decoders.vu_g1 import _parse_trep_03_structured
from tests.unit.test_g1_vu_semantics import _results, _trep03_body


def _counts(result):
    return {key: len(result.get(key) or []) for key in
            ("activities", "events", "faults", "places", "card_iw_records",
             "specific_conditions")}


def _parse_bytes(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


# ── Item 1: the half-truncated real file keeps the parent's counts ────────

def test_half_truncated_real_file_does_not_double_publish(tmp_path):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        raw = handle.read()
    result = _parse_bytes(tmp_path, "half.ddd", raw[:len(raw) // 2])
    counts = _counts(result)
    # the numbers the parent revision (8910c0e) produced for this cut
    assert counts == {"activities": 42, "events": 37, "faults": 3, "places": 49,
                      "card_iw_records": 25, "specific_conditions": 7}, counts
    # and no record appears twice with the same decoded content
    for key in ("faults", "events", "places", "specific_conditions"):
        records = [r for r in (result.get(key) or []) if isinstance(r, dict)]
        fingerprints = [tuple(sorted((k, str(v)) for k, v in r.items()
                                     if not k.startswith("_") and k != "time_status"))
                        for r in records]
        assert len(fingerprints) == len(set(fingerprints)), key


def test_the_intact_file_is_unchanged(tmp_path):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        raw = handle.read()
    result = _parse_bytes(tmp_path, "intact.ddd", raw)
    assert not (result["metadata"].get("decode_paths") or {}).get("fallback")
    assert not result["metadata"].get("heuristic_fields")


# ── Item 2: two byte-identical messages at different offsets ─────────────

def test_the_scan_keeps_two_identical_messages_at_different_offsets(tmp_path):
    body = _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(), n_adj=())
    stream = b"\x76\x03" + body + b"\x76\x03" + body
    result = _results()
    vu_g1.parse_vu_download_messages(stream, result)
    assert len(result["faults"]) == 2
    assert len(result["events"]) == 2


def test_a_re_read_of_the_same_offset_is_still_one(tmp_path):
    body = _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(), n_adj=())
    stream = b"\x76\x03" + body
    result = _results()
    # the same scan run twice: the second pass re-reads the same offsets
    vu_g1.parse_vu_download_messages(stream, result)
    vu_g1.parse_vu_download_messages(stream, result)
    assert len(result["faults"]) == 1
    assert len(result["events"]) == 1


def test_the_scan_and_the_walk_agree_on_the_identity(tmp_path):
    """A body the scan finds where the walk already read it is not a new record."""
    body = _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(), n_adj=())
    stream = b"\x76\x03" + body
    result = _results()
    # the walk names the record by the marker offset it yields (0 for this stream)
    assert _parse_trep_03_structured(body, result, message_offset=0) is True
    baseline = len(result["faults"])
    vu_g1.parse_vu_download_messages(stream, result)
    assert len(result["faults"]) == baseline, "the scan re-published the walk's record"


def test_a_body_the_walk_missed_is_published_once_by_the_scan(tmp_path):
    body = _trep03_body(event_type=0x02, fault_type=0x31, n_over=(), n_adj=())
    stream = b"\x76\x03" + body
    result = _results()
    vu_g1.parse_vu_download_messages(stream, result)
    vu_g1.parse_vu_download_messages(stream, result)
    assert len(result["faults"]) == 1
    assert len(result["events"]) == 1


# ── Item 3: the notice must not name a card type ─────────────────────────

def test_the_notice_and_origin_note_do_not_name_a_card_type():
    from app import gui
    from core.utils import report_format as rf
    from tests.unit.real_data import require_real_file
    notice = gui.CARD_ENVELOPE_NOTICE
    assert notice.startswith("Card image downloaded through the vehicle unit")
    assert "driver" not in notice.lower()
    path = require_real_file("*_D47C4D98DF.ddd")
    DecoderRegistry.reset_instance()
    result = TachoParser(path).parse()
    origin_note = str(result["metadata"].get("origin_note") or "")
    assert origin_note.startswith("Card image extracted from a VU Card Download"), (
        origin_note)
    assert "driver" not in origin_note.lower()
    rows = dict(rf.summary_rows(result))
    value = rows.get("Transfer header") or ""
    assert value.startswith("Card image downloaded through the vehicle unit")
    assert "driver" not in value.lower()


def test_every_catalog_notice_translation_drops_the_card_type():
    import glob
    import re
    msgid = ("Card image downloaded through the vehicle unit: the two leading bytes "
             "are the transfer header (SID + TREP 06) kept by the tool that saved it, "
             "not the standard storage form of a card file (DDP_050). Some other "
             "programs report such a file as corrupt; this reader reports the card's "
             "own signature verdict separately.")
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        text = open(path, encoding="utf-8").read()
        match = re.search(r'^msgid "%s"\nmsgstr "(.*)"$' % re.escape(msgid), text, re.M)
        assert match, path
        assert match.group(1) != msgid, path
