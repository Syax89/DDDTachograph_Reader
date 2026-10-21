"""The no-file empty state of the main window, and its recent-files list.

What the window shows *before* a file is opened is product surface, so it is
asserted on a real ``TachoExplorer`` (skipped cleanly when no display is
available, exactly like ``tests/unit/test_batch12_gui.py``):

* the right pane opens on the empty state instead of an empty table;
* its open action is the top bar's action, not a second implementation;
* "Recent files" lists the remembered files that still exist (bold name, muted
  directory), opens them through ``_start_parse`` and honours the ``_parsing``
  guard;
* a successful parse hides the empty state and *only* a successful parse is
  remembered; a failed first open brings the empty state back, a failed re-open
  keeps the previous file on screen.

``tests/unit/conftest.py`` pins the settings file to a per-test temporary path,
so no real history is read or written.
"""
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import app.gui as gui  # noqa: E402
import app.i18n as i18n  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "locale"

#: The smallest window the product allows.
MINIMUM_SIZE = "900x560"

#: Languages whose empty-state strings are markedly wider than English.
LONG_STRING_LANGUAGES = ("de", "fi", "nl", "bg", "hu", "el")

MINIMAL_DATA = {
    "metadata": {"generation": "G2 (Smart)"},
    "raw_tags": {},
    "generations": {},
}


def _stub_dialogs(monkeypatch):
    """Message boxes would block the test: record them instead."""

    class _Dialogs:
        calls: list = []

        def __getattr__(self, name):
            return lambda *args, **kwargs: _Dialogs.calls.append((name, args))

    monkeypatch.setattr(gui, "messagebox", _Dialogs())


def new_explorer(monkeypatch, **kwargs):
    """A real TachoExplorer (skipped when no display is available)."""
    tkinter = pytest.importorskip("tkinter")
    _stub_dialogs(monkeypatch)
    try:
        return gui.TachoExplorer(**kwargs)
    except tkinter.TclError:
        pytest.skip("no display available")


def close(app):
    """Close a window the way the product does, cancelling every timer."""
    try:
        for after_id in app.tk.call("after", "info"):
            app.tk.call("after", "cancel", after_id)
    except gui.tk.TclError:
        pass
    try:
        app.destroy()
    except gui.tk.TclError:
        pass


@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        close(app)


def _visible(widget):
    """Whether ``widget`` is currently managed (i.e. on screen)."""
    return bool(widget.winfo_manager())


def _recent_rows(app):
    return [(child, child.winfo_children())
            for child in app.recent_list.winfo_children()]


def _labels(widget):
    return [child.cget("text") for child in widget.winfo_children()
            if child.winfo_class() == "TLabel"]


def _centre(app):
    """The centred block inside the empty state (title, button, recent list)."""
    return app.empty_state.winfo_children()[0]


# ── the empty state itself ────────────────────────────────────────────────

def test_window_opens_on_the_empty_state(explorer):
    assert explorer.current_data is None
    assert _visible(explorer.empty_state)
    assert not _visible(explorer.table)
    assert not _visible(explorer.speed_chart)
    assert not _visible(explorer.activity_chart)


def test_empty_state_text_is_translated(explorer):
    texts = _labels(_centre(explorer))
    assert i18n._("Open a DDD file") in texts


def test_empty_state_open_button_runs_the_top_bar_action(explorer, monkeypatch):
    """One implementation: the button runs ``_open_file``, not a copy of it."""
    monkeypatch.setattr(gui.filedialog, "askopenfilename",
                        lambda **_kwargs: "/data/picked.ddd")
    opened = []
    monkeypatch.setattr(explorer, "_start_parse", opened.append)

    buttons = [child for child in _centre(explorer).winfo_children()
               if child.winfo_class() == "TButton"]
    assert len(buttons) == 1
    buttons[0].invoke()

    # ``_open_file`` starts the parse 150 ms *after* the picker returned (never inside the
    # native panel's call stack, see docs/developer/testing.md), so pump the loop for it.
    deadline = time.monotonic() + 5
    while not opened and time.monotonic() < deadline:
        explorer.update()
        time.sleep(0.01)
    assert opened == ["/data/picked.ddd"]
    # Both buttons are Tkinter registrations of the *same* handler.
    assert str(buttons[0].cget("command")).split("_", 1)[-1] == "open_file"
    assert str(explorer.btn_open.cget("command")).split("_", 1)[-1] == "open_file"


def test_no_recent_section_without_history(explorer):
    assert i18n.saved_recent_files() == []
    assert not _visible(explorer.recent_section)


# ── recent files ──────────────────────────────────────────────────────────

def test_recent_files_show_name_and_directory(explorer, tmp_path):
    first = tmp_path / "download-1.ddd"
    second = tmp_path / "download-2.ddd"
    for path in (first, second):
        path.write_bytes(b"\x00")
    assert i18n.add_recent_file(str(first))
    assert i18n.add_recent_file(str(second))

    explorer._refresh_recent_files()

    assert _visible(explorer.recent_section)
    rows = _recent_rows(explorer)
    assert len(rows) == 2
    # Most recent first; bold name then muted directory.
    assert _labels(rows[0][0]) == [second.name, str(tmp_path)]
    assert _labels(rows[1][0]) == [first.name, str(tmp_path)]


