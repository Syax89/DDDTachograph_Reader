"""Every foreground the palette draws as text clears WCAG AA (4.5:1).

The design review measured seven foregrounds below the 4.5:1 that WCAG 2.1
(1.4.3) asks of normal-size text — the orange footer warning and its banner,
the day-detail time column, the secondary labels, the "unknown" grey and the
three ``"gray"`` labels that were not in the palette at all — and the values
were darkened along their own hue until each cleared it, changing no wording
and no fill.

This module pins the results as *ratios*, not as hexes: a token may be retuned
for any other reason, but it may not go back under the line, and a new pair
that is added here has to pass before it ships. The backgrounds are the palette
entries the UI actually paints the text on:

* :data:`app.theme.SURFACE` — the window, the toolbar row, the status bar;
* :data:`app.theme.WHITE` — table cells and the day-detail log;
* :data:`app.theme.SURFACE_ALT` — the day-detail window's panels.

Two roles keep a *fill* and a *foreground* apart on purpose, and only the
foreground moved: ``ACTIVITY_REST`` still draws the rest bar in the blue-grey
:data:`app.theme.SLATE` used to have, and ``TEXT_FAINT`` still draws the
timeline's section divider (a 1 px rule, not a glyph) — the day-detail time
column reads the new ``TEXT_FAINT_TEXT`` instead.
"""
from pathlib import Path

import pytest

import app.theme as theme

GUI_PATH = Path(__file__).resolve().parents[2] / "app" / "gui.py"


def _luminance(hexcolor):
    """Relative luminance of a ``#rrggbb`` colour, per WCAG 2.1."""
    digits = hexcolor.lstrip("#")
    channels = [int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel):
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground, background):
    """WCAG contrast ratio between two ``#rrggbb`` colours (1.0 … 21.0)."""
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


#: ``(foreground, background, minimum ratio)`` — one row per pair the UI draws.
#:
#: The ``"gray"`` rows are the three labels that used to name an X11 colour
#: (``gray``, i.e. ``#bebebe``) instead of a palette entry: 1.72:1 on the
#: window background, the worst text in the application.
PAIRS = (
    ("WARNING", "SURFACE", 4.5),            # the footer warning + status badge
    ("WARNING", "WHITE", 4.5),
    ("CAUTION", "SURFACE", 4.5),            # the "partial" badge
    ("CAUTION", "WHITE", 4.5),
    ("MUTED", "SURFACE", 4.5),              # "unknown"/placeholder information
    ("MUTED", "WHITE", 4.5),
    ("SLATE", "SURFACE", 4.5),              # day-detail count/odometer columns
    ("SLATE", "WHITE", 4.5),
    ("TEXT_SUBTLE", "SURFACE_ALT", 4.5),    # the day-detail date line
    ("TEXT_SUBTLE", "SURFACE", 4.5),
    ("TEXT_FAINT_TEXT", "WHITE", 4.5),      # the day-detail time column
    ("TEXT_FAINT_TEXT", "SURFACE_ALT", 4.5),
    ("TEXT_MUTED", "SURFACE", 4.5),         # what the three "gray"s became
    ("TEXT_MUTED", "WHITE", 4.5),
    # The integrity banner's keyboard focus: the tint is its background, so
    # the foreground it draws there is the one that has to clear the line.
    ("TEXT_PRIMARY", "ACTIVE_BG", 4.5),
)


def test_the_wcag_formula_is_the_one_that_was_measured():
    """Anchor the arithmetic: black on white is 21:1, a colour on itself 1:1."""
    assert round(contrast_ratio("#000000", "#ffffff"), 2) == 21.0
    assert round(contrast_ratio("#ffffff", "#ffffff"), 2) == 1.0
    # The review's own numbers, reproduced from the values they were measured
    # on — so a change to the formula cannot silently re-baseline the table.
    assert round(contrast_ratio("#e65100", "#f4f6f9"), 2) == 3.50
    assert round(contrast_ratio("#90a4ae", "#ffffff"), 2) == 2.59
    assert round(contrast_ratio("#bebebe", "#f4f6f9"), 2) == 1.72


@pytest.mark.parametrize(("foreground", "background", "minimum"), PAIRS,
                         ids=[f"{fg}-on-{bg}" for fg, bg, _ in PAIRS])
def test_every_foreground_clears_aa_on_the_background_it_is_drawn_on(
        foreground, background, minimum):
    value = getattr(theme, foreground)
    ratio = contrast_ratio(value, getattr(theme, background))
    assert ratio >= minimum, (
        f"{foreground} {value} on {background} {getattr(theme, background)} is "
        f"{ratio:.2f}:1, below the {minimum}:1 that WCAG AA asks of body text "
        f"(it was darkened to clear this once already)")


def test_the_dispatched_backgrounds_are_measured_too():
    """Every background named in :data:`PAIRS` must be a real palette entry.

    A typo in the table would have quietly measured a colour the UI never
    paints.
    """
    for foreground, background, _minimum in PAIRS:
        assert getattr(theme, background).startswith("#"), background
        assert getattr(theme, foreground).startswith("#"), foreground


def test_the_fill_that_shared_slates_value_was_not_darkened_with_it():
    """The rest bar keeps the shade the chart has always drawn.

    ``SLATE`` is a foreground now, so darkening it for contrast would have
    darkened the "rest" bar of every activity chart with it. The chart reads
    :data:`app.theme.ACTIVITY_REST`, which is the colour that shipped.
    """
    assert theme.ACTIVITY_REST == "#78909c"
    assert theme.ACTIVITY_REST != theme.SLATE


def test_the_faint_divider_was_not_darkened_with_the_faint_text():
    """The timeline's 1 px section rule is a fill, and keeps its colour."""
    assert theme.TEXT_FAINT == "#90a4ae"
    assert theme.TEXT_FAINT_TEXT != theme.TEXT_FAINT


def test_the_gui_names_a_palette_entry_instead_of_a_raw_colour():
    """The three labels that used the X11 colour ``gray`` (#bebebe, 1.72:1).

    ``"gray"`` is not a palette entry, so nothing in this module could measure
    it — which is exactly how it reached a release at 1.72:1. Every foreground
    the UI draws names a token from :mod:`app.theme`, and every token is in
    the table above.
    """
    source = GUI_PATH.read_text(encoding="utf-8")
    for option in ("foreground", "fg", "background", "bg"):
        assert f'{option}="gray"' not in source, option
        assert f"{option}='gray'" not in source, option


def test_the_day_detail_time_column_reads_the_text_token():
    """C-3's fix in one line: the *text* that was 2.59:1 uses the new token.

    ``TEXT_FAINT`` still names the timeline dividers it also draws, so the
    column that could not be read had to move to a token of its own — this
    pins that it did.
    """
    source = GUI_PATH.read_text(encoding="utf-8")
    assert 'tag_configure("t_time", foreground=TEXT_FAINT_TEXT' in source
