"""Interface icons are drawn at the size the display needs (HiDPI).

The icon set ships at 16, 20, 24, 32, 40 and 48 px, but the interface asks in
*logical* pixels — 16 for tree rows and inline markers, 20 for the toolbar —
and which file that turns into depends on the display. Without that, a 16 px
icon sits in a 24 px row beside text that is twice as tall at 200 %, and the
four largest sizes of the set are never drawn at all.

Two things are pinned here:

* the mapping itself, as a pure function (:func:`app.icons.nearest_size`):
  nearest shipped size to ``logical * scale``, ties upward, clamped to the ends
  of the set, never a size that is not shipped, never a resample;
* a window really built at 200 % draws the larger files, and the boxes that
  hold them — the tree row, the summary panel's icon gutter, the toolbar
  buttons — grow with them, measured on the widgets rather than assumed.

The scale is simulated the only way the product reads it: ``winfo_fpixels("1i")``
reports ``scale * 96`` dpi, which ``TachoExplorer.__init__`` turns into
``tk scaling`` on X11 and ``_ui_scale`` turns back into a display ratio. So the
window under test reaches its icons through the same code a 192 dpi laptop
does — no test-only hook exists in ``app/gui.py`` for this.

Every test here skips cleanly without a display, like the other GUI tests.
"""
import os

import pytest

pytest.importorskip("tkinter")

import tkinter as tk  # noqa: E402

import app.gui as gui  # noqa: E402
import app.i18n as i18n  # noqa: E402
from app import icons  # noqa: E402

#: The display scale is simulated by reporting a proportional screen DPI (96 dpi
#: is 100 %). ``TachoExplorer.__init__`` derives ``tk scaling`` from exactly this
#: call on X11, so the window under test is a HiDPI window in the product's own
#: terms.
DPI_PER_SCALE = 96.0


@pytest.fixture(autouse=True)
def isolate_display_scale():
    """Put the display scale back after every test in this module.

    Tk keeps ``scaling`` for the whole *process*, not for one window: a test
    that simulates a HiDPI display would otherwise have every later window in
    the same pytest run built at that scale. This file changes it on purpose
    (it is the thing under test), so it has to hand it back — without this the
    *other* icon tests fail only when this module runs first.
    """
    original = _scaling()
    try:
        yield
    finally:
        _set_scaling(original)


# ── the mapping, as a pure function ───────────────────────────────────────

@pytest.mark.parametrize("logical,scale,expected", [
    # 100 %: today's sizes, exactly.
    (16, 1.0, 16),
    (20, 1.0, 20),
    # The two sizes the interface asks for, at the scales a user can pick.
    (16, 1.25, 20),
    (16, 1.5, 24),
    (16, 2.0, 32),
    (16, 2.5, 40),
    (16, 3.0, 48),
    (20, 1.5, 32),      # 20 * 1.5 = 30: 32 is nearer than 24
    (20, 2.0, 40),
    (20, 2.5, 48),
    # Off the ends of the set: the nearest *delivered* size, not a resample.
    (16, 0.5, 16),
    (16, 10.0, 48),
    (48, 1.0, 48),
])
def test_the_mapping_picks_the_nearest_delivered_size(logical, scale, expected):
    assert icons.nearest_size(logical, scale) == expected


@pytest.mark.parametrize("logical,scale,expected", [
    (16, 1.125, 20),    # 18 is exactly halfway between 16 and 20
    (16, 2.75, 48),     # 44 is exactly halfway between 40 and 48
    (20, 1.4, 32),      # 28 is exactly halfway between 24 and 32
])
def test_a_tie_goes_to_the_larger_file(logical, scale, expected):
    """A tie is broken upwards, deliberately.

    An icon one step too small is clipped by the row it sits in and its strokes
    smear; one step too large only adds margin — and the row height and the
    summary gutter are computed *from* the answer (``_tree_row_height``,
    ``_summary_icon_gutter``), so they grow with it.
    """
    assert icons.nearest_size(logical, scale) == expected
    # ... and the cases really are ties, or this test proves nothing.
    smaller = max(size for size in icons.SIZES if size < expected)
    assert abs(expected - logical * scale) == pytest.approx(
        abs(smaller - logical * scale))


def test_the_mapping_only_ever_answers_with_a_file_that_is_shipped():
    """No resampling, no invented size: every answer is a delivered file."""
    for logical in (1, 12, 16, 20, 24, 96):
        for step in range(1, 41):          # 10 %..400 %
            scale = step / 10.0
            size = icons.nearest_size(logical, scale)
            assert size in icons.SIZES, (logical, scale, size)
            assert os.path.isfile(icons.icon_path("summary", size)), size