def test_missing_files_are_hidden_but_not_forgotten(explorer, tmp_path):
    present = tmp_path / "here.ddd"
    present.write_bytes(b"\x00")
    gone = tmp_path / "gone.ddd"
    assert i18n.add_recent_file(str(present))
    assert i18n.add_recent_file(str(gone))

    explorer._refresh_recent_files()

    assert len(_recent_rows(explorer)) == 1
    assert _labels(_recent_rows(explorer)[0][0])[0] == present.name
    assert str(gone) in i18n.saved_recent_files()


def test_clicking_a_recent_file_opens_it_through_start_parse(explorer, tmp_path,
                                                             monkeypatch):
    target = tmp_path / "clicked.ddd"
    target.write_bytes(b"\x00")
    assert i18n.add_recent_file(str(target))
    explorer._refresh_recent_files()

    opened = []
    monkeypatch.setattr(explorer, "_start_parse", opened.append)
    row, children = _recent_rows(explorer)[0]
    for widget in [row, *children]:
        widget.event_generate("<Button-1>")

    assert opened == [str(target)] * 3


def test_a_running_parse_blocks_a_recent_file_click(explorer, tmp_path, monkeypatch):
    target = tmp_path / "busy.ddd"
    target.write_bytes(b"\x00")
    assert i18n.add_recent_file(str(target))
    explorer._refresh_recent_files()

    opened = []
    monkeypatch.setattr(explorer, "_start_parse", opened.append)
    explorer._parsing = True
    row, children = _recent_rows(explorer)[0]
    for widget in [row, *children]:
        widget.event_generate("<Button-1>")

    assert opened == []


# ── load / fail transitions ───────────────────────────────────────────────

def test_successful_parse_hides_the_empty_state_and_is_remembered(
        explorer, tmp_path):
    path = tmp_path / "loaded.ddd"
    path.write_bytes(b"\x00")

    explorer._parse_done(MINIMAL_DATA, str(path))
    explorer.update()

    assert not _visible(explorer.empty_state)
    assert _visible(explorer.table)
    assert i18n.saved_recent_files() == [str(path)]


def test_failed_first_open_keeps_the_empty_state(explorer, tmp_path):
    path = tmp_path / "broken.ddd"
    path.write_bytes(b"\x00")

    explorer._parse_error("boom")

    assert explorer.current_data is None
    assert _visible(explorer.empty_state)
    assert i18n.saved_recent_files() == [], "a failure must not be remembered"
    explorer._refresh_recent_files()
    assert not _visible(explorer.recent_section)


def test_failed_reopen_keeps_the_previous_file_on_screen(explorer, tmp_path):
    good = tmp_path / "good.ddd"
    good.write_bytes(b"\x00")
    explorer._parse_done(MINIMAL_DATA, str(good))
    explorer.update()
    assert not _visible(explorer.empty_state)

    explorer._parse_error("boom")

    assert explorer.current_data, "the previous file stays displayed and exportable"
    assert not _visible(explorer.empty_state)
    assert i18n.saved_recent_files() == [str(good)]


def test_restart_with_a_file_argument_records_it(monkeypatch, tmp_path):
    """The command-line path goes through ``_start_parse`` like any other."""
    path = tmp_path / "argument.ddd"
    path.write_bytes(b"\x00")

    app = new_explorer(monkeypatch, initial_file=str(path))
    try:
        assert _visible(app.empty_state), "nothing is loaded until the parse ends"
        app._parse_done(MINIMAL_DATA, str(path))
        app.update()
        assert i18n.saved_recent_files() == [os.path.abspath(str(path))]
    finally:
        close(app)


# ── minimum window, long translations ────────────────────────────────────

@pytest.mark.parametrize("code", LONG_STRING_LANGUAGES)
def test_long_translations_wrap_inside_the_minimum_window(monkeypatch, tmp_path,
                                                          code):
    """Translations and long paths must fit the smallest supported window."""
    catalog = CATALOG_DIR / code / "LC_MESSAGES" / "tacho.mo"
    if not catalog.exists():
        pytest.skip(f"catalog {code!r} is not built in this checkout")
    assert i18n.save_language(code), code

    deep = tmp_path / "vehicle-unit" / "2026" / "01" / "downloads"
    deep.mkdir(parents=True)
    long_name = "download-2026-01-01-" + "driver-name-" * 4 + "long.ddd"
    target = deep / long_name
    target.write_bytes(b"\x00")
    assert i18n.add_recent_file(str(target))

    app = new_explorer(monkeypatch)
    try:
        app.geometry(MINIMUM_SIZE)
        app.update()
        pane = app.empty_state.master
        title = app._wrap_labels[0]
        rows = [child for row in app.recent_list.winfo_children()
                for child in row.winfo_children()]

        assert title.cget("text") == i18n._("Open a DDD file")
        assert title.cget("text") != "Open a DDD file", "that is not the catalog"
        assert rows, "the recent file must be listed"
        for widget in [title, *rows]:
            assert widget.winfo_reqwidth() <= pane.winfo_width(), widget.cget("text")
            assert int(widget.cget("wraplength")) <= pane.winfo_width()
    finally:
        close(app)
