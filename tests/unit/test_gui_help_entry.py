"""Reaching Help: a native macOS Help menu, a toolbar button elsewhere.

The owner asked for Help "using the OS-native facilities where they exist": on
macOS the menu bar already exists, so Help belongs in it (and a menubar makes it
a real menu with macOS's own search field), while Windows and Linux have no
menubar in this app and get one small Help button at the end of the toolbar.

One rule shapes the implementation and is pinned here: *one* place holds the
addresses and the About text (:func:`app.gui.help_links`, :func:`app.gui.about_text`),
so the macOS menu and the Windows/Linux dialog can never disagree. The donation
link is the one the project already uses (`README.md`, "buy me a coffee"), not an
invented one.

Rendered against a real ``TachoExplorer`` (skipped cleanly with no display).
``sys.platform`` is monkeypatched for the macOS path: Tk on X11 does not *draw*
the Aqua menu bar, so what is asserted there is the structure Aqua keys on — a
menubar, a menu whose Tk name is ``help``, and the ``tk::mac::standardAboutPanel``
hook. Real Aqua rendering of that bar cannot be verified here.
"""
import sys

import pytest

pytest.importorskip("tkinter")

import tkinter as tk  # noqa: E402

import app.gui as gui  # noqa: E402
from core.utils.version import APP_NAME, __version__  # noqa: E402
from tests.unit.test_empty_state import close, new_explorer  # noqa: E402

GITHUB = "https://github.com/Syax89/DDDTachograph_Reader"
ISSUES = GITHUB + "/issues"
RELEASES = GITHUB + "/releases"
COFFEE = "https://buymeacoffee.com/syax89"


@pytest.fixture
def linux(monkeypatch):
    """The platform of every non-macOS test: no LaunchServices here."""
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.fixture
def launcher(monkeypatch):
    """``subprocess.Popen`` recorded, never launched."""
    spawned = []

    def _popen(args, **kwargs):
        spawned.append((args, kwargs))
        return None

    monkeypatch.setattr(gui.subprocess, "Popen", _popen)
    return spawned


@pytest.fixture
def links(monkeypatch):
    """``webbrowser.open`` recorded, never launched."""
    opened = []
    monkeypatch.setattr(gui.webbrowser, "open", lambda url: opened.append(url))
    return opened


@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        gui.HelpWindow._open_window = None
        close(app)


@pytest.fixture
def macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


# ── the one list both entry points use ─────────────────────────────────────

def test_the_link_list_is_the_project_addresses():
    labels = [label for label, _url in gui.help_links()]

    assert [url for _label, url in gui.help_links()] == [
        GITHUB, ISSUES, RELEASES, COFFEE]
    # the labels are msgids: translated at call time, never pre-baked
    assert labels == [gui._("DDD Reader on GitHub"), gui._("Report an issue"),
                      gui._("Releases"), gui._("Buy me a coffee")]


