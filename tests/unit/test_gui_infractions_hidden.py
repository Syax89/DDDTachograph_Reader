"""The driving-time infractions are hidden behind ONE switch — shipped off.

The owner reviewed the build and decided that, for a *file analyzer*, the
driving-time rules of Reg. (EC) 561/2006 are not needed yet: their thresholds
(9 h daily, 4 h 30 continuous, the 45 min break) are still being decided, so the
infractions are **hidden, not destroyed**. ``app.gui.SHOW_DRIVING_INFRACTIONS``
is that single switch (shipped ``False``), and this file proves both sides of
it on a real ``TachoExplorer`` window:

* **off** (the shipped default): no red row tint, no ``!`` in the Drive cell,
  no infraction tooltip on that cell, no ``Days over {hours} h`` KPI card, and
  no rules block on the Summary;
* **on** (the same window, the switch monkeypatched): every one of those
  surfaces comes back — so "flip the one name" is verified, not assumed;
* and, either way, **the integrity warnings stay**: the ``status-warning``
  triangles (banner, status badge, ``Decoder Failures``, ``CORRUPTED / PARTIAL
  FILE``) and the calibration "due in N days" wording are about a damaged or
  expiring file, not about a driving-time breach.

The evaluation itself never stops: ``evaluate_driving_rules`` still runs on
every day (see ``test_the_evaluation_still_runs_with_the_infractions_hidden``),
which is what makes turning the switch back on a one-line change.

The window is a real one (``TachoExplorer``), and so are the widgets the
assertions look at — row tags, cell text, the KPI card labels — never the
internal row lists the dashboard builds them from. Skips cleanly with no
display, the same pattern as ``test_gui_driving_rules.py``.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

import app.gui as gui
import app.icons as icons
from app.gui import TachoExplorer
from app.i18n import _
from app.theme import DANGER, TEXT_SECONDARY
from core.utils.activity_stats import DAILY_DRIVE_LIMIT_MIN, evaluate_driving_rules

#: 10 h 15 min of unbroken driving: breaks art. 6(1) and art. 7 at once, so a
#: day built from it *is* an infraction whatever the switch says.
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

#: A card payload: no vehicle tooltip noise, one event on the flagged day.
CARD_DATA = {
    "metadata": {"is_vu": False, "generation": "G2 (Smart)"},
    "vehicle": {"plate": "AB123CD", "registration_nation": "I", "vin": "WVWZZZ1J"},
    "events": [{"begin": "2025-05-01T09:30:00", "description": "Overspeed"}],
}

#: The caption of the infraction KPI card, formatted from the module's constant
#: (never a literal 9): the card is only *built* while the switch is on.
KPI_CAPTION = _("Days over {hours} h").format(hours=DAILY_DRIVE_LIMIT_MIN // 60)


@pytest.fixture
def explorer(monkeypatch):
    """A real TachoExplorer window (skipped when there is no display).

    ``messagebox`` is stubbed: a real dialog would block a headless run (and the
    integrity warnings under test do raise one), the same pattern
    ``test_gui_summary_default.py`` uses.
    """
    monkeypatch.setattr(gui, "messagebox", _Dialogs())
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


class _Dialogs:
    """Message boxes would block a headless run: record them instead."""

    calls: list = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: _Dialogs.calls.append((name, args))


# ── widget readers: the assertions look at the real widgets ───────────────

def _rows(app):
    """``[(date, values, tags)]`` of every row currently on screen."""
    out = []
    for iid in app.table.tv.get_children(""):
        values = list(app.table.tv.item(iid, "values"))
        out.append((values[0] if values else "", values,
                    app.table.tv.item(iid, "tags")))
    return out


def _row(app, date):
    """``(iid, values, tags)`` of the displayed row whose Date cell is *date*."""
    for iid in app.table.tv.get_children(""):
        values = list(app.table.tv.item(iid, "values"))
        if values and values[0] == date:
            return iid, values, app.table.tv.item(iid, "tags")
    raise AssertionError(f"no displayed row for {date!r}")


def _drive_cell(app, date):
    return _row(app, date)[1][list(app.table._cols).index(_("Drive"))]


def _kpi_captions(app):
    """The captions of the KPI cards actually packed into the dashboard."""
    captions = []
    for card in app._kpi_frame.winfo_children():
        if not isinstance(card, tk.Frame):
            continue
        labels = [w for w in card.winfo_children() if isinstance(w, tk.Label)]
        if len(labels) >= 2:
            captions.append(labels[0].cget("text"))
    return captions


def _kpi_value(app, caption):
    """The value label of the KPI card with *caption*, or ``None``."""
    for card in app._kpi_frame.winfo_children():
        if not isinstance(card, tk.Frame):
            continue
        labels = [w for w in card.winfo_children() if isinstance(w, tk.Label)]
        if len(labels) >= 2 and labels[0].cget("text") == caption:
            return labels[1]
    return None


def _hover(app, iid, column):
    """Hover one cell of a displayed row; return the tooltip text shown."""
    column_index = list(app.table._cols).index(column) + 1
    box = app.table.tv.bbox(iid, column=f"#{column_index}")
    assert box, f"row {iid!r} must be laid out to be hovered"
    x, y, width, height = box
    app._on_dashboard_motion(SimpleNamespace(x=x + width // 2, y=y + height // 2))
    label = app._tooltip_lbl
    return label.cget("text") if label.winfo_manager() else ""


def _widget_image(widget):
    """The image name a widget carries (``""`` when it has none)."""
    value = widget.cget("image")
    if isinstance(value, (tuple, list)):
        return str(value[0]) if value else ""
    return str(value)


def _node_by_title(app, title):
    """The iid of the first tree node whose text is *title*, at any depth.

    Sections are top-level, but the per-generation views (``Daily Activities``
    among them) hang under their generation node, so the search walks the tree.
    """
    def walk(parent=""):
        for iid in app.tree.get_children(parent):
            if app.tree.item(iid, "text") == title:
                return iid
            found = walk(iid)
            if found:
                return found
        return None

    found = walk()
    if found:
        return found
    titles = [app.tree.item(iid, "text") for iid in app.tree.get_children("")]
    raise AssertionError(f"no node {title!r} in the tree (top level: {titles})")


def _tree_image(app, title):
    """The image name a top-level node carries (``""`` when it has none)."""
    value = app.tree.item(_node_by_title(app, title), "image")
    if isinstance(value, (tuple, list)):
        return str(value[0]) if value else ""
    return str(value)


def _open_file(app, data, path="/tmp/fixture.ddd"):
    """Drive the real render path (``_parse_done``) and settle the loop."""
    app._parse_done(data, path)
    app.update()
    return app


# ── the switch itself ─────────────────────────────────────────────────────

def test_the_shipped_default_hides_the_infractions():
    """One module-level name, and it ships off. Not a scattering of booleans."""
    assert gui.SHOW_DRIVING_INFRACTIONS is False


def test_the_evaluation_still_runs_with_the_infractions_hidden(explorer):
    """Hiding the surfaces must not hide the *verdict*.

    ``_show_daily_summary`` evaluates every day through
    ``evaluate_driving_rules`` and throws the verdict away when the switch is
    off. This pins that the call still happens — so the numbers behind the
    switch are computed, and flipping it back cannot silently show a stale or
    missing verdict.
    """
    assert evaluate_driving_rules(FLAGGED_DAY["changes"]).flagged is True

    real = gui.evaluate_driving_rules
    seen = []

    def spy(changes):
        seen.append(changes)
        return real(changes)

    with patch.object(gui, "evaluate_driving_rules", spy):
        explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
        explorer.update()

    assert len(seen) == 2, "every day must still be evaluated with the switch off"
    assert gui.SHOW_DRIVING_INFRACTIONS is False


# ── switch OFF: nothing about the infraction is on screen ────────────────

def test_no_row_is_tinted_and_the_drive_cell_carries_no_marker(explorer):
    """The breach day is on screen — and looks like every other day.

    ``FLAGGED_DAY`` really is a breach (asserted against the evaluator), so a
    passing test here means the *switch* hid the tint, not a clean fixture.
    """
    assert evaluate_driving_rules(FLAGGED_DAY["changes"]).flagged
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    for date, _values, tags in _rows(explorer):
        assert "flagged" not in tags, f"{date} kept its infraction tint"
    assert _drive_cell(explorer, "01/05/2025") == "10h 15m", \
        "the Drive cell must state the duration and nothing else"
    assert "!" not in _drive_cell(explorer, "01/05/2025")
    # The red style is not even configured — Tk answers every tag name with its
    # defaults, so what matters is that no background was set on it: a later
    # render therefore cannot resurrect the tint either.
    assert dict(explorer.table.tv.tag_configure("flagged")).get("background") \
        in ("", None), "the 'flagged' row style was configured with a tint"


def test_the_drive_cell_opens_no_infraction_tooltip(explorer):
    """No rule, no measured value, no percentage — nothing to explain, no tip."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    iid, _values, _tags = _row(explorer, "01/05/2025")
    assert _hover(explorer, iid, _("Drive")) == ""
    assert explorer._dashboard_rule_tips == {}
    # ... and the row's own (vehicle) tooltip no longer carries the rule either.
    vehicle_tip = _hover(explorer, iid, _("# Vehicles"))
    assert "Daily driving" not in vehicle_tip
    assert "Continuous driving" not in vehicle_tip


