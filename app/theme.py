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
TEXT_SUBTLE = "#607d8b"
#: Chart axis labels and row annotations.
TEXT_MUTED = "#536273"
#: Faint annotations: the day-detail time column.
TEXT_FAINT = "#90a4ae"
#: Small caption above a KPI value.
TEXT_LABEL = "#6b7280"
#: Grey used for "unknown"/placeholder information.
MUTED = "#757575"
#: Blue-grey: the rest activity, table meta text, secondary KPI values.
SLATE = "#78909c"

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
#: Secondary accent: G2.2 files and manual entries.
ACCENT_PURPLE = "#6a1b9a"
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
#: Deepest red: a card that was withdrawn.
DANGER_DARK = "#b71c1c"
#: Pale red band behind an overspeeding interval.
DANGER_BAND = "#ffcdd2"
#: Warnings (partial/incomplete data).
WARNING = "#e65100"
#: Softer warning (unverified but not failed).
CAUTION = "#f57c00"

# ── Activities ─────────────────────────────────────────────────────────────
#: Drive bar/marker. The value is :data:`ACCENT`'s today — the two roles are
#: distinct on purpose ("this is Drive" vs "this is selected/interactive"), so
#: the activity colour can be retuned later without touching the selection.
ACTIVITY_DRIVE = "#1565c0"
#: Rest bar/marker. Same value as :data:`SLATE` today, for the same reason.
ACTIVITY_REST = "#78909c"
#: Work bar.
ACTIVITY_WORK = "#ef6c00"
#: Work marker in the day-detail log (deliberately duller than the bar).
ACTIVITY_WORK_MUTED = "#546e7a"
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
    "G2.2 (Smart V2)": ACCENT_PURPLE,
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
# shortcut: Menlo only exists on macOS, add per-platform fallback later
FONT_MONO = ("Menlo", 11)
FONT_MONO_BOLD = ("Menlo", 11, "bold")
FONT_MONO_NORMAL = ("Menlo", 11, "normal")
FONT_MONO_ITALIC = ("Menlo", 11, "italic")
FONT_MONO_SMALL = ("Menlo", 10)
FONT_MONO_LARGE = ("Menlo", 12, "bold")

#: Backwards-compatible aliases: the names the palette used while it lived in
#: ``TachoExplorer.__init__``/``app.gui``.
APP_BG = SURFACE
APP_FG = TEXT_PRIMARY