def test_the_donation_link_is_the_one_the_project_already_uses():
    """It is in README.md ("buy me a coffee"); the app must not invent one."""
    from pathlib import Path

    readme = (Path(gui.__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8")
    assert COFFEE in readme
    assert dict(gui.help_links())[gui._("Buy me a coffee")] == COFFEE


def test_the_about_text_carries_name_version_licence_and_credits():
    text = gui.about_text()

    assert APP_NAME in text
    assert __version__ in text
    assert "MIT" in text
    assert "Commission Regulation" in text, "credits the specifications"


def test_a_link_is_opened_through_webbrowser(linux, links):
    gui.open_url(ISSUES)

    assert links == [ISSUES]


# ── macOS: LaunchServices, not the osascript helper ───────────────────────

def test_macos_opens_a_link_with_usr_bin_open(macos, launcher, links):
    """The owner's Dock icon: ``webbrowser`` spawns osascript inside the bundle."""
    gui.open_url(ISSUES)

    assert launcher == [([gui._MACOS_OPEN, ISSUES],
                         {"stdout": gui.subprocess.DEVNULL,
                          "stderr": gui.subprocess.DEVNULL,
                          "close_fds": True})]
    assert links == [], "macOS must not go through webbrowser (extra Dock icon)"


def test_every_help_link_goes_through_usr_bin_open(macos, launcher, links):
    for _label, url in gui.help_links():
        gui.open_url(url)

    assert [args for args, _kwargs in launcher] == [
        [gui._MACOS_OPEN, url] for _label, url in gui.help_links()]
    assert links == []


def test_macos_falls_back_to_webbrowser_when_open_is_missing(
        macos, links, monkeypatch):
    def _missing(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", gui._MACOS_OPEN)

    monkeypatch.setattr(gui.subprocess, "Popen", _missing)
    gui.open_url(RELEASES)

    assert links == [RELEASES]


def test_macos_falls_back_to_webbrowser_on_an_oserror(
        macos, links, monkeypatch):
    def _broken(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(gui.subprocess, "Popen", _broken)
    gui.open_url(COFFEE)

    assert links == [COFFEE]


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "javascript:alert(1)",
    "mailto:someone@example.com",
    "",
])
def test_only_web_addresses_reach_the_system_opener(macos, launcher, links, url):
    """Only ``help_links()`` addresses are opened: nothing else may be launched."""
    with pytest.raises(ValueError):
        gui.open_url(url)

    assert launcher == [] and links == []


# ── macOS: a real menubar with a native Help menu ──────────────────────────

def test_macos_installs_a_menubar_with_a_menu_named_help(macos, monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        menubar = app.nametowidget(app.cget("menu"))
        assert isinstance(menubar, tk.Menu)
        # Aqua only treats a menu as the native Help menu when its Tk name is
        # `help` (i.e. the widget path ends in `.help`).
        help_menu = app.nametowidget(str(menubar) + ".help")
        assert isinstance(help_menu, tk.Menu)
        labels = [help_menu.entrycget(index, "label")
                  for index in range(help_menu.index("end") + 1)]
        assert labels == [label for label, _url in gui.help_links()]
    finally:
        close(app)


def test_the_macos_help_entries_open_their_urls(macos, monkeypatch, launcher):
    app = new_explorer(monkeypatch)
    try:
        menubar = app.nametowidget(app.cget("menu"))
        help_menu = app.nametowidget(str(menubar) + ".help")
        for index in range(help_menu.index("end") + 1):
            help_menu.invoke(index)
    finally:
        close(app)

    assert [args for args, _kwargs in launcher] == [
        [gui._MACOS_OPEN, url] for _label, url in gui.help_links()]


def test_macos_hooks_about_into_the_aqua_panel(macos, monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        # `createcommand` publishes a Tcl command under exactly this name; it is
        # what Tk 8.6's own "About <app>" item calls on Aqua.
        assert app.tk.call("info", "commands", "tk::mac::standardAboutPanel")
    finally:
        close(app)


def test_macos_adds_no_toolbar_help_button(macos, monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        assert app.btn_help is None
    finally:
        close(app)


def test_no_menubar_outside_macos(windows, monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        assert not app.cget("menu")
    finally:
        close(app)


# ── Windows / Linux: one Help button at the end of the toolbar ─────────────

def test_the_toolbar_help_button_exists_and_opens_the_dialog(windows, monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        assert app.btn_help is not None
        assert app.btn_help.cget("text") == gui._("Help")
        assert str(app.btn_help.pack_info()["side"]) == "right"
        # it is the last control of the bar: the right-most of all RIGHT-packed
        # siblings, ahead of the language button
        rights = [child for child in app.btn_help.master.pack_slaves()
                  if str(child.pack_info()["side"]) == "right"]
        assert rights[0] is app.btn_help
        app.btn_help.invoke()
        app.update()
        assert gui.HelpWindow._open_window is not None
    finally:
        close(app)


# ── the dialog itself: same data, every link clickable ────────────────────

def test_the_help_dialog_shows_the_about_text_and_one_button_per_link(
        explorer, links):
    window = gui.show_help(explorer)
    try:
        text = window.about_label.cget("text")
        assert APP_NAME in text and __version__ in text and "MIT" in text
        assert [button.cget("text") for button in window.link_buttons] == [
            label for label, _url in gui.help_links()]
        window.link_buttons[1].invoke()
        assert links == [ISSUES]
    finally:
        window.destroy()


def test_only_one_help_window_is_ever_open(explorer):
    first = gui.show_help(explorer)
    second = gui.show_help(explorer)
    try:
        assert second is first
    finally:
        gui.HelpWindow._open_window = None
        first.destroy()


def test_the_help_dialog_is_built_from_the_shared_data(explorer, monkeypatch):
    """No second copy of the addresses: the dialog asks ``help_links``."""
    monkeypatch.setattr(gui, "help_links", lambda: ((gui._("Releases"), RELEASES),))
    window = gui.show_help(explorer)
    try:
        assert [button.cget("text") for button in window.link_buttons] == [
            gui._("Releases")]
    finally:
        window.destroy()


def test_help_labels_are_translated_with_the_ui():
    """The Help chrome follows the language, like every other control."""
    import app.i18n as i18n

    assert i18n.install("it") == "it"
    try:
        assert gui._("Help") == "Aiuto"
        assert gui._("Report an issue") != "Report an issue"
    finally:
        i18n.install(i18n.DEFAULT_LANGUAGE)
