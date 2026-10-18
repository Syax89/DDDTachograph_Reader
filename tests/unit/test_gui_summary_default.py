"""The file overview ("Summary") is the node a freshly parsed file opens on.

A first-time user used to land straight in a technical section — Driver /
Cardholder for a card, Vehicle / Sensor for a VU — with no page saying what the
file actually is. ``app/gui.py`` now builds one extra top-level node, first in
the tree, rendered by the *existing* summary machinery
(``_add_section(..., summary=True)``, the same Field/Value panel the
Driver/Cardholder and Vehicle sections use), and points ``_auto_select_iid`` at
it for cards and VUs alike.

What is pinned here, against a real ``TachoExplorer`` (skipped cleanly when no
display is available, the same pattern as ``test_gui_driving_rules.py``):

* the node is first, keeps the summary renderer, and is what a parse selects;
* its rows carry the file period, the activity totals and the number of days the
  driving-time rules flag — cross-checked against
  ``core.utils.activity_stats.evaluate_driving_rules`` itself, so the overview
  cannot silently disagree with the evaluator;
* the applied limits are stated one short row each, derived from the
  ``core.utils.activity_stats`` constants (moving them moves the rows) and
  measured against the panel's own value column at the minimum window
  (900x560), where the single-sentence row this replaced was clipped;
* a file whose driver fields are all the ``N/A`` sentinel gains no empty driver
  block, and one that recorded no vehicle gains no vehicle block;
* the section that used to be auto-selected still exists and still renders its
  own panel when chosen — nothing was moved, renamed or removed;
* a file whose overview cannot be built falls back to the previous behaviour
  instead of leaving the pane blank;
* the no-file empty state is untouched;
* the real parse path (a generated mock ``.ddd`` in ``tests/mock_data``) lands
  on the same node.

``tests/unit/conftest.py`` pins the settings file and the translator for the
whole directory, so no real user settings are read or written.
"""
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import app.gui as gui  # noqa: E402
import app.i18n as i18n  # noqa: E402
from core.utils.activity_stats import evaluate_driving_rules  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DIR = REPO_ROOT / "tests" / "mock_data"

#: The node the overview is titled with (the emoji matches every other
#: top-level section title in the tree).
SUMMARY_TITLE = i18n._("\U0001f4cb  Summary")
FILE_INFO_TITLE = i18n._("\U0001f4c4  File Info")
#: The section that used to be auto-selected for a card / a VU.
DRIVER_TITLE = i18n._("\U0001f464  Driver / Cardholder")
VEHICLE_TITLE = i18n._("\U0001f69a  Vehicle")

#: The three rows the overview states the applied limits in — one short
#: label/value row each (see ``test_the_rules_rows_fit_the_value_column_at_the_
#: minimum_window`` for why they are not one sentence).
LIMIT_ROWS = (
    "  Daily driving limit",
    "  Continuous driving limit",
    "  Break that resets it",
)

#: ``TachoExplorer.minsize(900, 560)``: the smallest window the product
#: supports, and the geometry the single-sentence limits row was clipped at.
MINIMUM_SIZE = "900x560"

#: 10 h 15 min of unbroken driving: breaks Reg. (EC) 561/2006 art. 6(1) and
#: art. 7 at once, so the file has exactly one flagged day.
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

#: A day of rest only: no driving, no violation.
REST_DAY = {
    "date": "03/05/2025",
    "changes": [{"activity": "REST", "time": "00:00", "slot": "First"}],
}

#: Driver fields as an untouched ``TachoResult`` leaves them
#: (``core/registry/models.py``): the truthy "N/A" string, not an empty value.
NO_DRIVER = {
    "surname": "N/A",
    "firstname": "N/A",
    "card_number": "N/A",
    "issuing_nation": "N/A",
    "expiry_date": "N/A",
}


def card_data(**overrides):
    """A card-file payload rich enough to build every overview block."""
    data = {
        "metadata": {
            "is_vu": False,
            "generation": "G2 (Smart)",
            "file_size_bytes": 1234,
            "parsed_at": "2026-01-01T09:00:00",
            "app_version": "2.5.0",
            "integrity_check": "Verified",
        },
        "coverage": {
            "byte_accounted_pct": 100.0,
            "byte_accounted_bytes": 1234,
            "unknown_bytes": 0,
            "unknown_pct": 0.0,
            "structurally_identified_pct": 100.0,
        },
        "driver": {
            "surname": "BIANCHI",
            "firstname": "LUCA",
            "card_number": "I100000168598002",
            "issuing_nation": "I",
            "expiry_date": "2027-04-30",
        },
        "vehicle": {
            "plate": "AB123CD",
            "vin": "WVWZZZ1JZ3W386752",
            "registration_nation": "I",
        },
        "activities": [FLAGGED_DAY, CLEAN_DAY, REST_DAY],
        "raw_tags": {},
        "generations": {},
    }
    data.update(overrides)
    return data