@pytest.mark.parametrize("bad_scale", [0, -1, None, "scale", float("nan"),
                                       float("inf")])
def test_an_unusable_scale_falls_back_to_100_percent(bad_scale):
    """A display that cannot say how big it is must not collapse or explode.

    Zero, negative or not-a-number would otherwise send every request to the
    smallest file (or raise out of a widget build); 100 % is the safe reading.
    """
    assert icons.nearest_size(16, bad_scale) == 16
    assert icons.nearest_size(20, bad_scale) == 20


def test_the_scale_comes_from_tk_scaling_and_agrees_with_the_windows_model():
    """One source for the display scale, not a second one invented here.

    ``_ui_scale`` reads Tk's own ``scaling`` — the value fonts are sized by, and
    the one ``TachoExplorer.__init__`` sets. At 96 dpi that is ``96/72``, which
    must come back as exactly 1.0 (a 100 % display is the *identity* of this
    whole change); at 192 dpi it must come back as 2.0. On high-DPI Windows
    ``_px`` multiplies layout pixels by ``DPI/96`` and ``tk scaling`` is set to
    ``DPI/72``, so both readings land on the same factor.
    """
    root = _root()
    try:
        for dpi in (96.0, 120.0, 144.0, 192.0):
            root.tk.call("tk", "scaling", dpi / 72.0)
            # Tk stores ``scaling`` quantised (~0.2 % off on this build), so the
            # reading is compared with the tolerance that error needs: no
            # shipped size is within 0.2 % of a tie, so it never changes a file.
            assert gui._ui_scale(root) == pytest.approx(dpi / 96.0, abs=0.01), dpi
        # Windows: the layout factor and this one are the same number.
        for dpi_ratio in (1.25, 1.5, 2.0):
            root.tk.call("tk", "scaling", 96.0 * dpi_ratio / 72.0)
            assert gui._ui_scale(root) == pytest.approx(dpi_ratio, abs=0.01)
        # Below 100 % the scale is pinned at 100 %: nothing is resampled, so
        # the design size is the floor.
        root.tk.call("tk", "scaling", 0.5)
        assert gui._ui_scale(root) == 1.0
    finally:
        root.destroy()


def test_macos_stays_at_the_sixteen_pixel_files():
    """A Retina window must NOT get the large files.

    ``TachoExplorer.__init__`` sets ``tk scaling`` to 1.0 on macOS because Tk
    scales a Retina window itself and draws a ``PhotoImage`` pixel as a *point*:
    a 32 px file there would occupy 32 points, i.e. an icon twice the size the
    layout was built for. Reading ``scaling`` (rather than the physical pixel
    ratio) is what keeps that case correct, so it is pinned.
    """
    root = _root()
    try:
        root.tk.call("tk", "scaling", 1.0)      # what __init__ does on darwin
        assert gui._ui_scale(root) == 1.0
        assert gui._icon_px(16, root) == 16
        assert gui._icon_px(20, root) == 20
        # ... and the boxes that hold them keep today's design sizes.
        assert gui._tree_row_height(root) == gui._px(24) == 24
        assert gui._summary_icon_gutter(root) == 22
    finally:
        root.destroy()


# ── a window at 200 %: the large files, in boxes that grew ────────────────

def test_a_window_at_200_percent_draws_the_large_files_in_rows_that_hold_them(
        monkeypatch):
    """The defect: at 200 % a 16 px icon sat in a 24 px row beside 37 px text.

    Measured on the real window, per surface: which file is attached, the
    pixels of that image, and the box it is drawn in (the row's own ``bbox``,
    the gutter column, the button's requested height). The image must fit the
    box — with the file chosen by the scale, the row height and the gutter have
    to grow with it, or the icon is clipped by the very row it labels.
    """
    app = _explorer_at(monkeypatch, scale=2.0)
    try:
        row = _open_a_card(app)

        # ── the toolbar: three 20-logical-px buttons ──────────────────
        for widget, name in ((app.btn_open, "toolbar-open"),
                             (app.btn_export, "toolbar-export"),
                             (app.btn_lang, "toolbar-language")):
            image, path = _image_of(widget, widget.cget("image"))
            assert path == icons.icon_path(name, 40), path
            assert (image.width(), image.height()) == (40, 40)
            assert widget.winfo_reqheight() >= 40, (
                f"the {name} button is {widget.winfo_reqheight()} px tall "
                f"for a 40 px icon")

        # ── a section tree row: one 16-logical-px node icon ────────────
        image, path = _image_of(app, app.tree.item(row, "image"))
        assert path == icons.icon_path("summary", 32), path
        box = app.tree.bbox(row)
        assert len(box) == 4, "the row must be laid out to be measured"
        assert box[3] >= 32, f"a 32 px icon in a {box[3]} px tree row"
        assert gui._tree_row_height(app) >= 32

        # ── the summary panel: the header icon in its gutter ───────────
        app.tree.selection_set(row)
        app.update()
        table = app.table.tv
        header = next(iid for iid in table.get_children("")
                      if "summary_header" in table.item(iid, "tags")
                      and table.item(iid, "values")[0])
        image, path = _image_of(app, table.item(header, "image"))
        assert os.sep + "png" + os.sep + "32" + os.sep in path, path
        assert (image.width(), image.height()) == (32, 32), path
        gutter = int(table.column("#0", "width"))
        assert gutter >= 32, f"a 32 px icon in a {gutter} px gutter"
        box = table.bbox(header)
        assert box and box[3] >= 32, f"a 32 px icon in a {box} row"
        # The gutter is taken out of Field, so the Value column keeps its
        # width: gutter + Field is still the 220 logical px the panel gives the
        # labelled column, and Value takes whatever is left.
        assert gutter + int(table.column("Field", "width")) == gui._px(220)

        # ── nothing was resampled: the cache holds the delivered sizes ─
        sizes = {key[2] for key in icons._CACHE}
        assert sizes <= set(icons.SIZES), sizes
        assert {32, 40} <= sizes, sizes
    finally:
        _close(app)


