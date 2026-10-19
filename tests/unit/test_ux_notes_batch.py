"""Four things a user saw on screen: calibration labels, the record summary, a stale layout."""
import pytest

from core.utils.event_codes import describe_calibration_purpose
from core.utils.report_format import code_label, fmt_known_structure, fmt_scalar


@pytest.mark.parametrize("code, label", [
    (0x00, "Reserved"),
    (0x01, "Activation"),
    (0x04, "Periodic inspection"),
    (0x05, "Entry of VRN by company"),                    # Annex 1C, generation 2
    (0x06, "Time adjustment without calibration"),
    (0x07, "Reserved for future use (0x07)"),
    (0x7F, "Reserved for future use (0x7F)"),
    (0x80, "Manufacturer specific (0x80)"),
    (0x82, "Manufacturer specific (0x82)"),
    (0x83, "Manufacturer specific (0x83)"),
    (0xFF, "Manufacturer specific (0xFF)"),
    (None, "Unknown"),
])
def test_every_calibration_purpose_byte_has_a_label(code, label):
    assert describe_calibration_purpose(code) == label


def test_no_calibration_purpose_byte_is_left_as_a_bare_hex_code():
    assert all(not describe_calibration_purpose(c).startswith("0x") for c in range(256))


def test_the_record_summary_names_the_records_instead_of_listing_hex_codes():
    text = fmt_known_structure({"0x06": 1, "0x01": 88, "0x1C": 2, "0x40": 3, "0x99": 4})
    assert text == ("Date Of Day Downloaded \u00d71, Activity Change Info \u00d788, "
                    "Vu Place Daily Work Period Record \u00d72, "
                    "RFU 0x40 Detailed Speed Sample \u00d73, Record 0x99 \u00d74")
    assert "0x06=" not in text


@pytest.mark.parametrize("other", [{}, {"a": 1}, {"0x06": "x"}, {"0x06": True}, {"0x6": 1}])
def test_only_a_hex_keyed_count_table_is_rewritten(other):
    assert fmt_known_structure(other) is None


def test_the_trep_cell_does_not_repeat_its_own_code():
    assert fmt_scalar("0x32", key="trep", include_code_label=True) == "0x32"
    # a number still gets its name: 33 is not self-explanatory, 0x21 is TREP 21
    assert fmt_scalar(0x21, key="trep", include_code_label=True) == "33  (TREP 21)"
    assert code_label("0x0C", key="record_type") == "VuCalibrationRecord"   # unchanged


# ── the Vehicle page after a chart ────────────────────────────────────────────
from tests.unit.test_gui_summary_default import (  # noqa: E402,F401
    MOCK_DIR, _parse_file, explorer,
)


def _node(app, text, parent=""):
    for iid in app.tree.get_children(parent):
        if app.tree.item(iid, "text").strip() == text:
            return iid
        found = _node(app, text, iid)
        if found:
            return found
    return None


def test_the_vehicle_page_keeps_its_columns_after_a_chart(explorer):  # noqa: F811
    """Back from a chart the table is re-packed at the same size, so Tk never
    re-stretched the Value column: it stayed at its 100 px placeholder."""
    path = MOCK_DIR / "mock_g2_vu.ddd"
    if not path.exists():
        pytest.skip("run tests/integration/generate_mock_ddd.py first")
    explorer.geometry("1100x700")
    explorer.update()
    _parse_file(explorer, path)
    vehicle = _node(explorer, "Vehicle")
    explorer.tree.selection_set(vehicle)
    explorer.update()
    before = explorer.table.tv.column("Value", "width")

    explorer._show_speed_chart("2025-05-01", [(6 * 3600 + i, 60 + i % 5) for i in range(600)])
    explorer.update()
    explorer.tree.selection_set(_node(explorer, "File Info"))
    explorer.update()
    explorer._show_speed_chart("2025-05-01", [(6 * 3600 + i, 60 + i % 5) for i in range(600)])
    explorer.update()
    explorer.tree.selection_set(vehicle)
    explorer.update()

    assert before > 300
    assert explorer.table.tv.column("Value", "width") == before
