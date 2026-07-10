"""Unit tests for the anchor-based salvage pass (core.parser.salvage)."""
from core.parser import salvage
from tests.unit.real_data import require_real_file


def test_should_salvage_requires_partial_and_unparsed():
    # Partial but no unparsed bytes -> nothing to salvage.
    results = {"metadata": {"trep_report": {"is_partial": True}}, "raw_tags": {}}
    assert salvage.should_salvage(results) is False

    # Complete report -> never salvage.
    results = {
        "metadata": {"trep_report": {"is_partial": False}},
        "raw_tags": {"Unparsed Data": [{"offset": "0x0", "length": "500"}]},
    }
    assert salvage.should_salvage(results) is False

    # Partial + a sizeable unparsed region -> salvage.
    results = {
        "metadata": {"trep_report": {"is_partial": True}},
        "raw_tags": {"Unparsed Data": [{"offset": "0x0", "length": "500"}]},
    }
    assert salvage.should_salvage(results) is True


def test_should_salvage_ignores_tiny_regions():
    results = {
        "metadata": {"trep_report": {"is_partial": True}},
        "raw_tags": {"Unparsed Data": [{"offset": "0x0", "length": "4"}]},
    }
    assert salvage.should_salvage(results) is False


def test_salvage_recovers_embedded_card_from_unparsed_region():
    # A NO_PLATE file is a card-download-only VU stream; present its card image
    # as one large unparsed region and confirm salvage recovers real data.
    path = require_real_file("VU_NO_PLATE_NO_VIN_UNVERIFIED_06C93F5620.ddd")
    data = open(path, "rb").read()
    card = data[0x2:len(data)]
    results = {
        "metadata": {"trep_report": {"is_partial": True}},
        "raw_tags": {"Unparsed Data": [
            {"offset": f"0x{2:08X}", "length": str(len(card))}]},
    }

    gained = salvage.salvage_vu_download(data, results)

    assert "driver" in gained
    assert results["driver"]["surname"].isprintable()
    assert len(results.get("events") or []) > 0
    # Everything salvaged is flagged heuristic.
    assert "salvage" in results["metadata"]["heuristic_fields"]


def test_salvage_no_regions_is_noop():
    results = {"metadata": {}, "raw_tags": {}}
    assert salvage.salvage_vu_download(b"\x00" * 10, results) == []
