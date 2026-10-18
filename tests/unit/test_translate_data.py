"""The "translate file contents" preference (off by default).

Two kinds of text share the window: the application's own chrome, which is
always translated, and labels *decoded from the tachograph file* — an activity
name, a nation, a record-code name. The preference decides the second kind only:
off keeps them exactly as the file/decoder names them, on translates them too.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import app.i18n as i18n
import app.ui_text as ui_text
from core.utils.report_format import fmt_scalar

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "locale"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(i18n, "settings_path", lambda: str(path))
    return path


# ── the persisted preference ───────────────────────────────────────────────

def test_missing_preference_means_off(settings):
    assert i18n.saved_translate_data() is False


@pytest.mark.parametrize("stored", [True, False])
def test_roundtrip(settings, stored):
    assert i18n.save_translate_data(stored)
    assert i18n.saved_translate_data() is stored


@pytest.mark.parametrize("stored", ["true", "yes", 1, 0, None, [], {}])
def test_only_a_real_boolean_turns_it_on(settings, stored):
    """"yes", 1 and null are all values a hand-edited file can hold."""
    settings.write_text(json.dumps({"translate_file_content": stored}), encoding="utf-8")
    assert i18n.saved_translate_data() is False


def test_saving_preserves_the_language(settings):
    assert i18n.save_language("it")
    assert i18n.save_translate_data(True)
    assert i18n.saved_language() == "it"
    assert i18n.saved_translate_data() is True


def test_non_boolean_is_refused(settings):
    assert i18n.save_translate_data("yes") is False
    assert i18n.saved_translate_data() is False


# ── the display layer ──────────────────────────────────────────────────────

def test_data_text_is_a_pass_through_when_off():
    ui_text.configure_translate_data(False)
    assert ui_text.data_text("Drive") == "Drive"
    assert ui_text.data_text("Italy") == "Italy"


def test_data_text_translates_when_on(monkeypatch):
    if not (CATALOG_DIR / "it" / "LC_MESSAGES" / "tacho.mo").exists():
        pytest.skip("the Italian catalog is not built in this checkout")
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(CATALOG_DIR))
    assert i18n.install("it") == "it"
    ui_text.configure_translate_data(True)
    try:
        assert ui_text.data_text("Drive") == i18n._("Drive")
        assert ui_text.data_text("Drive") != "Drive"
    finally:
        ui_text.configure_translate_data(False)


@pytest.mark.parametrize("value", [None, 0, 3.5, b"raw", ["a"]])
def test_data_text_never_touches_non_strings(value):
    ui_text.configure_translate_data(True)
    try:
        assert ui_text.data_text(value) is value
    finally:
        ui_text.configure_translate_data(False)


# ── report_format stays byte-identical without a translator ────────────────

def test_fmt_scalar_output_is_unchanged_without_a_translator():
    assert fmt_scalar("I", key="nation") == "Italy"
    assert fmt_scalar(1, key="trep", include_code_label=True) == "1  (TREP 01)"


def test_fmt_scalar_applies_the_translator_to_derived_labels_only():
    calls = []

    def translator(text):
        calls.append(text)
        return f"<{text}>"

    assert fmt_scalar("I", key="nation", label_translator=translator) == "<Italy>"
    assert fmt_scalar(1, key="trep", include_code_label=True,
                      label_translator=translator) == "1  (<TREP 01>)"
    # The value itself is never handed to the translator.
    assert calls == ["Italy", "TREP 01"]
    assert fmt_scalar("IT1234567890", key="card_number",
                      label_translator=translator) == "IT1234567890"


# ── what the toggle is allowed to translate ────────────────────────────────

def _install_italian(monkeypatch):
    if not (CATALOG_DIR / "it" / "LC_MESSAGES" / "tacho.mo").exists():
        pytest.skip("the Italian catalog is not built in this checkout")
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(CATALOG_DIR))
    assert i18n.save_language("it")
    assert i18n.install("it") == "it"


def test_decoder_vocabulary_follows_the_preference(monkeypatch):
    """Event/fault names are decoder output: off keeps them, on translates them."""
    _install_italian(monkeypatch)
    import app.gui as gui

    for key in ("description", "record_purpose_label", "condition", "section", "status"):
        ui_text.configure_translate_data(False)
        assert gui.fmt_val("Over speeding", key=key) == "Over speeding", key
        ui_text.configure_translate_data(True)
        try:
            assert gui.fmt_val("Over speeding", key=key) == i18n._("Over speeding"), key
            assert gui.fmt_val("Over speeding", key=key) != "Over speeding", key
        finally:
            ui_text.configure_translate_data(False)


def test_free_text_is_unchanged_in_both_states(monkeypatch):
    """A name, a plate or an address has no catalog entry: it never changes."""
    _install_italian(monkeypatch)
    import app.gui as gui

    for value in ("GI.EFFE TRASPORTI S.R.L.", "AB123CD", "Via Roma 1"):
        for flag in (False, True):
            ui_text.configure_translate_data(flag)
            assert gui.fmt_val(value, key="company_name") == value, (value, flag)
    ui_text.configure_translate_data(False)


def test_any_cell_with_a_catalog_word_follows_the_preference(monkeypatch):
    """Inside the table the source of the text does not matter: only the tick."""
    _install_italian(monkeypatch)
    import app.gui as gui

    ui_text.configure_translate_data(False)
    assert gui.fmt_val("Drive", key="workshop_name") == "Drive"
    ui_text.configure_translate_data(True)
    try:
        assert gui.fmt_val("Drive", key="workshop_name") == i18n._("Drive")
    finally:
        ui_text.configure_translate_data(False)


def test_booleans_are_words_not_python(monkeypatch):
    """Summary rows carry raw bools: never Python's True/False on screen."""
    _install_italian(monkeypatch)
    import app.gui as gui

    ui_text.configure_translate_data(False)
    assert gui.fmt_val(True) == "Yes"
    assert gui.fmt_val(False) == "No"
    assert gui.fmt_val(1) == "1"          # an int is a value, not a flag
    ui_text.configure_translate_data(True)
    try:
        assert gui.fmt_val(True) == i18n._("Yes")
        assert gui.fmt_val(False) == i18n._("No")
    finally:
        ui_text.configure_translate_data(False)