def vu_data(**overrides):
    """A VU payload: no driver card, a recorded vehicle, one vehicle day."""
    data = {
        "metadata": {
            "is_vu": True,
            "origin": "vehicle_unit",
            "generation": "G2 (Smart)",
            "file_size_bytes": 2048,
            "integrity_check": "Partial (VU - chain ok)",
        },
        "driver": dict(NO_DRIVER),
        "vehicle": {
            "plate": "XY987ZW",
            "vin": "WDB9634031L123456",
            "registration_nation": "D",
        },
        "activities": [CLEAN_DAY],
        "raw_tags": {},
        "generations": {},
    }
    data.update(overrides)
    return data


class _Dialogs:
    """Message boxes would block a headless run: record them instead."""

    calls: list = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: _Dialogs.calls.append((name, args))


def new_explorer(monkeypatch):
    """A real TachoExplorer, or a clean skip when there is no display."""
    _Dialogs.calls = []
    monkeypatch.setattr(gui, "messagebox", _Dialogs())
    try:
        return gui.TachoExplorer()
    except gui.tk.TclError:
        pytest.skip("no display available")


def close(app):
    """Close a window the way the product does, cancelling every timer."""
    try:
        for after_id in app.tk.call("after", "info"):
            app.tk.call("after", "cancel", after_id)
    except gui.tk.TclError:
        pass
    try:
        app.destroy()
    except gui.tk.TclError:
        pass


@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        close(app)


def open_file(app, data, path="/tmp/fixture.ddd"):
    """Drive the real render path (``_parse_done``) and settle the event loop."""
    app._parse_done(data, path)
    app.update()
    return app


def tree_titles(app):
    """Top-level node titles, in tree order."""
    return [app.tree.item(iid, "text") for iid in app.tree.get_children("")]


def node_by_title(app, title):
    """The iid of the top-level node with *title*."""
    for iid in app.tree.get_children(""):
        if app.tree.item(iid, "text") == title:
            return iid
    raise AssertionError(f"no top-level node {title!r} in {tree_titles(app)}")


def summary_rows(app):
    """The overview's ``(label, value, is_header)`` rows."""
    payload = app._payloads[app._auto_select_iid]
    assert payload[4] is True, "the overview must use the summary renderer"
    return payload[2]


def row_value(rows, label):
    """The value of the row labelled *label* (an AssertionError if absent)."""
    for row in rows:
        if row[0] == label:
            return row[1]
    raise AssertionError(f"no summary row {label!r} in "
                         f"{[row[0] for row in rows]}")


def rendered(app):
    """``[(field, value, tags)]`` of the rows currently on screen."""
    return [(list(app.table.tv.item(iid, "values"))[0],
             list(app.table.tv.item(iid, "values"))[1],
             app.table.tv.item(iid, "tags"))
            for iid in app.table.tv.get_children("")]


def rendered_value(app, label):
    """The value cell of the rendered row labelled *label*."""
    for field, value, _tags in rendered(app):
        if field == label:
            return value
    raise AssertionError(f"no rendered row {label!r} in "
                         f"{[row[0] for row in rendered(app)]}")


def value_column_width(app):
    """On-screen width of the summary panel's Value column, in pixels.

    ``tv.column("Value", "width")`` only returns the un-stretched request
    (``_px(100)``): the column itself is ``stretch=True``, so its real width is
    the cell width the widget lays out — which is what Tk clips the text to.
    """
    for iid in app.table.tv.get_children(""):
        box = app.table.tv.bbox(iid, "Value")
        if box:
            return box[2]
    return int(app.table.tv.column("Value", "width"))


def select(app, iid):
    """Select a node the way a click does and let the panel render."""
    app.tree.selection_set(iid)
    app.update()


# ── the node itself ───────────────────────────────────────────────────────

def test_summary_is_the_first_node_and_file_info_keeps_its_place(explorer):
    open_file(explorer, card_data())

    titles = tree_titles(explorer)
    assert titles[0] == SUMMARY_TITLE
    assert titles[1] == FILE_INFO_TITLE, \
        "the existing nodes keep their order, the overview is prepended"


