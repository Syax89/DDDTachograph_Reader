"""Layout regressions for translated chart text (i18n follow-up of #13).

The two gaps covered here are only visible with a *real* Tk font and a real
canvas, so every test builds one (and is skipped when there is no display):

1. ``ActivityTimelineChart._draw`` reserved a fixed 100px left gutter for the
   activity row labels, which are right-aligned *and translated*. Dutch
   "Andere werkzaamheden", Bulgarian "На разположение" and Hungarian
   "Rendelkezésre állás" are wider than that reservation, so their bounding
   boxes started off-canvas (x=-47 / -15 / -20 at 1280x760) and the VU slot
   rows were clipped. English never clipped — its gutter must not move.
2. Two boundary strings leaked internal English slot keys to the UI: the
   activity tooltip printed the raw ``_layout`` slot tag, and the day-detail
   timeline hand-built "[Slot 1]"/"[Slot 2]" although the catalogs already
   translate the "Slot 1"/"Slot 2" messages.

``tests/unit/conftest.py`` pins the process-global translator and the settings
file for every test in this directory (``isolate_i18n``), so no real user
settings are read or written; each test additionally tears down its own Tk
root, its popups and every pending ``after`` job.
"""
import types
from pathlib import Path

import pytest

import app.i18n as i18n

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "locale"

DAY = "01/01/2026"
ISO_DAY = "2026-01-01"          # _activity_to_iso(DAY)
CHART_SIZE = "1280x760"         # the window the clipping was reproduced at
ACTIVITY_CODES = ("DRIVE", "WORK", "REST", "AVAILABLE")

#: A VU day: two slots, both with blocks, so the multi-slot layout (and the
#: per-row slot tag in the tooltip) is exercised.
VU_CHANGES = [
    {"time": "00:00", "activity": "DRIVE", "slot": "First"},
    {"time": "08:00", "activity": "AVAILABLE", "slot": "First"},
    {"time": "00:00", "activity": "REST", "slot": "Second"},
    {"time": "08:00", "activity": "WORK", "slot": "Second"},
]

#: The three languages whose labels were measured off-canvas by the reviewer.
CLIPPING_LANGUAGES = ("nl", "bg", "hu")


def _require_display():
    """Return ``tkinter``, skipping *before* the code under test runs.

    Catching ``TclError`` around the code under test instead would turn a real
    "widget from a destroyed interpreter" bug into a pass.
    """
    tkinter = pytest.importorskip("tkinter")
    try:
        probe = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display available")
    probe.destroy()
    return tkinter


def _require_catalog(code):
    """Install ``code`` and prove a catalog (not the English fallback) is live."""
    if not (CATALOG_DIR / code / "LC_MESSAGES" / "tacho.mo").exists():
        pytest.skip(f"catalog {code!r} is not built in this checkout")
    assert i18n.install(code) == code


@pytest.fixture
def root():
    """A real 1280x760 Tk root, torn down with all its pending timers."""
    tkinter = _require_display()
    win = tkinter.Tk()
    win.geometry(CHART_SIZE)
    try:
        yield win
    finally:
        # Nothing may fire at an already destroyed widget afterwards.
        try:
            for after_id in win.tk.call("after", "info"):
                win.tk.call("after", "cancel", after_id)
        except tkinter.TclError:
            pass
        try:
            win.destroy()
        except tkinter.TclError:
            pass


@pytest.fixture
def chart(root):
    """An ActivityTimelineChart laid out exactly as the dashboard lays it out."""
    import app.gui as gui

    widget = gui.ActivityTimelineChart(root)
    widget.pack(fill=gui.tk.BOTH, expand=True)
    root.update()
    return widget


def _activity_label_boxes(chart):
    """(text, bbox) for every activity row label currently on the canvas."""
    labels = {chart_label(act) for act in ACTIVITY_CODES}
    canvas = chart.canvas
    return [(canvas.itemcget(item, "text"), canvas.bbox(item))
            for item in canvas.find_all()
            if canvas.type(item) == "text"
            and canvas.itemcget(item, "text") in labels]


def chart_label(activity):
    import app.gui as gui

    return gui._act_label(activity)


