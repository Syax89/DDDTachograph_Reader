"""Dropping a ``.ddd`` file onto the main window (optional ``tkinterdnd2``).

Two layers are asserted separately:

* :func:`app.gui.dropped_paths` — the only place that interprets a dropped
  payload. It is pure (Tcl list splitting + an existence predicate), so it is
  tested with no Tk and no display at all, which is what the Windows paths and
  the garbage inputs need;
* the window glue — that the root really registers as a ``DND_FILES`` drop
  target when the package is available, that a drop reaches ``_start_parse``
  exactly like the file dialog does, and that a missing package *or* a tkdnd
  that cannot load is a silent no-op (the window still opens, with no hint).

``tests/unit/conftest.py`` pins the settings file to a per-test temporary path,
so no real history is read or written.

What is *not* exercised here: a real OS-level drop (a file dragged out of a file
manager). ``xdotool``/python-xlib are not available, so :func:`_drop` replays
exactly what tkdnd does with the <<Drop>> binding instead of synthesising an
XDND session.
"""
import sys
import types
from pathlib import Path

import pytest

import app.gui as gui
import app.i18n as i18n

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── the pure helper (no Tk, no display) ────────────────────────────────────

def test_plain_paths_are_returned_in_drop_order(tmp_path):
    first = tmp_path / "first.ddd"
    second = tmp_path / "second.ddd"
    for path in (first, second):
        path.write_bytes(b"\x00")

    assert gui.dropped_paths(f"{first} {second}") == [str(first), str(second)]
    assert gui.dropped_paths(f"{second} {first}") == [str(second), str(first)]


def test_a_braced_path_with_spaces_stays_one_path(tmp_path):
    """``{/a b/c.ddd}`` is one path, not two: only a Tcl splitter knows that."""
    spaced = tmp_path / "my download 2026.ddd"
    spaced.write_bytes(b"\x00")

    payload = "{%s}" % spaced
    assert gui.dropped_paths(payload) == [str(spaced)]
    # What a naive split would have produced, i.e. why the helper exists.
    assert len(payload.split()) > 1


def test_missing_files_are_dropped(tmp_path):
    present = tmp_path / "here.ddd"
    present.write_bytes(b"\x00")
    gone = tmp_path / "gone.ddd"

    assert gui.dropped_paths(f"{gone} {present}") == [str(present)]
    assert gui.dropped_paths(str(gone)) == []


def test_directories_are_not_files(tmp_path):
    """A folder is not something to parse: it is skipped, not opened."""
    folder = tmp_path / "downloads"
    folder.mkdir()

    assert gui.dropped_paths(str(folder)) == []
    assert gui.dropped_paths("{%s}" % folder) == []


@pytest.mark.parametrize("payload", ["", " ", "   \t\n ", "{}", "{} {}"])
def test_an_empty_payload_opens_nothing(payload):
    assert gui.dropped_paths(payload) == []


@pytest.mark.parametrize("payload", [None, 42, 3.5, b"/tmp/x.ddd", ["/tmp/x.ddd"],
                                     {"path": "/tmp/x.ddd"}, object()])
def test_a_non_string_payload_is_not_a_drop(payload):
    assert gui.dropped_paths(payload) == []


@pytest.mark.parametrize("payload", ["{", "}", "'/a b/c.ddd", "a\x00b"])
def test_a_malformed_payload_never_raises(payload):
    assert gui.dropped_paths(payload) == []


def test_windows_style_paths_are_parsed_by_tcl_rules():
    """Drive letters, spaces, backslashes and UNC names survive the split.

    No such file exists on a Linux test host, so the existence predicate is
    injected: what is asserted here is the *parsing*, not the disk.
    """
    payload = ("{C:/x y/z.ddd} C:/plain/z.ddd "
               r"{{C:\Program Files\tacho\x y.ddd}} "
               r"{\\server\share\my file.ddd}")

    assert gui.dropped_paths(payload, isfile=lambda path: True) == [
        "C:/x y/z.ddd",
        "C:/plain/z.ddd",
        "{C:\\Program Files\\tacho\\x y.ddd}",  # doubly braced: braces are data
        "\\\\server\\share\\my file.ddd",
    ]
    assert gui.dropped_paths(payload) == [], "none of them exists on this host"


def test_a_symlink_to_a_file_counts_as_a_file(tmp_path):
    target = tmp_path / "real.ddd"
    target.write_bytes(b"\x00")
    link = tmp_path / "link.ddd"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    assert gui.dropped_paths(f"{target} {link}") == [str(target), str(link)]


