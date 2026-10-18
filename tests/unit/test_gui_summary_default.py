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
* **every** row the panel renders is measured, in **every** one of the 34
  catalogs and in every state of the INTEGRITY block, against the widths the
  panel really lays out — and the rows that still cannot fit are named, with
  their measured widths, and proven readable in full through the panel's hover
  reveal (``test_every_row_of_the_summary_panel_fits_its_column_in_every_language``);
  the measurement font is pinned (DejaVu Sans, the widest default font the
  supported platforms hand out) instead of the machine's, because the same row
  is 194 px in Noto Sans and 204 px in DejaVu and this suite used to be green
  or red depending on which one it got
  (``test_the_fit_sweep_measures_a_pinned_font``);
* the two rows that were measured too wide in the review of the commit that
  introduced this panel — the byte-accounted coverage value and the card
  signature verdict — now fit in all 34 catalogs;
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
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

import app.gui as gui  # noqa: E402
import app.i18n as i18n  # noqa: E402
from core.utils.activity_stats import evaluate_driving_rules  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DIR = REPO_ROOT / "tests" / "mock_data"

#: The node the overview is titled with. The label is plain text: the icon
#: that used to sit in front of it is a row image (``app/icons.py``), so the
#: msgid is the words alone.
SUMMARY_TITLE = i18n._("Summary")
FILE_INFO_TITLE = i18n._("File Info")
#: The section that used to be auto-selected for a card / a VU.
DRIVER_TITLE = i18n._("Driver / Cardholder")
VEHICLE_TITLE = i18n._("Vehicle")

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

#: The font family every fit measurement below is taken with — **pinned**, never
#: the machine's own.
#:
#: ``theme.FONT_BODY`` is ``("", 10)``: an empty family, which Tk resolves to
#: whatever the platform calls its default UI font. That is Noto Sans on a
#: desktop with Noto installed, DejaVu Sans on a stock Ubuntu runner, Segoe UI
#: on Windows and the system font on macOS — and they are not the same width.
#: DejaVu Sans is ~5 % wider than Noto Sans, which is exactly how this panel
#: came to clip eight rows on CI (``  Byte-bilanzierte Abdeckung`` 204 px in a
#: 198 px Field column there, 194 px here) while the same suite was green
#: locally. A fit measured against "whatever this machine happens to have" is
#: therefore not a fit: it is a fit against one font, and the next machine's is
#: wider. So the sweep measures DejaVu Sans — the widest default sans that ships
#: with a supported platform — at the panel's own 10 pt.
MEASURE_FAMILY = "DejaVu Sans"


def measurement_family():
    """The family the measurements below use, warning loudly when it is missing.

    Measuring a *narrower* font than :data:`MEASURE_FAMILY` is worse than not
    measuring at all — it reports a fit that another machine will not reproduce.
    So a machine without DejaVu Sans gets a warning that says so in as many
    words (and names the font actually used inside every failure message) rather
    than a quiet pass; ``test_the_fit_sweep_measures_a_pinned_font`` pins both
    halves of that.
    """
    if MEASURE_FAMILY in set(gui.tkfont.families()):
        return MEASURE_FAMILY
    fallback = gui.tkfont.nametofont("TkDefaultFont").actual("family")
    warnings.warn(
        f"{MEASURE_FAMILY} is not installed: the summary fit sweep is measuring "
        f"{fallback!r} instead, which is usually narrower than the font this "
        f"panel is verified against, so a row that clips on a stock Ubuntu "
        f"runner can pass here. Install the DejaVu fonts (fonts-dejavu-core on "
        f"Debian/Ubuntu) to measure the pinned font.",
        UserWarning, stacklevel=3)
    return fallback


def measure_font(heading=False):
    """The panel's body (or bold heading) font, pinned to :data:`MEASURE_FAMILY`.

    The size and weight come from ``theme.FONT_BODY``/``FONT_HEADING`` — only
    the family is overridden, so moving the panel to 11 pt moves the measurement
    with it and a font the sweep never renders still cannot pass unmeasured.
    """
    spec = gui.FONT_HEADING if heading else gui.FONT_BODY
    return gui.tkfont.Font(family=measurement_family(), size=spec[1],
                           weight="bold" if "bold" in spec else "normal")