class TestTranslatedChartLabelsFitTheCanvas:
    """The left gutter must grow to fit translated row labels, and no further."""

    @pytest.mark.parametrize("code", CLIPPING_LANGUAGES)
    def test_measured_clippers_stay_inside_the_canvas(self, root, chart, code):
        _require_catalog(code)
        translated = [chart_label(act) for act in ACTIVITY_CODES]
        # The catalog is really in use: no label is still its English msgid.
        assert all(t != act for t, act in zip(translated, ACTIVITY_CODES, strict=True))

        chart.show(DAY, True, VU_CHANGES)
        root.update()

        canvas_width = chart.canvas.winfo_width()
        boxes = _activity_label_boxes(chart)
        assert boxes, "no activity labels were drawn"
        for text, (x0, _y0, x1, _y1) in boxes:
            assert x0 >= 0, f"{code}: {text!r} starts off-canvas at x={x0}"
            assert x1 <= canvas_width, \
                f"{code}: {text!r} ends past the canvas at x={x1}"

    def test_every_catalog_fits(self, root, chart):
        """Cheap sweep over every shipped language, not just the measured ones."""
        clipped = []
        for code in i18n.LANGUAGES:
            mo = CATALOG_DIR / code / "LC_MESSAGES" / "tacho.mo"
            if not mo.exists():
                continue
            i18n.install(code)
            chart.show(DAY, True, VU_CHANGES)
            root.update()
            canvas_width = chart.canvas.winfo_width()
            for text, (x0, _y0, x1, _y1) in _activity_label_boxes(chart):
                if x0 < 0 or x1 > canvas_width:
                    clipped.append((code, text, (x0, x1)))
        assert clipped == []

    def test_english_gutter_is_unchanged(self, root, chart):
        """English is the calibration: the original 100px gutter must survive."""
        i18n.install("en")
        chart.show(DAY, True, VU_CHANGES)
        root.update()

        assert chart._layout["left"] == 100
        boxes = _activity_label_boxes(chart)
        assert {text for text, _bbox in boxes} == {chart_label(a) for a in ACTIVITY_CODES}
        assert all(x0 >= 0 for _text, (x0, _y0, _x1, _y1) in boxes)
        # "Available" is the widest English label and still right-aligned in
        # the original gutter, exactly where it was before the fix.
        available = next(bbox for text, bbox in boxes if text == "Available")
        # Tk's bbox is inclusive, so the right-aligned edge lands on
        # (left - label_gap) +- 1 px.
        assert chart._layout["left"] - 8 <= available[2] <= chart._layout["left"] - 7


class TestHoverTooltipSlotIsTranslated:
    """The tooltip shows the translated slot; ``_layout`` keeps the raw key."""

    def test_german_tooltip_translates_slot_but_layout_keeps_the_key(self, root, chart):
        _require_catalog("de")
        assert i18n._("Slot 1") == "Steckplatz 1"

        chart.show(DAY, True, VU_CHANGES)
        root.update()

        drive = next(row for row in chart._layout["act_rows"]
                     if row[0] == "DRIVE" and row[3])
        _act, y0, y1, _blocks, slot_tag = drive
        # Internal bookkeeping stays the English key the backend emits.
        assert slot_tag == "Slot 1"

        chart._show_hover(types.SimpleNamespace(
            x=chart._layout["left"] + 10, y=(y0 + y1) / 2))
        hover_texts = [chart.canvas.itemcget(item, "text")
                       for item in chart.canvas.find_withtag("act_hover")
                       if chart.canvas.type(item) == "text"]

        assert len(hover_texts) == 1
        assert hover_texts[0].startswith("Steckplatz 1  Lenkzeit")
        assert "Slot 1" not in hover_texts[0]


class TestDayDetailSlotFragmentsAreTranslated:
    """Manual/inserted card records show a localized slot, not a built string."""

    #: ``card_slot`` is the card's raw 0/1 index as the backend reports it:
    #: 0 renders as "Slot 1", non-zero as "Slot 2", ``None`` as no fragment.
    #: Those semantics are the backend's and must not change here.
    _DATA = {
        "card_iw_records": [
            {
                "manual_input": True,
                "card_slot": 0,
                "insertion_time": f"{ISO_DAY}T08:00:00",
                "withdrawal_time": f"{ISO_DAY}T09:00:00",
                "odometer_insertion_km": 1000,
            },
            {
                "manual_input": False,
                "card_slot": 1,
                "holder_first_names": "Anna",
                "holder_surname": "Muster",
                "insertion_time": f"{ISO_DAY}T10:00:00",
                "withdrawal_time": f"{ISO_DAY}T11:00:00",
            },
        ],
    }

    @pytest.fixture
    def window(self, root):
        import app.gui as gui

        popup = gui.DayDetailWindow(root, DAY, [], 0, 0, "", {}, [], [], [],
                                    self._DATA, is_vu=True)
        try:
            yield popup
        finally:
            # The reuse registry is process-global; drop this window and the
            # key it registered so no later test inherits a dead object.
            try:
                popup._on_close()
            except Exception:
                pass
            gui.DayDetailWindow.forget_all()

    def _slot_fragments(self, window):
        """Detail strings of the manual / insertion entries as displayed."""
        entries = window._build_shared_timeline()
        return {kind: [e[5] for e in entries if e[2] == kind]
                for kind in ("MANUAL", "CARD_IN")}

    def test_english_display_bytes_are_unchanged(self, window):
        i18n.install("en")
        fragments = self._slot_fragments(window)

        assert fragments["MANUAL"][0].endswith("[Slot 1]")
        assert fragments["CARD_IN"][0].endswith("[Slot 2]")

    def test_german_fragments_use_the_translated_slot(self, window):
        _require_catalog("de")
        assert (i18n._("Slot 1"), i18n._("Slot 2")) == ("Steckplatz 1", "Steckplatz 2")

        fragments = self._slot_fragments(window)

        assert fragments["MANUAL"][0].endswith("[Steckplatz 1]")
        assert fragments["CARD_IN"][0].endswith("[Steckplatz 2]")
        assert "[Slot" not in fragments["MANUAL"][0]
        assert "[Slot" not in fragments["CARD_IN"][0]
        # The data behind it is untouched: the raw card_slot keys stay 1/2.
        assert [rec["card_slot"] for rec in self._DATA["card_iw_records"]] == [0, 1]
