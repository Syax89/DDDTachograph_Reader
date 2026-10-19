"""Layout of the main window: where the tree/table sash starts, and the plain
wording of the table's size label and the generation nodes.

Each test fails against the previous behaviour (sash in the middle, ``1 columns``,
two spaces before the annex).
"""
import pytest

from tests.unit.test_gui_summary_default import (
    MINIMUM_SIZE, STATUS_CASES, close, new_explorer, open_file)

import app.i18n as i18n
from app.gui import SASH_START, _px

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("DISPLAY"), reason="needs a display")


@pytest.fixture
def window(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        close(app)


def _pane(app):
    return next(w for w in _walk(app) if w.winfo_class().lower() == "tpanedwindow")


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def test_the_tree_starts_at_its_natural_width_not_half_the_window(window):
    window.geometry(MINIMUM_SIZE)
    window.update()
    assert _pane(window).sashpos(0) == _px(SASH_START)
    # The table gets the rest: it was 411 px at this size when the sash sat in
    # the middle, and File Info's value column was clipped there.
    open_file(window, STATUS_CASES[0][1])
    assert window.table.tv.winfo_width() >= _px(560)


def test_a_drag_of_the_sash_is_not_undone_by_a_later_resize(window):
    window.update()
    pane = _pane(window)
    # First layout done (the sash was placed), then the user drags it.
    assert pane.sashpos(0) == _px(SASH_START)
    pane.sashpos(0, _px(330))
    window.update()
    window.geometry(f"{_px(1500)}x{_px(800)}")
    window.update()
    assert pane.sashpos(0) == _px(330)


def test_a_one_column_table_does_not_say_1_columns(window):
    i18n.install("en")
    open_file(window, STATUS_CASES[0][1])
    window.table.show("T", ["Only"], [["a"]])
    window.update()
    label = window.table.count_lbl.cget("text")
    assert "1 columns" not in label and "1 rows" not in label
    assert label.startswith("Rows: 1 \u00b7 Columns: 1")


def test_a_generation_node_has_one_space_before_its_annex(window):
    i18n.install("en")
    from app.engine import TachoParser
    path = "tests/mock_data/mock_g2_card.ddd"
    if not __import__("os").path.exists(path):
        pytest.skip("mock data not generated")
    open_file(window, TachoParser(path).parse(), path="/data/mock.ddd")
    texts = [window.tree.item(i, "text") for i in window.tree.get_children("")]
    annexed = [t for t in texts if "[Annex" in t]
    assert annexed, texts
    assert all("  " not in t for t in annexed), annexed
