"""Chrome of the details table: heading bar, horizontal scrollbar, dividers.

The summary panel (Driver / Cardholder, Vehicle, …) is a list of labelled rows,
not a two-column table: an empty heading bar above it read as a rendering
glitch, and a horizontal scrollbar sat under tables that fitted. Section
dividers were rows of 40 dash characters that stopped well short of the pane
and looked like typed text rather than a rule.
"""
import inspect

import pytest

pytest.importorskip("tkinter")

import tkinter as tk  # noqa: E402

from app import gui  # noqa: E402
from app.gui import DataTable  # noqa: E402


@pytest.fixture
def table():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    widget = DataTable(root)
    widget.pack(fill=tk.BOTH, expand=True)
    yield widget
    root.destroy()


def test_a_data_table_keeps_its_heading_bar(table):
    """The summary panel hides the heading bar; loading a table brings it back."""
    table.tv["show"] = ""
    table.show("Days", ["Date", "Km"], [["01/05/2025", "120"]])
    assert "headings" in str(table.tv["show"])


def test_the_scrollbar_follows_whether_a_column_runs_off_the_edge(table):
    """The bar is gridded on demand, so a table that fits shows no chrome."""

    class Shows:
        """Stands in for the treeview: only xview() decides the bar."""

        value = (0.0, 1.0)

        def xview(self):
            return self.value

    real = table.tv
    fake = Shows()
    table.tv = fake
    try:
        table._sync_xscroll()
        assert table._xsb.winfo_manager() == ""

        fake.value = (0.0, 0.6)
        table._sync_xscroll()
        assert table._xsb.winfo_manager() == "grid"

        fake.value = (0.0, 1.0)
        table._sync_xscroll()
        assert table._xsb.winfo_manager() == ""
    finally:
        table.tv = real


def test_the_summary_dividers_are_not_rows_of_dash_characters():
    """A dash row was the old separator; the bands and spacers replaced it."""
    assert '"\\u2500" * 40' not in inspect.getsource(gui.TachoExplorer)