def test_summary_uses_the_existing_summary_panel(explorer):
    """Not a new widget: the same ``summary=True`` Field/Value panel."""
    open_file(explorer, card_data())
    iid = node_by_title(explorer, SUMMARY_TITLE)

    assert explorer._payloads[iid][4] is True
    assert explorer._payloads[iid][1] == [i18n._("Field"), i18n._("Value")]
    # ... rendered by _show_summary: no heading bar, summary mode on.
    assert explorer.table.tv.cget("show") == ""
    assert explorer.table._summary_mode is True
    assert explorer.table.title_lbl.cget("text") == SUMMARY_TITLE


def test_summary_is_the_node_selected_after_a_parse(explorer):
    open_file(explorer, card_data())

    selection = explorer.tree.selection()
    assert selection, "a parse must select a node"
    assert explorer.tree.item(selection[0], "text") == SUMMARY_TITLE
    assert selection[0] == explorer.tree.get_children("")[0]


def test_summary_blocks_are_all_present_in_order(explorer):
    open_file(explorer, card_data())
    headers = [row[0] for row in summary_rows(explorer) if row[2] and row[0]]

    assert headers == [
        i18n._("\U0001f4c4  FILE"),
        i18n._("\U0001f464  CARDHOLDER"),
        i18n._("\U0001f697  VEHICLE"),
        i18n._("\U0001f4ca  TOTALS"),
        i18n._("\u23f1\ufe0f  DRIVING-TIME RULES"),
        i18n._("\U0001f512  INTEGRITY"),
    ]


# ── the facts the overview states ─────────────────────────────────────────

def test_file_block_names_the_file_and_the_period_it_covers(explorer):
    open_file(explorer, card_data(), path="/data/driver_card.ddd")
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Filename")) == "driver_card.ddd"
    assert row_value(rows, i18n._("  Generation")) == "G2 (Smart)"
    assert row_value(rows, i18n._("  Origin")) == i18n._("Driver Card")
    assert row_value(rows, i18n._("  Period covered")) == \
        i18n._("{first} \u2192 {last}").format(first="01/05/2025",
                                                 last="03/05/2025")


def test_file_block_says_so_when_there_are_no_activity_days(explorer):
    open_file(explorer, card_data(activities=[]))

    assert row_value(summary_rows(explorer), i18n._("  Period covered")) == \
        i18n._("No activity data available.")


def test_totals_block_sums_the_file_with_the_shared_duration_formatter(explorer):
    """18 h 15 m of drive over three days: 10 h 15 m + 8 h + a day of rest."""
    open_file(explorer, card_data())
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Drive")) == "18h 15m"
    assert row_value(rows, i18n._("  Work")) == "0h 00m"
    assert row_value(rows, i18n._("  Rest")) == "53h 45m"
    assert row_value(rows, i18n._("  Available")) == "0h 00m"
    assert row_value(rows, i18n._("  Days with activity")) == "3"


def test_driving_time_rules_count_the_flagged_days(explorer):
    """One flagged day — and the number is the evaluator's own verdict."""
    open_file(explorer, card_data())
    rows = summary_rows(explorer)

    expected = sum(1 for day in (FLAGGED_DAY, CLEAN_DAY, REST_DAY)
                   if evaluate_driving_rules(day["changes"]).flagged)
    assert expected == 1, "the fixture must contain exactly one violation"
    assert row_value(rows, i18n._("  Days flagged")) == str(expected)


def test_a_clean_file_reports_a_zero_and_never_a_warning(explorer):
    """Zero flagged days is the good news: a plain count, no ⚠ marker."""
    open_file(explorer, card_data(activities=[CLEAN_DAY, REST_DAY]))
    rows = summary_rows(explorer)

    flagged = row_value(rows, i18n._("  Days flagged"))
    assert flagged == "0"
    assert "\u26a0" not in flagged
    for label in LIMIT_ROWS:
        assert "\u26a0" not in row_value(rows, i18n._(label))


def test_rules_block_states_the_limits_it_applied(explorer):
    """One short row per limit, formatted exactly as the panel formats them."""
    open_file(explorer, card_data())
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Daily driving limit")) == \
        gui._fmt_duration_minutes(gui.DAILY_DRIVE_LIMIT_MIN)
    assert row_value(rows, i18n._("  Continuous driving limit")) == \
        gui._fmt_duration_minutes(gui.CONTINUOUS_DRIVE_LIMIT_MIN)
    assert row_value(rows, i18n._("  Break that resets it")) == \
        i18n._("{minutes} min").format(minutes=gui.QUALIFYING_BREAK_MIN)


