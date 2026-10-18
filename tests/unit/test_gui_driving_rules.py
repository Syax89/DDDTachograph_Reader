"""Daily Activities dashboard: days that break the EU driving-time rules.

Regulation (EC) 561/2006 art. 6(1) (more than 9 h of daily driving) and art. 7
(more than 4 h 30 min of continuous driving without a 45 min break). A flagged
day must be recognisable *without* colour — the same marker the Ev column
already uses goes into its Drive cell — and must say which rule it broke and by
how much in its row tooltip; a clean day must carry neither. The dashboard's
KPI row counts the flagged days of the whole file.

Two levels are checked: the widget logic with ``object.__new__`` plus mocks
(no display needed) and one real render into a ``TachoExplorer`` window, which
skips cleanly when there is no display — the same pattern as the other GUI
tests.

The real render also pins the two interactions that broke the flag once
(header-click sort and the filter box, both of which re-render every row): the
tint, the month-total emphasis and the violation marker must survive them, and
row's tooltips must stay attached to that row's *own* day rather than to
the position it happened to occupy before the reorder.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app.gui import TachoExplorer, _driving_rule_explanation
from app.i18n import _
from app.theme import DANGER, TEXT_SECONDARY
from core.utils.activity_stats import (
    DAILY_DRIVE_LIMIT_MIN,
    RULE_CONTINUOUS_DRIVING,
    RULE_DAILY_DRIVING,
    DrivingRuleBreach,
)

#: 10 h 15 min of unbroken driving: breaks art. 6(1) and art. 7 at once.
FLAGGED_DAY = {
    "date": "01/05/2025",
    "changes": [
        {"activity": "DRIVE", "time": "00:00", "slot": "First"},
        {"activity": "REST", "time": "10:15", "slot": "First"},
    ],
}

#: 8 h of driving in two 4 h stretches: inside both limits.
CLEAN_DAY = {
    "date": "02/05/2025",
    "changes": [
        {"activity": "DRIVE", "time": "00:00", "slot": "First"},
        {"activity": "REST", "time": "04:00", "slot": "First"},
        {"activity": "DRIVE", "time": "04:45", "slot": "First"},
        {"activity": "REST", "time": "08:45", "slot": "First"},
    ],
}

#: The driving-rule marker in the Drive cell. Not an emoji and not an icon:
#: a ttk.Treeview cell can hold text only, so the mark is an ASCII "!" (the
#: row tint and the cell tooltip carry the rest).
WARNING_MARK = "!"
WARNING_MARK_CELL = "  " + WARNING_MARK
KPI_CAPTION = _("Days over {hours} h").format(hours=DAILY_DRIVE_LIMIT_MIN // 60)

#: A card-file payload with the bits the row tooltips are built from: a vehicle
#: plate (the "# Vehicles" cell tooltip) and one event on the flagged day (the
#: "Ev" cell tooltip). A day in April gives the dashboard a second month, hence
#: a separator row next to the month-total rows.
CARD_DATA = {
    "metadata": {"is_vu": False},
    "vehicle": {"plate": "AB123CD", "registration_nation": "I", "vin": "WVWZZZ1J"},
    "events": [{"begin": "2025-05-01T09:30:00", "description": "Overspeed"}],
}
APRIL_DAY = {"date": "30/04/2025", "changes": [
    {"activity": "REST", "time": "00:00", "slot": "First"},
]}


def _fast_dashboard(activities, data=None):
    """Run ``_show_daily_summary``'s fast path with mocks; return its arguments.

    Returns ``(columns, table_rows, row_tags, tooltips, rule_tips, kpis)`` —
    exactly what the full render would hand to the table and the KPI cards.
    """
    app = object.__new__(TachoExplorer)
    app._vu_slot_filter = "Slot 1"
    app._show_empty = Mock()
    captured = []
    app._update_dashboard_in_place = Mock(
        side_effect=lambda *a, **kw: captured.append((a, kw)))
    app._show_daily_summary(activities, data or {"metadata": {"is_vu": False}},
                            _fast_refresh=True)
    assert captured, "the dashboard must render"
    args, kwargs = captured[-1]
    (_date_range, kpis, table_rows, row_tags,
     columns, tooltips, _ev_tooltips, _activities, _data) = args
    return (columns, table_rows, row_tags, tooltips,
            kwargs.get("rule_tips") or {}, kpis)


def _row_of(table_rows, date):
    for index, row in enumerate(table_rows):
        if row[0] == date:
            return index, row
    raise AssertionError(f"no row for {date}")


def _kpi(kpis, caption):
    for label, value, colour in kpis:
        if label == caption:
            return value, colour
    raise AssertionError(f"no KPI card {caption!r}")


# ── the flag itself ────────────────────────────────────────────────────────

def test_flagged_day_marks_the_drive_cell_and_explains_it_in_the_tooltip():
    """The marker is in the Drive cell; the tooltip names rule and value."""
    columns, rows, row_tags, tooltips, rule_tips, _kpis = _fast_dashboard([FLAGGED_DAY])
    index, row = _row_of(rows, "01/05/2025")

    drive_cell = row[columns.index(_("Drive"))]
    assert drive_cell == f"10h 15m{WARNING_MARK_CELL}"
    assert row_tags[index] == "flagged"
    tip = tooltips[index]
    assert "Daily driving 10h 15m \u2014 limit 9h 00m" in tip
    assert "Continuous driving 10h 15m without a 45 min break" in tip
    # the same explanation hangs off the Drive cell, where the marker sits
    assert "Daily driving 10h 15m" in rule_tips[index]


def test_clean_day_carries_no_marker_and_no_explanation():
    columns, rows, row_tags, tooltips, rule_tips, _kpis = _fast_dashboard([CLEAN_DAY])
    index, row = _row_of(rows, "02/05/2025")

    drive_cell = row[columns.index(_("Drive"))]
    assert drive_cell == "8h 00m"
    assert WARNING_MARK not in drive_cell
    assert row_tags[index] is None
    assert "Daily driving" not in tooltips.get(index, "")
    assert "Continuous driving" not in tooltips.get(index, "")
    assert rule_tips == {}, "a clean day has no rule tooltip to show"


def test_continuous_driving_alone_is_flagged_and_named():
    """4 h 31 min in one stretch: under the 9 h limit, still a breach."""
    day = {"date": "03/05/2025", "changes": [
        {"activity": "DRIVE", "time": "00:00", "slot": "First"},
        {"activity": "REST", "time": "04:31", "slot": "First"},
    ]}
    columns, rows, row_tags, tooltips, rule_tips, kpis = _fast_dashboard([day])
    index, row = _row_of(rows, "03/05/2025")

    assert row[columns.index(_("Drive"))] == f"4h 31m{WARNING_MARK_CELL}"
    assert row_tags[index] == "flagged"
    assert "Continuous driving 4h 31m without a 45 min break \u2014 limit 4h 30m" \
        in tooltips[index]
    assert "Daily driving" not in tooltips[index]
    # The KPI counts every flagged day, art. 7 only included: that is the
    # documented meaning of the card (see the caption comment in gui.py).
    assert _kpi(kpis, KPI_CAPTION) == ("1", DANGER)


def test_flagged_marker_survives_the_month_subtotal_rows():
    """The month total row and the Ev column are left exactly as they were."""
    columns, rows, row_tags, _tooltips, _rule_tips, _kpis = _fast_dashboard([FLAGGED_DAY])
    total_index = next(i for i, tag in enumerate(row_tags) if tag == "total")
    assert rows[total_index][columns.index(_("Drive"))] == "10h 15m"
    assert WARNING_MARK not in rows[total_index][columns.index(_("Drive"))]
    # the day's Ev column still only carries the events marker (none here)
    _index, row = _row_of(rows, "01/05/2025")
    assert row[columns.index(_("Ev"))] == ""


# ── the KPI card ───────────────────────────────────────────────────────────

def test_kpi_card_counts_the_flagged_days_in_danger():
    _c, _r, _t, _tips, _rule_tips, kpis = _fast_dashboard([FLAGGED_DAY, CLEAN_DAY])
    value, colour = _kpi(kpis, KPI_CAPTION)
    assert value == "1"
    assert colour == DANGER


def test_kpi_card_is_neutral_when_nothing_is_flagged():
    _c, _r, _t, _tips, _rule_tips, kpis = _fast_dashboard([CLEAN_DAY])
    value, colour = _kpi(kpis, KPI_CAPTION)
    assert value == "0"
    assert colour == TEXT_SECONDARY


def test_kpi_caption_names_the_legal_daily_limit():
    """Art. 6(1) is nine hours; the caption is formatted from the constant."""
    assert KPI_CAPTION == "Days over 9 h"


# ── the tooltip text helper ────────────────────────────────────────────────

def test_explanation_states_measured_value_and_limit_per_rule():
    breaches = (
        DrivingRuleBreach(RULE_DAILY_DRIVING, "First", 615, DAILY_DRIVE_LIMIT_MIN),
        DrivingRuleBreach(RULE_CONTINUOUS_DRIVING, "First", 615, 270),
    )
    lines = _driving_rule_explanation(breaches).split("\n")
    assert lines == [
        "Daily driving 10h 15m \u2014 limit 9h 00m",
        "Continuous driving 10h 15m without a 45 min break \u2014 limit 4h 30m",
    ]


def test_explanation_of_a_clean_day_is_empty():
    assert _driving_rule_explanation(()) == ""


# ── a real render (skips without a display) ────────────────────────────────

@pytest.fixture
def explorer():
    """A real TachoExplorer window (skipped when there is no display)."""
    tkinter = pytest.importorskip("tkinter")
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


def _rendered_rows(app):
    """Return ``[(date, values, tags)]`` for every row currently in the table."""
    return [(list(app.table.tv.item(iid, "values"))[0],
             list(app.table.tv.item(iid, "values")),
             app.table.tv.item(iid, "tags"))
            for iid in app.table.tv.get_children("")]


def _kpi_widget(app, caption):
    """Return the value label of the dashboard KPI card with ``caption``."""
    for card in app._kpi_frame.winfo_children():
        if not isinstance(card, tk.Frame):
            continue
        labels = [w for w in card.winfo_children() if isinstance(w, tk.Label)]
        if len(labels) >= 2 and labels[0].cget("text") == caption:
            return labels[1]
    raise AssertionError(f"no KPI card {caption!r} in the dashboard")


def test_rendered_dashboard_tints_and_marks_the_flagged_row(explorer):
    """End to end: the row is tagged, the marker is in the cell, the KPI counts."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY],
                                 {"metadata": {"is_vu": False}})

    drive_col = list(explorer.table._cols).index(_("Drive"))
    rows = _rendered_rows(explorer)
    by_date = {date: (values, tags) for date, values, tags in rows}

    flagged_values, flagged_tags = by_date["01/05/2025"]
    assert flagged_values[drive_col] == f"10h 15m{WARNING_MARK_CELL}"
    # ttk.Treeview styles whole rows only: the violation is a row tint.
    assert "flagged" in flagged_tags
    clean_values, clean_tags = by_date["02/05/2025"]
    assert clean_values[drive_col] == "8h 00m"
    assert "flagged" not in clean_tags

    # The explanation hangs off the flagged row's own tooltip, nowhere else.
    order = [date for date, _values, _tags in rows]
    tips = explorer._dashboard_tooltips
    assert "Daily driving 10h 15m" in tips[order.index("01/05/2025")]
    assert "Daily driving" not in tips.get(order.index("02/05/2025"), "")

    value_lbl = _kpi_widget(explorer, KPI_CAPTION)
    assert value_lbl.cget("text") == "1"
    assert value_lbl.cget("foreground") == DANGER