def test_the_splitter_can_be_injected(tmp_path):
    """The window passes ``self.tk.splitlist``; nothing else is asked of it."""
    seen = []

    def split(data):
        seen.append(data)
        return ("/injected/x.ddd",)

    assert gui.dropped_paths("/injected/x.ddd", split=split,
                             isfile=lambda path: path.startswith("/injected/"),
                             ) == ["/injected/x.ddd"]
    assert seen == ["/injected/x.ddd"]


def test_the_helper_uses_a_display_less_tcl_splitter(tmp_path):
    """It must work in a process that never opened a window (CLI, batch)."""
    spaced = tmp_path / "no display needed.ddd"
    spaced.write_bytes(b"\x00")

    assert gui._drop_splitter()("{a b} c") == ("a b", "c")
    assert gui.dropped_paths("{%s}" % spaced) == [str(spaced)]


# ── the window (needs a display, like tests/unit/test_empty_state.py) ──────

def _stub_dialogs(monkeypatch):
    """Message boxes would block the test: record them instead."""

    class _Dialogs:
        calls: list = []

        def __getattr__(self, name):
            return lambda *args, **kwargs: _Dialogs.calls.append((name, args))

    monkeypatch.setattr(gui, "messagebox", _Dialogs())


def _new_window(monkeypatch):
    """A real TachoExplorer, skipped when no display is available."""
    tkinter = pytest.importorskip("tkinter")
    _stub_dialogs(monkeypatch)
    try:
        return gui.TachoExplorer()
    except tkinter.TclError:
        pytest.skip("no display available")


def _close(window):
    """Close a window the way the product does, cancelling every timer."""
    try:
        for after_id in window.tk.call("after", "info"):
            window.tk.call("after", "cancel", after_id)
    except gui.tk.TclError:
        pass
    try:
        window.destroy()
    except gui.tk.TclError:
        pass


def _payload(*paths):
    """The payload tkdnd produces for these paths: a Tcl list, braces if needed."""
    return " ".join("{%s}" % path for path in paths)


def _drop(window, payload):
    """Deliver a ``<<Drop>>`` the way tkdnd does — and return its action.

    tkdnd quotes ``%D`` as one Tcl word before evaluating the bound script
    (``tkdnd_generic.tcl``: ``%D   [list $data]``, checked on tkdnd 2.10.3);
    ``event_generate`` cannot reproduce that, it carries no ``%D``. Replaying
    the two steps exercises the real binding, not just the handler behind it —
    though it does assume that one-word substitution, which only a live drop
    from a file manager could confirm.
    """
    script = str(window.tk.call("bind", window._w, "<<Drop>>"))
    assert "%D" in script, "the window is not bound to <<Drop>>"
    return window.tk.call("uplevel", "#0", script.replace("%D", "{%s}" % payload))


def _drop_target_types(window):
    """The types tkdnd has registered for this window (its own bookkeeping)."""
    return window.tk.call("bind", window._w, "<<DropTargetTypes>>")


@pytest.fixture
def explorer(monkeypatch):
    pytest.importorskip("tkinterdnd2")
    window = _new_window(monkeypatch)
    try:
        yield window
    finally:
        _close(window)


def test_the_window_registers_as_a_file_drop_target(explorer):
    assert explorer._dnd_enabled
    # tkdnd records the accepted types as the <<DropTargetTypes>> binding; the
    # platform-independent DND_Files is mapped per OS (text/uri-list on X11).
    assert _drop_target_types(explorer), "the root is not a registered drop target"
    assert "%D" in str(explorer.tk.call("bind", explorer._w, "<<Drop>>"))
    # ... and the package really is loaded in this interpreter.
    assert explorer.tk.call("package", "present", "tkdnd")


def test_the_empty_state_advertises_dropping_only_when_it_works(explorer):
    hint = explorer.drop_hint
    assert hint is not None
    assert hint.cget("text") == i18n._("or drop it here")
    assert str(hint.cget("foreground")) == gui.MUTED
    assert int(hint.cget("wraplength")) > 0
    assert hint in explorer._wrap_labels, "the hint must re-wrap with the rest"


def test_the_hint_follows_the_ui_language(monkeypatch):
    """It is a normal ``_()`` string, so the catalogs translate it too."""
    pytest.importorskip("tkinterdnd2")
    if not (REPO_ROOT / "locale" / "it" / "LC_MESSAGES" / "tacho.mo").is_file():
        pytest.skip("'it' is not built in this checkout")
    assert i18n.save_language("it")
    assert i18n.install("it") == "it"

    window = _new_window(monkeypatch)
    try:
        assert window.drop_hint.cget("text") == "oppure trascina qui il file"
    finally:
        _close(window)


