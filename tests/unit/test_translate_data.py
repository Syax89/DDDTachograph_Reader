"""The "translate file contents" preference (off by default).

Two kinds of text share the window: the application's own chrome, which is
always translated, and labels *decoded from the tachograph file* — an activity
name, a nation, a record-code name. The preference decides the second kind only:
off keeps them exactly as the file/decoder names them, on translates them too.
"""
import json
from pathlib import Path

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


# ── the window ─────────────────────────────────────────────────────────────

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
