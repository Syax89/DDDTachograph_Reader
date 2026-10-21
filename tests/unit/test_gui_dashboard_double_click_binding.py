"""A view that is not a dashboard must not keep the dashboard's double-click.

``_show_daily_summary`` binds ``<Double-1>`` on the table so a day row opens the
day-detail window. ``_cleanup_dashboard`` — the one path every view switch goes
through — unbound only ``<Motion>``, so the handler stayed armed in every later
plain table, still closing over the previous dashboard's ``_dashboard_data``
and ``_dashboard_activity_list``. Reproduced on a real window before the fix:
after leaving *Daily Activities*, ``table.tv.bind("<Double-1>")`` was still
``_on_dashboard_double_click`` and the day list of the previous dashboard was
still on the window; opening a second file in that state left the handler
pointing at the *first* file's parse tree.
"""
import pytest

pytest.importorskip("tkinter")

import tkinter as tk

import app.gui as gui
from app.gui import TachoExplorer
from tests.unit.test_gui_driving_rules import CARD_DATA, CLEAN_DAY, FLAGGED_DAY

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("DISPLAY"), reason="needs a display")

#: What the window must no longer hold once the dashboard is gone.
DASHBOARD_STATE = ("_dashboard_activity_list", "_dashboard_data",
                   "_dashboard_is_vu", "_dashboard_tooltips",
                   "_dashboard_ev_tips", "_dashboard_rule_tips",
                   "_dashboard_card_day_km")


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


def _render_dashboard(app):
    app._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    app.update()


def test_the_dashboard_binds_the_double_click(explorer):
    _render_dashboard(explorer)
    assert explorer.table.tv.bind("<Double-1>")


def test_leaving_the_dashboard_unbinds_the_double_click(explorer):
    _render_dashboard(explorer)
    explorer._cleanup_dashboard()
    assert explorer.table.tv.bind("<Double-1>") == ""
    assert explorer.table.tv.bind("<Motion>") == ""


def test_leaving_the_dashboard_drops_its_state(explorer):
    _render_dashboard(explorer)
    assert explorer._dashboard_activity_list
    explorer._cleanup_dashboard()
    for attribute in DASHBOARD_STATE:
        assert getattr(explorer, attribute, None) in (None, [], {}), attribute


def test_a_plain_table_view_has_no_dashboard_handler(explorer):
    """End to end through the real view switch: the handler is gone.

    ``_show_table`` is what a click on any non-dashboard node runs, and it is
    the path a user takes from *Daily Activities* to an ordinary table of the
    same file (or, after opening another file, of that one).
    """
    _render_dashboard(explorer)
    explorer._show_table("Section", ["Field", "Value"], [["a", "b"]])
    assert explorer.table.tv.bind("<Double-1>") == ""
    assert getattr(explorer, "_dashboard_data", None) is None


def test_the_summary_view_has_no_dashboard_handler(explorer):
    _render_dashboard(explorer)
    explorer._show_summary("Section", ["Field", "Value"], [["a", "b"]], "")
    assert explorer.table.tv.bind("<Double-1>") == ""
    assert getattr(explorer, "_dashboard_data", None) is None


def test_the_cleanup_survives_a_second_call(explorer):
    _render_dashboard(explorer)
    explorer._cleanup_dashboard()
    explorer._cleanup_dashboard()          # idempotent, no TclError
    assert explorer.table.tv.bind("<Double-1>") == ""


def test_the_module_still_exposes_the_handler(explorer):
    """The handler itself is untouched — only its lifetime changed."""
    assert gui.TachoExplorer._on_dashboard_double_click.__name__ == \
        "_on_dashboard_double_click"