def test_a_dropped_file_is_opened_through_start_parse(explorer, tmp_path):
    target = tmp_path / "dropped with space.ddd"
    target.write_bytes(b"\x00")
    opened = []
    explorer._start_parse = opened.append

    assert _drop(explorer, _payload(str(target))) == "copy"

    assert opened == [str(target)]


def test_several_dropped_files_open_the_first_and_say_so(explorer, tmp_path):
    first = tmp_path / "first.ddd"
    second = tmp_path / "second.ddd"
    for path in (first, second):
        path.write_bytes(b"\x00")
    opened = []
    explorer._start_parse = opened.append

    _drop(explorer, _payload(str(first), str(second)))

    assert opened == [str(first)]
    assert explorer.status.cget("text") == i18n._(
        "Several files dropped \u2014 opened the first one")


def test_a_drop_is_ignored_while_a_parse_is_running(explorer, tmp_path):
    """The same guard as the file dialog: one parse at a time."""
    target = tmp_path / "busy.ddd"
    target.write_bytes(b"\x00")
    opened = []
    explorer._start_parse = opened.append
    explorer._parsing = True

    assert _drop(explorer, _payload(str(target))) == "copy"
    assert opened == []


def test_a_dropped_directory_opens_nothing_and_says_so(explorer, tmp_path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    opened = []
    explorer._start_parse = opened.append

    _drop(explorer, _payload(str(folder)))

    assert opened == []
    assert explorer.status.cget("text") == i18n._("Nothing to open in that drop")


def test_a_missing_file_opens_nothing_and_says_so(explorer, tmp_path):
    opened = []
    explorer._start_parse = opened.append

    _drop(explorer, _payload(str(tmp_path / "vanished.ddd")))

    assert opened == []
    assert explorer.status.cget("text") == i18n._("Nothing to open in that drop")


def test_a_payload_that_arrives_as_several_words_is_rejoined(explorer, tmp_path):
    """Defensive: tkdnd passes %D as one word, but a build that split it must
    not lose the drop to a Tcl argument-count error."""
    first = tmp_path / "first.ddd"
    second = tmp_path / "second.ddd"
    for path in (first, second):
        path.write_bytes(b"\x00")
    opened = []
    explorer._start_parse = opened.append

    # Through the registered Tcl command, i.e. the way an event would call it —
    # with two arguments instead of one.
    assert explorer.tk.call(explorer._drop_command,
                            str(first), str(second)) == "copy"

    assert opened == [str(first)]


def test_the_extension_is_not_restricted(explorer, tmp_path):
    """The picker offers "All Files" too: a drop is judged by its contents."""
    odd = tmp_path / "download.tacho"
    odd.write_bytes(b"\x00")
    opened = []
    explorer._start_parse = opened.append

    _drop(explorer, _payload(str(odd)))

    assert opened == [str(odd)]


def test_a_missing_package_leaves_a_working_window_without_the_hint(monkeypatch):
    """The import fails: no drop target, no hint, everything else unchanged."""
    monkeypatch.setitem(sys.modules, "tkinterdnd2", None)
    window = _new_window(monkeypatch)
    try:
        window.update()
        assert window._dnd_enabled is False
        assert window.drop_hint is None
        assert _drop_target_types(window) == ""
        labels = [child.cget("text")
                  for child in window.empty_state.winfo_children()[0].winfo_children()
                  if child.winfo_class() == "TLabel"]
        assert i18n._("Open a DDD file") in labels
        assert i18n._("or drop it here") not in labels
        # The rest of the window is fully functional.
        assert window.status.cget("text") == i18n._("Ready \u2014 open a .ddd file")
        assert window.winfo_exists()
    finally:
        _close(window)


def test_a_tkdnd_that_cannot_load_is_also_silent(monkeypatch):
    """Installed but unusable (wrong platform/Tcl build): a no-op, never a crash."""
    broken = types.ModuleType("tkinterdnd2")

    class _TkinterDnD:
        @staticmethod
        def _require(_root):
            raise RuntimeError("Unable to load tkdnd library.")

    broken.TkinterDnD = _TkinterDnD
    broken.DND_FILES = "DND_Files"
    monkeypatch.setitem(sys.modules, "tkinterdnd2", broken)

    window = _new_window(monkeypatch)
    try:
        assert window._dnd_enabled is False
        assert window.drop_hint is None
        assert _drop_target_types(window) == ""
        assert window.winfo_exists()
    finally:
        _close(window)