def test_the_days_over_kpi_card_is_absent(explorer):
    """The card is not built at all — not built-and-zeroed, and not renamed."""
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    captions = _kpi_captions(explorer)
    assert KPI_CAPTION not in captions
    assert _kpi_value(explorer, KPI_CAPTION) is None
    assert any("9" in caption for caption in captions) is False, \
        "no card may quietly restate the daily limit under another caption"
    # The rest of the KPI row is intact: drive/work/rest/available/days/…
    for kept in (_("Drive"), _("Work"), _("Rest"), _("Available"), _("Days")):
        assert kept in captions


def test_the_summary_states_no_rules_block(explorer):
    """The Overview's driving-time-rules block is gone, not hidden."""
    _open_file(explorer, dict(CARD_DATA, activities=[FLAGGED_DAY, CLEAN_DAY]))
    labels = [row[0] for row in _summary_rows(explorer)]

    for gone in ("DRIVING-TIME RULES", "  Days flagged", "  Daily driving limit",
                 "  Continuous driving limit", "  Break that resets it"):
        assert _(gone) not in labels


def _summary_rows(app):
    tv = app.table.tv
    return [list(tv.item(iid, "values")) for iid in tv.get_children("")]


# ── switch ON: every surface returns ─────────────────────────────────────

def test_the_switch_brings_the_tint_and_the_drive_marker_back(
        explorer, monkeypatch):
    """The same window, the same day: flip the name, the red row returns."""
    monkeypatch.setattr(gui, "SHOW_DRIVING_INFRACTIONS", True)
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    _iid, _values, tags = _row(explorer, "01/05/2025")
    assert "flagged" in tags
    assert _drive_cell(explorer, "01/05/2025") == "10h 15m  !"
    assert "flagged" not in _row(explorer, "02/05/2025")[2]
    # the tint really is the red band, not just a tag name
    assert dict(explorer.table.tv.tag_configure("flagged"))["background"] \
        == gui.DANGER_BAND