def test_a_window_at_100_percent_is_untouched(monkeypatch):
    """The other half of the change: at 100 % nothing moves.

    Same files, same row height, same gutter, same column widths as before the
    icons were ever scaled — the design numbers are what a 100 % display gets.
    """
    app = _explorer_at(monkeypatch, scale=1.0)
    try:
        row = _open_a_card(app)
        image, path = _image_of(app, app.tree.item(row, "image"))
        assert path == icons.icon_path("summary", 16), path
        assert gui._tree_row_height(app) == 24
        assert app.tree.bbox(row)[3] == 24
        for widget, name in ((app.btn_open, "toolbar-open"),
                             (app.btn_export, "toolbar-export"),
                             (app.btn_lang, "toolbar-language")):
            image, path = _image_of(widget, widget.cget("image"))
            assert path == icons.icon_path(name, 20), path
            assert (image.width(), image.height()) == (20, 20)

        app.tree.selection_set(row)
        app.update()
        assert gui._summary_icon_gutter(app) == 22
        assert int(app.table.tv.column("#0", "width")) == 22
        assert int(app.table.tv.column("Field", "width")) == 198
    finally:
        _close(app)


def test_the_canvas_icon_does_not_run_into_its_label(monkeypatch):
    """The one icon drawn on a canvas: its label must clear the image.

    The activity dashboard draws the driver icon on the canvas and the name
    after it at a fixed 18 px offset — which at 200 % printed the name over a
    32 px icon. The offset is the image's own width now (16 + 2 = 18 at 100 %,
    unchanged), so the gap between image and text stays a gap at every scale.
    """
    app = _explorer_at(monkeypatch, scale=2.0)
    try:
        chart = _activity_chart(app)
        images = [item for item in chart.canvas.find_all()
                  if chart.canvas.type(item) == "image"]
        assert images, "the dashboard should draw the driver icon"
        for item in images:
            box = chart.canvas.bbox(item)
            assert box, "the icon must be drawn to be measured"
            assert box[2] - box[0] == 32, box
            # Every text item on that row starts at or after the image's right
            # edge: nothing is drawn on top of the icon.
            for text in chart.canvas.find_all():
                if chart.canvas.type(text) != "text":
                    continue
                text_box = chart.canvas.bbox(text)
                if text_box and text_box[1] < box[3] and text_box[3] > box[1]:
                    assert text_box[0] >= box[2], (
                        f"text at {text_box} overlaps the icon at {box}")
    finally:
        _close(app)


def _activity_chart(app):
    """The dashboard chart for one card day, laid out by its own entry point.

    A card's day is a single ``Cardholder`` slot, which is the one that leads
    with the driver icon — the canvas item this test is about.
    """
    day = [{"time": "00:00", "activity": "DRIVE", "slot": "First"},
           {"time": "12:00", "activity": "REST", "slot": "First"}]
    app._show_activity_chart("01/05/2025", False, day, 0, 0, "BIANCHI LUCA",
                             {}, [])
    app.update()
    return app.activity_chart


