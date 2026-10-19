"""UI localization (issue #13): language list, settings, catalogs, GUI switch.

The catalogs themselves (``locale/<code>/LC_MESSAGES/tacho.po``) are contributed
separately, so nothing here requires them: the tooling, the fallback behaviour
and the GUI language switch are exercised against synthetic catalogs, and the
real ones are checked extra-hard *when present* (parametrized, skipped
otherwise). The public msgid list is derived from ``app/gui.py`` itself, never
from a scratch file, so these tests are self-contained in a fresh checkout.
"""
import ast
import gettext
import importlib.util
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

import app.i18n as i18n

#: The real implementation, captured before the per-test fixture replaces
#: ``settings_path`` so no test ever reads or writes the user's settings file.
REAL_SETTINGS_PATH = i18n.settings_path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUI_PATH = REPO_ROOT / "app" / "gui.py"
COMPILER_PATH = REPO_ROOT / "scripts" / "compile_translations.py"
CATALOG_DIR = REPO_ROOT / "locale"

#: msgids that reach ``_()`` through a variable rather than a literal. They are
#: listed explicitly (and cross-checked below) because no AST scan can see them.
DYNAMIC_MSGIDS = frozenset({
    "Slot 1",
    "Slot 2",
    "Cardholder",
    "Generation 1",
    "Generation 2",
    "Generation 2.2",
    "GNSS Authentication (0x960F)",
    "Load/Unload Authentication (0x6399)",
})

#: Chrome strings every catalog must actually translate (a catalog that copies
#: English into msgstr is valid per entry, but would not be a translation).
CHROME_MSGIDS = (
    "Ready — open a .ddd file",
    "Language",
    "Drive",
    "Events",
    "No file loaded",
    "Export failed",
)


# ── helpers ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def compiler():
    """Import ``scripts/compile_translations.py`` (not an importable package)."""
    spec = importlib.util.spec_from_file_location("compile_translations", COMPILER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _activity_labels():
    """Return the values of the module-level ACTIVITY_LABEL dict in gui.py."""
    tree = ast.parse(GUI_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ACTIVITY_LABEL" for t in node.targets):
            return {value.value for value in node.value.values}
    raise AssertionError("ACTIVITY_LABEL not found in app/gui.py")


def _literal_msgids():
    """Every ``_("literal")`` msgid in gui.py."""
    tree = ast.parse(GUI_PATH.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_" and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


def _all_msgids():
    """Every msgid the GUI can ask for: literals plus the dynamic ones."""
    return _literal_msgids() | _activity_labels() | DYNAMIC_MSGIDS


#: Every language the app offers needs a catalog; English is the msgid language.
EXPECTED_CATALOG_CODES = tuple(code for code in i18n.LANGUAGES if code != "en")


def _catalog_codes(suffix):
    """Languages that actually ship ``locale/<code>/LC_MESSAGES/tacho.<suffix>``."""
    if not CATALOG_DIR.is_dir():
        return set()
    return {path.parent.parent.name for path in CATALOG_DIR.glob(f"*/LC_MESSAGES/tacho.{suffix}")}


def _write_po(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path



# ── language table ─────────────────────────────────────────────────────────

def test_language_table_is_the_agreed_scope():
    """34 choices, English first, native names, ISO-639 codes."""
    assert i18n.DEFAULT_LANGUAGE == "en"
    assert i18n.LANGUAGES["en"] == "English"
    assert len(i18n.LANGUAGES) == 34
    assert list(i18n.LANGUAGES)[0] == "en"
    for code, name in i18n.LANGUAGES.items():
        assert re.fullmatch(r"[a-z]{2}", code), code
        assert name.strip() == name and name, code
    # Native names: the ones with a non-Latin script keep it, and no other
    # language pretends to be English.
    for code in ("ru", "uk", "bg", "el", "sr", "mk", "be"):
        assert any(ord(ch) > 127 for ch in i18n.LANGUAGES[code]), code
    assert [c for c, n in i18n.LANGUAGES.items() if n == "English"] == ["en"]


def test_language_scope_is_exactly_the_agreed_set():
    """24 EU languages plus Norwegian, Icelandic, Russian, Ukrainian,
    Belarusian, Turkish, Serbian, Bosnian, Albanian, Macedonian — 34 with English."""
    assert set(i18n.LANGUAGES) == {
        "en", "bg", "cs", "da", "de", "el", "es", "et", "fi", "fr", "ga", "hr",
        "hu", "it", "lt", "lv", "mt", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
        "nb", "is", "ru", "uk", "be", "tr", "sr", "bs", "sq", "mk",
    }
    assert EXPECTED_CATALOG_CODES == tuple(
        code for code in i18n.LANGUAGES if code != "en")
    assert len(EXPECTED_CATALOG_CODES) == 33


# ── settings file ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("platform,env", [
    ("win32", {"APPDATA": "appdata"}),
    ("darwin", {"HOME": "home"}),
    ("linux", {"XDG_CONFIG_HOME": "config"}),
])
def test_settings_path_uses_the_platform_convention(monkeypatch, tmp_path, platform, env):
    for key, directory in env.items():
        monkeypatch.setenv(key, str(tmp_path / directory))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys, "platform", platform)

    path = Path(REAL_SETTINGS_PATH())

    if platform == "win32":
        assert path == tmp_path / "appdata" / "TachoReader" / "settings.json"
    elif platform == "darwin":
        assert path == tmp_path / "home" / "Library" / "Application Support" / \
            "TachoReader" / "settings.json"
    else:
        assert path == tmp_path / "config" / "TachoReader" / "settings.json"
    assert path.name == "settings.json"


@pytest.mark.parametrize("payload", [
    "[]", "{}", "null", "1", '"it"', "[1, 2]", "not json at all", "",
    '{"language": []}', '{"language": {}}', '{"language": 1}',
    '{"language": null}', '{"language": true}', '{"language": ["it"]}',
    '{"language": "xx"}', '{"language": ""}',
])
def test_corrupt_or_unknown_settings_fall_back_to_english(payload):
    """The file is user-editable: anything but a supported code means English."""
    path = Path(i18n.settings_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")

    assert i18n.saved_language() == "en"


def test_saved_language_is_honoured():
    assert i18n.save_language("it")
    assert i18n.saved_language() == "it"


def test_save_language_preserves_unrelated_settings():
    path = Path(i18n.settings_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"window": {"w": 1280}, "language": "it"}),
                    encoding="utf-8")

    assert i18n.save_language("de")

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "window": {"w": 1280}, "language": "de"}


