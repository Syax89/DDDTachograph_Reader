"""Unit tests for content-based origin detection (core.parser.origin_detector)."""
from core.parser.origin_detector import (
    detect_origin, ORIGIN_CARD, ORIGIN_VU)


def _results_with_tags(*tag_ids):
    return {"raw_tags": {
        f"tag_{t:04X}": [{"tag_id": f"0x{t:04X}"}] for t in tag_ids}}


def test_card_header_is_card():
    origin, note, wrapped = detect_origin(False, _results_with_tags(0x0002))
    assert origin == ORIGIN_CARD
    assert wrapped is False
    assert note == ""


def test_standalone_trep06_card_is_reclassified_as_card():
    # VU header, only TREP 06, card-only EFs present -> card (VU-wrapped).
    results = _results_with_tags(0x0002, 0x0501, 0x0520)
    origin, note, wrapped = detect_origin(True, results, vu_treps=[0x06])
    assert origin == ORIGIN_CARD
    assert wrapped is True
    assert "TREP 06" in note


def test_real_vu_download_stays_vu():
    # Overview + activities present -> genuine VU.
    results = _results_with_tags(0x7601, 0x7602, 0x7603)
    origin, note, wrapped = detect_origin(True, results, vu_treps=[0x01, 0x02, 0x03])
    assert origin == ORIGIN_VU
    assert wrapped is False


def test_vu_with_card_copy_stays_vu():
    # TREP 06 alongside other TREPs is a VU download with a card copy.
    results = _results_with_tags(0x7601, 0x0520)
    origin, _note, wrapped = detect_origin(True, results, vu_treps=[0x01, 0x06])
    assert origin == ORIGIN_VU
    assert wrapped is False


def test_trep06_without_card_tags_stays_vu():
    # A lone TREP 06 that does not decode to card EFs is not reclassified.
    results = _results_with_tags(0x7605)
    origin, _note, wrapped = detect_origin(True, results, vu_treps=[0x06])
    assert origin == ORIGIN_VU
    assert wrapped is False


def test_wrapped_card_file_end_to_end():
    # A real VU-wrapped card dump must parse as a driver card (not a partial
    # VU download) with the driver holder data recovered.
    from app.engine import TachoParser
    from tests.unit.real_data import require_real_file
    path = require_real_file("VU_NO_PLATE_NO_VIN_UNVERIFIED_81E64B117F.ddd")
    meta = TachoParser(path).parse()["metadata"]

    assert meta["origin"] == ORIGIN_CARD
    assert meta["is_vu"] is False
    assert "trep_report" not in meta
    assert "TREP 06" in meta.get("origin_note", "")
