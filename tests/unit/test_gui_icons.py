"""The interface draws its icons from the commissioned set (``assets/icons``).

The UI used to put emoji in front of its labels. An emoji is drawn by whichever
font the operating system picks, so the same build showed a thin grey outline on
one machine, a full-colour cartoon on another and an empty box on a third. The
replacement is a monochrome PNG set, and ``app/icons.py`` is the only way the
interface asks for one.

What is pinned here:

* every icon name the code asks for exists, at the size it asks for — the names
  are *derived* (from the source, and from a live render that records every
  request), never retyped, so a typo in a call site fails this file;
* ``icon()`` answers ``None`` for a name that is not in the set, instead of
  raising into the middle of a widget build;
* a cached image survives garbage collection. This is the bug that makes this
  integration fail silently: Tkinter destroys a ``PhotoImage`` the moment
  nothing references it, and a destroyed image renders as an empty row, with no
  error anywhere;
* no emoji is left in any string ``app/gui.py`` renders (or ``app/cli.py``
  prints) — and the check is written so a reintroduced emoji fails it;
* the four section headers the commission asked to tell apart
  (``TOTALS``/``STATISTICS``/``COMPLETENESS``/``PARAMETERS``) really carry four
  different icons, and the toolbar buttons keep their text beside their icon.

Rendered against a real ``TachoExplorer``, which skips cleanly when there is no
display — the same pattern as the other GUI tests.
"""
import ast
import gc
import inspect
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import tkinter as tk  # noqa: E402

import app.gui as gui  # noqa: E402
import app.i18n as i18n  # noqa: E402
from app import icons  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Emoji ranges: the pictographic blocks, the dingbats the UI used, and the
#: clock faces. Arrows (→), dashes (—) and geometric shapes (▾ ●) are *not*
#: emoji: they are drawn by the UI font like any other character and are out of
#: scope. This mirrors the ranges ``scripts/strip_msgid_emoji.py`` strips.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2139, 0x2139),
    (0x231A, 0x231B),
    (0x23F0, 0x23F3),
    (0xFE0F, 0xFE0F),
)


def _widget_image(widget):
    """The image name a ttk widget carries (``""`` when it has none).

    ``cget("image")`` hands back a Tcl list (``('pyimage3',)``), not a string.
    """
    value = widget.cget("image")
    if isinstance(value, (tuple, list)):
        return str(value[0]) if value else ""
    return str(value)


def _item_image(tv, iid):
    """The image name a treeview item carries (``""`` when it has none)."""
    value = tv.item(iid, "image")
    if isinstance(value, (tuple, list)):
        return str(value[0]) if value else ""
    return str(value)


def _header_rows_on_screen(app):
    """``{label: image name}`` of the rows drawn as summary section headers.

    Read from the widget, not from ``_all_rows``: the whole point is what the
    panel is actually drawing. Separator rows carry the same tag but no label,
    and are skipped.
    """
    tv = app.table.tv
    headers = {}
    for iid in tv.get_children(""):
        if "summary_header" not in tv.item(iid, "tags"):
            continue
        label = tv.item(iid, "values")[0]
        if label:
            headers[label] = _item_image(tv, iid)
    return headers


def _layout_names(layout):
    """Element names of a ttk layout, at every depth."""
    for name, options in layout:
        yield name
        yield from _layout_names(options.get("children") or ())


def _let_timers_run(app, seconds=0.6):
    """Run the real Tk event loop so the panel's own ``after()`` fires.

    The summary panel schedules a re-render through ``filter_var.set("")``, so a
    test that only calls ``update()`` never sees the state a user sees half a
    second later.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.update()
        time.sleep(0.01)


def _emoji_in(text):
    """The emoji characters of *text*, sorted (empty when there are none)."""
    return sorted({char for char in text
                   if any(low <= ord(char) <= high for low, high in _EMOJI_RANGES)})


# ── the names the code asks for ───────────────────────────────────────────

def _source_strings(path):
    """Every string constant in *path* that is not a docstring.

    Docstrings describe the code; they are not rendered. Everything else — an
    ``_()`` msgid, an f-string part, a tooltip — is, or can be.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings]