def test_rendered_dashboard_kpi_returns_to_neutral_without_a_flagged_day(explorer):
    """The card's colour follows the value, also on a slot-toggle refresh."""
    explorer._show_daily_summary([FLAGGED_DAY], {"metadata": {"is_vu": False}})
    assert _kpi_widget(explorer, KPI_CAPTION).cget("foreground") == DANGER

    explorer._show_daily_summary([CLEAN_DAY], {"metadata": {"is_vu": False}},
                                 _fast_refresh=True)
    value_lbl = _kpi_widget(explorer, KPI_CAPTION)
    assert value_lbl.cget("text") == "0"
    assert value_lbl.cget("foreground") == TEXT_SECONDARY


# ── sorting and filtering: the flag must survive them ──────────────────────

def _displayed(app):
    """``[(values, tags)]`` of the rows currently on screen, in display order."""
    return [(list(app.table.tv.item(iid, "values")),
             app.table.tv.item(iid, "tags"))
            for iid in app.table.tv.get_children("")]


def _row_with_date(app, date):
    """Return ``(iid, values, tags)`` of the displayed row whose Date cell is it."""
    for iid in app.table.tv.get_children(""):
        values = list(app.table.tv.item(iid, "values"))
        if values and values[0] == date:
            return iid, values, app.table.tv.item(iid, "tags")
    raise AssertionError(f"no displayed row for {date}")