def test_activity_cells_use_the_same_word_as_the_chart(monkeypatch):
    _install_italian(monkeypatch)
    import app.gui as gui

    ui_text.configure_translate_data(False)
    assert gui.fmt_val("DRIVE", key="activity") == "Drive"
    assert gui._act_label("DRIVE") == "Drive"
    ui_text.configure_translate_data(True)
    try:
        assert gui.fmt_val("DRIVE", key="activity") == i18n._("Drive")
        assert gui.fmt_val("DRIVE", key="activity") == gui._act_label("DRIVE")
    finally:
        ui_text.configure_translate_data(False)


# ── the window ─────────────────────────────────────────────────────────────

def _explorer(monkeypatch):
    """A real, Italian window with modal dialogs stubbed out."""
    tkinter = pytest.importorskip("tkinter")
    try:
        probe = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display available")
    probe.destroy()

    import app.gui as gui
    monkeypatch.setattr(gui, "messagebox", Mock())
    return gui.TachoExplorer()


#: The smallest file that renders a table with a file-decoded value: a
#: calibration record whose nation column is "I" ("Italy" / "Italia").
MOCK_CARD = {
    "metadata": {"generation": "Generation 1", "is_vu": False,
                 "origin": "driver_card", "file_size_bytes": 4096,
                 "parsed_at": "", "app_version": "test",
                 "integrity_check": "Verified"},
    "coverage": {},
    "driver": {},
    "generations": {"Generation 1": {
        "CalibrationData": [{"nation": "I", "workshop_name": "OFFICINA"}],
        "EventsData": [{"description": "Over speeding",
                        "record_purpose_label": "Active / on-going event or fault",
                        "begin_time": "2024-11-26T00:00:00Z"}]}},
}


def test_clicking_the_toggle_rerenders_the_visible_table(monkeypatch):
    """Rows are formatted when the tree is built: the click must rebuild them."""
    if not (CATALOG_DIR / "it" / "LC_MESSAGES" / "tacho.mo").exists():
        pytest.skip("the Italian catalog is not built in this checkout")
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(CATALOG_DIR))
    # The window constructor reinstalls the *saved* language, so it must be
    # persisted before it is built (otherwise it comes back up in English).
    assert i18n.save_language("it")
    assert i18n.install("it") == "it"
    ui_text.configure_translate_data(False)

    window = _explorer(monkeypatch)
    label = i18n._("Calibration Data")

    def section_node():
        """The tree node whose payload is the calibration table."""
        for iid, payload in window._payloads.items():
            if isinstance(payload, tuple) and payload and payload[0] == label:
                return iid
        raise AssertionError(f"no node for {label!r}")

    def cells():
        tv = window.table.tv
        return [str(cell) for iid in tv.get_children("")
                for cell in tv.item(iid, "values")]

    try:
        window._parse_done(MOCK_CARD, "mock.ddd")
        window.update()
        window.tree.selection_set(section_node())
        window.update()

        assert any("Italy" in cell for cell in cells()), cells()
        assert not any("Italia" in cell for cell in cells()), cells()

        menu = window.nametowidget(window.btn_lang["menu"])
        menu.invoke(2)                      # the real checkbutton, a real click
        window.update()

        assert any("Italia" in cell for cell in cells()), cells()
        assert not any("Italy" in cell for cell in cells()), cells()
        assert window.table.title_lbl.cget("text") == label, "selection moved"
        assert window.tree.selection() == (section_node(),), "selection moved"
        assert i18n.saved_translate_data() is True

        # A decoder label in a table follows the same click, not only nations.
        events = i18n._("Events Data")
        window.tree.selection_set(next(
            iid for iid, payload in window._payloads.items()
            if isinstance(payload, tuple) and payload and payload[0] == events))
        window.update()
        translated = i18n._("Over speeding")
        assert translated != "Over speeding", "catalog is missing the event label"
        assert any(translated in cell for cell in cells()), cells()
        assert not any("Over speeding" in cell for cell in cells()), cells()

        menu.invoke(2)
        window.update()
        window.tree.selection_set(section_node())
        window.update()
        assert any("Italy" in cell for cell in cells()), cells()
        assert i18n.saved_translate_data() is False
    finally:
        for after_id in window.tk.call("after", "info"):
            window.tk.call("after", "cancel", after_id)
        window._on_close()
        ui_text.configure_translate_data(False)


def test_activity_label_follows_the_preference(monkeypatch):
    tkinter = pytest.importorskip("tkinter")
    try:
        probe = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display available")
    probe.destroy()

    import app.gui as gui

    if not (CATALOG_DIR / "it" / "LC_MESSAGES" / "tacho.mo").exists():
        pytest.skip("the Italian catalog is not built in this checkout")
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(CATALOG_DIR))
    assert i18n.install("it") == "it"

    ui_text.configure_translate_data(False)
    assert gui._act_label("DRIVE") == "Drive"
    ui_text.configure_translate_data(True)
    try:
        assert gui._act_label("DRIVE") == i18n._("Drive")
        assert gui._act_label("DRIVE") != "Drive"
    finally:
        ui_text.configure_translate_data(False)