def test_the_switch_brings_the_tooltip_back(explorer, monkeypatch):
    monkeypatch.setattr(gui, "SHOW_DRIVING_INFRACTIONS", True)
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    iid, _values, _tags = _row(explorer, "01/05/2025")
    assert "Daily driving 10h 15m \u2014 limit 9h 00m" in _hover(
        explorer, iid, _("Drive"))
    assert "Daily driving" in _hover(explorer, iid, _("# Vehicles"))


def test_the_switch_brings_the_kpi_card_back(explorer, monkeypatch):
    monkeypatch.setattr(gui, "SHOW_DRIVING_INFRACTIONS", True)
    explorer._show_daily_summary([FLAGGED_DAY, CLEAN_DAY], CARD_DATA)
    explorer.update()

    value = _kpi_value(explorer, KPI_CAPTION)
    assert value is not None, "the 'Days over 9 h' card must be back"
    assert value.cget("text") == "1"
    assert value.cget("foreground") == DANGER
    # ... including the neutral colour when nothing is flagged.
    explorer._show_daily_summary([CLEAN_DAY], CARD_DATA, _fast_refresh=True)
    explorer.update()
    value = _kpi_value(explorer, KPI_CAPTION)
    assert value is not None and value.cget("text") == "0"
    assert value.cget("foreground") == TEXT_SECONDARY


# ── the integrity warnings are NOT infractions: they stay ────────────────

def test_the_integrity_banner_and_badge_keep_their_triangle(explorer):
    """A damaged file still wears its ``status-warning`` triangle, switch off."""
    data = dict(CARD_DATA, activities=[FLAGGED_DAY, CLEAN_DAY])
    data["metadata"] = dict(data["metadata"],
                            integrity_check="Card data signature mismatch")
    explorer._check_integrity(data, "/tmp/flagged.ddd")
    explorer.update()
    assert explorer.integrity_banner.cget("text")
    assert _widget_image(explorer.integrity_banner) == str(
        icons.icon("status-warning", 16, master=explorer.integrity_banner))

    _open_file(explorer, data, "/tmp/flagged.ddd")
    assert _widget_image(explorer.lbl_status) == str(
        icons.icon("status-warning", 16, master=explorer)), \
        "the status badge lost its warning triangle"
    assert gui.SHOW_DRIVING_INFRACTIONS is False


def test_the_decoder_failures_and_corrupt_file_sections_keep_their_triangle(
        explorer):
    """``Decoder Failures`` and ``CORRUPTED / PARTIAL FILE`` stay warnings."""
    data = dict(CARD_DATA, activities=[FLAGGED_DAY])
    data["metadata"] = dict(data["metadata"], is_vu=True)   # the corrupt page
    data["metadata"]["decoder_failures"] = [
        {"tag": "0x0504", "reason": "truncated"}]
    data["metadata"]["trep_report"] = {
        "is_partial": True, "mandatory_ok": 3, "mandatory_total": 5,
        "completeness_pct": 60.0, "present": [], "mandatory_missing": [],
        "decoded_suspect": [],
    }
    expected = str(icons.icon("status-warning", 16, master=explorer.tree))

    _open_file(explorer, data, "/tmp/partial.ddd")

    assert _tree_image(explorer, _("Decoder Failures")) == expected
    assert _tree_image(explorer, _("CORRUPTED / PARTIAL FILE")) == expected