def _date_order(app):
    return [values[0] for values, _tags in _displayed(app)]


def _apply_filter_now(app, text):
    """Set the filter box and run the re-render at once (the box debounces)."""
    app.table.filter_var.set(text)
    if app.table._filter_after_id is not None:
        app.table.tv.after_cancel(app.table._filter_after_id)
        app.table._filter_after_id = None
    app.table._apply_filter()


def _hover(app, iid, column):
    """Hover one cell of a displayed row; return the tooltip text shown.

    The coordinates come from the widget's own layout (``bbox``) and are handed
    to the real motion handler, which resolves them back with ``identify_row``
    and ``identify_column`` — so this exercises the same row/column lookup the
    pointer drives, not a stub of it.
    """
    column_index = list(app.table._cols).index(column) + 1
    box = app.table.tv.bbox(iid, column=f"#{column_index}")
    assert box, f"row {iid!r} must be laid out to be hovered"
    x, y, width, height = box
    # The middle of the cell: a real (x, y) the widget itself resolves back to
    # this row and column, so identify_row/identify_column do the real lookup.
    app._on_dashboard_motion(
        SimpleNamespace(x=x + width // 2, y=y + height // 2))
    label = app._tooltip_lbl
    return label.cget("text") if label.winfo_manager() else ""


def test_flagged_tint_and_month_total_tags_survive_a_header_sort(explorer):
    """A header click re-renders every row: the tags must travel with them."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY, APRIL_DAY], CARD_DATA)
    explorer.update()
    assert "flagged" in _row_with_date(explorer, "01/05/2025")[2]
    # before the sort the newest day is on top, the month emphasis below it
    assert _date_order(explorer).index("02/05/2025") < \
        _date_order(explorer).index("01/05/2025")

    explorer.table._sort_by(_("Date"))      # ascending: chronological order
    explorer.update()

    # only the dated rows follow the chronological key; the month label and the
    # month-total rows sort after them, and must keep their own tags
    dated = [d for d in _date_order(explorer) if d.count("/") == 2]
    assert dated == ["30/04/2025", "01/05/2025", "02/05/2025"]
    _iid, values, tags = _row_with_date(explorer, "01/05/2025")
    assert "flagged" in tags
    assert "flagged" not in _row_with_date(explorer, "02/05/2025")[2]
    # the marker is in the cell text, which a sort never rewrites
    drive_col = list(explorer.table._cols).index(_("Drive"))
    assert values[drive_col] == f"10h 15m{WARNING_MARK_CELL}"

    # the pre-existing row emphasis keeps working through the same mechanism
    tags_of_rows = [tags for _values, tags in _displayed(explorer)]
    assert sum("total" in tags for tags in tags_of_rows) == 2       # two months
    assert sum("separator" in tags for tags in tags_of_rows) == 1
    assert sum("flagged" in tags for tags in tags_of_rows) == 1


def test_flagged_tint_and_tooltip_survive_a_filter(explorer):
    """The filter re-renders the rows too; the surviving flag keeps its own tip."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    _apply_filter_now(explorer, "01/05/2025")
    explorer.update()

    order = _date_order(explorer)
    assert "02/05/2025" not in order, "the clean day must be filtered out"
    iid, values, tags = _row_with_date(explorer, "01/05/2025")
    assert "flagged" in tags
    drive_col = list(explorer.table._cols).index(_("Drive"))
    assert values[drive_col] == f"10h 15m{WARNING_MARK_CELL}"
    assert "Daily driving 10h 15m" in _hover(explorer, iid, _("Drive"))

    # clearing the box brings the clean day back, still untinted and tip-free
    _apply_filter_now(explorer, "")
    explorer.update()
    assert set(_date_order(explorer)) >= {"01/05/2025", "02/05/2025"}
    assert "flagged" not in _row_with_date(explorer, "02/05/2025")[2]


def test_drive_cell_tooltip_follows_the_flagged_day_through_a_sort(explorer):
    """Where the marker sits, the explanation must be: on that day, and only there.

    Reproduces the reported failure exactly — 01/05 flagged, 02/05 clean, sort
    Date ascending so the flagged day becomes display row 0 — and checks both
    directions: the flagged row still explains itself, the clean row stays
    silent even though it now occupies the flagged row's old position.
    """
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    explorer.table._sort_by(_("Date"))
    explorer.update()

    flagged_iid, _values, flagged_tags = _row_with_date(explorer, "01/05/2025")
    clean_iid, _values, _tags = _row_with_date(explorer, "02/05/2025")
    children = explorer.table.tv.get_children("")
    assert children.index(flagged_iid) == 0, "the flagged day must now be row 0"
    assert children.index(clean_iid) == 1
    assert "flagged" in flagged_tags

    flagged_tip = _hover(explorer, flagged_iid, _("Drive"))
    assert "Daily driving 10h 15m \u2014 limit 9h 00m" in flagged_tip
    assert "Continuous driving 10h 15m without a 45 min break" in flagged_tip

    clean_tip = _hover(explorer, clean_iid, _("Drive"))
    assert "Daily driving" not in clean_tip
    assert "Continuous driving" not in clean_tip
    assert clean_tip == "", "a clean day must not open a violation tooltip"


def test_drive_cell_tooltip_stays_with_its_day_after_a_filter(explorer):
    """Same guarantee when the rows are rebuilt by the filter box."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()
    _apply_filter_now(explorer, "02/05/2025")
    explorer.update()

    clean_iid, _values, _tags = _row_with_date(explorer, "02/05/2025")
    assert _hover(explorer, clean_iid, _("Drive")) == ""

    _apply_filter_now(explorer, "01/05/2025")
    explorer.update()
    flagged_iid, _values, _tags = _row_with_date(explorer, "01/05/2025")
    assert "Daily driving 10h 15m" in _hover(explorer, flagged_iid, _("Drive"))


def test_vehicle_and_ev_tooltips_keep_working_after_a_sort(explorer):
    """The driver/vehicle and Ev cells keep their own tooltips, per day."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()
    explorer.table._sort_by(_("Date"))
    explorer.update()

    flagged_iid, _values, _tags = _row_with_date(explorer, "01/05/2025")
    clean_iid, _values, _tags = _row_with_date(explorer, "02/05/2025")

    # the vehicle cell still names the plate, plus the rule on the flagged day
    vehicle_tip = _hover(explorer, flagged_iid, _("# Vehicles"))
    assert "AB123CD" in vehicle_tip
    assert "Daily driving 10h 15m" in vehicle_tip
    clean_vehicle_tip = _hover(explorer, clean_iid, _("# Vehicles"))
    assert "AB123CD" in clean_vehicle_tip
    assert "Daily driving" not in clean_vehicle_tip

    # the Ev cell still explains the day's event, on that day only
    ev_tip = _hover(explorer, flagged_iid, _("Ev"))
    assert "09:30" in ev_tip and "Overspeed" in ev_tip
    assert _hover(explorer, clean_iid, _("Ev")) == ""


def test_tooltip_is_hidden_when_the_pointer_leaves_the_tooltip_cells(explorer):
    """Moving from the Drive cell to a cell without a tooltip closes the box."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()
    flagged_iid, _values, _tags = _row_with_date(explorer, "01/05/2025")

    assert "Daily driving 10h 15m" in _hover(explorer, flagged_iid, _("Drive"))
    assert _hover(explorer, flagged_iid, _("Km")) == "", \
        "a cell with no tooltip must not keep the previous one on screen"
