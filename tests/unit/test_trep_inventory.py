"""Unit tests for TREP completeness inventory (core.parser.trep_inventory)."""
from core.parser import trep_inventory as ti


def test_family_mapping():
    assert ti._family("G1 (Digital)") == "G1"
    assert ti._family("G2 (Smart)") == "G2"
    assert ti._family("G2.2 (Smart V2)") == "G2.2"
    assert ti._family("") == "G1"


def test_complete_g1_download():
    report = ti.build_trep_report("G1 (Digital)", [0x01, 0x02, 0x03, 0x05, 0x04])
    # Overview (0x01) is the only mandatory TREP (DDP_054).
    assert report["mandatory_total"] == 1
    assert report["mandatory_ok"] == 1
    assert report["completeness_pct"] == 100.0
    assert report["is_partial"] is False
    assert report["mandatory_missing"] == []


def test_partial_missing_mandatory():
    report = ti.build_trep_report("G1 (Digital)", [0x06, 0x11])
    assert report["mandatory_ok"] == 0
    assert report["is_partial"] is True
    missing = {t["name"] for t in report["mandatory_missing"]}
    assert missing == {"Overview"}


def test_selective_download_without_activities_is_not_partial():
    # A legal selective download (Overview + one optional section) is complete:
    # Activities/EventsFaults/TechnicalData are NOT mandatory (C-F3 / D2-004).
    report = ti.build_trep_report("G1 (Digital)", [0x01, 0x11, 0x14])
    assert report["is_partial"] is False
    assert report["completeness_pct"] == 100.0
    assert report["mandatory_missing"] == []


def test_suspect_section_still_flags_partial():
    report = ti.build_trep_report(
        "G1 (Digital)", [0x01, 0x02, 0x03, 0x05], suspect_treps=[0x05])
    assert report["mandatory_present"] == 1
    assert report["mandatory_ok"] == 1
    assert report["is_partial"] is True
    assert {t["name"] for t in report["decoded_suspect"]} == {"TechnicalData"}


def test_incomplete_walk_flags_partial():
    report = ti.build_trep_report(
        "G2 (Smart)", [0x21, 0x22, 0x23, 0x25], complete_walk=False)
    assert report["generation"] == "G2"
    assert report["mandatory_ok"] == 1
    assert report["is_partial"] is True


def test_g22_mandatory_set():
    report = ti.build_trep_report("G2.2 (Smart V2)", [0x31, 0x32, 0x33, 0x35])
    assert report["generation"] == "G2.2"
    assert report["mandatory_ok"] == 1
    assert report["is_partial"] is False


def test_format_summary_string():
    report = ti.build_trep_report("G1 (Digital)", [0x01, 0x03], suspect_treps=[0x03])
    s = ti.format_trep_summary(report)
    assert "mandatory OK" in s
    assert "suspect" in s
