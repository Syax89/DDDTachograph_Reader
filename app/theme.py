"""Central palette and font specs for the Tkinter UI.

Every colour the desktop UI paints and every font tuple it asks Tk for lives
here, so a palette change is a one-file edit instead of a hunt through
``app/gui.py``. The values are exactly the ones the UI shipped with: moving
them here changed no pixel.

Usage::

    from app.theme import ACCENT, FONT_TITLE, SURFACE

Naming follows the *role* of the colour, not the widget that happens to use it,
because most values are shared by several widgets:

* ``SURFACE*``  — neutral backgrounds (window, panels, cards, table rows).
* ``TEXT*``/``MUTED``/``SLATE`` — foregrounds, from the strongest to the faintest.
* ``BORDER``/``SCROLLBAR_*``/``ACTIVE_BG``/``CONTROL_HOVER_BG`` — widget chrome.
* ``ACCENT*``/``SUCCESS``/``WARNING``/``CAUTION``/``DANGER*`` — brand and verdict colours.
* ``ACTIVITY_*`` — the tachograph activity bars and day-detail markers.
* ``TOOLTIP_*``/``CHART_*`` — hover tips and chart axes/grid.

The tuple constants are font *specs*, not ``tkfont.Font`` objects: Tk resolves
family sizes per display, so the UI must keep passing tuples (or a canvas-owned
``Font`` built from one) exactly as before.
"""
import sys

# ── Neutral surfaces ───────────────────────────────────────────────────────
#: Window/application background (classic-widget palette, ttk ``darkcolor``).
SURFACE = "#f4f6f9"
#: Day-detail window panel background.
SURFACE_ALT = "#fafafa"
#: KPI cards on the dashboard.
SURFACE_RAISED = "#f8f9fa"
#: KPI grid frame and the table's separator row.
SURFACE_SUNKEN = "#f0f0f0"

#: Plain white: canvases, menus, cards, marker outlines, "text on accent".
WHITE = "#ffffff"
#: Table rows, alternating with :data:`ROW_ODD`.
ROW_EVEN = WHITE
ROW_ODD = "#f2f6fb"
#: ttk entry/combobox/tree field background (same white as the rows).
FIELD_BG = WHITE
#: Table header and button faces.
HEADER_BG = "#e3e9f2"
#: Same face as :data:`HEADER_BG`, named for the buttons that reuse it.
BUTTON_BG = HEADER_BG
#: Flat toggle button sitting on the window background.
TOGGLE_BG = "#e8edf2"

# ── Text ───────────────────────────────────────────────────────────────────
#: Default application foreground.
TEXT_PRIMARY = "#1c2733"
#: Slightly softer primary text: info labels, KPI values, tooltip body.
TEXT_SECONDARY = "#37474f"
#: Day-detail body text: the strongest foreground in the UI.
TEXT_STRONG = "#263238"
#: Section subtitle under a page title.
TEXT_SUBTLE = "#587380"
#: Chart axis labels and row annotations.
TEXT_MUTED = "#536273"
#: Faint annotations. **Not text any more**: this is the section divider drawn
#: on the activity timeline (a 1 px line, not a glyph), and it keeps the value
#: it shipped with so the chart looks the same. Text that used to be drawn in
#: it takes :data:`TEXT_FAINT_TEXT`.
TEXT_FAINT = "#90a4ae"
#: The faintest *foreground* the UI draws — the day-detail time column. Same
#: hue as :data:`TEXT_FAINT`, darkened until it clears 4.5:1 on the white it is
#: written on (it was 2.59:1, well under AA): see ``tests/unit/test_theme_contrast.py``.
TEXT_FAINT_TEXT = "#5d7480"
#: Small caption above a KPI value.
TEXT_LABEL = "#6b7280"
#: Grey used for "unknown"/placeholder information.
MUTED = "#6f6f6f"
#: Blue-grey foreground: day-detail count/odometer columns, section subtitles,
#: secondary KPI values. It is *not* :data:`ACTIVITY_REST`'s value any more:
#: that stays the lighter "rest" blue-grey the chart draws, and only this
#: foreground was darkened to clear 4.5:1 as text.
SLATE = "#5a707b"