def test_two_scales_never_share_a_cached_image(monkeypatch):
    """The cache key is the *resolved* size, not the logical one.

    The cache lives per Tcl interpreter (see ``app/icons.py``), so a rebuilt
    window cannot collide anyway — but a single window whose ``tk scaling``
    changes (a monitor change, a language switch that rebuilds at another DPI)
    would answer the same logical request with the same key at a different
    size, and hand back the wrong image. Asking twice must therefore produce
    two images, both kept alive.
    """
    app = _explorer_at(monkeypatch, scale=1.0)
    try:
        small = gui._icon("summary", 16, app)
        assert small is not None and small.width() == 16
        app.tk.call("tk", "scaling", 2.0 * 96.0 / 72.0)     # the window at 200 %
        large = gui._icon("summary", 16, app)
        assert large is not None and large.width() == 32
        assert large is not small
        # Both stay referenced (a PhotoImage nothing holds renders as nothing).
        names = app.tk.call("image", "names")
        assert str(small) in names and str(large) in names
        assert {(16, "summary"), (32, "summary")} <= {
            (size, name) for _interp, name, size in icons._CACHE}
    finally:
        _close(app)


# ── helpers ───────────────────────────────────────────────────────────────

def _root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw()
    return window


def _scaling():
    """The display scale Tk will give a window built right now."""
    root = _root()
    try:
        return float(root.tk.call("tk", "scaling"))
    finally:
        root.destroy()


def _set_scaling(value):
    root = _root()
    try:
        root.tk.call("tk", "scaling", value)
    finally:
        root.destroy()


def _explorer_at(monkeypatch, scale):
    """A real TachoExplorer on a display reporting ``scale * 96`` dpi."""
    class NoDialogs:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    monkeypatch.setattr(gui, "messagebox", NoDialogs())
    monkeypatch.setattr(gui.TachoExplorer, "winfo_fpixels",
                        lambda self, value: scale * DPI_PER_SCALE)
    try:
        app = gui.TachoExplorer()
    except tk.TclError:
        pytest.skip("no display available")
    # The scale is injected through the X11 branch of __init__ (the screen DPI).
    # On darwin __init__ forces ``tk scaling`` to 1.0 and on win32 it reads
    # ``_WIN_DPI`` instead, so the window would come out at 100 % there: say so
    # and skip rather than fail on a platform this simulation cannot reach.
    actual = gui._ui_scale(app)
    if abs(actual - scale) > 0.05:
        _close(app)
        pytest.skip(f"the window was built at scale {actual:.2f}, not {scale}: "
                    "this simulation drives the X11 branch of __init__")
    app.geometry("%dx%d" % (gui._px(1280), gui._px(760)))
    app.update()
    return app


def _open_a_card(app):
    """Parse a minimal card file and return the node the window selected."""
    app._parse_done(_card_data(), "/tmp/scaled_icons.ddd")
    app.update()
    # The overview is what a fresh parse selects (and what carries the icons).
    for iid in app.tree.get_children(""):
        if app.tree.item(iid, "text").startswith(i18n._("Summary")):
            return iid
    raise AssertionError([app.tree.item(iid, "text")
                          for iid in app.tree.get_children("")])


def _image_of(widget, value):
    """``(PhotoImage, file path)`` for the image a widget/tree item carries.

    The path is read back through the loader's own cache, so a test can assert
    *which delivered file* is on screen rather than only how big it draws.
    """
    name = value
    if isinstance(value, (tuple, list)):
        name = str(value[0]) if value else ""
    assert name, "the widget carries no image"
    for (_interp, icon_name, size), image in icons._CACHE.items():
        if str(image) == str(name):
            return image, icons.icon_path(icon_name, size)
    raise AssertionError(f"image {name!r} did not come from app.icons")


def _close(app):
    try:
        for after_id in app.tk.call("after", "info"):
            app.tk.call("after", "cancel", after_id)
    except tk.TclError:
        pass
    try:
        app.destroy()
    except tk.TclError:
        pass


def _card_data():
    """A card payload rich enough to build the overview and the tree."""
    return {
        "metadata": {
            "is_vu": False,
            "generation": "G2 (Smart)",
            "integrity_check": "Verified",
            "file_size_bytes": 1234,
            "parsed_at": "2026-01-01T09:00:00",
            "app_version": "2.5.0",
        },
        "coverage": {"byte_accounted_pct": 100.0, "unknown_bytes": 0,
                     "unknown_pct": 0.0, "structurally_identified_pct": 100.0},
        "driver": {
            "surname": "BIANCHI",
            "firstname": "LUCA",
            "card_number": "I100000000000000",
            "issuing_nation": "I",
            "expiry_date": "2027-04-30",
        },
        "vehicle": {"plate": "AB123CD", "vin": "WVWZZZ1JZ3W386752",
                    "registration_nation": "I"},
        "activities": [{
            "date": "01/05/2025",
            "changes": [{"activity": "DRIVE", "time": "00:00", "slot": "First"},
                        {"activity": "REST", "time": "10:15", "slot": "First"}],
        }],
        "raw_tags": {},
        "generations": {},
    }
