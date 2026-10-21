"""Leaving a dashboard must destroy its tooltip label, not hide it.

``_show_dashboard`` creates one ``tk.Label`` inside the table's treeview for the
row tooltips; ``_cleanup_dashboard`` only called ``place_forget()``, so every
dashboard render left its label behind as a child of the treeview. Reproduced
on a real window before the fix: six visits to *Daily Activities* left six
``Label`` children, one of them still holding the last tooltip's text, and
``_cleanup_dashboard`` removed none of them. The sibling summary tooltip
(``_cleanup_summary_tooltip``) already destroys its own label; this pins the
same contract for the dashboard one.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app.gui import TachoExplorer
from tests.unit.test_gui_driving_rules import CARD_DATA, CLEAN_DAY, FLAGGED_DAY

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("DISPLAY"), reason="needs a display")


@pytest.fixture
def explorer():
    """A real TachoExplorer window (skipped when there is no display)."""
    try:
        app = TachoExplorer()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        yield app
    finally:
        try:
            for after_id in app.tk.call("after", "info"):
                app.tk.call("after", "cancel", after_id)
        except tk.TclError:
            pass
        try:
            app.destroy()
        except tk.TclError:
            pass


def _labels_in_table(app):
    """The tooltip labels currently living inside the table's treeview."""
    return [w for w in app.table.tv.winfo_children() if isinstance(w, tk.Label)]


def _render_days(app, days=(FLAGGED_DAY, CLEAN_DAY)):
    app._show_daily_summary(list(days), CARD_DATA)
    app.update()


def test_a_dashboard_render_leaves_exactly_one_tooltip_label(explorer):
    _render_days(explorer)
    assert len(_labels_in_table(explorer)) == 1


def test_repeated_dashboard_renders_do_not_accumulate_labels(explorer):
    """Six visits used to leave six labels on the treeview."""
    _render_days(explorer)
    first = _labels_in_table(explorer)[0]
    for _ in range(5):
        _render_days(explorer)
    labels = _labels_in_table(explorer)
    assert len(labels) == 1, f"{len(labels)} tooltip labels survived five re-renders"
    assert labels[0] is not first, "the label of the previous render must be gone"
    assert not first.winfo_exists(), "the previous render's label was only hidden"


def test_leaving_the_dashboard_destroys_its_tooltip_label(explorer):
    _render_days(explorer)
    label = _labels_in_table(explorer)[0]
    explorer._cleanup_dashboard()
    assert _labels_in_table(explorer) == []
    assert not label.winfo_exists()
    assert getattr(explorer, "_tooltip_lbl", None) is None


def test_the_hover_handler_survives_a_cleanup_without_a_label(explorer):
    """A motion event after the dashboard is gone must not raise."""
    _render_days(explorer)
    explorer._cleanup_dashboard()
    explorer._on_dashboard_motion(SimpleNamespace(x=5, y=5))