def test_rules_block_reads_the_limits_from_the_constants(explorer, monkeypatch):
    """Move the three constants and the rows follow: no literal is baked in.

    Together with the default-value assertions above this pins both halves of
    the contract — the numbers are not hardcoded (they change with the
    constants) and are not formatted ad hoc (they use the shared duration
    formatter and the ``{minutes} min`` message).
    """
    monkeypatch.setattr(gui, "DAILY_DRIVE_LIMIT_MIN", 600)
    monkeypatch.setattr(gui, "CONTINUOUS_DRIVE_LIMIT_MIN", 240)
    monkeypatch.setattr(gui, "QUALIFYING_BREAK_MIN", 60)

    open_file(explorer, card_data())
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Daily driving limit")) == "10h 00m"
    assert row_value(rows, i18n._("  Continuous driving limit")) == "4h 00m"
    assert row_value(rows, i18n._("  Break that resets it")) == "60 min"


def test_the_rules_rows_fit_the_value_column_at_the_minimum_window(explorer):
    """The row this replaced was clipped at 900x560 — the app's own minsize.

    The overview used to state both limits in one sentence ("9h 00m daily
    driving \u00b7 4h 30m continuous without a 45 min break"), 439 px of text
    in the 187 px value column the summary panel gets at the smallest window it
    supports. The panel deliberately never auto-fits (``_show_summary``) and Tk
    *clips* an overlong cell instead of wrapping it, so that row was cut off
    mid-string. Measured here on the real panel: the value cell's own width
    (``bbox``) against the font's measurement of every rules row.
    """
    explorer.geometry(MINIMUM_SIZE)
    explorer.update()
    open_file(explorer, card_data())
    explorer.update()

    value_w = value_column_width(explorer)
    assert value_w > 0, "the panel must be laid out to be measured"
    font = gui.tkfont.nametofont("TkDefaultFont")
    for label in LIMIT_ROWS:
        text = rendered_value(explorer, i18n._(label))
        assert font.measure(text) <= value_w, (
            f"{label!r} ({text!r}) is {font.measure(text)} px wide in a "
            f"{value_w} px value column at {MINIMUM_SIZE}")


def test_integrity_block_repeats_the_file_info_verdict_and_coverage(explorer):
    open_file(explorer, card_data())
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Status")) == i18n._("No EF signatures verified")
    assert row_value(rows, i18n._("  Byte-accounted coverage")).startswith("100.0% ")
    # The overview may not invent a verdict of its own.
    info = explorer._build_file_info(explorer.current_data)
    assert row_value(rows, i18n._("  Status")) == info[i18n._("Integrity")]


def test_coverage_row_is_absent_when_the_parse_reported_none(explorer):
    data = card_data()
    data.pop("coverage")
    open_file(explorer, data)
    labels = [row[0] for row in summary_rows(explorer)]

    assert i18n._("  Byte-accounted coverage") not in labels
    assert i18n._("  Status") in labels


# ── blocks that must not appear empty ─────────────────────────────────────

def test_a_file_without_driver_data_gains_no_driver_block(explorer):
    """All driver fields at the "N/A" sentinel: no empty CARDHOLDER block."""
    open_file(explorer, card_data(driver=dict(NO_DRIVER)))
    rows = summary_rows(explorer)

    assert i18n._("\U0001f464  CARDHOLDER") not in [row[0] for row in rows]
    assert DRIVER_TITLE not in tree_titles(explorer), \
        "and the pre-existing no-driver rule is unchanged"
    # The rest of the overview is still there — only the driver block is gone.
    assert tree_titles(explorer)[0] == SUMMARY_TITLE
    assert row_value(rows, i18n._("  Days flagged")) == "1"


def test_a_card_that_recorded_no_vehicle_gains_no_vehicle_block(explorer):
    open_file(explorer, card_data(vehicle={
        "plate": "N/A", "vin": "N/A", "registration_nation": "N/A"}))
    rows = summary_rows(explorer)

    assert i18n._("\U0001f697  VEHICLE") not in [row[0] for row in rows]


def test_a_card_that_recorded_a_vehicle_shows_plate_vin_and_registration(explorer):
    open_file(explorer, card_data())
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Plate")) == "AB123CD"
    assert row_value(rows, i18n._("  VIN")) == "WVWZZZ1JZ3W386752"
    assert row_value(rows, i18n._("  Registration")) == "Italy"