def drawn_font(heading=False):
    """The font the panel really draws a body (or header) cell with.

    The mirror image of :func:`measure_font`, and the difference matters: the
    *fit* of a row is a question about the widest font a user's machine may hand
    the panel, so it is answered with the pinned one; the *reveal* is a runtime
    decision the panel makes by measuring the font it is drawing with
    (``_DataTable._summary_cell_font``: ``TkDefaultFont`` for a body cell,
    ``FONT_HEADING`` for a block header), so asking it whether a cell should be
    revealed has to use that same font — otherwise the test reports a reveal
    that the panel, on this machine's narrower font, correctly does not make.

    The two coincide whenever the platform's default family *is* the pinned
    one, which is exactly the CI configuration.
    """
    if heading:
        return gui.tkfont.Font(font=gui.FONT_HEADING)
    return gui.tkfont.nametofont("TkDefaultFont")

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


def card_with(integrity="Verified", ef=None):
    """A card fixture whose INTEGRITY verdict is switched to *integrity*/*ef*.

    ``_integrity_label`` picks the Status row's wording from the file's
    verification data, so the row cannot be measured with one fixture: these
    helpers rebuild the same card with each verdict's input.
    """
    data = card_data()
    data["metadata"] = dict(data["metadata"], integrity_check=integrity)
    data.pop("ef_signature_verification", None)
    if ef is not None:
        data["ef_signature_verification"] = ef
    return data


def vu_with(sv=None, integrity="Partial (VU - chain ok)"):
    """A vehicle-unit fixture whose signature report is switched."""
    data = vu_data()
    data["metadata"] = dict(data["metadata"], integrity_check=integrity)
    data.pop("signature_verification", None)
    if sv is not None:
        data["signature_verification"] = sv
    return data


#: One fixture per verdict ``TachoExplorer._integrity_label`` can return — the
#: branches of the card mapping and of the vehicle-unit one, each with the input
#: that reaches it (the VU fallbacks reuse the card mapping's messages). The fit
#: sweep below renders all of them in all 34 catalogs, because the Status row's
#: width is a property of the *value*, not the row.
STATUS_CASES = (
    ("card: all verified", card_with(ef={"verified": 3})),
    ("card: ef mismatch", card_with(integrity="Invalid", ef={"failed": 1})),
    ("card: ef skipped", card_with(ef={"skipped": 2})),
    ("card: chain invalid",
     card_with(integrity="Invalid Certificate Chain", ef={})),
    ("card: chain unanchored", card_with(integrity="Missing ERCA root", ef={})),
    ("card: key untrusted",
     card_with(integrity="card signing key not trusted", ef={})),
    ("card: ef verification failed",
     card_with(integrity="EF Signature Verification Failed", ef={})),
    ("card: verification error", card_with(integrity="Error: decoder stop", ef={})),
    ("card: no ef results", card_data()),
    # A non-empty ef_results keeps the "No EF signatures verified" branch (which
    # precedes these two) from swallowing them.
    ("card: partial verification",
     card_with(integrity="Partial (chain ok)", ef={"ef_results": [{"ok": True}]})),
    ("card: incomplete certificates",
     card_with(integrity="Incomplete certificates",
               ef={"ef_results": [{"ok": True}]})),
    ("vu: root anchored", vu_with({"all_treps_valid": True, "msca_to_vu": True,
                                   "root_anchored": True},
                                  integrity="Verified")),
    ("vu: chain partial", vu_with({"all_treps_valid": True, "msca_to_vu": True})),
    ("vu: chain unverified", vu_with({"all_treps_valid": True})),
    ("vu: erca missing", vu_with(integrity="Missing ERCA root")),
)

#: The panel states "No activity data available." in the period row when the
#: file carries no days: a second message whose translated width is not the
#: date range's, so the row is measured in this state too.
NO_DAYS_CASE = ("card: no activity days", card_data(activities=[]))