def _literal_icon_requests():
    """``{(name, size)}`` for every ``_icon("name", size)`` call in gui.py.

    The literal call sites are the ones a test can check without a display; the
    indirect ones (``_add_section(..., icon=...)``, ``_SummaryHeader(...)``,
    the status badge) are checked from the live render below.
    """
    tree = ast.parse((REPO_ROOT / "app" / "gui.py").read_text(encoding="utf-8"))
    requests = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in ("_icon", "icon") or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        size = 16
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            size = node.args[1].value
        requests.add((first.value, size))
    return requests


def test_every_icon_the_source_asks_for_exists_at_the_size_it_asks_for():
    requests = _literal_icon_requests()
    assert requests, "no icon call site found — did the helper get renamed?"

    missing = sorted("%s@%d" % (name, size) for name, size in requests
                     if not os.path.isfile(icons.icon_path(name, size)))
    assert not missing, missing


def test_the_indirect_icon_arguments_also_exist():
    """Names passed through a parameter: tree rows, summary headers, badges.

    Derived the same way (the string literals in those positions), so renaming
    an icon in the set breaks this instead of blanking a row at runtime.
    """
    tree = ast.parse((REPO_ROOT / "app" / "gui.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = getattr(node.func, "id", None)
        if called == "_add_section":
            for keyword in node.keywords:
                if keyword.arg == "icon" and isinstance(keyword.value, ast.Constant):
                    names.add(keyword.value.value)
        elif called == "_SummaryHeader":
            for keyword in node.keywords:
                if keyword.arg == "icon" and isinstance(keyword.value, ast.Constant):
                    names.add(keyword.value.value)
    # The status badge passes a name chosen at runtime; its table is the source.
    names.update(name for name in gui._BADGE_WORDS if name)
    assert len(names) >= 15, sorted(names)

    missing = sorted(name for name in names
                     if not os.path.isfile(icons.icon_path(name, 16)))
    assert not missing, missing


def test_a_live_render_only_asks_for_icons_that_exist(monkeypatch):
    """Every request the running window makes resolves — recorded, not assumed."""
    requested = []
    real = gui.icons.icon

    def spy(name, size=16, master=None):
        requested.append((name, size))
        return real(name, size, master=master)

    monkeypatch.setattr(gui.icons, "icon", spy)
    app = _new_explorer(monkeypatch)
    try:
        app._parse_done(_card_data(), "/tmp/icons_fixture.ddd")
        app.update()
        for iid in app.tree.get_children(""):
            app.tree.selection_set(iid)
            app.update()
    finally:
        _close(app)

    assert requested, "the window asked for no icon at all"
    unresolved = sorted({"%s@%d" % (name, size) for name, size in requested
                         if not os.path.isfile(icons.icon_path(name, size))})
    assert not unresolved, unresolved
    # The mapping the brief asked for, on the rows it asked for it.
    assert ("summary", 16) in requested
    assert ("toolbar-open", 20) in requested


# ── the loader itself ─────────────────────────────────────────────────────

def test_an_unknown_name_returns_none_instead_of_raising(root):
    assert icons.icon("no-such-icon", 16, master=root) is None
    assert icons.icon("", 16, master=root) is None
    assert icons.icon("status-ok", 17, master=root) is None, \
        "17 px is not a delivered size"
    assert not any("no-such-icon" in str(key) for key in icons._CACHE)


def test_a_cached_image_survives_a_forced_collection(root):
    """The blank-row bug: an un-referenced PhotoImage is destroyed by Tkinter."""
    image = icons.icon("status-ok", 16, master=root)
    assert image is not None
    tcl_name = str(image)
    del image
    gc.collect()

    assert tcl_name in root.tk.call("image", "names"), \
        "the cached image was garbage-collected and its row would be blank"
    again = icons.icon("status-ok", 16, master=root)
    assert str(again) == tcl_name, "the second call must re-use the cached image"
    assert again.width() == 16


def test_a_rebuilt_window_gets_its_own_images(root):
    """A language switch destroys the window and builds a new one.

    The cached images belong to the Tcl interpreter of the root that made them,
    so they die with that window; handing them to the new one raises
    ``TclError: image "pyimageN" doesn't exist`` and the window fails to build.
    The cache must therefore be rebuilt for the new root, not re-used.
    """
    first = icons.icon("status-ok", 16, master=root)
    assert first is not None
    old_interpreter = id(root.tk)
    root.destroy()                       # exactly what the restart does

    second_root = tk.Tk()
    try:
        second_root.withdraw()
        again = icons.icon("status-ok", 16, master=second_root)
        assert again is not None
        assert again is not first, "an image from the dead window was re-used"
        assert str(again) in second_root.tk.call("image", "names")
        assert old_interpreter not in {key[0] for key in icons._CACHE}, \
            "the dead window's images should have been dropped"
    finally:
        _close(second_root)


def test_the_loader_is_usable_without_a_tk_root():
    """Importing must not need a root; *creating* an image does, and says so."""
    assert "tkinter" not in str(inspect.signature(icons.icon))
    source = inspect.getsource(icons)
    assert "PhotoImage(" in source
    # No module-level image: the cache starts empty in a fresh interpreter.
    assert isinstance(icons._CACHE, dict)


def test_the_set_is_found_from_the_package_not_the_working_directory(monkeypatch):
    """A frozen bundle and a source checkout resolve the same way."""
    expected = REPO_ROOT / "assets" / "icons"
    assert Path(icons.icons_dir()) == expected
    monkeypatch.chdir(REPO_ROOT / "app")
    assert Path(icons.icons_dir()) == expected, \
        "the path must not depend on the current directory"
    monkeypatch.setattr(icons.sys, "_MEIPASS", str(REPO_ROOT / "bundle"), raising=False)
    assert Path(icons.icons_dir()) == REPO_ROOT / "bundle" / "assets" / "icons"


# ── no emoji left in what the interface shows ─────────────────────────────

@pytest.mark.parametrize("module", ["app/gui.py", "app/cli.py"])
def test_no_emoji_is_left_in_any_rendered_string(module):
    offenders = {}
    for text in _source_strings(REPO_ROOT / module):
        found = _emoji_in(text)
        if found:
            offenders[text] = found
    assert not offenders, offenders


def test_the_emoji_check_would_catch_a_reintroduced_glyph():
    """The guard above is only worth something if it fails on an emoji."""
    assert _emoji_in("TOTALS") == []
    assert _emoji_in("\u26a0\ufe0f  Decoder Failures") == ["\u26a0", "\ufe0f"]
    assert _emoji_in("\U0001f4ca  TOTALS") == ["\U0001f4ca"]
    # Not emoji: the sort/expander arrows and the en dash are ordinary text.
    assert _emoji_in("\u25be  3") == []
    assert _emoji_in("01/05/2025 \u2014 02/05/2025") == []


# ── the mapping the brief asked for ───────────────────────────────────────

def test_the_four_sections_the_brief_named_no_longer_share_a_glyph(explorer):
    """TOTALS / STATISTICS / COMPLETENESS / PARAMETERS are told apart.

    They shared one emoji by accident, so a long list could not tell the four
    blocks apart. The icons come from the rows the builders really produce.
    """
    labels = {
        i18n._("TOTALS"),
        i18n._("STATISTICS"),
        i18n._("COMPLETENESS"),
        i18n._("PARAMETERS"),
    }
    used = {}
    for builder in (gui.TachoExplorer._build_overview_summary,
                    gui.TachoExplorer._build_driver_summary,
                    gui.TachoExplorer._build_vehicle_summary,
                    gui.TachoExplorer._build_sensor_summary,
                    gui.TachoExplorer._build_trep_summary):
        for row in _header_rows(explorer, builder):
            if row[0] in labels:
                used.setdefault(row[0], set()).add(row.icon)

    chosen = {label: next(iter(names)) for label, names in used.items()}
    assert chosen == {
        i18n._("TOTALS"): "statistics",
        i18n._("STATISTICS"): "statistics",
        i18n._("COMPLETENESS"): "completeness",
        i18n._("PARAMETERS"): "parameters",
    }
    # Three glyphs for four labels: the set has exactly three icons for the one
    # emoji they shared, and TOTALS / STATISTICS are never on screen together
    # (the overview shows the first, the driver and vehicle panels the second).
    # COMPLETENESS and PARAMETERS are the two that used to be indistinguishable.
    assert len(set(chosen.values())) == 3, chosen


def test_the_four_status_icons_are_the_four_status_icons(explorer):
    """Four states, four delivered files, four different drawings.

    The set tells them apart by shape (circle/check, triangle/!, circle/cross,
    circle/?), so the ordering above is not the only signal. Which state maps to
    which name is pinned by ``_BADGE_WORDS``/the badge tests; this one pins that
    the four names are backed by four *distinct* 16 px files.
    """
    from app.icons import icon

    shapes = {}
    for name in ("status-ok", "status-warning", "status-error", "status-unknown"):
        image = icon(name, 16, master=explorer)
        assert image is not None, name
        shapes[name] = (image.width(), image.height())
    assert set(shapes) == {"status-ok", "status-warning", "status-error",
                           "status-unknown"}
    # Distinct artwork: the four files are not copies of one another.
    digests = {name: (REPO_ROOT / "assets" / "icons" / "png" / "16" /
                      (name + ".png")).read_bytes() for name in shapes}
    assert len(set(digests.values())) == 4


def test_a_clean_file_leaves_no_warning_icon_behind(monkeypatch, explorer):
    """The banner and the badge show an icon only while they say something.

    Both labels are re-configured on every parse, and a Tk label keeps the
    image it was configured with: without clearing it, a verified file would
    display the previous file's warning triangle next to an empty label.
    """
    clean = _card_data()
    # A card whose EF signatures were checked and verified produces no warning.
    clean["ef_signature_verification"] = {"verified": 13, "failed": 0,
                                          "skipped": 0, "total": 13}
    explorer._check_integrity(clean, "/tmp/clean.ddd")
    explorer.update()
    assert explorer._integrity_warnings == []
    assert explorer.integrity_banner.cget("text") == ""
    assert _widget_image(explorer.integrity_banner) == ""

    explorer._parse_done(clean, "/tmp/clean.ddd")
    explorer.update()
    assert _widget_image(explorer.lbl_status) == "", \
        "a verified file shows no status icon"
    assert explorer.lbl_status.cget("text") == ""


def test_a_flagged_file_shows_the_warning_icon(monkeypatch, explorer):
    """The same labels do carry their icon when there is something to say."""
    data = _card_data()
    data["metadata"]["integrity_check"] = "Card data signature mismatch"
    explorer._check_integrity(data, "/tmp/flagged.ddd")
    explorer.update()
    assert explorer.integrity_banner.cget("text")
    image = _widget_image(explorer.integrity_banner)
    assert image and image != "", "the banner must show the warning icon"
    assert image == str(icons.icon("status-warning", 16,
                                   master=explorer.integrity_banner))


# ── the panel keeps its icons while it lives ─────────────────────────────

def test_the_summary_icons_survive_the_panels_own_timers(explorer):
    """The headline panel's icons must still be drawn half a second later.

    ``_show_summary`` sets the filter box to ``""``, and that write trace
    schedules ``_apply_filter`` 300 ms out. That re-render used to redraw the
    section headers as ordinary rows — no band, no icon — so the icons existed
    only for the third of a second before the timer fired. The timer is a real
    ``after()`` here: it is driven, not assumed.
    """
    explorer._parse_done(_card_data(), "/tmp/icons_timers.ddd")
    explorer.update()

    headers = _header_rows_on_screen(explorer)
    assert {"TOTALS", "INTEGRITY"} <= set(headers), headers
    missing = {label: image for label, image in headers.items() if not image}
    assert not missing, missing

    _let_timers_run(explorer)          # the scheduled _apply_filter fires here
    after_timer = _header_rows_on_screen(explorer)
    assert after_timer == headers, (
        "the panel's own re-render dropped the section icons: %r" % (after_timer,))


def test_the_summary_icons_survive_a_filter_change(explorer):
    """Filtering re-renders every row; the surviving header keeps its icon."""
    explorer._parse_done(_card_data(), "/tmp/icons_filter.ddd")
    explorer.update()
    _let_timers_run(explorer)
    before = _header_rows_on_screen(explorer)
    assert {"TOTALS", "INTEGRITY"} <= set(before), (
        "precondition: the panel must still be drawing its headers: %r" % (before,))
    assert all(before.values()), before

    explorer.table.filter_var.set(i18n._("TOTALS"))
    _let_timers_run(explorer)
    filtered = _header_rows_on_screen(explorer)
    assert list(filtered) == [i18n._("TOTALS")], filtered
    assert filtered[i18n._("TOTALS")], "the surviving header row lost its icon"

    explorer.table.filter_var.set("")
    _let_timers_run(explorer)
    assert _header_rows_on_screen(explorer) == before


def test_the_summary_icons_survive_a_sort(explorer):
    """A header click on any column re-renders through _apply_filter as well."""
    explorer._parse_done(_card_data(), "/tmp/icons_sort.ddd")
    explorer.update()
    _let_timers_run(explorer)
    before = _header_rows_on_screen(explorer)
    assert {"TOTALS", "INTEGRITY"} <= set(before), (
        "precondition: the panel must still be drawing its headers: %r" % (before,))
    assert all(before.values()), before

    explorer.table._sort_by(i18n._("Field"))
    explorer.update()
    _let_timers_run(explorer)

    after = _header_rows_on_screen(explorer)
    assert set(after) == set(before), (set(before) - set(after), set(after) - set(before))
    assert after == {label: before[label] for label in after}, (
        "the sort redrew the section headers without their icons: %r" % (after,))


def test_the_icon_gutter_has_room_for_the_whole_icon(explorer):
    """A 22 px gutter must paint a 16 px icon, not a clipped sliver.

    ttk reserves its expander indicator (~19 px in this theme) *before* the row
    image, so the section icons were painted past the gutter's right edge —
    three columns of a sixteen-pixel drawing, which reads as a blank row. The
    panel's rows are a flat list, so its treeview style drops the indicator;
    this pins both halves: the room, and the absence of dead space in front of
    the icon.
    """
    from tkinter import ttk

    tv = explorer.table.tv
    gutter = int(tv.column("#0", "width"))
    image = icons.icon("file-info", 16, master=tv)
    assert image is not None
    assert gutter >= image.width(), (gutter, image.width())

    assert str(tv.cget("style")) == "Summary.Treeview"
    names = set(_layout_names(ttk.Style(explorer).layout("Summary.Treeview.Item")))
    assert {"Treeitem.image", "Treeitem.text"} <= names, names
    assert "Treeitem.indicator" not in names, (
        "the indicator would push the icon out of the gutter: %r" % (sorted(names),))


# ── the toolbar keeps its text ────────────────────────────────────────────

def test_toolbar_buttons_carry_an_image_and_keep_their_text(explorer):
    expected = ((explorer.btn_open, "toolbar-open", i18n._("Open DDD file")),
                (explorer.btn_export, "toolbar-export", i18n._("Export")),
                (explorer.btn_lang, "toolbar-language",
                 i18n.LANGUAGES[explorer._language]))
    for widget, name, text in expected:
        image = icons.icon(name, 20, master=explorer)
        assert image is not None, name
        assert _widget_image(widget) == str(image), widget
        assert widget.cget("text") == text
        assert str(widget.cget("compound")) == "left"


def test_a_toolbar_icon_is_not_a_character_in_the_label(explorer):
    """The label is the words alone: the icon is the image beside it."""
    for widget in (explorer.btn_open, explorer.btn_export, explorer.btn_lang):
        assert _emoji_in(widget.cget("text")) == []


# ── fixtures ──────────────────────────────────────────────────────────────

def _card_data():
    """A card payload rich enough to build every section the tree has."""
    return {
        "metadata": {
            "is_vu": False,
            "generation": "G2 (Smart)",
            "integrity_check": "Verified",
            "file_size_bytes": 1234,
            "parsed_at": "2026-01-01T09:00:00",
            "app_version": "2.5.0",
        },
        "coverage": {"byte_accounted_pct": 100.0, "unknown_bytes": 0,
                     "unknown_pct": 0.0, "structurally_identified_pct": 100.0},
        "driver": {
            "surname": "BIANCHI",
            "firstname": "LUCA",
            "card_number": "I100000000000000",
            "issuing_nation": "I",
            "expiry_date": "2027-04-30",
        },
        "vehicle": {"plate": "AB123CD", "vin": "WVWZZZ1JZ3W386752",
                    "registration_nation": "I"},
        "activities": [{
            "date": "01/05/2025",
            "changes": [{"activity": "DRIVE", "time": "00:00", "slot": "First"},
                        {"activity": "REST", "time": "10:15", "slot": "First"}],
        }],
        "raw_tags": {},
        "generations": {},
    }


def _header_rows(app, builder):
    """The ``_SummaryHeader`` rows a summary builder produces for a full file.

    The builders take data and return rows — they build no widgets — so they
    can be called on a real (unparsed) window, which is where the icons a user
    actually sees come from.
    """
    if not getattr(app, "current_file", None):
        app.current_file = "/tmp/icons_fixture.ddd"
    if builder.__name__ == "_build_trep_summary":
        report = {"mandatory_ok": 3, "mandatory_total": 4,
                  "completeness_pct": 75,
                  "present": [{"name": "TREP 1", "trep": "0x01"}],
                  "mandatory_missing": [], "decoded_suspect": []}
        _cols, rows = builder(app, report, {"salvage_recovered": ["TREP 9"]})
    else:
        _cols, rows = builder(app, _builder_data(builder))
    return [row for row in rows if isinstance(row, gui._SummaryHeader)]


def _builder_data(builder):
    """Data shaped for one of the other summary builders."""
    data = _card_data()
    data["sensor_info"] = {"sensor_approval": "A", "first_date": "2025-01-01",
                           "last_date": "2025-01-02"}
    data["sensor_daily_records"] = [{"date": "2025-01-01"}]
    data["calibrations"] = [{"next_calibration_date": "2030-01-01T00:00:00+00:00"}]
    data["vu_info"] = {"manufacturer": "VDO"}
    data["signature_verification"] = {}
    return data


def _new_explorer(monkeypatch):
    """A real TachoExplorer, or a clean skip when there is no display."""
    class NoDialogs:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    monkeypatch.setattr(gui, "messagebox", NoDialogs())
    try:
        return gui.TachoExplorer()
    except tk.TclError:
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
def root():
    """A bare Tk root for the loader tests (the window tests build their own)."""
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw()
    try:
        yield window
    finally:
        _close(window)


@pytest.fixture
def explorer(monkeypatch):
    app = _new_explorer(monkeypatch)
    try:
        yield app
    finally:
        _close(app)
