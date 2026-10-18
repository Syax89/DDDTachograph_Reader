"""Tooltip containment at the *minimum supported* window (i18n follow-up).

The hover tooltip is shared by the three chart branches (card markers,
out-of-scope markers, activity blocks). It clamps the measured text back inside
the canvas, and wraps a string that is wider than the canvas — but wrapping
makes the tip *taller* than the single line the anchor was chosen for, and only
the horizontal axis was corrected. On the smallest window the product allows
(``TachoExplorer.minsize(900, 560)``) at 192 DPI the real child canvas is only
566x372, so hovering slot 2's rest row at its right plot edge drew
``text bbox (6, 309, 544, 383)`` inside ``background bbox (0, 305, 550, 387)``:
11 px of text and 15 px of frame — the duration line — sat below the canvas.

These regressions are therefore measured on a *real* ``TachoExplorer`` at that
minimum geometry (never on a standalone chart whose canvas is faked to be as
wide as the window), with the display's own DPI: at 100 DPI the tip fits, at
192 DPI the old helper clipped. The frame's 1px outline is part of the bound —
``canvas.bbox()`` already includes it — so all four edges of both items are
asserted, and the tooltip text must still be complete (Tk wraps on whitespace,
so comparing the joined words proves nothing was dropped).

``tests/unit/conftest.py`` pins the process-global translator and the settings
file for every test here, so no real user settings are read or written; each
test cancels its pending ``after`` jobs and closes the app through
``_on_close()``.
"""
import types
from pathlib import Path

import pytest

import app.i18n as i18n

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "locale"

DAY = "01/01/2026"

#: ``TachoExplorer.minsize(900, 560)`` — the smallest window we support, and
#: the geometry the controller and the reviewer reproduced the clipping at.
MINIMUM_SIZE = "900x560"

#: ``TachoExplorer.__init__``'s ``geometry("1280x760")`` — the default window.
DEFAULT_SIZE = "1280x760"

#: The reviewed repro day: slot 1 drives all day while slot 2 rests, so slot
#: 2's rest row is both the widest and the bottom-most tooltip of the chart.
VU_TWO_SLOT_DAY = [
    {"time": "00:00", "activity": "DRIVE", "slot": "First"},
    {"time": "00:00", "activity": "REST", "slot": "Second"},
]

SLOT_TWO_REST_TEXT = "Alloggiamento 2  Riposo  [00:00 \u2014 24:00]  \u00b7  24h 00m"

#: A driver name long enough to push the card-marker tooltip off a small canvas.
LONG_DRIVER_NAME = "Massimiliano Alessandro Della Valle-Schwarzenegger"

#: The card-marker word in each language the marker test parametrizes, written
#: out literally so it can prove which catalog is actually live (the fixture
#: window starts in Italian, "en" must really switch back to English).
INSERTION_LABEL = {"en": "Insertion", "it": "Inserimento"}


def _require_display():
    """Return ``tkinter``, skipping *before* the code under test runs."""
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


def _install_language(code):
    """Make ``code`` the live translator and prove it (never a silent skip).

    ``i18n.install()`` returns the code even when it falls back to
    ``NullTranslations`` for a missing ``.mo``, so a sweep that skipped absent
    catalogs would quietly *shrink* its own coverage — and the ``app`` fixture
    starts in Italian, so forgetting to install the parametrized language would
    leave an "en" case running in Italian. Both are failures here.
    """
    if code != "en":  # English is the source text: there is no catalog for it
        catalog = CATALOG_DIR / code / "LC_MESSAGES" / "tacho.mo"
        assert catalog.exists(), f"catalog {code!r} is not built in this checkout"
    assert i18n.install(code) == code, f"could not install {code!r}"
    return code