# ── Borders and widget chrome ──────────────────────────────────────────────
BORDER = "#c5cfdb"
#: KPI card outline.
CARD_BORDER = "#d0d0d0"
SCROLLBAR_BG = "#cdd7e4"
SCROLLBAR_HOVER_BG = "#b6c3d6"
#: Active/hovered control background and the progress-bar trough.
ACTIVE_BG = "#dbe4f0"
#: Hover background of ttk buttons, menu buttons and table headings.
CONTROL_HOVER_BG = "#d2ddec"
#: Pressed ttk button face.
BUTTON_PRESSED_BG = "#c3d1e6"

# ── Accents ────────────────────────────────────────────────────────────────
#: Primary accent: selection, links, G2 files, primary buttons. Activity
#: colours are separate (see the ``ACTIVITY_*`` block below).
ACCENT = "#1565c0"
#: Verified/insertion green.
SUCCESS = "#2e7d32"
#: Resting background of the small "link" buttons (`?`, slot toggle).
LINK_BUTTON_BG = "#e3f2fd"
#: Their hover background.
HOVER_BG = "#bbdefb"

# ── Verdict colours ────────────────────────────────────────────────────────
#: Errors, failed checks, the "over the limit" parts of a speed trace.
DANGER = "#c62828"
#: The brighter red used for the speed-limit gridline and markers.
DANGER_STRONG = "#d32f2f"
#: Pale red band behind an overspeeding interval.
DANGER_BAND = "#ffcdd2"
#: Warnings (partial/incomplete data). The hue is the shipped one, darkened
#: from #e65100 (3.50:1 on :data:`SURFACE`) so the verdict reads at 4.7:1.
WARNING = "#c14400"
#: Softer warning (unverified but not failed). Darkened from #f57c00
#: (2.50:1) to 4.7:1, same hue.
CAUTION = "#ad5700"

# ── Activities ─────────────────────────────────────────────────────────────
#: Drive bar/marker. The value is :data:`ACCENT`'s today — the two roles are
#: distinct on purpose ("this is Drive" vs "this is selected/interactive"), so
#: the activity colour can be retuned later without touching the selection.
ACTIVITY_DRIVE = "#1565c0"
#: A 25 % tint of :data:`ACTIVITY_DRIVE` on white: the fill under the
#: detailed-speed min–max envelope. Light enough that the mean line and the
#: red over-limit parts still read on top of it.
ACTIVITY_DRIVE_TINT = "#c4d8ef"
#: Rest bar/marker. This *is* the shade the chart draws; :data:`SLATE` used to
#: share it, but the foreground was darkened for contrast and this fill was
#: deliberately left alone.
ACTIVITY_REST = "#78909c"
#: Work bar.
ACTIVITY_WORK = "#ef6c00"
#: Available bar.
ACTIVITY_AVAILABLE = "#f9a825"
#: Ferry/train crossings.
ACTIVITY_FERRY = "#7b1fa2"
#: Events, faults, conditions, power/border/load-unload markers, sub-labels.
ACTIVITY_EVENT = "#5d4037"
#: A record whose activity is not recognised.
ACTIVITY_UNKNOWN = "#bdbdbd"

# ── Charts ─────────────────────────────────────────────────────────────────
#: Major gridline (a full hour) and minor gridline (a 15-minute tick).
CHART_GRID_MAJOR = "#d9e1ea"
CHART_GRID_MINOR = "#edf1f5"

#: Band drawn where the unit recorded no sample at all, so "no data" never
#: reads as a vehicle standing still at 0 km/h. A warm neutral, deliberately
#: outside the blue family: next to the pale blue speed-range band a grey-blue
#: gap read as more of the same signal, and a gap is the *absence* of signal.
#: Kept out of the red family too — missing information is not a violation.
GAP_BAND = "#e0d9cf"

