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


# ── a warning box must not freeze the window in its "opening" state ───────────
def test_the_integrity_warning_opens_after_the_file_is_on_screen(explorer, monkeypatch):  # noqa: F811
    """A modal box opened from inside the render left the bar running, Open and
    Export disabled and the pane on "Loading…" until it was closed (and for good
    if it opened behind the window, e.g. after a drag & drop)."""
    from app import gui
    seen = []

    class Spy:
        def __getattr__(self, name):
            return lambda *a, **k: seen.append((
                name, explorer._parsing, explorer._rendering,
                str(explorer.btn_open.cget("state")), bool(explorer.progress.winfo_ismapped())))

    monkeypatch.setattr(gui, "messagebox", Spy())
    path = MOCK_DIR / "mock_g2_vu.ddd"
    if not path.exists():
        pytest.skip("run tests/integration/generate_mock_ddd.py first")
    explorer.geometry("1100x700")
    explorer.update()
    _parse_file(explorer, path)
    _parse_file(explorer, MOCK_DIR / "mock_g2_card.ddd")      # a file is already open
    # Force a flagged file through the real open path.
    flagged = dict(explorer.current_data)
    flagged["metadata"] = dict(flagged.get("metadata") or {}, integrity_check="Card data signature mismatch")
    seen.clear()
    explorer._parse_done(flagged, "/tmp/flagged.ddd")
    explorer.update()

    assert seen, "the warning was lost"
    name, parsing, rendering, open_state, bar = seen[0]
    assert (name, parsing, rendering, open_state, bar) == ("showwarning", False, False, "normal", False)
    assert explorer.tree.selection(), "the pane must already show the file"


# ── Record Type: off the screen, beside the section title in the exports ───────
def test_the_record_type_column_is_not_on_screen(explorer):  # noqa: F811
    """Every node of a VU file whose records carry a record code: no "Record Type"."""
    import time

    from tests.unit.test_gui_summary_default import open_file, vu_data
    calibrations = [{"purpose": "Activation", "record_type": "0x0C", "name": "VuCalibrationRecord"},
                    {"purpose": "Periodic inspection", "record_type": "0x0C", "name": "VuCalibrationRecord"}]
    places = [{"description": "Start", "record_type": "0x1C"}]
    explorer.geometry("1100x700")
    explorer.update()
    open_file(explorer, vu_data(generations={"Generation 2": {
        "CalibrationData": calibrations, "Places": places,
        "VU Identifications": [{"description": "Unit", "record_type": "0x19"}]}}))
    seen = 0

    def walk(parent=""):
        for iid in explorer.tree.get_children(parent):
            yield iid
            yield from walk(iid)

    for iid in list(walk()):
        explorer.tree.selection_set(iid)
        explorer.update()
        time.sleep(0.01)
        fields = [explorer.table.tv.item(r, "values")[0] for r in explorer.table.tv.get_children("")
                  if explorer.table.tv.item(r, "values")]
        assert "Record Type" not in explorer.table._cols
        assert "Record Type" not in fields
        seen += 1
    assert seen >= 6
    titles = [explorer.tree.item(i, "text") for i in walk()]
    assert any("Calibration" in t for t in titles), titles   # the sections were really rendered


def test_a_constant_record_type_moves_to_the_section_note_in_the_exports():
    from core.utils.report_format import section_tables
    calibs = [{"purpose": "Activation", "record_type": "0x0C"},
              {"purpose": "Periodic inspection", "record_type": "0x0C"}]
    (label, desc, headers, rows, _t), = list(section_tables({"calibrations": calibs}))
    assert "Record Type" not in headers and headers == ["Purpose"]
    assert rows == [["Activation"], ["Periodic inspection"]]
    assert "Record type: 0x0C (VuCalibrationRecord)." in desc


def test_a_varying_record_type_stays_a_column_in_the_exports():
    from core.utils.report_format import section_tables
    items = [{"purpose": "a", "record_type": "0x0C"}, {"purpose": "b", "record_type": "0x0D"}]
    (_l, desc, headers, rows, _t), = list(section_tables({"calibrations": items}))
    assert headers[-1] == "Record Type" and [r[-1] for r in rows] == ["0x0C", "0x0D"]
    assert "Record type" not in desc


# ── every language knows the labels added today ───────────────────────────────
NEW_LABELS = ("Entry of VRN by company", "Time adjustment without calibration",
              "Reserved for future use", "Manufacturer specific")


def test_every_catalog_translates_every_new_label():
    import gettext
    from pathlib import Path
    from app import i18n
    root = Path(__file__).resolve().parents[2] / "locale"
    langs = [p.name for p in root.iterdir() if p.is_dir()]
    assert len(langs) == 33
    for lang in langs:
        catalog = gettext.GNUTranslations(open(root / lang / "LC_MESSAGES" / "tacho.mo", "rb"))
        for label in NEW_LABELS:
            assert catalog.gettext(label).strip(), f"{lang}: {label!r}"
    assert i18n.LANGUAGES  # the catalogs are the ones the app ships


@pytest.mark.parametrize("lang", ["it", "de", "ru", "el"])
def test_a_coded_label_keeps_its_code_and_translates_its_words(lang):
    from app import i18n, ui_text
    i18n.install(lang)
    ui_text.configure_translate_data(True)
    try:
        for label in ("Manufacturer specific", "Reserved for future use"):
            text = ui_text.data_text(f"{label} (0x83)")
            assert text.endswith(" (0x83)")
            assert text != f"{label} (0x83)", f"{lang}: {label} untranslated"
        assert ui_text.data_text("Entry of VRN by company") != "Entry of VRN by company"
        assert ui_text.data_text("Unlisted thing (0x83)") == "Unlisted thing (0x83)"
    finally:
        ui_text.configure_translate_data(False)
        i18n.install("en")