@pytest.mark.parametrize("code", ["xx", "", "EN", None, 1, ["it"], {"it": 1}])
def test_save_language_rejects_anything_but_a_supported_code(code):
    assert i18n.save_language(code) is False
    assert i18n.saved_language() == "en"


def test_failed_write_keeps_the_previous_settings(monkeypatch):
    path = Path(i18n.settings_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    original = {"language": "it", "window": {"w": 800}}
    path.write_text(json.dumps(original), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    assert i18n.save_language("de") is False
    assert json.loads(path.read_text(encoding="utf-8")) == original
    # The half-written temporary file must not be left behind.
    assert list(path.parent.glob(".settings-*")) == []


def test_unwritable_settings_location_is_reported_not_raised(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(i18n, "settings_path",
                        lambda: str(blocker / "TachoReader" / "settings.json"))

    assert i18n.save_language("it") is False
    assert i18n.saved_language() == "en"


# ── translator / catalog loading ───────────────────────────────────────────

def test_install_falls_back_to_english_without_catalogs(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(tmp_path / "locale"))

    assert i18n.install("it") == "it"
    assert i18n._("Ready — open a .ddd file") == "Ready — open a .ddd file"


@pytest.mark.parametrize("payload", [b"\x00\x01\x02", b"\xde\x12\x04\x95", b"junk" * 100])
def test_corrupt_catalog_never_crashes_and_means_english(tmp_path, monkeypatch, payload):
    catalog = tmp_path / "locale" / "it" / "LC_MESSAGES" / "tacho.mo"
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(payload)
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(tmp_path / "locale"))

    assert i18n.install("it") == "it"
    assert i18n._("Drive") == "Drive"


@pytest.mark.parametrize("code", ["xx", "", "EN", None, 1, ["it"]])
def test_only_supported_codes_are_installed(code):
    assert i18n.install(code) == "en"
    assert i18n._("Drive") == "Drive"


def test_po_mo_roundtrip_is_utf8_for_every_language(compiler, tmp_path, monkeypatch):
    """PO -> MO -> GNUTranslations returns the exact non-ASCII text, 33/33."""
    root = tmp_path / "locale"
    for code in [c for c in i18n.LANGUAGES if c != "en"]:
        _write_po(root / code / "LC_MESSAGES" / "tacho.po", (
            '# handwritten catalog, no header entry on purpose\n'
            '#, fuzzy\n'
            'msgid "Drive"\n'
            'msgstr "FUZZY {code}"\n'
            '\n'
            'msgid "Ready — open a .ddd file"\n'
            'msgstr "Ready {code} — àèìòù ça va 😀"\n'
            'msgid "Language"\n'
            'msgstr "Langue {code} \\"citée\\" "\n'
            '    "multi-line"\n'
        ).format(code=code))
        data, count = compiler.build_catalog(str(root / code / "LC_MESSAGES" / "tacho.po"))
        (root / code / "LC_MESSAGES" / "tacho.mo").write_bytes(data)
        assert count == 2  # the fuzzy entry is skipped, like msgfmt

    monkeypatch.setattr(i18n, "locale_dir", lambda: str(root))

    for code in [c for c in i18n.LANGUAGES if c != "en"]:
        i18n.install(code)
        assert i18n._("Ready — open a .ddd file") == f"Ready {code} — àèìòù ça va 😀"
        assert i18n._("Language") == f'Langue {code} "citée" multi-line'
        assert i18n._("Drive") == "Drive"  # fuzzy: English fallback
        # GNUTranslations really reads the charset from our generated header.
        with open(root / code / "LC_MESSAGES" / "tacho.mo", "rb") as fh:
            raw = gettext.GNUTranslations(fh)
        assert raw.info()["content-type"] == "text/plain; charset=UTF-8"


# ── compiler (PO subset) ───────────────────────────────────────────────────

GOOD_PO = """\
# Italian translation of the UI
# Copyright: the contributors
#, fuzzy
msgid "Fuzzy"
msgstr "Fuzzy"

msgid ""
msgstr ""
"Project-Id-Version: TachoReader\\n"
"Content-Type: text/plain; charset=UTF-8\\n"

# No blank line before this comment-separated entry on purpose.
msgid "Ready — open a .ddd file"
msgstr "Pronto — apri un file .ddd"
msgid "Drive"
msgstr "Guida"
#, fuzzy
msgid "Work"
msgstr "Lavoro"
msgid "PDF (.pdf)"
msgstr "PDF (.pdf)"
msgid "{percent:.2f}% of file"
msgstr "{percent:.2f}% del file"
msgid "Tab\\there and a \\"quote\\""
msgstr "Tab\\tqui e una \\"citazione\\""
"""


def test_parse_po_handles_separators_fuzzy_and_escapes(compiler, tmp_path):
    path = _write_po(tmp_path / "it" / "LC_MESSAGES" / "tacho.po", GOOD_PO)

    pairs = compiler.parse_po(str(path))

    assert pairs == [
        ("Ready — open a .ddd file", "Pronto — apri un file .ddd"),
        ("Drive", "Guida"),
        ("PDF (.pdf)", "PDF (.pdf)"),  # technical constant: unchanged is valid
        ("{percent:.2f}% of file", "{percent:.2f}% del file"),
        ('Tab\there and a "quote"', 'Tab\tqui e una "citazione"'),
    ]


@pytest.mark.parametrize("body,expected", [
    ('msgctxt "menu"\nmsgid "a"\nmsgstr "b"\n', "msgctxt"),
    ('msgid "a"\nmsgid_plural "b"\nmsgstr "c"\n', "msgid_plural"),
    ('msgid "a"\nmsgstr[0] "b"\n', "msgstr["),
    ('msgid "a"\nmsgstr "b"\nmsgid "a"\nmsgstr "c"\n', "duplicate"),
    ('msgid 42\nmsgstr "b"\n', "non-string"),
    ('msgid "a"\nmsgstr ""\n', "untranslated"),
    ('msgid "{a}"\nmsgstr "b"\n', "placeholders differ"),
    ('msgid "a"\nmsgstr "b {a}"\n', "placeholders differ"),
    ('msgid "x {a:.2f}"\nmsgstr "y {a:.2%}"\n', "placeholders differ"),
    ('"stray"\n', "continuation"),
    ('msgid "a"\n"b"\n', "no 'msgstr'"),
    ('random text\n', "unexpected line"),
])
def test_compiler_rejects_broken_catalogs(compiler, tmp_path, body, expected):
    path = _write_po(tmp_path / "it" / "LC_MESSAGES" / "tacho.po", body)

    with pytest.raises(compiler.CatalogError) as excinfo:
        compiler.parse_po(str(path))

    assert expected in str(excinfo.value)
    assert "tacho.po:" in str(excinfo.value)


def test_check_mode_passes_for_fresh_mo_and_fails_when_stale(compiler, tmp_path,
                                                             monkeypatch, capsys):
    locale_root = tmp_path / "locale"
    _write_po(locale_root / "it" / "LC_MESSAGES" / "tacho.po", GOOD_PO)
    monkeypatch.setattr(compiler, "ROOT", str(tmp_path))
    monkeypatch.setattr(compiler, "expected_languages", lambda: {"it"})

    assert compiler.main([]) == 0
    mo_path = locale_root / "it" / "LC_MESSAGES" / "tacho.mo"
    assert mo_path.is_file()
    assert compiler.main(["--check"]) == 0

    mo_path.write_bytes(b"stale")
    assert compiler.main(["--check"]) == 1
    assert "stale catalog" in capsys.readouterr().err

    mo_path.unlink()
    assert compiler.main(["--check"]) == 1

    assert compiler.main([]) == 0
    assert compiler.main(["--check"]) == 0


def test_check_mode_reports_bad_catalogs(compiler, tmp_path, monkeypatch, capsys):
    _write_po(tmp_path / "locale" / "it" / "LC_MESSAGES" / "tacho.po",
              'msgid "{a}"\nmsgstr "b"\n')
    monkeypatch.setattr(compiler, "ROOT", str(tmp_path))
    monkeypatch.setattr(compiler, "expected_languages", lambda: {"it"})

    assert compiler.main(["--check"]) == 1
    assert "placeholders differ" in capsys.readouterr().err


def test_expected_catalogs_are_every_menu_language_but_english(compiler):
    assert compiler.expected_languages() == set(i18n.LANGUAGES) - {"en"}


def test_one_missing_language_catalog_is_a_failure(compiler, tmp_path, monkeypatch, capsys):
    """A language in the menu without a catalog must not pass the build."""
    locale_root = tmp_path / "locale"
    for code in EXPECTED_CATALOG_CODES:
        _write_po(locale_root / code / "LC_MESSAGES" / "tacho.po", GOOD_PO)
    monkeypatch.setattr(compiler, "ROOT", str(tmp_path))

    assert compiler.main([]) == 0
    assert compiler.main(["--check"]) == 0

    (locale_root / "mk" / "LC_MESSAGES" / "tacho.po").unlink()

    assert compiler.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "no catalog for 1 language" in err
    assert "mk" in err


def test_missing_locale_directory_is_a_failure(compiler, tmp_path, monkeypatch, capsys):
    """No catalog at all means the UI would stay English: that must fail."""
    monkeypatch.setattr(compiler, "ROOT", str(tmp_path / "empty"))

    assert compiler.main([]) == 1
    assert compiler.main(["--check"]) == 1
    assert "no catalogs found" in capsys.readouterr().err


def test_unknown_argument_is_a_usage_error(compiler):
    assert compiler.main(["--frobnicate"]) == 2


# ── msgid coverage ─────────────────────────────────────────────────────────

def test_every_msgid_the_gui_uses_is_declared():
    """Dynamic msgids are explicit, and every literal is non-empty."""
    literals = _literal_msgids()
    assert len(literals) > 250
    for msgid in literals:
        assert msgid, "empty msgid would translate everything"
    # The dynamic list is complete: each entry really is used by gui.py.
    source = GUI_PATH.read_text(encoding="utf-8")
    for msgid in DYNAMIC_MSGIDS:
        assert msgid in source, msgid


def test_every_offered_language_ships_po_and_mo():
    """A language in the menu without a catalog is a broken menu entry."""
    assert _catalog_codes("po") == set(EXPECTED_CATALOG_CODES)
    assert _catalog_codes("mo") == set(EXPECTED_CATALOG_CODES)


@pytest.mark.parametrize("code", EXPECTED_CATALOG_CODES)
def test_shipped_catalog_covers_every_msgid(compiler, code):
    """Every catalog translates every msgid, with the same placeholders."""
    po_path = CATALOG_DIR / code / "LC_MESSAGES" / "tacho.po"
    pairs = dict(compiler.parse_po(str(po_path)))  # validates structure + specs

    expected = _all_msgids()
    missing = expected - set(pairs)
    assert not missing, f"{code}: missing msgids: {sorted(missing)[:5]}"
    for msgid in expected:
        assert pairs[msgid].strip(), f"{code}: empty translation for {msgid!r}"
        assert compiler._placeholders(pairs[msgid]) == compiler._placeholders(msgid)


@pytest.mark.parametrize("code", EXPECTED_CATALOG_CODES)
def test_shipped_catalog_translates_real_chrome(compiler, code, tmp_path, monkeypatch):
    """A catalog that copies English around is not a translation."""
    po_path = CATALOG_DIR / code / "LC_MESSAGES" / "tacho.po"
    mo_path = po_path.with_suffix(".mo")
    assert mo_path.is_file(), f"{code}: {mo_path.name} is missing (run the compiler)"

    monkeypatch.setattr(i18n, "locale_dir", lambda: str(CATALOG_DIR))
    assert i18n.install(code) == code
    translated = [msgid for msgid in CHROME_MSGIDS if i18n._(msgid) != msgid]
    assert len(translated) >= 3, f"{code}: chrome strings are not translated"


@pytest.mark.parametrize("code", EXPECTED_CATALOG_CODES)
def test_shipped_catalog_mo_is_up_to_date(compiler, code):
    """The committed .mo must be exactly what the .po compiles to."""
    po_path = CATALOG_DIR / code / "LC_MESSAGES" / "tacho.po"
    mo_path = po_path.with_suffix(".mo")

    data, _count = compiler.build_catalog(str(po_path))

    assert mo_path.read_bytes() == data, f"{code}: stale .mo (recompile it)"


# ── build spec ─────────────────────────────────────────────────────────────

def test_build_spec_bundles_compiled_catalogs(tmp_path, monkeypatch):
    """PyInstaller must ship locale/<code>/LC_MESSAGES/tacho.mo, not just the tree."""
    mo = tmp_path / "locale" / "it" / "LC_MESSAGES" / "tacho.mo"
    mo.parent.mkdir(parents=True)
    mo.write_bytes(b"\x00")
    recorded = {}

    def stub(name):
        def _record(*_args, **kwargs):
            recorded[name] = kwargs
            return object()
        return _record

    def analysis(*_args, **kwargs):
        recorded["Analysis"] = kwargs
        return types.SimpleNamespace(pure=None, zipped_data=None, scripts=None,
                                     binaries=None, zipfiles=None,
                                     datas=kwargs.get("datas"))

    namespace = {name: stub(name) for name in ("PYZ", "EXE", "COLLECT", "BUNDLE")}
    namespace["Analysis"] = analysis
    saved_path = list(sys.path)
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        exec(compile((REPO_ROOT / "build.spec").read_text(encoding="utf-8"),
                     "build.spec", "exec"), namespace)
    finally:
        sys.path[:] = saved_path

    datas = recorded["Analysis"]["datas"]
    assert (str(mo), os.path.join("locale", "it", "LC_MESSAGES")) in datas


# ── GUI: language menu and in-process restart ──────────────────────────────

DAY = "01/01/2026"
CURRENT_FILE = os.path.join("opened", "current.ddd")


def _require_display():
    """Skip when there is no display — *before* the code under test runs.

    Wrapping the call in ``except TclError: skip`` instead would turn a real
    ``TclError`` raised by the bug (a widget from a destroyed interpreter) into
    a pass. Returns the ``tkinter`` module for the caller's convenience.
    """
    tkinter = pytest.importorskip("tkinter")
    try:
        probe = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display available")
    probe.destroy()
    return tkinter


def _open_day_popup(app, day=DAY):
    from app.gui import DayDetailWindow
    return DayDetailWindow(app, day, [], 0, 0, "", {}, [], [], [], {})


@pytest.fixture
def explorer(monkeypatch):
    """A real TachoExplorer window (skipped when there is no display)."""
    tkinter = pytest.importorskip("tkinter")
    from app.gui import TachoExplorer
    try:
        app = TachoExplorer()
    except tkinter.TclError:
        pytest.skip("no display available")
    try:
        yield app
    finally:
        try:
            app.destroy()
        except tkinter.TclError:
            pass


def test_language_menu_lists_every_language_with_column_breaks(explorer):
    menu = explorer.nametowidget(explorer.btn_lang["menu"])

    # Top level: just the language submenu and the independent preference.
    assert menu.entrycget(0, "label") == i18n._("Language")
    assert menu.type(0) == "cascade"
    assert menu.type(1) == "separator"
    assert menu.entrycget(2, "label") == i18n._("Translate file contents")
    assert menu.index("end") == 2

    languages = explorer.nametowidget(menu.entrycget(0, "menu"))
    labels = [languages.entrycget(i, "label")
              for i in range(languages.index("end") + 1)]
    assert labels == list(i18n.LANGUAGES.values())
    assert labels[0] == "English"
    # 34 entries in one column would not fit a small screen.
    breaks = [i for i in range(len(labels))
              if languages.entrycget(i, "columnbreak") == 1]
    assert breaks and len(labels) / (len(breaks) + 1) <= 12
    # The button shows the language actually in use, in its own language.
    assert explorer.btn_lang.cget("text").endswith("English")
    assert explorer._language == "en"


def test_switch_is_refused_while_a_parse_is_running(explorer, monkeypatch):
    calls = []
    monkeypatch.setattr("app.gui.save_language", lambda code: calls.append(code) or True)
    explorer._parsing = True
    explorer._language_var.set("it")

    explorer._switch_language("it")

    assert calls == []
    assert explorer._language_var.get() == "en"
    assert explorer._restart_requested is False
    assert explorer.winfo_exists()


def test_switch_is_refused_while_an_export_is_running(explorer, monkeypatch):
    calls = []
    monkeypatch.setattr("app.gui.save_language", lambda code: calls.append(code) or True)
    explorer._exporting = True
    explorer._language_var.set("de")

    explorer._switch_language("de")

    assert calls == []
    assert explorer._language_var.get() == "en"
    assert explorer._restart_requested is False
    assert explorer.winfo_exists()


def test_failed_save_keeps_the_window_and_the_selection(explorer, monkeypatch):
    warned = []
    monkeypatch.setattr("app.gui.save_language", lambda code: False)
    monkeypatch.setattr("app.gui.messagebox.showwarning",
                        lambda title, message: warned.append((title, message)))
    explorer._language_var.set("fr")

    explorer._switch_language("fr")

    assert warned and warned[0][0] == "Language"
    assert explorer._language_var.get() == "en"
    assert explorer._restart_requested is False
    assert explorer.winfo_exists()


def test_switch_requests_a_restart_that_reopens_the_current_file(explorer, monkeypatch):
    tkinter = pytest.importorskip("tkinter")
    monkeypatch.setattr("app.gui.save_language", lambda code: True)
    explorer.current_file = os.path.join("some", "dir", "current.ddd")
    explorer._language_var.set("it")

    explorer._switch_language("it")
    explorer.update()  # let the idle handler destroy the window

    assert explorer._restart_requested is True
    assert explorer._restart_file == explorer.current_file
    try:
        gone = not explorer.winfo_exists()
    except tkinter.TclError:  # the whole interpreter is gone, not just the widget
        gone = True
    assert gone


def test_language_switch_during_the_render_cannot_restart_the_window(explorer, monkeypatch):
    """Regression: rendering a loaded file is still busy time.

    ``_parse_done`` renders through ``DataTable.show``, whose sizing
    ``update()`` pumps the event loop, so a language selection dispatched from
    it used to find ``_parsing`` already cleared by ``_finish_parse`` and
    schedule the restart. The teardown then destroyed the widgets
    ``_parse_done`` was still configuring (``TclError: invalid command name
    .!frame2.!label``), leaving the error path talking to a dead window. The
    selection must be refused while the render runs -- and work afterwards.
    """
    tkinter = pytest.importorskip("tkinter")
    import app.gui as gui

    saved, dialogs = [], []
    monkeypatch.setattr(gui, "save_language", lambda code: saved.append(code) or True)
    monkeypatch.setattr(gui.messagebox, "showerror",
                        lambda title, message: dialogs.append(title))
    # The payload is not the subject here: keep the tree walk out of the way so
    # the render that matters (the placeholder pane below) stays the real one.
    explorer._populate_tree = lambda data: None
    explorer._update_top_bar = lambda data: None
    explorer._check_integrity = lambda data, path: None
    # Queue the selection exactly as the menu/timer does, then let the table's
    # nested update() inside the render dispatch it mid-call.
    explorer.after_idle(lambda: explorer._switch_language("it"))

    explorer._parse_done({"metadata": {"generation": "Gen2"}, "raw_tags": [{"tag": 1}]},
                         CURRENT_FILE)

    assert dialogs == []                     # the render completed cleanly
    assert saved == []                       # nothing persisted, no restart asked
    assert explorer._restart_requested is False
    assert explorer._language_var.get() == "en"
    assert explorer.winfo_exists()           # the window was not torn down
    assert explorer._parsing is False        # the guard is released afterwards
    assert explorer.current_file == CURRENT_FILE
    assert str(explorer.btn_open.cget("state")) == "normal"
    assert str(explorer.btn_export.cget("state")) == "normal"

    # With the render over, the same selection goes through normally.
    explorer._language_var.set("it")
    explorer._switch_language("it")

    assert saved == ["it"]
    assert explorer._restart_requested is True
    assert explorer._restart_file == CURRENT_FILE
    explorer.update()  # the idle restart tears the window down
    try:
        gone = not explorer.winfo_exists()
    except tkinter.TclError:  # the whole interpreter is gone, not just the widget
        gone = True
    assert gone


def test_failed_render_holds_then_releases_the_busy_guard(explorer, monkeypatch):
    """A render that raises is busy time too, and must still end idle: the
    guard covers the failing render and is released by the time it returns."""
    import app.gui as gui

    seen, dialogs = [], []
    monkeypatch.setattr(gui, "save_language", lambda code: True)
    monkeypatch.setattr(gui.messagebox, "showerror",
                        lambda title, message: dialogs.append(title))

    def explode(data):
        seen.append(explorer._parsing)   # a selection here must be refused
        explorer._switch_language("it")
        assert explorer._restart_requested is False
        raise RuntimeError("render boom")

    explorer._populate_tree = explode

    explorer._parse_done({"metadata": {}, "raw_tags": [{"tag": 1}]}, CURRENT_FILE)
    explorer.update()   # the error box now waits for the idle loop, i.e. for the busy state to end

    assert seen == [True]
    assert dialogs == ["Rendering Error"]
    assert explorer._parsing is False
    assert explorer._language_var.get() == "en"
    assert str(explorer.btn_open.cget("state")) == "normal"


def test_main_rebuilds_the_window_in_the_chosen_language(monkeypatch, capfd):
    """The main loop is the restart mechanism: no exec, no stale argv file.

    ``mainloop()`` waits for every Tk main window in the thread, so a restart
    must ``quit()`` its own loop (``_shutdown``) instead of relying on
    ``destroy()``; otherwise the loop never returns and the app freezes. The
    stray root below reproduces that condition and doubles as the watchdog that
    turns a freeze into a bounded failure instead of a hung suite.
    """
    tkinter = _require_display()
    import app.gui as gui

    monkeypatch.setattr(gui, "save_language", i18n.save_language)
    monkeypatch.setattr(sys, "argv", ["tacho", "STALE_FROM_ARGV.ddd"])
    opened = []
    watchdog = {"fired": False}

    class Recording(gui.TachoExplorer):
        def __init__(self, initial_file=None):
            super().__init__(initial_file=initial_file)
            opened.append(self)
            if len(opened) == 1:
                self.current_file = os.path.join("opened", "now.ddd")
                self.after(10, lambda: self._switch_language("it"))
            else:
                self.after(10, self._on_close)

    monkeypatch.setattr(gui, "TachoExplorer", Recording)
    stray = tkinter.Tk()
    stray.withdraw()

    def release_stray():
        # Only reached when the restart failed to quit its own main loop.
        watchdog["fired"] = True
        stray.destroy()

    stray.after(3000, release_stray)
    try:
        gui.main()  # never swallow TclError here: it would hide a restart bug
    finally:
        try:
            stray.quit()
            stray.destroy()
        except tkinter.TclError:
            pass

    assert watchdog["fired"] is False, \
        "main loop did not return: the restart does not quit() its loop"
    assert len(opened) == 2
    assert opened[0]._restart_requested is True
    assert opened[1]._initial_file == os.path.join("opened", "now.ddd")
    assert opened[1]._restart_requested is False
    assert opened[1]._language == "it"
    assert i18n.saved_language() == "it"
    # Closing the old root must not leave timers firing at dead widgets.
    assert "invalid command name" not in capfd.readouterr().err


def test_shutdown_cancels_this_interpreters_pending_timers():
    """A closed root must not leave ``after`` scripts behind in its interpreter.

    Tk keeps running them and reports each one on stderr as "invalid command
    name", which is what a real language restart used to spew.
    """
    _require_display()
    import app.gui as gui

    app = gui.TachoExplorer()
    fired = []
    app.after(5000, lambda: fired.append("table-fit"))
    app.after(5000, lambda: fired.append("poll"))
    assert app.tk.call("after", "info")  # timers queued

    app._shutdown()

    assert app.tk.call("after", "info") == ""
    assert fired == []
    app.destroy()  # and the root still tears down without a Tcl error


def test_language_restart_reopen_same_day_has_no_stale_popup(monkeypatch):
    """Regression: a restart must not reuse a day popup from the dead root.

    ``DayDetailWindow._open_windows`` is process-global, while the windows
    themselves die with their Tk interpreter. Opening the same day (same file)
    after a language restart used to hit the previous window and raise
    ``TclError: application has been destroyed``.
    """
    _require_display()
    import app.gui as gui

    monkeypatch.setattr(gui, "save_language", i18n.save_language)
    monkeypatch.setattr(sys, "argv", ["tacho"])
    apps, popups = [], {}

    class Recording(gui.TachoExplorer):
        def __init__(self, initial_file=None):
            super().__init__(initial_file=initial_file)
            apps.append(self)
            if len(apps) == 1:
                self.current_file = CURRENT_FILE
                popups["first"] = _open_day_popup(self)
                self.after(10, lambda: self._switch_language("it"))
            else:
                self.after(10, self._reopen_day)

        def _reopen_day(self):
            # Same file identity and same day -> the exact key that collided.
            self.current_file = CURRENT_FILE
            try:
                popups["second"] = _open_day_popup(self)
                popups["alive"] = bool(popups["second"].winfo_exists())
                popups["registered"] = list(DayDetailWindow._open_windows.values())
            finally:
                self._on_close()  # the real lifecycle: shutdown + destroy

    from app.gui import DayDetailWindow
    monkeypatch.setattr(gui, "TachoExplorer", Recording)
    gui.main()

    assert len(apps) == 2
    assert apps[1]._initial_file == CURRENT_FILE  # the same file was reopened
    assert popups["second"] is not popups["first"]  # a fresh window, not the dead one
    assert popups["alive"] is True
    assert popups["second"] in popups["registered"]


def test_closing_the_root_forgets_the_day_popup_registry(monkeypatch):
    """Going away must clear the reuse registry, not leak dead Tk objects."""
    _require_display()
    import app.gui as gui

    app = gui.TachoExplorer()
    try:
        popup = _open_day_popup(app)
        assert gui.DayDetailWindow._open_windows
        app._on_close()  # what WM close / restart go through
        assert app._destroyed is True
        assert gui.DayDetailWindow._open_windows == {}
        with pytest.raises(pytest.importorskip("tkinter").TclError):
            popup.winfo_exists()  # the window itself is gone with the root
    finally:
        try:
            app.destroy()
        except pytest.importorskip("tkinter").TclError:
            pass