#: The verdict each fixture must put in the Status row. Asserted by the sweep, so
#: a fixture edited into reaching a *different* branch (the branches share their
#: input shape: an empty ``ef_results`` swallows the Partial/Incomplete cases)
#: cannot quietly measure another verdict's width and still pass.
CASE_VERDICTS = {
    "card: all verified": "All signatures verified",
    "card: ef mismatch": "Signature mismatch",
    "card: ef skipped": "EF signatures incomplete",
    "card: chain invalid": "Certificate chain invalid",
    "card: chain unanchored": "Certificate chain not anchored to a trusted root",
    "card: key untrusted": "Card signing key not trusted",
    "card: ef verification failed": "EF signature verification failed",
    "card: verification error": "Verification error",
    "card: no ef results": "No EF signatures verified",
    "card: partial verification": "Partial verification",
    "card: incomplete certificates": "Incomplete certificates",
    "vu: root anchored": "VU signatures verified (root anchored)",
    "vu: chain partial": "VU TREP signatures verified (chain partial)",
    "vu: chain unverified": "VU TREP signatures valid (chain unverified)",
    "vu: erca missing": "ERCA root not available",
    "card: no activity days": "No EF signatures verified",
}

#: The only rows of the overview allowed to be wider than the panel's columns,
#: named here with their measured widths at 900x560 (measured with the pinned
#: DejaVu Sans at 10 pt, see :data:`MEASURE_FAMILY`: 187 px value column /
#: 198 px field column), because the panel does not get to shorten them — the
#: wording belongs to the code that owns the fact:
#:
#: ``Status`` — ``_integrity_label``'s 15 verdicts. 11 of them exceed 187 px in
#:   at least one catalog and 5 exceed it in all 34 (the fully-verified VU
#:   verdict is 394 px in bg, the unverified-chain one 486 px in el, the
#:   untrusted-key one 400 px in mk). Two were shortened because the length
#:   bought nothing — "Signature mismatch" (176 px worst) and the coverage
#:   percentage above — but the rest are security verdicts whose wording is not
#:   this panel's to trade away, and no single short form fits all 34 catalogs.
#: ``Period covered`` — the catalogs' "No activity data available." in the 29
#:   languages where it is wider than the column (372 px in el); the date range
#:   "01/05/2025 → 03/05/2025" fits everywhere (184 px, 3 px spare).
#: ``Origin`` — the catalogs' "Vehicle Unit (VU)", which a VU file's overview
#:   states in the FILE block: 259 px in ru, 242 px in be, 241 px in lt, and over
#:   the column in bg, lv, mk and uk as well. It is the same string the File Info
#:   section and the dashboards show, so it is not this panel's wording to cut
#:   either.
#: ``DRIVING-TIME RULES`` (a block *header*, not a value) — the translated title
#:   clips the 198 px Field column in 22 catalogs (317 px in ro); the other five
#:   headers fit everywhere. The msgid used to carry a ``⏱️`` prefix that the
#:   icon work removed from every catalog and from the call site: a name keyed
#:   on the old spelling matches no rendered row, so it silently stopped
#:   exempting anything and the sweep reported the title as unexpected in those
#:   16 catalogs.
#:
#: None of them is a silent pass: ``test_an_over_wide_cell_is_readable_in_full_on_hover``
#: pins the panel's hover reveal, and the sweep below measures that reveal on
#: every one of those cells, in every catalog, as it goes. Any *other* row that
#: stops fitting fails the sweep with its width, its language and its text.
OVER_WIDE_ROWS = ("  Status", "  Period covered", "  Origin",
                  "DRIVING-TIME RULES")

#: The row the defect reported as clipped — the one this test file exists to keep
#: fitting — so it may never join :data:`OVER_WIDE_ROWS`: not its 198 px Field
#: label and not its 187 px Value. Its label is the one nine catalogs had to
#: shorten (they stated "byte-accounted coverage" in 195–205 px; they now say it
#: in 101–166 px), which is why this register is the single row a future catalog
#: cannot quietly widen.
MUST_FIT_ROWS = ("  Byte-accounted coverage",)


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


