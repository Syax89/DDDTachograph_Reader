"""The tree column fit must be exact and must not cost one measure per node.

`_fit_tree_column` used to visit every node (collapsed ones included) and call
``font.measure`` plus two Tcl round trips per node: 1328 nodes cost ~2.7 s of a 3.4 s
render on a 128 KB G2 download, and a full-year download has many more day nodes. The
optimised version must produce the **same width to the pixel** while measuring only a
handful of labels (the widest candidate first, pruned by an exact upper bound).

The reference implementation below is the old algorithm, kept verbatim: any test that
compares against it is a proof of equality, not an approximation.
"""
import json
import os
import tkinter.font as tkfont

import pytest

pytest.importorskip("tkinter")

from app import gui  # noqa: E402
from app import i18n  # noqa: E402
from tests.unit.real_data import real_ddd_files  # noqa: E402
from tests.unit.test_empty_state import close, new_explorer  # noqa: E402
from tests.unit.test_gui_accessibility import _open_mock  # noqa: E402

MOCKS = ["mock_g1_card.ddd", "mock_g1_vu.ddd", "mock_g2_card.ddd",
         "mock_g2_vu.ddd", "mock_g22_card.ddd", "mock_g22_vu.ddd"]

#: The tree every mock renders, captured before the optimisation (texts, images,
#: tags and depth — the drawn result). Node ids are not part of it: they are
#: assigned by Tk and carry no meaning for the user.
TREE_SNAPSHOT = json.loads(open(os.path.join(
    os.path.dirname(__file__), "tree_snapshot_mocks.json"), encoding="utf-8").read())


@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        gui.DayDetailWindow._open_windows.clear()
        close(app)


def _reference_width(app):
    """The pre-optimisation algorithm, verbatim: one measure per node."""
    style = gui.ttk.Style(app)
    font = tkfont.Font(font=style.lookup("Treeview", "font") or "TkDefaultFont")
    indent = int(float(style.lookup("Treeview", "indent") or 20))
    needed = 0

    def visit(parent, depth):
        nonlocal needed
        for iid in app.tree.get_children(parent):
            width = (indent * (depth + 1) - 1 + font.measure(app.tree.item(iid, "text"))
                     + gui._px(8))
            image = app.tree.item(iid, "image")
            if isinstance(image, (tuple, list)):
                image = image[0] if image else ""
            if image:
                width += int(app.tk.call("image", "width", str(image))) + gui._px(4)
            needed = max(needed, width)
            visit(iid, depth + 1)

    visit("", 0)
    return max(needed, gui._px(200))


def _fitted_width(app):
    app._fit_tree_column()
    return int(app.tree.column("#0", "width"))


def _add_day_nodes(app, count):
    """A synthetic full-year tree: `count` day nodes under one parent."""
    parent = app.tree.insert("", "end", text="Daily Activities")
    for index in range(count):
        app.tree.insert(parent, "end",
                        text=f"Day {index + 1:05d} - 01/01/2024 (UTC)")
    app.update()


def _count_measures(app, monkeypatch):
    calls = {"n": 0}
    original = tkfont.Font.measure

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(tkfont.Font, "measure", counting)
    app._fit_tree_column()
    return calls["n"]


# ── Exactness: the width may not move by a pixel ─────────────────────────

@pytest.mark.parametrize("name", MOCKS)
def test_the_fitted_width_equals_the_reference_for_every_mock(explorer, name):
    _open_mock(explorer, name)
    explorer.update()
    assert _fitted_width(explorer) == _reference_width(explorer)


@pytest.mark.parametrize("language", ["el", "de", "ru", "ja", "ar"])
def test_the_fitted_width_equals_the_reference_in_every_script(explorer, language):
    i18n.install(language)
    try:
        _open_mock(explorer, "mock_g2_vu.ddd")
        explorer.update()
        assert _fitted_width(explorer) == _reference_width(explorer)
    finally:
        i18n.install("en")


def test_the_fitted_width_equals_the_reference_on_a_year_of_days(explorer):
    _add_day_nodes(explorer, 5000)
    explorer.update()
    assert _fitted_width(explorer) == _reference_width(explorer)


def test_the_fitted_width_equals_the_reference_on_the_real_files(explorer):
    files = real_ddd_files()
    if not files:
        pytest.skip("no private corpus available")
    for path in files:
        explorer._parse_done(gui.TachoParser(path).parse(), path)
        explorer.update()
        assert _fitted_width(explorer) == _reference_width(explorer), path


# ── Cost: a handful of measures, whatever the node count ─────────────────

def test_a_year_of_days_needs_very_few_measures(explorer, monkeypatch):
    _add_day_nodes(explorer, 5000)
    explorer.update()
    assert _count_measures(explorer, monkeypatch) <= 200


def test_an_empty_tree_keeps_the_minimum_width(explorer):
    explorer.tree.delete(*explorer.tree.get_children(""))
    assert _fitted_width(explorer) == gui._px(200)


# ── The drawn result is identical ────────────────────────────────────────

def _dump_tree(app):
    """``[depth, text, icon, tags]`` per node, in draw order.

    Tk hands back process-local image names (``pyimage19``), so each distinct name is
    mapped to ``icon1``, ``icon2`` … by first use: the same node drawing the same icon
    keeps the same tag across runs, which is the property the user can see.
    """
    rows = []
    icons = {}

    def walk(parent, depth):
        for iid in app.tree.get_children(parent):
            text = app.tree.item(iid, "text")
            image = app.tree.item(iid, "image")
            if isinstance(image, (tuple, list)):
                image = image[0] if image else ""
            icon = ""
            if image:
                key = str(image)
                icon = icons.setdefault(key, f"icon{len(icons) + 1}")
            tags = app.tree.item(iid, "tags")
            rows.append([depth, text, icon, list(tags) if tags else []])
            walk(iid, depth + 1)

    walk("", 0)
    return rows


@pytest.mark.parametrize("name", MOCKS)
def test_the_tree_contents_are_unchanged(explorer, name):
    _open_mock(explorer, name)
    explorer.update()
    explorer._fit_tree_column()
    assert _dump_tree(explorer) == TREE_SNAPSHOT[name]