# ── Tooltips ───────────────────────────────────────────────────────────────
#: Chart hover tip: pale yellow box with a grey outline and dark text.
TOOLTIP_BG = "#fffde7"
TOOLTIP_BORDER = "#9e9e9e"
TOOLTIP_FG = "#17212b"
#: Dashboard cell tooltip (a flat classic-widget yellow).
DASHBOARD_TOOLTIP_BG = "#ffffcc"

#: Generation badge colours (the keys are the generation names as displayed).
GEN_COLORS = {
    "G1 (Digital)": SUCCESS,
    "G2 (Smart)": ACCENT,
    # G2.2's purple. It used to be the ACCENT_PURPLE token, whose only other
    # user was the day-detail colour map that no longer exists.
    "G2.2 (Smart V2)": "#6a1b9a",
    "Unknown": MUTED,
}

# ── Fonts ──────────────────────────────────────────────────────────────────
# Plain tuples, exactly as they were written inline before: Tk resolves the
# family ("") to the platform UI font and the size to points.
FONT_TITLE = ("", 13, "bold")            # table / chart section titles
FONT_PAGE_TITLE = ("", 16, "bold")       # day-detail window title
FONT_SUBTITLE = ("", 11)                 # day-detail date line
FONT_SUBTITLE_BOLD = ("", 11, "bold")    # loaded-file name in the top bar
FONT_HEADING = ("", 10, "bold")          # table headers, small headings
FONT_BODY = ("", 10)                     # status line, toggle buttons
FONT_SMALL = ("", 9)                     # KPI caption, tooltip text
FONT_CAPTION = ("", 8)                   # chart row annotations
FONT_CAPTION_BOLD = ("", 8, "bold")      # activity row labels
FONT_BADGE = ("", 12, "bold")            # the `?` chart button
FONT_KPI_VALUE = ("", 14, "bold")        # dashboard KPI number
FONT_CANVAS_TITLE = ("TkDefaultFont", 11, "bold")  # summary drawn on a canvas

# Monospace log text of the day-detail window.
#
# "Menlo" exists on macOS only: on Windows and X11 Tk does not fail on an
# unknown family, it quietly substitutes the default *proportional* font, and
# the log's columns stopped lining up. So the family is chosen per platform:
#
# * macOS: Menlo, the system monospace, exactly as before;
# * Windows: Courier New, the fixed-pitch family every Windows Tk has;
# * everything else: "Monospace", fontconfig's generic fixed-pitch family. A
#   generic name is used instead of one font's name (DejaVu Sans Mono) because
#   it is the one request every X11 desktop answers with *its* monospace font —
#   DejaVu Sans Mono, Liberation Mono, Noto Sans Mono… — so there is no distro
#   whose default install leaves it unresolved.


def mono_family(platform=None):
    """The fixed-pitch family to ask Tk for on *platform* (default: this one).

    A function rather than an ``if`` at import time so every platform's answer
    is reachable from a test on any machine — a branch that only runs on the
    interpreter that happens to be on the runner is a branch nothing checks.
    """
    if platform is None:
        platform = sys.platform
    if platform == "darwin":
        return "Menlo"
    if platform == "win32":
        return "Courier New"
    return "Monospace"


#: Lower case on purpose: ``_colour_constants()`` in the palette test collects
#: every *upper-case* string constant of this module, and this one is a family
#: name, not a colour.
_mono_family = mono_family()

FONT_MONO = (_mono_family, 11)
FONT_MONO_BOLD = (_mono_family, 11, "bold")
FONT_MONO_NORMAL = (_mono_family, 11, "normal")
FONT_MONO_ITALIC = (_mono_family, 11, "italic")
FONT_MONO_SMALL = (_mono_family, 10)
FONT_MONO_LARGE = (_mono_family, 12, "bold")

#: Backwards-compatible aliases: the names the palette used while it lived in
#: ``TachoExplorer.__init__``/``app.gui``.
APP_BG = SURFACE
APP_FG = TEXT_PRIMARY