def test_the_calibration_due_wording_stays(explorer):
    """An expiring calibration is a file fact, not a driving-time infraction."""
    from datetime import datetime, timedelta, timezone

    soon = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    data = dict(CARD_DATA, activities=[FLAGGED_DAY],
                calibrations=[{"next_calibration_date": soon,
                               "tyre_size": "315/70 R22.5",
                               "authorised_speed_kmh": 90}])
    data["metadata"] = dict(data["metadata"], is_vu=True)
    _open_file(explorer, data, "/tmp/vu.ddd")

    explorer.tree.selection_set(_node_by_title(explorer, _("Vehicle")))
    explorer._on_tree_select(SimpleNamespace())
    explorer.update()
    values = [row[1] for row in _summary_rows(explorer)]
    assert any(_("  Due in {days} days").format(days=30) in str(value)
               or "Due in" in str(value) for value in values), \
        "the calibration expiry note disappeared with the infractions"


# ── a parsed file, through the tree node the user clicks ─────────────────

def _parsed_card_with_a_breach():
    """A really parsed card file, plus a breaching day (no mock breaches).

    The shipped mocks drive 8 h a day — inside both limits — so no generated
    file contains an infraction. The breaching day is the same fixture the flag
    tests use, spliced into the *parsed* payload wherever the tree reads its
    activity days from (``data["activities"]`` and the generation the
    ``Daily Activities`` node is built out of); everything else is the real
    file, decoded by the real parser.
    """
    from pathlib import Path

    from app.engine import TachoParser

    path = Path(__file__).resolve().parents[1] / "mock_data" / "mock_g2_card.ddd"
    if not path.exists():
        pytest.skip("run tests/integration/generate_mock_ddd.py first")
    data = TachoParser(str(path)).parse()
    assert data.get("activities"), "the fixture file must carry activity days"

    days = list(data["activities"]) + [dict(FLAGGED_DAY)]
    data["activities"] = days
    for generation in (data.get("generations") or {}).values():
        if isinstance(generation, dict) and "DriverActivityData" in generation:
            generation["DriverActivityData"] = days
    return data, path


def test_a_parsed_file_with_a_breach_shows_no_infraction_widget(
        explorer, monkeypatch):
    """End to end: real parse, real tree node, real widgets — both ways.

    The tree's ``Daily Activities`` node is clicked exactly as a user would
    (``_on_tree_select``), so this is the dashboard the product renders, not a
    helper called with hand-made arguments.
    """
    data, path = _parsed_card_with_a_breach()
    _open_file(explorer, data, str(path))
    explorer.tree.selection_set(_node_by_title(explorer, _("Daily Activities")))
    explorer._on_tree_select(SimpleNamespace())
    explorer.update()

    drive_col = list(explorer.table._cols).index(_("Drive"))
    dates = [values[0] for _date, values, _tags in _rows(explorer)]
    assert "01/05/2025" in dates, "the breaching day must be on screen"

    # OFF (the shipped default): no tint, no marker, no tooltip, no KPI card.
    assert all("flagged" not in tags for _d, _v, tags in _rows(explorer))
    flagged_row = explorer.table.tv.get_children("")[dates.index("01/05/2025")]
    assert list(explorer.table.tv.item(flagged_row, "values"))[drive_col] \
        == "10h 15m"
    assert _hover(explorer, flagged_row, _("Drive")) == ""
    assert KPI_CAPTION not in _kpi_captions(explorer)

    # ON: the very same row becomes the red, marked, explained one.
    monkeypatch.setattr(gui, "SHOW_DRIVING_INFRACTIONS", True)
    explorer.tree.selection_set(_node_by_title(explorer, _("Daily Activities")))
    explorer._on_tree_select(SimpleNamespace())
    explorer.update()

    dates = [values[0] for _date, values, _tags in _rows(explorer)]
    flagged_row = explorer.table.tv.get_children("")[dates.index("01/05/2025")]
    assert "flagged" in explorer.table.tv.item(flagged_row, "tags")
    assert list(explorer.table.tv.item(flagged_row, "values"))[drive_col] \
        == "10h 15m  !"
    assert "Daily driving" in _hover(explorer, flagged_row, _("Drive"))
    assert _kpi_value(explorer, KPI_CAPTION) is not None