def field_column_width(app):
    """On-screen width of the summary panel's Field column, in pixels."""
    for iid in app.table.tv.get_children(""):
        box = app.table.tv.bbox(iid, "Field")
        if box:
            return box[2]
    return int(app.table.tv.column("Field", "width"))


def panel_rows(app, headers=False):
    """``[(rendered_row, label, value, is_header)]`` of the panel's rows.

    The blank separators are skipped; every other row — in render order, with
    its index among the rendered rows — is returned, so a row added to the panel
    later is measured without anyone having to list it here. *headers* also
    returns the block titles, which are rows too (empty value cell, bold font).
    """
    rows = []
    for number, row in enumerate(summary_rows(app)):
        if len(row) < 3:
            continue
        if row[2]:
            if headers and row[0]:
                rows.append((number, row[0], "", True))
            continue
        rows.append((number, row[0], row[1], False))
    return rows


def panel_row_number(app, label):
    """Index among the rendered rows of the row labelled *label*."""
    for number, row_label, _value, _header in panel_rows(app, headers=True):
        if row_label == label:
            return number
    raise AssertionError(f"no summary row {label!r} in "
                         f"{[label for _n, label, _v, _h in panel_rows(app, headers=True)]}")


def row_iid(app, row_number):
    """The treeview id of rendered row *row_number*, as of the current render.

    Row ids are not stable across a re-render, and ``update()`` flushes exactly
    the idle work that re-renders the panel, so an id read before an ``update``
    and used after it can be gone: ``bbox`` then raises ``Item ... not found``
    instead of returning a box. That made the all-catalog sweep fail
    intermittently, so every use below re-reads the row from the live widget.
    """
    children = app.table.tv.get_children("")
    assert row_number < len(children), (
        f"row {row_number} is gone: the panel re-rendered with "
        f"{len(children)} rows while the test held a stale one")
    return children[row_number]