@pytest.fixture
def app():
    """A real, Italian ``TachoExplorer``; closed the way the product closes it.

    Italian is persisted through the *patched* settings file first so the
    constructor's own ``install(saved_language())`` really loads it, exactly as
    it does for a user who picked Italiano in the menu.
    """
    tkinter = _require_display()
    import app.gui as gui

    _require_catalog("it")
    assert i18n.save_language("it")
    explorer = gui.TachoExplorer()
    try:
        yield explorer
    finally:
        # Nothing may fire at an already destroyed widget afterwards.
        try:
            for after_id in explorer.tk.call("after", "info"):
                explorer.tk.call("after", "cancel", after_id)
        except tkinter.TclError:
            pass
        try:
            explorer._on_close()
        except tkinter.TclError:
            pass


def _show_day(explorer, size, *, markers=(), oos_events=None):
    """Lay the dashboard chart out for the two-slot day at ``size``."""
    explorer.geometry(size)
    explorer.update()
    explorer._show_activity_chart(DAY, True, VU_TWO_SLOT_DAY, 0, 0, "",
                                  {}, list(markers), list(oos_events or []))
    explorer.update()
    return explorer.activity_chart


def _row(chart, activity, slot_tag):
    return next(row for row in chart._layout["act_rows"]
                if row[0] == activity and row[4] == slot_tag)


def _hover(chart, x, y):
    chart._show_hover(types.SimpleNamespace(x=x, y=y))


def _tooltip_items(chart):
    """``[(kind, text_or_None, bbox, coords)]`` for the tooltip currently drawn."""
    canvas = chart.canvas
    items = []
    for item in canvas.find_withtag("act_hover"):
        kind = canvas.type(item)
        items.append((kind,
                      canvas.itemcget(item, "text") if kind == "text" else None,
                      canvas.bbox(item),
                      [float(value) for value in canvas.coords(item)]))
    return items


def _expected_slot_text(chart, activity, slot_tag):
    """The tooltip the product builds for a whole-day block, per language."""
    import app.gui as gui

    return (f"{i18n._(slot_tag)}  {gui._act_label(activity)}  "
            f"[00:00 \u2014 24:00]  \u00b7  24h 00m")


def _assert_tooltip_contains(chart, expected_text, *, context=""):
    """Both tooltip items are wholly on-canvas and the whole text survived.

    The bound covers the background frame's default 1px outline as well:
    ``canvas.bbox()`` of a rectangle is its coordinates grown by the stroke, so
    a bbox inside ``[0, width] x [0, height]`` is exactly "the visible frame,
    stroke included, is inside the canvas".
    """
    canvas = chart.canvas
    width, height = canvas.winfo_width(), canvas.winfo_height()
    dpi = chart.winfo_fpixels("1i")
    items = _tooltip_items(chart)
    kinds = sorted(kind for kind, _text, _bbox, _coords in items)
    assert kinds == ["rectangle", "text"], (context, items)

    for kind, _text, (x0, y0, x1, y1), _coords in items:
        assert x0 >= 0, f"{context} {kind} starts left of the canvas at x={x0}"
        assert y0 >= 0, f"{context} {kind} starts above the canvas at y={y0}"
        assert x1 <= width, \
            f"{context} {kind} ends past the canvas at x={x1} (width={width}, dpi={dpi})"
        assert y1 <= height, \
            f"{context} {kind} ends below the canvas at y={y1} (height={height}, dpi={dpi})"

    text = next(text for kind, text, _bbox, _coords in items if kind == "text")
    # Tk wraps on whitespace, so equal joined words == equal content: the full
    # string is drawn, nothing was truncated to make it fit.
    assert "".join(text.split()) == "".join(expected_text.split()), (context, text)
    return text


