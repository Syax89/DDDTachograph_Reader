"""The top toolbar's controls are text-only (portability, not a redesign).

The Open/Export buttons used to carry a decorated glyph in front of their label
(``📂``/``📤``) and the Language button a globe (``🌐``). Those code points are
drawn by a *platform* font: where the fallback is missing the glyph renders as
an empty box or a blank gap of a few pixels, so the same build looks different
on Windows, macOS and Linux — and on a minimal Linux desktop the icon simply
disappears. The three controls now show plain text, and the empty-state Open
button repeats the top bar's label without the folder glyph.

What must *not* change is pinned here too: the Open button still runs
``_open_file``, Export is still a Menubutton that starts disabled and keeps its
four-format menu, and the Language button still names the language actually in
use in that language's own name.

Rendered against a real ``TachoExplorer`` window, which skips cleanly when there
is no display — the same pattern as the other GUI tests. No dialog and no export
is ever invoked: the message box is replaced by a stub that fails the test if
anything tries to open one.
"""
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app import i18n
from app.gui import TachoExplorer

#: The glyphs that used to decorate the controls; none may come back.
FOLDER, OUTBOX, GLOBE = "\U0001f4c2", "\U0001f4e4", "\U0001f310"
DECORATION = (FOLDER, OUTBOX, GLOBE)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _has_decoration(text):
    return any(glyph in text for glyph in DECORATION)


def _new_explorer(monkeypatch):
    """A real TachoExplorer, or a clean skip when there is no display."""
    tkinter = pytest.importorskip("tkinter")

    class NoDialogs:
        def __getattr__(self, name):
            return lambda *args, **kwargs: pytest.fail(
                f"unexpected dialog {name}{args!r}")

    monkeypatch.setattr("app.gui.messagebox", NoDialogs())
    try:
        return TachoExplorer()
    except tkinter.TclError:
        pytest.skip("no display available")


def _close(app):
    """Close a window the way the product does, cancelling every timer."""
    try:
        for after_id in app.tk.call("after", "info"):
            app.tk.call("after", "cancel", after_id)
    except tk.TclError:
        pass
    try:
        app.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def explorer(monkeypatch):
    app = _new_explorer(monkeypatch)
    try:
        yield app
    finally:
        _close(app)


def _empty_state_open_button(app):
    """The one open button inside the empty state's centred block."""
    centre = app.empty_state.winfo_children()[0]
    buttons = [child for child in centre.winfo_children()
               if child.winfo_class() == "TButton"]
    assert len(buttons) == 1, "the empty state has exactly one open button"
    return buttons[0]


# ── English (the msgid language) ──────────────────────────────────────────

def test_top_controls_show_plain_text(explorer):
    assert explorer.btn_open.cget("text") == i18n._("Open DDD file")
    assert explorer.btn_export.cget("text") == i18n._("Export")
    for text in (explorer.btn_open.cget("text"), explorer.btn_export.cget("text")):
        assert not _has_decoration(text), text


def test_empty_state_open_button_repeats_the_plain_label(explorer):
    """The same action, the same wording — and no second folder glyph."""
    button = _empty_state_open_button(explorer)
    assert button.cget("text") == i18n._("Open DDD file")
    assert not _has_decoration(button.cget("text"))


def test_no_toolbar_control_carries_a_decoration_glyph(explorer):
    """A sweep of the whole top bar, so the next glyph fails here too."""
    top = explorer.btn_open.master
    texts = [child.cget("text") for child in top.winfo_children()
             if "text" in child.keys()]
    assert texts, "the toolbar should have labelled children"
    assert not {text for text in texts if _has_decoration(text)}


def test_language_button_shows_only_the_native_name(explorer):
    assert explorer.btn_lang.cget("text") == i18n.LANGUAGES[explorer._language]
    assert explorer.btn_lang.cget("text") == "English"
    assert GLOBE not in explorer.btn_lang.cget("text")


# ── the same three controls in a translated language ──────────────────────

@pytest.mark.parametrize("code,native,open_text,export_text", [
    ("it", "Italiano", "Apri file DDD", "Esporta"),
    ("de", "Deutsch", "DDD-Datei öffnen", "Exportieren"),
])
def test_translated_controls_are_text_only(monkeypatch, code, native,
                                           open_text, export_text):
    """Proof the catalog fills the label — not an English literal."""
    if not (REPO_ROOT / "locale" / code / "LC_MESSAGES" / "tacho.mo").is_file():
        pytest.skip(f"'{code}' is not built in this checkout")
    assert i18n.save_language(code)
    assert i18n.install(code) == code

    app = _new_explorer(monkeypatch)
    try:
        assert app._language == code
        assert app.btn_open.cget("text") == open_text
        assert app.btn_export.cget("text") == export_text
        assert _empty_state_open_button(app).cget("text") == open_text
        assert app.btn_lang.cget("text") == native
        for text in (app.btn_open.cget("text"), app.btn_export.cget("text"),
                     app.btn_lang.cget("text")):
            assert not _has_decoration(text), text
    finally:
        _close(app)


# ── behaviour that must not have moved ────────────────────────────────────

def test_open_button_still_runs_the_open_file_command(explorer):
    assert str(explorer.btn_open.cget("command")).split("_", 1)[-1] == "open_file"


def test_export_still_starts_disabled_and_keeps_its_four_entries(explorer):
    assert str(explorer.btn_export.cget("state")) == "disabled"

    menu = explorer.nametowidget(explorer.btn_export["menu"])
    labels = [menu.entrycget(index, "label")
              for index in range(menu.index("end") + 1)]
    assert labels == [i18n._("PDF (.pdf)"), i18n._("Excel (.xlsx)"),
                      i18n._("CSV (.csv)"), i18n._("JSON (.json)")]
    assert [menu.type(index) for index in range(menu.index("end") + 1)] == \
        ["command"] * 4, "the split menu still opens a plain command list"


def test_toolbar_placement_is_unchanged(explorer):
    """Same sides as before: Open/Export left, Language right."""
    assert explorer.btn_open.pack_info()["side"] == tk.LEFT
    assert explorer.btn_export.pack_info()["side"] == tk.LEFT
    assert explorer.btn_lang.pack_info()["side"] == tk.RIGHT