def hover_cell(app, row_number, column):
    """Hover the cell of rendered row *row_number*; return the reveal, if any.

    ``None`` means the panel showed no reveal for that cell.
    """
    app.table.tv.see(row_iid(app, row_number))
    app.update()
    # ... and re-read the row after the update, which may have re-rendered it.
    iid = row_iid(app, row_number)
    box = app.table.tv.bbox(iid, column)
    assert box, f"row {row_number} has no laid-out {column} cell to hover"
    app._on_summary_motion(
        SimpleNamespace(x=box[0] + box[2] // 2, y=box[1] + box[3] // 2))
    app.update_idletasks()
    if app._summary_tip_lbl.winfo_manager():
        return app._summary_tip_lbl.cget("text")
    return None


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
    # ... rendered by _show_summary: no heading bar, summary mode on. The tree
    # column is shown as the icon gutter, and it is the only column that can
    # carry a row image (`cget` hands back a Tcl list, not a string).
    show = {str(part) for part in explorer.table.tv.cget("show")}
    assert show == {"tree"}, show
    assert "headings" not in show, "still no heading bar above the panel"
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
        i18n._("FILE"),
        i18n._("CARDHOLDER"),
        i18n._("VEHICLE"),
        i18n._("TOTALS"),
        i18n._("DRIVING-TIME RULES"),
        i18n._("INTEGRITY"),
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
    """Zero flagged days is the good news: a plain count, no warning marker."""
    open_file(explorer, card_data(activities=[CLEAN_DAY, REST_DAY]))
    rows = summary_rows(explorer)

    flagged = row_value(rows, i18n._("  Days flagged"))
    assert flagged == "0"
    assert "!" not in flagged
    for label in LIMIT_ROWS:
        assert "!" not in row_value(rows, i18n._(label))


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


def test_the_fit_sweep_measures_a_pinned_font(explorer, monkeypatch):
    """The sweep's font is pinned, and a machine without it says so out loud.

    The rows of this panel are measured against a font, and which font decides
    whether the suite passes: the same label measured 194 px on the machine the
    panel was tuned on and 204 px on the Ubuntu runner, because DejaVu Sans is
    ~5 % wider than Noto Sans and ``FONT_BODY`` asks Tk for *the default* family
    rather than naming one. The sweep therefore measures :data:`MEASURE_FAMILY`.
    Both halves of that are pinned here: that the pin really returns that
    family (body and bold) when it is installed, and that a machine without it
    gets a warning naming the font it fell back to — never a quiet pass against
    a narrower one.
    """
    if MEASURE_FAMILY not in set(gui.tkfont.families()):
        warnings.warn(f"{MEASURE_FAMILY} is not installed, so the installed half "
                      f"of this test has nothing to check", UserWarning,
                      stacklevel=2)
    else:
        body = measure_font()
        assert body.actual("family") == MEASURE_FAMILY
        assert body.actual("size") == gui.FONT_BODY[1]
        assert body.actual("weight") == "normal"
        # ... and the heading font is the bold one the headers are drawn with,
        # not the body font in disguise.
        heading = measure_font(heading=True)
        assert heading.actual("family") == MEASURE_FAMILY
        assert heading.actual("weight") == "bold"
        assert heading.measure("MMM") > body.measure("MMM")

    # The missing-font path: the fallback is announced, with the font it fell
    # back to, so a machine that cannot measure the pinned font cannot pass
    # quietly on a narrower one.
    real_families = gui.tkfont.families
    monkeypatch.setattr(
        gui.tkfont, "families",
        lambda: [name for name in real_families() if name != MEASURE_FAMILY])
    with pytest.warns(UserWarning, match="is not installed"):
        family = measurement_family()
    # Whatever the machine's default turns out to be, the fallback reports the
    # font it is really measuring rather than claiming the pinned one.
    assert family == gui.tkfont.nametofont("TkDefaultFont").actual("family")


def test_the_rules_rows_fit_the_value_column_at_the_minimum_window(explorer):
    """The row this replaced was clipped at 900x560 — the app's own minsize.

    The overview used to state both limits in one sentence ("9h 00m daily
    driving \u00b7 4h 30m continuous without a 45 min break"), 469 px of text
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
    font = measure_font()
    for label in LIMIT_ROWS:
        text = rendered_value(explorer, i18n._(label))
        assert font.measure(text) <= value_w, (
            f"{label!r} ({text!r}) is {font.measure(text)} px wide in a "
            f"{value_w} px value column at {MINIMUM_SIZE}")


def test_every_row_of_the_summary_panel_fits_its_column_in_every_language(explorer):
    """Measure the whole panel, in every catalog — not a hand-picked few rows.

    Tk *clips* a cell wider than its column instead of wrapping it, so a row that
    does not fit is a row the user cannot read in full (the panel never auto-fits
    — see ``_show_summary``). The overview has rows whose width comes from the
    catalogs and from the file, so "does it fit" is a question per row **and**
    per language: this walks every row of every state of the panel in all 34
    catalogs, against the widths the real panel lays out at the 900x560 minimum.

    Four things make it honest rather than a wide pass:

    * the row set is not written down here — it is whatever the panel renders,
      block headers included, so a row added later is measured without anyone
      remembering to list it;
    * the font is *pinned* (:func:`measure_font`), not the machine's: the same
      label is 194 px in Noto Sans and 204 px in DejaVu Sans, and this sweep is
      green-or-red depending on which one the platform hands out. Eight rows
      clipped on the Ubuntu runner while the suite was green on a Noto desktop;
    * a row that is too wide is either *named* in :data:`OVER_WIDE_ROWS` and
      proven readable in full through the panel's hover reveal, or it fails with
      its measured width, its catalog and its text. Nothing can join a silent
      pass. The reveal half of that is asked in the font the panel draws with
      (:func:`drawn_font`), because a machine whose own font fits the cell is
      correctly shown nothing on hover — the two fonts coincide on CI.
    """
    explorer.geometry(MINIMUM_SIZE)
    explorer.update()
    font = measure_font()
    # Block headers are drawn bold, so they are measured with their own font —
    # the translated "DRIVING-TIME RULES" title clips in 22 catalogs (317 px in
    # ro) while the body font would call it a fit.
    heading_font = measure_font(heading=True)
    # The sweep is only meaningful in the *pinned* font: ``cget("family")`` is
    # what was asked for, so this catches a measurement quietly taken from the
    # machine's default (``sans-serif``/``TkDefaultFont``) instead — which is the
    # defect this file was fixed for, and which ``actual("family")`` alone would
    # hide on a machine whose default *is* DejaVu Sans.
    measured_family = measurement_family()
    for name, used in (("body", font), ("heading", heading_font)):
        assert used.cget("family") == measured_family, (
            f"the {name} font the sweep measures with is {used.cget('family')!r}, "
            f"not the pinned {measured_family!r}: the sweep has stopped "
            f"measuring the font this panel is verified against")
    # The fonts the panel actually draws with, which is what its reveal decision
    # measures (see :func:`drawn_font`): stable for the whole sweep.
    drawn_body = drawn_font()
    drawn_heading = drawn_font(heading=True)
    cases = STATUS_CASES + (NO_DAYS_CASE,)

    unexpected: list[str] = []
    named: list[str] = []
    measured = 0
    for lang in i18n.LANGUAGES:
        i18n.install(lang)
        named_here = tuple(i18n._(name) for name in OVER_WIDE_ROWS)
        must_fit_here = tuple(i18n._(name) for name in MUST_FIT_ROWS)
        for case, data in cases:
            open_file(explorer, data, path="/data/driver_card.ddd")
            assert rendered_value(explorer, i18n._("  Status")) == \
                i18n._(CASE_VERDICTS[case]), \
                f"{lang} {case}: the fixture no longer reaches that verdict"
            widths = {"Field": field_column_width(explorer),
                      "Value": value_column_width(explorer)}
            assert widths["Value"] > 0, "the panel must be laid out to be measured"
            for number, label, value, is_header in panel_rows(explorer, headers=True):
                cell_font = heading_font if is_header else font
                drawn = drawn_heading if is_header else drawn_body
                for column, text in (("Field", label), ("Value", str(value))):
                    measured += 1
                    got = cell_font.measure(text)
                    if got <= widths[column]:
                        continue
                    detail = (f"{lang} {case} {column} row {label!r}: "
                              f"{got} px in {widths[column]} px — {text!r}")
                    if label not in named_here:
                        if label in must_fit_here:
                            unexpected.append(f"{detail} (must fit; it is the "
                                              f"row this test was widened for)")
                        else:
                            unexpected.append(detail)
                        continue
                    revealed = hover_cell(explorer, number, column)
                    # The width the panel itself clips to for *this* cell, so the
                    # reveal question is asked against the same number the panel
                    # used (``_clipped_summary_cell`` measures `bbox(...)[2]`).
                    iid = row_iid(explorer, number)
                    cell = explorer.table.tv.bbox(iid, column)
                    assert cell, f"{detail} has no laid-out cell to measure"
                    if drawn.measure(text) > cell[2]:
                        assert revealed == text, (
                            f"{detail} is named as allowed to be too wide, but "
                            f"the panel does not reveal it in full "
                            f"(hover showed {revealed!r})")
                    else:
                        # This machine draws a narrower font, so the panel shows
                        # the cell in full and there is nothing to reveal — the
                        # reveal must never cover text that already fits.
                        assert revealed is None, (
                            f"{detail} is named as allowed to be too wide for the "
                            f"pinned font, but this machine's drawn font fits it "
                            f"({drawn.measure(text)} px in {cell[2]} px) so the "
                            f"panel must not reveal it (hover showed {revealed!r})")
                    named.append(detail)
    # A sweep that stopped measuring would pass every assertion above.
    assert measured >= len(i18n.LANGUAGES) * len(cases) * 20, \
        f"only {measured} cells measured: the sweep is not covering the panel"
    assert not unexpected, (
        f"the summary panel clips these rows at 900x560 (measured with "
        f"{measurement_family()} at {gui.FONT_BODY[1]} pt):\n  "
        + "\n  ".join(unexpected))
    assert named, ("no row was too wide in any catalog — the hazard this sweep "
                   "guards against has changed; re-measure and update the "
                   "OVER_WIDE_ROWS rationale instead of deleting the sweep")


def test_an_over_wide_cell_is_readable_in_full_on_hover(explorer):
    """The panel's reveal: a clipped cell shows its whole text, a fitting one not.

    The Status row's verdicts, the catalogs' "no activity data" message and the
    translated block titles can be wider than the column they sit in, and the
    panel does not get to reword them (see :data:`OVER_WIDE_ROWS`), so the text
    has to stay readable another way: hovering the cell reveals it in full, in
    the font the cell is actually drawn with. Nothing else may be revealed — the
    reveal must never cover a value the panel already shows completely.
    """
    explorer.geometry(MINIMUM_SIZE)
    explorer.update()
    i18n.install("it")
    # "Catena di certificati non ancorata a una radice attendibile": 411 px in a
    # 187 px value column — Italian's widest verdict, and one of the eleven that
    # cannot be shortened without losing the verdict. Measured in the font the
    # panel draws it with (:func:`drawn_font`), because that is the font whose
    # width decides whether the panel reveals it at all.
    open_file(explorer, dict(STATUS_CASES)["card: chain unanchored"],
              path="/data/driver_card.ddd")
    explorer.update()

    font = drawn_font()
    value_w = value_column_width(explorer)
    status_number = panel_row_number(explorer, i18n._("  Status"))
    status_text = rendered_value(explorer, i18n._("  Status"))
    assert font.measure(status_text) > value_w, \
        "this fixture is the clipped one: the test needs a too-wide verdict"

    assert hover_cell(explorer, status_number, "Value") == status_text
    # The binding is really wired: a generated <Motion> over the same cell
    # produces the same reveal, so the wiring — not just the handler — is tested.
    explorer._hide_summary_tooltip()
    assert explorer._summary_tip_lbl.winfo_manager() == ""
    iid = explorer.table.tv.get_children("")[status_number]
    box = explorer.table.tv.bbox(iid, "Value")
    assert box, "the Status cell must be visible to generate a motion event"
    explorer.table.tv.event_generate(
        "<Motion>", x=box[0] + box[2] // 2, y=box[1] + box[3] // 2, when="now")
    explorer.update_idletasks()
    assert explorer._summary_tip_lbl.winfo_manager() == "place"
    assert explorer._summary_tip_lbl.cget("text") == status_text
    # ... and hovering a cell that fits hides it again.
    coverage_number = panel_row_number(explorer, i18n._("  Byte-accounted coverage"))
    assert hover_cell(explorer, coverage_number, "Value") is None
    # A block header is a row too: the title clips in this language's neighbours
    # and must be revealable with the bold font it is drawn with.
    rules_header = panel_row_number(explorer, i18n._("DRIVING-TIME RULES"))
    heading_font = drawn_font(heading=True)
    header_text = i18n._("DRIVING-TIME RULES")
    revealed = hover_cell(explorer, rules_header, "Field")
    if heading_font.measure(header_text) > field_column_width(explorer):
        assert revealed == header_text
    else:
        assert revealed is None
    # ... and a <Leave> on the panel hides it (the binding, not just the handler).
    hover_cell(explorer, status_number, "Value")
    assert explorer._summary_tip_lbl.winfo_manager() == "place"
    explorer.table.tv.event_generate("<Leave>", when="now")
    explorer.update_idletasks()
    assert explorer._summary_tip_lbl.winfo_manager() == ""
    # The reveal belongs to the summary panel: another view drops it entirely
    # (File Info is a plain table, not a summary page).
    # ... in the catalog installed at the top of this test (Italian), so the
    # node's title is translated at call time, not the module-level English one.
    select(explorer, node_by_title(explorer, i18n._("File Info")))
    assert explorer._summary_tip_lbl is None
    assert explorer._summary_motion_bind is None
    assert explorer._summary_leave_bind is None


def test_the_two_rows_the_review_measured_fit_every_catalog(explorer):
    """The defect this work started from: those two rows, in all 34 catalogs.

    Measured on the panel at 900x560 by the review of the commit that added the
    overview: ``Status`` = "Card data signature mismatch" was 215 px in English
    and 405 px in mk, over the 187 px value column in 32 of 34 catalogs, and
    ``Byte-accounted coverage`` = "100.0% (1 234 567 / 1 234 567 bytes)" was
    264 px in **all** of them. Both values now state the same fact in the width
    the panel has: "Signature mismatch" (176 px worst) and "100.0%" (53 px).
    """
    explorer.geometry(MINIMUM_SIZE)
    explorer.update()
    font = measure_font()
    # The default fixture's Status is "No EF signatures verified", one of the
    # verdicts still wider than the column (260 px in el) and therefore named in
    # OVER_WIDE_ROWS and revealed on hover; here the two *shortened* values are
    # what must fit, so the row list is per case.
    cases = (
        ("card: ef mismatch", dict(STATUS_CASES)["card: ef mismatch"],
         ("  Status", "  Byte-accounted coverage")),
        ("card: default", card_data(), ("  Byte-accounted coverage",)),
    )

    for lang in i18n.LANGUAGES:
        i18n.install(lang)
        for case, data, msgids in cases:
            open_file(explorer, data, path="/data/driver_card.ddd")
            field_w = field_column_width(explorer)
            value_w = value_column_width(explorer)
            for msgid in msgids:
                label = i18n._(msgid)
                text = rendered_value(explorer, label)
                assert font.measure(label) <= field_w, (
                    f"{lang} {case}: the {label!r} label is "
                    f"{font.measure(label)} px in a {field_w} px column")
                assert font.measure(text) <= value_w, (
                    f"{lang} {case}: {msgid.strip()!r} = {text!r} is "
                    f"{font.measure(text)} px in a {value_w} px value column")


def test_integrity_block_repeats_the_file_info_verdict_and_coverage(explorer):
    open_file(explorer, card_data())
    rows = summary_rows(explorer)

    assert row_value(rows, i18n._("  Status")) == i18n._("No EF signatures verified")
    # The overview states the percentage; the byte arithmetic ("100.0%
    # (1 234 / 1 234 bytes)", 202 px) does not fit this panel's 187 px value
    # column in any catalog and repeats the number the percentage already
    # gives — see test_the_coverage_row_fits_every_catalog. File Info owns it.
    coverage_row = row_value(rows, i18n._("  Byte-accounted coverage"))
    assert coverage_row == "100.0%"
    # The overview may not invent a verdict of its own.
    info = explorer._build_file_info(explorer.current_data)
    assert row_value(rows, i18n._("  Status")) == info[i18n._("Integrity")]
    assert info[i18n._("Byte-accounted coverage")].startswith(
        "100.0% (1 234 / 1 234 bytes"), \
        "the detail page keeps the byte counts the overview summarises"


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

    assert i18n._("CARDHOLDER") not in [row[0] for row in rows]
    assert DRIVER_TITLE not in tree_titles(explorer), \
        "and the pre-existing no-driver rule is unchanged"
    # The rest of the overview is still there — only the driver block is gone.
    assert tree_titles(explorer)[0] == SUMMARY_TITLE
    assert row_value(rows, i18n._("  Days flagged")) == "1"


def test_a_card_that_recorded_no_vehicle_gains_no_vehicle_block(explorer):
    open_file(explorer, card_data(vehicle={
        "plate": "N/A", "vin": "N/A", "registration_nation": "N/A"}))
    rows = summary_rows(explorer)

    assert i18n._("VEHICLE") not in [row[0] for row in rows]


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
    assert i18n._("CARD DETAILS") in [row[0] for row in rendered(explorer)]


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