class TestTooltipAtTheMinimumWindow:
    """The reviewed defect: a wrapped tip must also move up, not just left."""

    def test_italian_slot_two_rest_tooltip_stays_inside_the_minimum_window(self, app):
        """900x560, 192 DPI, Italian: the bottom line used to be cut off."""
        chart = _show_day(app, MINIMUM_SIZE)
        canvas = chart.canvas

        # The window really is at its minimum and the canvas really is the
        # narrower child of it — not a standalone chart pretending to be it.
        assert [app.winfo_width(), app.winfo_height()] == [900, 560]
        assert canvas.winfo_width() < app.winfo_width()
        assert canvas.winfo_height() < app.winfo_height()

        row = _row(chart, "REST", "Slot 2")
        left, plot_width = chart._layout["left"], chart._layout["plot_width"]
        # Right plot edge of the bottom row: widest translation, lowest tip.
        _hover(chart, left + plot_width - 1, (row[1] + row[2]) / 2)

        text = _assert_tooltip_contains(
            chart, _expected_slot_text(chart, "REST", "Slot 2"),
            context=f"canvas={canvas.winfo_width()}x{canvas.winfo_height()}")

        assert text.split() == SLOT_TWO_REST_TEXT.split()
        # Internal bookkeeping still holds the English keys the backend emits.
        assert row[4] == "Slot 2"
        assert sorted(chart._slots) == ["Slot 1", "Slot 2"]

    def test_every_catalog_fits_at_the_minimum_and_default_windows(self, app):
        """Cheap sweep: 34 languages x both slot rows x both plot edges, x2 sizes."""
        clipped = []
        for size in (MINIMUM_SIZE, DEFAULT_SIZE):
            visited = []
            # ``i18n.LANGUAGES`` already contains "en": iterate it once, or the
            # English case would simply be drawn twice.
            for code in i18n.LANGUAGES:
                _install_language(code)
                visited.append(code)
                chart = _show_day(app, size)
                canvas = chart.canvas
                width, height = canvas.winfo_width(), canvas.winfo_height()
                left, plot_width = chart._layout["left"], chart._layout["plot_width"]
                for activity, slot_tag in (("DRIVE", "Slot 1"), ("REST", "Slot 2")):
                    row = _row(chart, activity, slot_tag)
                    y = (row[1] + row[2]) / 2
                    # Left edge (the wrap case) and right edge (the clamp case);
                    # Slot 2's row also sits on the bottom edge of the canvas.
                    for x in (left, left + plot_width - 1):
                        _hover(chart, x, y)
                        context = f"{code}@{size} canvas={width}x{height} " \
                                  f"event=({x:.0f},{y:.0f}) {slot_tag}:{activity}"
                        try:
                            _assert_tooltip_contains(
                                chart, _expected_slot_text(chart, activity, slot_tag),
                                context=context)
                        except AssertionError as error:
                            clipped.append(str(error))
                # The raw slot keys must never be rewritten by the fix.
                assert sorted(chart._slots) == ["Slot 1", "Slot 2"]
                assert all(row[4] in ("Slot 1", "Slot 2")
                           for row in chart._layout["act_rows"])
            # Every shipped language exactly once — no duplicated English.
            assert visited == list(i18n.LANGUAGES), visited
        assert clipped == []

    @pytest.mark.parametrize("code", ("en", "it"))
    def test_long_marker_and_oos_labels_fit_the_minimum_window(self, app, code):
        """The other two callers of the shared renderer, at the minimum size."""
        # The fixture window is Italian, so the parametrized language has to be
        # installed explicitly — an un-installed "en" case would silently test
        # Italian and prove nothing about English.
        _install_language(code)
        markers = [(86000, "Slot 2", LONG_DRIVER_NAME, True)]
        oos_events = [(86000, "Ferry/Train crossing near the harbour terminal", None)]
        chart = _show_day(app, MINIMUM_SIZE, markers=markers, oos_events=oos_events)

        marker_x, marker_y = chart._layout["markers_info"][0][:2]
        _hover(chart, marker_x, marker_y)
        text = _assert_tooltip_contains(
            chart, "{}: {} ({})".format(i18n._("\u25bc Insertion"),
                                        LONG_DRIVER_NAME, i18n._("Slot 2")),
            context=f"{code} card marker")
        # Literal, translator-independent proof that *this* catalog is live:
        # English "Insertion" vs the fixture's Italian "Inserimento".
        assert INSERTION_LABEL[code] in text, text
        assert INSERTION_LABEL["it" if code == "en" else "en"] not in text, text

        oos_x, oos_y = chart._layout["oos_info"][0][:2]
        _hover(chart, oos_x, oos_y)
        _assert_tooltip_contains(
            chart,
            "Ferry/Train crossing near the harbour terminal: ?",
            context=f"{code} out-of-scope marker")