def test_a_vehicle_unit_shows_its_vehicle_facts(explorer):
    open_file(explorer, vu_data())
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Plate")) == "XY987ZW"
    assert row_value(rows, i18n._("  Registration")) == "Germany"
    assert row_value(rows, i18n._("  Origin")) == i18n._("Vehicle Unit (VU)")


# ── nothing that was there before has moved or disappeared ────────────────

def test_the_previously_auto_selected_card_section_still_renders(explorer):
    open_file(explorer, card_data())

    select(explorer, node_by_title(explorer, DRIVER_TITLE))
    assert explorer.table.title_lbl.cget("text") == DRIVER_TITLE
    assert rendered_value(explorer, i18n._("  Name")) == "LUCA BIANCHI"
    assert rendered_value(explorer, i18n._("  Card number")) == "I100000168598002"
    assert i18n._("\U0001faaa  CARD DETAILS") in [row[0] for row in rendered(explorer)]


def test_the_previously_auto_selected_vu_section_still_renders(explorer):
    open_file(explorer, vu_data())

    select(explorer, node_by_title(explorer, VEHICLE_TITLE))
    assert explorer.table.title_lbl.cget("text") == VEHICLE_TITLE
    assert rendered_value(explorer, i18n._("  Plate")) == "XY987ZW"


def test_selecting_the_overview_again_after_another_section(explorer):
    open_file(explorer, card_data())
    select(explorer, node_by_title(explorer, DRIVER_TITLE))

    select(explorer, node_by_title(explorer, SUMMARY_TITLE))
    assert explorer.table._summary_mode is True
    assert rendered_value(explorer, i18n._("  Days flagged")) == "1"


def test_the_translate_data_rebuild_keeps_the_overview_selected(explorer):
    """_refresh_data_text repopulates the tree and re-selects the same node."""
    open_file(explorer, card_data())

    explorer._refresh_data_text()
    explorer.update()

    selection = explorer.tree.selection()
    assert selection[0] == explorer.tree.get_children("")[0]
    assert explorer.tree.item(selection[0], "text") == SUMMARY_TITLE
    assert rendered_value(explorer, i18n._("  Days flagged")) == "1"


# ── fallbacks ─────────────────────────────────────────────────────────────

def test_an_unbuildable_overview_falls_back_to_the_previous_default(
        explorer, monkeypatch):
    """A file whose overview cannot be built keeps the old landing section."""
    def boom(_self, _data):
        raise RuntimeError("overview unavailable")

    monkeypatch.setattr(gui.TachoExplorer, "_build_overview_summary", boom)
    open_file(explorer, card_data())

    titles = tree_titles(explorer)
    assert SUMMARY_TITLE not in titles
    # The old default (Driver / Cardholder for a card) is selected again, and
    # the pane is rendered — never blank.
    selection = explorer.tree.selection()
    assert explorer.tree.item(selection[0], "text") == DRIVER_TITLE
    assert rendered_value(explorer, i18n._("  Card number")) == "I100000168598002"


def test_the_no_file_empty_state_is_untouched(explorer):
    """Before any file is opened there is no tree at all — so no Summary."""
    assert explorer.current_data is None
    assert tree_titles(explorer) == []
    assert explorer.empty_state.winfo_manager(), "the empty state is showing"
    assert not explorer.table.winfo_manager()


# ── the real parse path ───────────────────────────────────────────────────

def _parse_file(app, path, timeout_s=30.0):
    """Open *path* through the product's own threaded parse path."""
    import time

    app._start_parse(str(path))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.update()
        if app.current_data is not None and not app._parsing:
            app.update()
            return
        time.sleep(0.02)
    raise AssertionError("the parse did not finish in time")


def test_a_really_parsed_card_file_opens_on_the_overview(explorer):
    """End to end through TachoParser: a generated mock G2 card."""
    path = MOCK_DIR / "mock_g2_card.ddd"
    if not path.exists():
        pytest.skip("run tests/integration/generate_mock_ddd.py first")

    _parse_file(explorer, path)

    selection = explorer.tree.selection()
    assert explorer.tree.item(selection[0], "text") == SUMMARY_TITLE
    assert explorer.table._summary_mode is True
    rows = summary_rows(explorer)
    # A real file: the identity comes from the decoded card, not the fixture.
    assert row_value(rows, i18n._("  Filename")) == path.name
    assert i18n._("  Days with activity") in [row[0] for row in rows]
    assert i18n._("  Days flagged") in [row[0] for row in rows]
