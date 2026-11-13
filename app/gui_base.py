"""Shared foundation of the GUI: platform/DPI set-up, theme and icon access,
the event pump, the data table, the activity timeline, the help window and the
formatting helpers every view uses.

Split out of ``app/gui.py``, which keeps only the main window class
(``TachoExplorer``, composed from the ``gui_explorer_*`` mixins) and the entry
points, and re-exports every name defined here so ``app.gui.<name>`` keeps
working.
"""
import gc
import os
import sys
import re
import json
import queue
import functools
import subprocess
import threading
import time
import traceback
import logging
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class _LiveGuiNames:
    """Attribute access resolved on ``app.gui`` at call time.

    The test-suite (and only it) replaces a few names on the ``app.gui``
    module — ``messagebox``, ``TachoParser``, ``SHOW_DRIVING_INFRACTIONS``,
    ``_PUMP_USES_EVENTS`` … — and expects the interface to use the replacement.
    Code that moved out of ``app/gui.py`` reads those names through this object,
    so the replacement still applies. Run as ``python -m app.gui`` the module is
    ``__main__``; with ``app.gui`` not loaded at all, this module's own binding
    is used.
    """

    def __getattr__(self, name):
        for key in ("app.gui", "__main__"):
            module = sys.modules.get(key)
            if module is None:
                continue
            path = getattr(module, "__file__", "") or ""
            if key == "__main__" and not path.endswith(os.path.join("app", "gui.py")):
                continue
            if hasattr(module, name):
                return getattr(module, name)
        return globals()[name]


_live = _LiveGuiNames()


# ── Windows High-DPI ────────────────────────────────────────────────────────
# _WIN_SCALE is the ratio of the display's effective DPI to the 96-DPI baseline
# (1.0 at 100%, 1.5 at 150%, 2.0 at 200%). Once we opt into Per-Monitor DPI
# awareness Windows stops auto-scaling the window, so the whole UI — fonts AND
# fixed pixel sizes — must be scaled by this factor ourselves.
_WIN_DPI = 96
_WIN_SCALE = 1.0
if sys.platform == "win32":
    try:
        from ctypes import windll
        # Try SetProcessDpiAwareness(2) — Per-Monitor V2 (Win 10 1703+)
        windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    # Get system DPI to compute scaling factor
    try:
        hdc = windll.user32.GetDC(0)
        if hdc:
            _WIN_DPI = windll.gdi32.GetDeviceCaps(hdc, 88) or 96  # LOGPIXELSX
            windll.user32.ReleaseDC(0, hdc)
            _WIN_SCALE = _WIN_DPI / 96.0
    except Exception:
        _WIN_SCALE = 1.5  # fallback guess for >96 dpi
        _WIN_DPI = 144


def _px(value):
    """Scale a design pixel value to the current display (Windows HiDPI).

    Design sizes throughout the UI are authored for a 96-DPI (100%) screen;
    on high-DPI Windows displays they are multiplied by the DPI ratio so the
    layout keeps its intended physical size instead of shrinking.

    **This is not a pure scale factor, and the icons do not read it.** It is
    the *identity* everywhere except high-DPI Windows: on macOS Tk scales a
    Retina window itself, and on X11 a pixel is a pixel — only the font sizes
    follow the screen there (``tk scaling``, set in
    :meth:`TachoExplorer.__init__`). So ``_px`` cannot answer "how big is this
    display"; :func:`_ui_scale` does, from that same ``tk scaling`` value, and
    the two agree on Windows (``_px`` multiplies by ``_WIN_SCALE ==
    DPI/96``). Anything derived from a display scale — the icon files, the tree
    row height, the summary gutter — takes it from :func:`_ui_scale`; ``_px``
    keeps scaling the layout exactly as before, so a 100% display is untouched.
    """
    if sys.platform == "win32" and _WIN_SCALE > 1.0:
        return int(round(value * _WIN_SCALE))
    return int(value)

import tkinter as tk  # noqa: E402
import webbrowser  # noqa: E402
from tkinter import ttk, filedialog, font as tkfont, messagebox  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

from app.engine import TachoParser  # noqa: E402
from core.utils.encoding import BytesEncoder  # noqa: E402

from core.utils.version import __version__  # noqa: E402
from core.utils import load_trace  # noqa: E402
from core.utils import report_format  # noqa: E402
from core.utils.report_format import (  # noqa: E402
    NATION_COLS, VERDICT_CORRUPT, VERDICT_PARTIAL, VERDICT_VERIFIED,
    fmt_known_structure, fmt_scalar, integrity_verdict)
from core.utils.activity_stats import (  # noqa: E402
    DAILY_DRIVE_LIMIT_MIN, evaluate_driving_rules,
    recorded_until_seconds)
from core.decoders.common import nation_full_name  # noqa: E402
from app.i18n import (  # noqa: E402
    LANGUAGES, _, add_recent_file, install, save_language, save_translate_data,
    saved_language, saved_recent_files, saved_translate_data)
from app import icons  # noqa: E402
from app import ui_text  # noqa: E402
from app.gui_day_detail import (  # noqa: E402,F401  (moved; re-exported)
    ACTIVITY_LABEL,
    DayDetailWindow,
    _DETAIL_DUR,
    _DETAIL_RANGE,
    _act_label,
    _activity_label,
    _activity_to_iso,
    _changes_for_slot,
    _condition_label,
    _fmt_empty_prefix,
    _fmt_range_dur,
    _format_duration,
    _hhmm_to_min,
    _parse_iso,
)
from app.gui_text import (  # noqa: E402,F401  (moved; re-exported)
    CARD_ENVELOPE_NOTICE,
    CARD_HEADER_NOTICE,
    DONATION_URL,
    HIDDEN_KEYS,
    LEADING_KEYS,
    PROJECT_URL,
    TRAILING_KEYS,
    _bool_text,
    _columns_for,
    _drop_empty_values,
    _envelope_notice,
    _header_notice,
    _integrity_bullets,
    _signature_verdict_clause,
    _summary_block,
    about_text,
    help_links,
)
from app.gui_data import (  # noqa: E402,F401  (moved; re-exported)
    _activity_days,
    _attach_day_distance,
    _calibration_days_left,
    _compute_activity_totals,
    _driver_names_by_date,
    _driving_rule_explanation,
    _fmt_duration_minutes,
    _utc_speed_block,
    detailed_speed_blocks_by_day,
    detailed_speed_by_day,
)
from app.gui_speed_chart import (  # noqa: E402,F401  (moved; re-exported)
    DetailedSpeedChart,
    SPEED_DAY_SECONDS,
    SPEED_GAP_SECONDS,
    SPEED_LIMIT_KMH,
    SPEED_MIN_VIEW_SECONDS,
    SpeedBin,
    _KPI_CARD_BORDER,
    _KPI_CARD_PADX,
    _KPI_CARD_PADY,
    _KPI_GRID_PAD,
    _KPI_WIDTH_SLACK,
    _LEGEND_GLYPH_WIDTH,
    _flow_rows,
    _fmt_seconds_duration,
    _kpi_card,
    default_speed_view,
    envelope_fill_pieces,
    speed_envelope_runs,
)
from app.theme import (  # noqa: E402,F401  (re-exported: GEN_COLORS/ROW_*/HEADER_BG, FONT_MONO*, …)
    ACCENT, ACTIVITY_AVAILABLE, ACTIVITY_DRIVE, ACTIVITY_DRIVE_TINT,
    ACTIVITY_EVENT,
    ACTIVITY_FERRY, ACTIVITY_REST, ACTIVITY_UNKNOWN, ACTIVITY_WORK,
    ACTIVE_BG, BORDER,
    BUTTON_PRESSED_BG, CAUTION, CARD_BORDER, CHART_GRID_MAJOR, CHART_GRID_MINOR, GAP_BAND,
    CONTROL_HOVER_BG, DANGER, DANGER_BAND, DANGER_STRONG,
    DASHBOARD_TOOLTIP_BG, FIELD_BG, FONT_BADGE, FONT_BODY, FONT_CANVAS_TITLE,
    FONT_CAPTION, FONT_CAPTION_BOLD, FONT_HEADING, FONT_KPI_VALUE, FONT_MONO,
    FONT_MONO_BOLD, FONT_MONO_ITALIC, FONT_MONO_LARGE, FONT_MONO_NORMAL,
    FONT_MONO_SMALL,
    FONT_PAGE_TITLE, FONT_SMALL, FONT_SUBTITLE, FONT_SUBTITLE_BOLD, FONT_TITLE,
    GEN_COLORS, HEADER_BG, HOVER_BG, LINK_BUTTON_BG, MUTED, ROW_EVEN, ROW_ODD,
    SCROLLBAR_BG, SCROLLBAR_HOVER_BG, SLATE, SUCCESS, SURFACE, SURFACE_ALT,
    SURFACE_RAISED, SURFACE_SUNKEN, TEXT_FAINT, TEXT_FAINT_TEXT, TEXT_LABEL,
    TEXT_MUTED,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_STRONG, TEXT_SUBTLE, TOGGLE_BG,
    TOOLTIP_BG, TOOLTIP_BORDER, TOOLTIP_FG, WARNING, WHITE)

_log = logging.getLogger("tacho_gui")

try:
    from app.export import ExportManager
except ImportError:
    ExportManager = None  # type: ignore[assignment,misc]


#: Longest the render of a freshly parsed file may hold the main thread before
#: it pumps the event loop again.
#:
#: A ``ttk.Progressbar`` in indeterminate mode animates from a Tk *timer*, and
#: timers are delivered only while the loop runs — so a render that never yields
#: freezes the busy bar for exactly as long as it takes, which the user reads as
#: a hang (greyed buttons, motionless bar). One frame at 60 Hz is short enough
#: that the bar keeps moving and long enough that pumping stays cheap next to
#: the work it interrupts. See ``TachoExplorer._pump_render``.
_RENDER_PUMP_INTERVAL = 1 / 60

#: Upper bound of the adaptive gap between pumps (see ``_pump_render``): the
#: busy bar must still tick at least ~4 times a second however slow a pump is.
_RENDER_PUMP_MAX_GAP = 0.25

#: How often a warning that must wait for a file to finish opening looks again
#: (see ``TachoExplorer._warn_when_idle``). A timer, not an idle callback: an
#: idle callback is re-entered — the whole idle queue is — by every
#: ``update_idletasks()`` the render pumps, and a callback that re-arms itself
#: makes that drain loop without end while the render is still running.
_WARN_POLL_MS = 50


def _pump_uses_events(environ=os.environ, platform=sys.platform):
    """Whether the render pump may process events (``update()``) or only idle tasks.

    macOS: idle tasks only, because ``update()`` can block there inside Tk's native event
    tracking after the file picker closed. ``DDD_PUMP_MODE=events|idle`` overrides it
    (support: flip the behaviour without a rebuild)."""
    return {"events": True, "idle": False}.get(environ.get("DDD_PUMP_MODE", ""),
                                               platform != "darwin")


_PUMP_USES_EVENTS = _pump_uses_events()

#: ``Progressbar.start(12)`` ticks every 12 ms; without events the pump steps the bar itself,
#: at most this many ticks per pump.
_BAR_TICK = 0.012
_BAR_MAX_TICKS = 8


def _flush(widget):
    """``update()``, or only the idle tasks (layout/redraw) where events must not run."""
    if _live._PUMP_USES_EVENTS:
        widget.update()
    else:
        widget.update_idletasks()


def _bring_to_front(window):
    """Finish the pending layout and raise *window* before a modal box opens.

    ``update_idletasks()`` (never ``update()``: this runs inside a Tk callback and
    a nested *event* loop there could deliver another open) settles geometry, the
    redraw and the deferred selection render, so the box is parented to the
    window the user is about to see rather than to one still halfway through
    being rebuilt. ``lift()`` then keeps the box from opening *behind* the window
    — the state a drag & drop from another application left the window in.

    Module-level, like :func:`_flush`, and best-effort for the same reason: the
    window-less doubles the trace tests use have nothing to flush or raise, and
    neither may stop a notice from being shown.
    """
    try:
        window.update_idletasks()
        window.lift()
    except Exception:                 # noqa: BLE001 - see the docstring
        _log.debug("could not bring the window forward: %s",
                   traceback.format_exc())


class _RenderAbandoned(Exception):
    """The window went away while a render was pumping its event loop.

    Raised by :meth:`TachoExplorer._pump_render` and absorbed by the render it
    interrupts: with the window gone there is nothing left to draw and no widget
    left to restore, so the render stops there instead of walking a destroyed
    widget tree and leaving a traceback behind.
    """


#: True once an icon lookup has failed loudly (see :func:`_icon`).
_ICON_FAILURE_LOGGED = False

#: Tk's ``scaling`` is pixels per *point* (72 per inch); a logical pixel is
#: 1/96 inch. The ratio between the two is what turns Tk's value — the one
#: fonts are already sized by — into a display scale: 96 dpi is
#: ``96/72 * 72/96 == 1.0``.
_SCALE_PER_TK_UNIT = 72.0 / 96.0


def _ui_scale(master=None):
    """The display scale of *master*'s window: 1.0 at 100 %, 2.0 at 200 %.

    Derived from Tk's own ``scaling``, the value :class:`TachoExplorer` sets in
    :meth:`~TachoExplorer.__init__` (and that every font is already sized by),
    so the icons have no separate notion of "how big is this display" to fall
    out of step with the text they sit beside. Dividing out the 72-per-inch
    point gives the ratio to the 96 dpi the layout is authored at:

    * Windows sets ``scaling`` to ``DPI/72``, so this yields ``DPI/96`` — the
      same factor :func:`_px` multiplies layout pixels by;
    * macOS sets it to 1.0 (Tk scales a Retina window itself, and a
      ``PhotoImage`` pixel is drawn as a *point* there), so this stays 1.0 and
      the 16 px files keep their logical size — asking for the 32 px one would
      draw an icon twice as large;
    * X11 sets it from the screen's real DPI, which is the only half of a Linux
      HiDPI window that scales today: fonts follow ``scaling``, ``_px`` is the
      identity there (see its docstring). The icons follow the fonts, which is
      what they are drawn next to.

    A window that cannot answer (no ``tk scaling``: a stub interpreter in a
    test) is treated as 100 %: 16 px, today's behaviour. So is anything below
    100 %: the set's smallest file is the size the layout is authored for, and
    nothing is resampled, so a display that reports less cannot make the icons
    smaller than the design (that is also what keeps macOS — ``scaling`` 1.0,
    i.e. 0.75 by this arithmetic — exactly where it is today).
    """
    if master is None:
        master = getattr(tk, "_default_root", None)
    try:
        scale = float(master.tk.call("tk", "scaling")) * _SCALE_PER_TK_UNIT
    except Exception:
        return 1.0
    return max(1.0, scale)


def _icon_px(size=16, master=None):
    """The delivered file size for a *logical* icon size at *master*'s scale."""
    return icons.nearest_size(size, _ui_scale(master))


def _tree_row_height(master=None):
    """Row height that holds the row icon at *master*'s display scale.

    A tree row carries a 16-logical-px icon (section nodes, summary headers),
    and the file drawn for it grows with the scale while ``rowheight`` is a
    fixed number in device pixels — which is how a scaled icon ends up clipped
    by its own row. So the row is the taller of the design height and the image
    plus a little room. At 100 % this is the design height unchanged (16 + 8 is
    exactly 24), i.e. today's layout.
    """
    return max(_px(_TREE_ROW_HEIGHT),
               _icon_px(16, master) + _px(_ROW_ICON_PADDING))


def _summary_icon_gutter(master=None):
    """Width of the summary panel's icon gutter (column ``#0``), in device px.

    ``_SUMMARY_ICON_GUTTER`` is the design width for the 16 px icons; at a
    higher scale the file drawn in it is larger, so the gutter grows with it.
    It is a floor too: at 100 % this is the design width, unchanged.
    """
    return max(_px(_SUMMARY_ICON_GUTTER),
               _icon_px(16, master) + _px(_SUMMARY_ICON_MARGIN))


def _icon(name, size=16, master=None):
    """The commissioned icon *name* at *size* logical px, or ``None``.

    *size* is a **request**, not a file: 16 (tree rows, inline markers) or 20
    (toolbar) is the size the icon has on a 100 % display, which is also the
    size the surrounding layout is authored in. Which of the delivered files is
    drawn is decided for the scale of the window that will draw it — a 32 px
    file beside text that is twice as tall at 200 % (:func:`_ui_scale`,
    :func:`app.icons.nearest_size`). Nothing is resampled: the set ships 16 to
    48 px for exactly this.

    Wraps :func:`app.icons.icon` for widget options: the set is a data file, so
    a bundle that lost ``assets/icons`` (or a headless caller with no Tk root)
    must cost a blank icon, never a traceback. The image itself is cached by
    :mod:`app.icons`, which also keeps it alive — Tkinter blanks a row whose
    ``PhotoImage`` nothing references any more. The cache is keyed by the
    *resolved* size, so two windows at two scales never share an image.

    *master* is the widget the image will be shown in: a ``PhotoImage`` belongs
    to one Tk interpreter, so the icon has to be decoded in the window that
    will draw it (and it is the widget asked for its ``scaling`` above).
    """
    global _ICON_FAILURE_LOGGED
    try:
        return icons.icon(name, _icon_px(size, master), master=master)
    except Exception:
        # Logged once at WARNING: a bundle that lost the set would otherwise
        # show twenty blank icons and say nothing about why.
        detail = traceback.format_exc()
        if not _ICON_FAILURE_LOGGED:
            _ICON_FAILURE_LOGGED = True
            _log.warning("icons unavailable (%r): %s", name, detail)
        else:
            _log.debug("icon %r unavailable: %s", name, detail)
        return None


#: Badge icon -> the character the *window title* shows for it. The title bar is
#: plain text (a window manager draws it, and it has no room for an icon), so
#: the status is spelled out there instead of drawn.
_BADGE_WORDS = {
    "status-warning": "!",
    "status-error": "\u00d7",
    "status-unknown": "?",
}



#: Whether the driving-time infractions are *shown*. **False by default.**
#:
#: This is the one switch for every infraction surface of the UI: the red row
#: tint on a flagged day of the Daily-Activities dashboard, the ``!`` marker in
#: that day's Drive cell, the tooltip that names the broken rule with the
#: measured value, and the "Days over {hours} h" KPI card. Turning those back on
#: is flipping this single name — no other change is needed for *them*.
#:
#: It does **not** bring back the file overview's "DRIVING-TIME RULES" block.
#: That block (the flagged-day count and the three limits) was removed from
#: ``_build_overview_summary`` outright, not put behind this switch, so
#: restoring it would mean writing the code again — its msgids (the title, the
#: count and the three limits) are gone from the catalogs too.
#:
#: Why off: the owner reviewed the build and decided that, for a *file
#: analyzer*, the driving-time rules of Reg. (EC) 561/2006 are not needed yet.
#: Their thresholds (9 h of daily driving, 4 h 30 min of continuous driving, the
#: 45 min break that resets it) are still being decided, and a red row painted
#: on a rule whose limits are not final reads as a verdict the product does not
#: stand behind.
#:
#: Hide, do not destroy: the evaluation is untouched and still runs on every day
#: (``core.utils.activity_stats.evaluate_driving_rules``, called in
#: :meth:`TachoExplorer._show_daily_summary`), so the numbers behind the switch
#: are already computed when it flips.
#:
#: It deliberately does **not** hide anything about the file itself: the
#: integrity warnings (the ``status-warning`` triangles on the banner, on the
#: status badge, on ``Decoder Failures`` and on ``CORRUPTED / PARTIAL FILE``),
#: the calibration "due in N days" text and the chart event markers all stay
#: visible — a damaged or expiring file is not a driving-time breach.
SHOW_DRIVING_INFRACTIONS = False


# ── Section definitions ──
# The tree is now driven directly by :func:`build_generations_tree` output.
# See ``_populate_tree`` and ``core/registry/models.py``.


# ── Value formatting ───────────────────────────────────────────────────────



def _fmt_dict(d):
    """Readable summary of known tachograph nested structures."""
    known = fmt_known_structure(d)
    if known is not None:
        return known
    # Compact generic fallback. The key is handed to fmt_val so a nested label
    # ("calibration_purpose_label") follows the same rules as a flat cell, and
    # bookkeeping children are dropped exactly like at the top level.
    items = ", ".join(f"{k}={fmt_val(val, key=k)}" for k, val in d.items()
                      if k not in report_format.MODEL_ONLY_DICT_KEYS)
    return items if len(items) <= 120 else items[:120] + "\u2026"


#: Chrome around the table (titles, column headers, section names) is always
#: translated. What sits *inside* the table — every cell, whatever produced it —
#: follows the "translate file contents" preference instead.




def fmt_val(v, key=None):
    """Render any parser value for display: booleans as Yes/No, floats
    trimmed, large ints with thousands spaces, 0xFFFFFF sentinels as N/A,
    bytes as hex, ISO timestamps shortened, dicts/lists flattened. Nation
    code columns are expanded to the full English country name.

    Labels *derived* from the file (the nation name, the code label) go through
    ``ui_text.data_text``, so they follow the "translate file contents"
    preference; everything else is the value itself."""
    if isinstance(v, bool):
        # fmt_scalar answers "Yes"/"No" for exports, which stay English; the
        # window shows the translated word.
        return _bool_text(v)
    if isinstance(v, dict):
        return _fmt_dict(v)
    if isinstance(v, list):
        if not v:
            return ""
        if all(not isinstance(x, (dict, list)) for x in v):
            return ", ".join(fmt_val(x) for x in v)
        return f"[{len(v)} items]"
    if isinstance(v, str) and key in NATION_COLS:
        # The nation cell expands "I" to "Italy": that is fmt_scalar's job.
        return fmt_scalar(v, key=key, label_translator=ui_text.data_text)
    if isinstance(v, str):
        # Anything shown in a cell is translated only when the preference is on;
        # a string with no catalog entry (a name, a plate, an address, a code)
        # falls through unchanged. Formatting still has to happen: fmt_scalar
        # turns ISO timestamps into the display form.
        text = ui_text.activity(v) if key == "activity" else ui_text.data_text(v)
        return fmt_scalar(text, key=key, include_code_label=True,
                          label_translator=ui_text.data_text)
    return fmt_scalar(v, key=key, include_code_label=True,
                      label_translator=ui_text.data_text)




def _rows_for(records, transformer):
    """Build (headers, rows) for a section: applies the optional record
    transformer (e.g. day → one row per activity change) and formats cells."""
    cols = _columns_for(records, transformer)
    rows = []
    for rec in records:
        if transformer:
            rec = transformer(rec)
        items = rec if isinstance(rec, list) else [rec]
        for item in items:
            if isinstance(item, dict):
                rows.append([fmt_val(item.get(c), key=c) for c in cols])
            else:
                rows.append([fmt_val(item)])
    # Transformer output keys are already display labels; raw record keys go
    # through the display-text layer, which humanises and translates them (rows
    # above keep the raw key order).
    headers = cols if transformer else [ui_text.label(c) for c in cols]
    return headers, rows


class _SummaryHeader(tuple):
    """A summary section row: ``(label, value, True)`` that also names its icon.

    The summary panel renders its section headers as rows, and the commission
    asked for a distinct glyph per section — ``TOTALS``, ``STATISTICS``,
    ``COMPLETENESS`` and ``PARAMETERS`` all shared one by accident. The icon
    therefore travels *with the row* (as an attribute, not as a text prefix),
    which is also what lets :meth:`DataTable._render` draw it instead of typing
    it: the tuple itself stays the ``(label, value, is_header)`` shape every
    caller and test already reads.
    """

    icon: str

    def __new__(cls, label, *, icon=None, value=""):
        # ``icon``/``value`` are keyword-only on purpose: passed positionally, a
        # value would be read as an icon name, and the row would silently lose
        # the text it was given.
        row = super().__new__(cls, (label, value, True))
        row.icon = icon
        return row


def _kv_rows(d):
    """Convert a dict to (Field, Value) rows, flattening nested dicts one level.

    A *list* of records is accepted too (a key/value view of its first record), so a
    caller can ask for the field view of a record list without checking its shape
    first — the section tables remain the place where a list is rendered in full.

    A row whose value formats to nothing is not a row: the panel has no "empty"
    column, so a blank pair would only read as a defect (the EF verification
    report publishes ``key_trust=None``, ``untrusted_generations=[]`` and
    ``missing_core_efs=[]`` on a healthy card). The rule itself is shared —
    ``report_format.row_has_content`` — so the export sheets cannot drift from
    the panel.
    """
    if isinstance(d, (list, tuple)):
        d = d[0] if d and isinstance(d[0], dict) else {}
    rows = []
    # `confidence` and the shared BOOKKEEPING_KEYS stay in the JSON: only that
    # explicit set is skipped — HIDDEN_KEYS also holds `name`, which VU Company
    # Info does show.
    for k, v in report_format.dict_section_items(d):
        field = ui_text.label(k)
        if isinstance(v, dict) and v:
            for sk, sv in v.items():
                # A nested status/raw companion is bookkeeping too: drop the
                # children the shared set hides so the panel keeps its rows.
                if sk in report_format.MODEL_ONLY_DICT_KEYS:
                    continue
                subfield = f"{field} \u203a {ui_text.label(sk)}"
                subvalue = fmt_val(sv, key=sk)
                if not report_format.row_has_content(subvalue):
                    continue
                rows.append([subfield, subvalue])
        else:
            value = fmt_val(v, key=k)
            if not report_format.row_has_content(value):
                continue
            rows.append([field, value])
    return ([_("Field"), _("Value")], rows)





































# ── Excel-style data table ─────────────────────────────────────────────────

class _TableRow(list):
    """One row's values, carrying what a sort or filter rebuild must keep.

    ``DataTable._render`` re-inserts every row after a sort or a filter change
    and stripes the rows ``even``/``odd`` by *display* position, so anything
    that was attached to a row *position* used to be lost on the first header
    click: the tint of a day that breaks a driving-time rule, the month-total
    emphasis, and the tooltip that belongs to one specific day. Keeping the row
    tag, the row icon and a stable key on the row itself makes them travel with
    it — sorting only reorders the list, filtering only drops entries.
    """

    __slots__ = ("tag", "key", "icon")

    def __init__(self, values, tag=None, key=None, icon=None):
        super().__init__(values)
        #: Row tag; ``None`` means "use the display-position zebra stripe".
        self.tag = tag
        #: Stable identity of the row, used to look up per-row tooltips.
        self.key = key
        #: Icon name of a summary section row (see ``_SummaryHeader``).
        self.icon = icon


def _without_indicator(layout):
    """A ttk item *layout* with the expander indicator taken out.

    A ``Treeview`` reserves the indicator's width (about 19 px in the clam
    theme) *before* the row image, so an image in a narrow tree column is
    painted past its right edge: the summary panel's 16 px icons showed three
    columns of themselves and looked blank. That panel is a flat list — no row
    ever has children — so the indicator is dead space there.

    Derived from the active theme's own layout, so the image, the text and the
    row height stay exactly as the theme draws them. A theme that names its
    elements differently simply keeps its indicator.
    """
    stripped = []
    for element in layout:
        name, options = element
        options = dict(options)
        if "children" in options:
            options["children"] = _without_indicator(options["children"])
        if name != "Treeitem.indicator":
            stripped.append((name, options))
    return stripped


#: Initial width of the tree pane; the data table gets the rest.
#:
#: 260 px clipped five rows of a fully expanded G2 card tree. The widest of
#: them, "EF Signatures (Card Data Integrity)" at depth 2, needs 285 px in the
#: font the tree draws (DejaVu Sans at 10 pt): 39 px of row chrome — one
#: indent step per level plus the 1 px the item padding absorbs — and 246 px of
#: text. The tree shares its pane with a 15 px scrollbar when the rows do not
#: fit, and the treeview keeps 4 px of its own, so a 260 px sash left the
#: column 241 px. 312 px gives it 293 px: 8 px over the widest row, and 52 px
#: that the File Info table can spare at the 900x560 minimum — its Value column
#: still fits every one of the ten cells there
#: (``tests/unit/test_gui_accessibility.py`` measures both sides).
SASH_START = 312


def _autohide(scrollbar, show, hide):
    """A ``yscrollcommand`` that hides the bar while everything is visible.

    An always-on bar with a full thumb scrolls nothing and takes ~14 px from the
    table beside it.
    """
    def command(first, last):
        scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            hide()
        else:
            show()
    return command


def _wrap_at_underscores(text, font, width):
    """Break a name with no spaces after its underscores, to fit *width* px.

    Tk wraps only at whitespace, so a long file name such as
    ``VU_FW000FB_XLRTEM4300G000000_VERIFIED_05BC0642C1.ddd`` was cut mid-word
    ("VERIFIE" / "D_05BC..."). A part longer than the width is left to Tk.
    """
    measure = tkfont.Font(font=font).measure
    lines, line = [], ""
    for part in re.findall(r"[^_]*_|[^_]+", text):
        if line and measure(line + part) > width:
            lines.append(line)
            line = part
        else:
            line += part
    lines.append(line)
    return "\n".join(lines)


def _right_padding(frame):
    """Right-hand padding of a ``ttk.Frame`` (``padding`` takes 1, 2 or 4 values)."""
    parts = [int(float(v)) for v in re.findall(r"\d+(?:\.\d+)?", str(frame.cget("padding")))]
    if not parts:
        return 0
    if len(parts) >= 3:           # left top right [bottom]
        return parts[2]
    return parts[0]               # 1 value: all sides; 2: (x, y)


def _pack_padx(widget):
    """Total horizontal padding (both sides) a packed widget is placed with."""
    padx = widget.pack_info().get("padx", 0)
    if isinstance(padx, (tuple, list)):
        return sum(int(v) for v in padx) if len(padx) > 1 else 2 * int(padx[0])
    return 2 * int(padx)


def _elide_to_width(text, font, width):
    """Shorten *text* to fit *width* px, marking the cut with an ellipsis.

    Tk clips a label silently — the words simply stop, with nothing to say
    that they were cut — which is not something the UI may do to a translated
    integrity verdict. Trimming to whole characters and ending the visible part
    with "…" says "there is more" without changing the wording itself.
    """
    ellipsis = "\u2026"
    if width <= 0 or font.measure(ellipsis) > width:
        return ""
    # Longest prefix that fits together with the ellipsis: a binary search, so
    # the measure cost stays logarithmic in a sentence that can be 460 px wide.
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if font.measure(text[:middle].rstrip() + ellipsis) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ellipsis


class DataTable(ttk.Frame):
    """Header-only treeview: grid with sortable columns and filter."""

    def __init__(self, parent):
        super().__init__(parent)

        head = ttk.Frame(self)
        head.pack(fill=tk.X, padx=8, pady=(8, 2))
        self.title_lbl = ttk.Label(head, text="", font=FONT_TITLE)
        self.title_lbl.pack(side=tk.LEFT)
        self.count_lbl = ttk.Label(head, text="", foreground=TEXT_MUTED)
        self.count_lbl.pack(side=tk.LEFT, padx=(8, 0))
        filt = ttk.Frame(self)
        self.filt_bar = filt
        filt.pack(fill=tk.X, padx=8, pady=(0, 4))
        # The magnifier belongs to the filter row, not to the text: it is an
        # image from the commissioned set, so it looks the same on every
        # platform (an emoji here was drawn by whichever font the OS picked).
        self.filter_icon = ttk.Label(filt, image=_icon("search", 16, self) or "")
        self.filter_icon.pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_args: self._schedule_filter())
        self.filter_entry = ttk.Entry(filt, textvariable=self.filter_var)
        self.filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Rows draw their icon in the tree column (see _show_summary); ttk's
        # expander indicator would push that icon out of the gutter, and no row
        # of this table is ever expandable, so the panel gets a style without
        # it. Invisible in every other view: they hide column #0 entirely with
        # show="headings".
        try:
            ttk.Style(self).layout(
                "Summary.Treeview.Item",
                _without_indicator(ttk.Style(self).layout("Treeview.Item")))
            row_style = "Summary.Treeview"
        except tk.TclError:      # a theme that cannot describe its layout
            _log.debug("treeview item layout not customised: %s",
                       traceback.format_exc())
            row_style = "Treeview"
        self.tv = ttk.Treeview(body, show="headings", selectmode="browse",
                               style=row_style)
        ysb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.tv.yview)
        xsb = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.tv.xview)
        self.tv.configure(
            yscrollcommand=_autohide(ysb, ysb.grid, ysb.grid_remove),
            xscrollcommand=xsb.set)

        self.tv.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        self._xsb = xsb
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.tv.tag_configure("even", background=ROW_EVEN)
        self.tv.tag_configure("odd", background=ROW_ODD)
        self.tv.tag_configure("summary_header",
                              font=FONT_HEADING,
                              background=HEADER_BG)

        self._cols = []
        self._all_rows = []
        # Treeview iid -> stable row key, filled by _render for rows that have
        # one (see _TableRow); the dashboard tooltips are looked up through it.
        self._iid_keys = {}
        self._sort_state = {}
        self._fit_after_id = None
        self._filter_after_id = None
        self._fitted = False
        # When True the table shows a fixed-width summary (Field/Value) and the
        # content-proportional auto-fit must never run, or a late <Configure>
        # timer would resize its columns inconsistently between visits.
        self._summary_mode = False

        self.tv.bind("<Configure>", lambda e: self._schedule_fit())

        # The table is the only way out of the file with its data in a form
        # another program can take, and a treeview copies nothing by itself.
        # Ctrl+C (Cmd+C on macOS) copies what is selected as one tab-separated
        # line per row, in column order and without the headings — the shape a
        # spreadsheet pastes into columns.
        for sequence in ("<Control-c>", "<Control-C>"):
            self.tv.bind(sequence, self._copy_selection)
        if sys.platform == "darwin":
            self.tv.bind("<Command-c>", self._copy_selection)

    def _copy_selection(self, _event=None):
        """Put the selected rows on the clipboard (TSV, no header).

        Returns ``"break"`` so the key does not fall through to the class
        binding, which would copy something else (or nothing).
        """
        selected = self.tv.selection()
        if not selected:
            return "break"
        rows = ["\t".join(str(cell) for cell in self.tv.item(iid, "values"))
                for iid in selected]
        self.clipboard_clear()
        self.clipboard_append("\n".join(rows))
        return "break"

    def _sync_xscroll(self):
        """Show the horizontal scrollbar only when a column runs off the edge.

        A scrollbar under every table — including the ones that fit, and the
        summary panel whose value column stretches — is chrome that suggests
        hidden content. Gridded on demand, it appears exactly when it is true.
        """
        try:
            needed = self.tv.xview()[1] < 1.0
        except tk.TclError:  # widget already destroyed
            return
        if needed and not self._xsb.winfo_manager():
            self._xsb.grid(row=1, column=0, sticky="ew")
        elif not needed and self._xsb.winfo_manager():
            self._xsb.grid_remove()

    def show(self, title, columns, rows, meta=""):
        """Display a table: sets headers (click to sort), sizes columns,
        resets the filter and renders all rows."""
        if self._fit_after_id is not None:
            self.tv.after_cancel(self._fit_after_id)
            self._fit_after_id = None
        if self._filter_after_id is not None:
            self.tv.after_cancel(self._filter_after_id)
            self._filter_after_id = None
        self.filt_bar.pack(fill=tk.X, padx=8, pady=(0, 4), before=self.tv.master)
        self.title_lbl.config(text=title)
        self.count_lbl.config(
            text=_("Rows: {rows} \u00b7 Columns: {columns}").format(
                rows=len(rows), columns=len(columns))
            + (f"   \u2014   {meta}" if meta else ""))
        self.filter_var.set("")

        self._cols = list(columns)
        self._sort_state = {}
        self._fitted = False
        self._summary_mode = False
        self.tv["show"] = "headings"

        self.tv["columns"] = self._cols
        for c in self._cols:
            # The heading is anchored like the cells under it (clam centres a
            # heading by default, which left every title floating over the
            # middle of a left-aligned column).
            self.tv.heading(c, text=str(c), anchor=tk.W,
                            command=lambda col=c: self._sort_by(col))
            min_w = max(len(str(c)) * _px(9) + _px(24), _px(60))
            self.tv.column(c, minwidth=min_w, anchor=tk.W, stretch=False)

        self.set_rows(rows)
        self.tv.update_idletasks()
        self._fit_columns()
        _flush(self.tv)
        self._sync_xscroll()
        if self._fit_after_id is not None:
            self.tv.after_cancel(self._fit_after_id)
            self._fit_after_id = None

    def _fit_columns(self):
        """Distribute available width proportionally to content length.

        Runs only for the initial layout of a table (until the first
        successful fit). After that, columns keep whatever width the user
        set — auto-fit no longer overrides them. Loading a new table resets
        this via :meth:`show`.
        """
        if not self._cols or self._fitted or self._summary_mode:
            return
        available = self.tv.winfo_width()
        if available < 50:
            self._fit_after_id = self.tv.after(200, self._fit_columns)
            return
        weights = [max(max(self._content_width(c), len(str(c)) * _px(9)) + _px(24), _px(70)) for c in self._cols]
        total_weight = sum(weights)
        if total_weight == 0:
            return
        # Leave room for scrollbar
        usable = max(available - _px(20), _px(100))
        for c, w in zip(self._cols, weights, strict=False):
            min_w = max(len(str(c)) * _px(9) + _px(24), _px(70))
            self.tv.column(c, width=max(int(usable * w / total_weight), min_w))
        self._fitted = True

    def _content_width(self, col):
        idx = self._cols.index(col)
        longest = len(str(col))
        for r in self._all_rows[:200]:
            if idx < len(r):
                longest = max(longest, len(str(r[idx])))
        return longest * _px(8)

    def _schedule_fit(self):
        if self._fitted or self._summary_mode:
            return
        if self._fit_after_id is not None:
            self.tv.after_cancel(self._fit_after_id)
        self._fit_after_id = self.tv.after(300, self._fit_columns)

    def set_rows(self, rows, tags=None, keys=None):
        """Replace the content, keeping each row's tag and stable key.

        ``tags`` and ``keys`` are parallel to ``rows`` and both optional. Both
        live on the row (:class:`_TableRow`), so they survive the re-render a
        sort or a filter change triggers: the tint of a flagged day and the
        tooltip of that same day stay with it however the table is ordered.
        """
        self._all_rows = [
            _TableRow(values,
                      tag=tags[i] if tags is not None and i < len(tags) else None,
                      key=keys[i] if keys is not None and i < len(keys) else None,
                      # A summary section row already names its icon; carrying it
                      # here keeps it across the rebuild a sort or a filter does.
                      icon=getattr(values, "icon", None))
            for i, values in enumerate(rows)
        ]
        self._render(self._all_rows)

    def row_key(self, iid):
        """Stable key of a displayed row (see :meth:`set_rows`), or ``None``."""
        return self._iid_keys.get(iid)

    def _render(self, rows, summary=None):
        """Draw *rows*; ``summary`` defaults to the mode the panel is in.

        ``_apply_filter`` and ``_sort_by`` re-render without naming a mode, and
        the summary panel is re-rendered by its own timers (setting the filter
        box schedules one), so a hard default of "not a summary" used to redraw
        the section headers as plain rows a third of a second after they
        appeared — losing their band and their icon. The panel's mode is
        ``_summary_mode``; callers that build a different kind of panel set that
        flag instead of passing an argument.
        """
        if summary is None:
            summary = self._summary_mode
        self.tv.delete(*self.tv.get_children())
        self._iid_keys = {}
        for i, r in enumerate(rows):
            image = ""
            if summary and len(r) >= 3 and r[2]:
                tag = "summary_header"
                vals = list(r[:2])
                # The section header carries its icon in the panel's icon
                # gutter (column #0, see _show_summary): the icon belongs to
                # the row, not to the text, so the label stays translatable
                # and searchable without a glyph glued to it.
                icon_name = getattr(r, "icon", None)
                if icon_name:
                    image = _icon(icon_name, 16, self.tv) or ""
            elif summary:
                tag = "even" if i % 2 == 0 else "odd"
                vals = list(r[:2])   # the third field only marks a section row
            else:
                # A row's own tag (violation tint, month total, separator) wins
                # over the zebra stripe, and travels with the row through the
                # re-render a sort or a filter change causes — see _TableRow.
                tag = getattr(r, "tag", None) or ("even" if i % 2 == 0 else "odd")
                vals = list(r)
            # Summary rows are built with raw values; a bool must not reach the
            # screen as Python's "True"/"False".
            vals = [_bool_text(v) if isinstance(v, bool) else v for v in vals]
            key = getattr(r, "key", None)
            if key is None:
                self.tv.insert("", tk.END, values=vals, tags=(tag,), image=image)
            else:
                iid = self.tv.insert("", tk.END, values=vals, tags=(tag,),
                                     image=image, iid=str(key))
                self._iid_keys[iid] = key

    def _schedule_filter(self):
        if self._filter_after_id is not None:
            self.tv.after_cancel(self._filter_after_id)
        self._filter_after_id = self.tv.after(300, self._apply_filter)

    def _apply_filter(self):
        """Re-render keeping only rows where any cell contains the query."""
        q = self.filter_var.get().strip().lower()
        if not q:
            self._render(self._all_rows)
            return
        filtered = [r for r in self._all_rows
                    if any(q in str(c).lower() for c in r)]
        self._render(filtered)

    def _sort_by(self, col):
        """Toggle-sort by column; dd/mm/yyyy dates sort chronologically,
        numeric strings numerically, "Xh YYm" durations by their minutes, and
        everything else alphabetically."""
        idx = self._cols.index(col)
        descending = self._sort_state.get(col, False)
        date_re = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
        # Every activity column of the dashboard holds a duration in the
        # ``_fmt_duration_minutes`` shape ("9h 30m"), optionally followed by the
        # infringement marker ("  !"). Compared as text, "12h 00m" sorted before
        # "5h 00m" — that is "1" < "5" — so the sort disagreed with the numbers
        # it was sorting.
        duration_re = re.compile(r"\s*(\d+)h\s+(\d+)m")

        def key(row):
            v = row[idx] if idx < len(row) else ""
            s = str(v)
            m = date_re.match(s)
            if m:  # dd/mm/yyyy → chronological
                return (0, int(m.group(3)) * 10000 + int(m.group(2)) * 100 + int(m.group(1)))
            d = duration_re.match(s)
            if d:  # "Xh YYm" → minutes, so 12h sorts after 5h
                return (0, int(d.group(1)) * 60 + int(d.group(2)))
            try:
                # thousands are rendered with spaces (fmt_val)
                num = float(s.replace(" ", "").replace(",", "."))
                return (0, num)
            except (ValueError, TypeError):
                return (1, s.lower())

        self._all_rows.sort(key=key, reverse=descending)
        self._sort_state[col] = not descending
        for c in self._cols:
            # Re-stating the anchor keeps the sort arrow on the same side as
            # the cells it heads, on the dashboard (centred columns) too.
            self.tv.heading(c, text=str(c) + (" \u25be" if c == col and descending
                                              else " \u25b4" if c == col else ""),
                            anchor=self.tv.column(c, "anchor"))
        self._apply_filter()


#: Width of the summary panel's icon gutter (the tree column holding the
#: 16 px section icons). Taken out of the Field column, so the Value column
#: keeps the width it had before the icons arrived. It is the *design* width,
#: for a 100 % display: at a higher scale the file drawn in it is larger, so
#: the gutter grows (see :func:`_summary_icon_gutter`).
_SUMMARY_ICON_GUTTER = 22
#: Height of one tree row at 100 %, in logical px.
_TREE_ROW_HEIGHT = 24
#: Room a row icon needs around itself (vertical padding, and the gutter's
#: horizontal margin). Both are chosen so the design values above are exactly
#: what they are at 100 % — 16 + 8 is 24, 16 + 6 is 22 — and only take over
#: when a scaled display asks for a larger file.
_ROW_ICON_PADDING = 8
_SUMMARY_ICON_MARGIN = 6


















# ── Activity timeline chart ─────────────────────────────────────────────
ACTIVITY_COLORS = {
    "DRIVE": ACTIVITY_DRIVE,
    "WORK": ACTIVITY_WORK,
    "REST": ACTIVITY_REST,
    "AVAILABLE": ACTIVITY_AVAILABLE,
}

#: Activity rows of the timeline. UNKNOWN is a bucket of the shared segmentation
#: (a card-not-inserted period, Annex 1C §2.1 note 2; an unrecognised activity
#: code; a missing 00:00 status entry, §2.170) whose minutes the dashboard
#: reports, so the chart paints it too — on a row of its own, added only when the
#: day holds any unknown minutes, so a fully known day keeps its four rows.
ACTIVITY_ROWS = ("DRIVE", "WORK", "REST", "AVAILABLE")
UNKNOWN_ACTIVITY_ROW = "UNKNOWN"




class ActivityTimelineChart(ttk.Frame):
    """Gantt timeline for one UTC day of driver activity changes."""

    def __init__(self, parent):
        super().__init__(parent)
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=8, pady=(8, 2))
        self.title_lbl = ttk.Label(header, font=FONT_TITLE)
        self.title_lbl.pack(side=tk.LEFT)
        self.detail_btn = tk.Label(header, text="?", font=FONT_BADGE,
                                   fg=ACCENT, bg=LINK_BUTTON_BG, padx=6, pady=0,
                                   cursor="hand2", relief=tk.FLAT,
                                   bd=1, highlightthickness=0)
        self.detail_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.detail_btn.bind("<Enter>", lambda e: e.widget.configure(bg=HOVER_BG))
        self.detail_btn.bind("<Leave>", lambda e: e.widget.configure(bg=LINK_BUTTON_BG))
        # The day's facts — date, distance, driver, vehicle — each carry their
        # own icon, so they are one small label each instead of a single
        # joined string: an emoji inside one label cannot be replaced by an
        # image, and the icon belongs to the part, not to the text.
        self.info_bar = ttk.Frame(self)
        self.info_bar.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._info_labels: list = []
        self.canvas = tk.Canvas(self, background=WHITE, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 2))
        self.canvas.bind("<Configure>", lambda _event: self._schedule_draw())
        self.canvas.bind("<Motion>", self._show_hover)
        self.canvas.bind("<Leave>", lambda _event: self.canvas.delete("act_hover"))
        self.summary_lbl = ttk.Label(self, foreground=TEXT_MUTED, anchor=tk.W,
                                     justify=tk.LEFT)
        self.summary_lbl.pack(fill=tk.X, padx=8, pady=(2, 8))
        self._day = ""
        self._slots = {}      # slot_label -> [(start_s, end_s, activity), ...]
        self._slot_schedule = {}
        self._markers = []
        self._oos_events = []
        self._driver_name = ""
        self._draw_after_id = None
        self._label_font = None   # measuring font for the translated row labels
        self._layout = None
        self._info_parts = []
        self._activities = []
        self._day_km = 0
        self._changes_count = 0
        self._vehicle_info = []
        self._details_data = {}
        self._recorded_until = None

    def show(self, day, is_vu, activities, day_km=0, changes_count=0,
             driver_info="", slot_schedule=None, markers=None,
             vehicle_info=None, oos_events=None, data=None, recorded_until=None):
        self._day = day
        self._recorded_until = recorded_until
        self._slots = self._build_blocks(activities, is_vu, recorded_until)
        self._slot_schedule = slot_schedule or {}
        self._markers = markers or []
        self._oos_events = oos_events or []
        self._driver_name = driver_info
        self._activities = activities
        self._day_km = day_km
        self._changes_count = changes_count
        self._vehicle_info = vehicle_info or []
        self._details_data = data or {}
        self._is_vu = is_vu

        def _open_detail(e):
            if not self._day:
                return
            _live.DayDetailWindow(self.winfo_toplevel(), self._day,
                            self._activities, self._day_km,
                            self._changes_count, self._driver_name,
                            self._slot_schedule, self._markers,
                            self._oos_events, self._vehicle_info,
                            self._details_data, is_vu=self._is_vu,
                            recorded_until=self._recorded_until)

        self.detail_btn.unbind("<Button-1>")
        self.detail_btn.bind("<Button-1>", _open_detail)
        self.title_lbl.config(text=_("Daily Activities - {day} (UTC)").format(day=day))
        info_parts = [("date-range", day)]
        if is_vu:
            # No icon for the day's distance: the set has no road/odometer
            # glyph, and "123 km" already says what the number is.
            info_parts.append((None, f"{day_km} km"))
        if changes_count:
            info_parts.append((None, _("{count} changes").format(count=changes_count)))
        if driver_info:
            info_parts.append(("driver", driver_info))
        vehicle_info = vehicle_info or []
        if not is_vu and vehicle_info:
            info_parts.append(("vehicle", self._format_vehicles(vehicle_info)))
        self._info_parts = info_parts
        self._show_info_parts(info_parts)
        self._schedule_draw()

    def _show_info_parts(self, parts):
        """Render the ``(icon name, text)`` info line, one label per part."""
        for label in self._info_labels:
            label.destroy()
        self._info_labels = []
        for index, (icon_name, text) in enumerate(parts):
            image = _icon(icon_name, 16, self.info_bar) if icon_name else None
            label = ttk.Label(self.info_bar, text=text, foreground=TEXT_SECONDARY,
                              image=image or "", compound=tk.LEFT)
            label.pack(side=tk.LEFT, padx=(8 if index else 0, 2))
            self._info_labels.append(label)

    @staticmethod
    def _format_vehicles(vehicles):
        """Format the vehicles-driven label for a day.

        One vehicle → just the plate. Multiple → each plate with its
        start–end time window so the switch-over is visible. The vehicle icon
        is the row's, not the text's (see :meth:`_show_info_parts`).
        """
        def _hhmm(dt):
            return dt.strftime("%H:%M") if dt is not None else "?"

        if len(vehicles) == 1:
            return str(vehicles[0]['plate'])
        parts = [f"{v['plate']} ({_hhmm(v['start'])}\u2013{_hhmm(v['end'])})"
                 for v in vehicles]
        return ", ".join(parts)

    @staticmethod
    def _parse_time(time_str):
        """'HH:MM' → seconds since midnight, or None if unusable.

        Delegates to the shared :func:`core.utils.activity_stats.parse_time` so
        the GUI timeline rejects the same out-of-range times (``'25:00'``,
        ``'08:75'``) as the report, cover and CLI instead of accepting them.
        """
        from core.utils.activity_stats import parse_time
        return parse_time(time_str)

    @staticmethod
    def _build_blocks(changes, is_vu, recorded_until=None):
        """Convert a list of activity changes to per-slot block lists.

        The segmentation comes from :func:`core.utils.activity_stats.day_segments`,
        the single routine behind the Daily-Activities dashboard, the CLI
        summary and the PDF report. Re-deriving it here made the chart disagree
        with the dashboard on 471 of 1750 single-slot days of the tracked
        samples: it painted a card-not-inserted period as Rest (Annex 1C §2.1
        note 2 makes it UNKNOWN), left a missing leading 00:00 status entry
        unaccounted (§2.170) and dropped an unrecognised activity label. The
        blocks now tile the whole 24 h day, so a block's minutes always add up
        to what the dashboard reports for the same slot.
        """
        from core.utils.activity_stats import day_segments

        blocks = {}

        def label(raw_slot):
            if is_vu:
                return "Slot 1" if str(raw_slot) == "First" else "Slot 2"
            # A driver card records one holder's activities, whichever slot the
            # card was in, so they stay in the one "Cardholder" section the
            # chart has always shown for card files.
            return "Cardholder"

        # A slot with records but no usable time keeps its (empty) section, as
        # it did before: the axes and the slot label are still drawn.
        for ch in changes:
            if isinstance(ch, dict):
                blocks.setdefault(label(ch.get("slot") or "First"), [])
        for raw_slot, segments in day_segments(changes, recorded_until).items():
            blocks.setdefault(label(raw_slot), []).extend(segments)
        return blocks

    def _rows(self):
        """The activity rows to draw, in order.

        The four activities always; UNKNOWN only when the day has unknown
        minutes, in the neutral colour :data:`ACTIVITY_UNKNOWN` — those minutes
        are a bucket of the dashboard's totals, so leaving them unpainted made
        the chart show fewer hours than the dashboard for the same day.
        """
        if any(activity == UNKNOWN_ACTIVITY_ROW
               for blocks in self._slots.values()
               for _start, _end, activity in blocks):
            return [*ACTIVITY_ROWS, UNKNOWN_ACTIVITY_ROW]
        return list(ACTIVITY_ROWS)

    def _schedule_draw(self):
        if self._draw_after_id is not None:
            self.after_cancel(self._draw_after_id)
        self._draw_after_id = self.after_idle(self._draw)

    def _draw(self):
        self._draw_after_id = None
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 120 or height < 100:
            return

        if not self._slots:
            return

        rows = self._rows()
        # Translated row labels are wider than the original 100px gutter.
        label_gap, label_pad = 8, 4
        if self._label_font is None:
            self._label_font = tkfont.Font(root=canvas, font=FONT_CAPTION_BOLD)
        widest_label = max(self._label_font.measure(_act_label(act)) for act in rows)
        left, right, top, bottom = (max(100, widest_label + label_gap + label_pad),
                                    14, 64, height - 32)
        plot_width = width - left - right
        totals_bar = 80
        usable_width = plot_width - totals_bar - 12
        plot_height = bottom - top
        gap = 4

        slot_order = sorted(self._slots.keys())
        has_multi = len(slot_order) > 1

        if has_multi:
            section_gap = 44
            per_section_h = (plot_height - section_gap) // 2
        else:
            section_gap = 0
            per_section_h = plot_height

        self._layout = {"left": left, "plot_width": usable_width,
                        "act_rows": [], "has_multi": has_multi,
                        "markers_info": []}

        # Time axis ticks — drawn across both sections
        for hour in range(0, 25, 6):
            x = left + usable_width * hour / 24
            canvas.create_line(x, top, x, bottom, fill=CHART_GRID_MINOR)
            canvas.create_text(x, top - 22, text=f"{hour:02d}:00",
                               anchor=tk.S, fill=TEXT_MUTED)

        # Out-of-scope / ferry-train markers (between card markers and activity rows)
        OOS_COLORS = {
            "OutOfScope Begin": ACTIVITY_WORK,
            "OutOfScope End": ACTIVITY_WORK,
            "Ferry/Train Begin": ACTIVITY_FERRY,
            "Ferry/Train End": ACTIVITY_FERRY,
            # Generation 1 single ferry/train crossing code (Annex 1C §2.154).
            "Ferry/Train crossing": ACTIVITY_FERRY,
        }
        # Section header height (slot label + markers, above activity rows)
        header_h = 56 if has_multi else 24
        oos_info = []
        for sec, cond, ts in self._oos_events:
            x = left + sec * usable_width / 86400
            color = OOS_COLORS.get(cond, ACTIVITY_UNKNOWN)
            size = 4
            is_begin = "Begin" in cond
            marker_y = top + header_h - 42 if has_multi else top + header_h - 17
            if is_begin:
                canvas.create_polygon(x, marker_y + 2, x - size, marker_y - 3,
                                      x + size, marker_y - 3,
                                      fill=color, outline=color, tags="oos_marker")
            else:
                canvas.create_polygon(x, marker_y - 2, x - size, marker_y + 3,
                                      x + size, marker_y + 3,
                                      fill=color, outline=color, tags="oos_marker")
            oos_info.append((x, marker_y, cond, ts))
        self._layout["oos_info"] = oos_info

        usable_h = per_section_h - header_h
        row_h = max(18, min(30, (usable_h - (len(rows) - 1) * gap) // len(rows)))

        totals_lines = []

        for sidx, slot_name in enumerate(slot_order):
            section_top = top + sidx * (per_section_h + section_gap)

            # Divider line between sections
            if sidx > 0:
                dy = section_top - section_gap // 2
                canvas.create_line(left - 8, dy, left + usable_width + 8, dy,
                                   fill=TEXT_FAINT, width=1)

            slot_blocks = self._slots.get(slot_name, [])

            # Slot label: the cardholder section is the driver's, so it leads
            # with the driver icon (drawn, not typed: see app/icons.py). The
            # canvas needs the image object on its own item, hence the offset
            # for the text that follows it.
            label_icon = None
            if slot_name == "Cardholder" and self._driver_name:
                label_text = self._driver_name
                label_icon = _icon("driver", 16, canvas)
            else:
                label_text = _(slot_name)
            label_y = section_top + header_h // 3
            label_x = left
            if label_icon is not None:
                canvas.create_image(left, label_y, image=label_icon, anchor=tk.W)
                # The offset is the *image's* width, not the 16 px it was
                # requested at: on a scaled display the file drawn here is
                # larger (see _icon), and a fixed offset would print the name on
                # top of it. At 100 % this is 16 + 2 = 18, exactly as before.
                label_x = left + label_icon.width() + _px(2)
            canvas.create_text(label_x, label_y,
                               text=label_text, anchor=tk.W,
                               fill=TEXT_STRONG, font=FONT_CANVAS_TITLE)

            # Per-slot totals
            totals = {}
            for start_s, end_s, act in slot_blocks:
                totals[act] = totals.get(act, 0) + (end_s - start_s)
            parts = []
            for act in rows:
                seconds = totals.get(act, 0)
                if seconds:
                    h, m = divmod(seconds // 60, 60)
                    parts.append(f"{h}h {m:02d}m {_act_label(act)}")
            slot_text = _(slot_name)
            totals_lines.append(f"  {slot_text}:  " + "  |  ".join(parts) if parts
                                else f"  {slot_text}:  —")

            # Activity rows start after the header
            rows_top = section_top + header_h
            for ridx, act in enumerate(rows):
                y0 = rows_top + ridx * (row_h + gap)
                y1 = y0 + row_h
                color = ACTIVITY_COLORS.get(act, ACTIVITY_UNKNOWN)

                # Activity label on the left
                canvas.create_text(left - label_gap, (y0 + y1) / 2,
                                   text=_act_label(act),
                                   anchor=tk.E, fill=TEXT_SECONDARY,
                                   font=FONT_CAPTION_BOLD)

                blocks = sorted(
                    [(s, e) for s, e, a in slot_blocks if a == act],
                    key=lambda b: b[0])

                slot_tag = slot_name if has_multi else ""
                self._layout["act_rows"].append((act, y0, y1, blocks, slot_tag))

                for start_s, end_s in blocks:
                    x0 = left + start_s * usable_width / 86400
                    x1 = left + end_s * usable_width / 86400
                    canvas.create_rectangle(x0, y0 + 4, x1, y1 - 4,
                                            fill=color, outline=color)

                # Per-row total on the right
                act_total = sum(e - s for s, e in blocks)
                th, tm = divmod(act_total // 60, 60)
                total_text = f"{th}h {tm:02d}m"
                total_x = left + usable_width + 16
                canvas.create_text(total_x, (y0 + y1) / 2, text=total_text,
                                   anchor=tk.W, fill=TEXT_MUTED, font=FONT_CAPTION)

            # Draw card-insertion / withdrawal markers in the header area
            slot_index = {name: idx for idx, name in enumerate(slot_order)}
            for sec, m_slot, m_name, is_ins in self._markers:
                if not m_name:
                    continue
                sidx = slot_index.get(m_slot)
                if sidx is None:
                    continue
                marker_section_top = top + sidx * (per_section_h + section_gap)
                marker_x = left + sec * usable_width / 86400
                marker_y = marker_section_top + header_h - 14
                size = 6
                color = SUCCESS if is_ins else DANGER
                if is_ins:
                    canvas.create_polygon(marker_x, marker_y + 4, marker_x - size, marker_y - 6,
                                          marker_x + size, marker_y - 6,
                                          fill=color, outline=color, tags="act_marker")
                else:
                    canvas.create_polygon(marker_x, marker_y - 4, marker_x - size, marker_y + 6,
                                          marker_x + size, marker_y + 6,
                                          fill=color, outline=color, tags="act_marker")
                self._layout["markers_info"].append(
                    (marker_x, marker_y, m_slot, m_name, is_ins, sec))

        self.summary_lbl.config(text="\n".join(totals_lines))

    def _draw_hover_tip(self, text, event, reserve):
        """Draw a hover tooltip that always stays inside the canvas.

        ``reserve`` is the old fixed guess at the room the text needs; it keeps
        tooltips that already fit exactly where they were. The real bounding
        box is then measured, so a translated (longer) string is moved back
        inside the canvas instead of losing its tail, and one that is wider
        than the whole canvas is wrapped to the available width. Wrapping makes
        the tip taller than the one-line anchor asked for, so the frame is
        finally clamped on BOTH axes; its own bbox already carries the 1px
        outline, and the text always moves with it.
        """
        canvas = self.canvas
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        pad = 5
        margin = pad + 1
        text_id = canvas.create_text(
            min(event.x + 12, width - reserve), max(event.y - 24, 4), text=text,
            anchor=tk.NW, fill=TOOLTIP_FG, tags="act_hover")
        x1, y1, x2, y2 = canvas.bbox(text_id)
        if x2 > width - margin:
            canvas.move(text_id, width - margin - x2, 0)
            x1, y1, x2, y2 = canvas.bbox(text_id)
        if x1 < margin:
            # Tk breaks lines on the requested width but reports a bbox a pixel
            # or two wider than that budget, which would poke the frame past the
            # right edge: shrink the budget by the excess actually measured.
            budget = max(1, width - 2 * margin)
            for _ in range(3):
                canvas.itemconfigure(text_id, width=budget)
                x1, y1, x2, y2 = canvas.bbox(text_id)
                excess = (x2 - x1) - (width - 2 * margin)
                if excess <= 0 or budget <= 1:
                    break
                budget = max(1, budget - excess)
            canvas.move(text_id, margin - x1, 0)
            x1, y1, x2, y2 = canvas.bbox(text_id)
        bg = canvas.create_rectangle(
            x1 - pad, y1 - 3, x2 + pad, y2 + 3,
            fill=TOOLTIP_BG, outline=TOOLTIP_BORDER, tags="act_hover")
        canvas.tag_lower(bg, text_id)
        # Clamp what the user actually sees: the frame's bbox (its 5/3px pad and
        # the 1px outline included), not just the text. Trying to fit both axes
        # leaves an already-fitting tip alone, and a tip larger than the canvas
        # is pinned to the origin instead of being half drawn off-canvas.
        x1, y1, x2, y2 = canvas.bbox(bg)
        dx = width - x2 if x2 > width else 0
        dy = height - y2 if y2 > height else 0
        if x1 + dx < 0:
            dx = -x1
        if y1 + dy < 0:
            dy = -y1
        if dx or dy:
            canvas.move(text_id, dx, dy)
            canvas.move(bg, dx, dy)

    def _show_hover(self, event):
        if not self._layout or not self._slots:
            return
        self.canvas.delete("act_hover")
        left = self._layout["left"]
        plot_width = self._layout["plot_width"]

        # Check markers first
        for mx, my, m_slot, m_name, is_ins, _sec in self._layout.get("markers_info", []):
            if abs(event.x - mx) <= 10 and abs(event.y - my) <= 10:
                kind = _("\u25bc Insertion") if is_ins else _("\u25b2 Withdrawal")
                text = f"{kind}: {m_name} ({_(m_slot)})"
                self._draw_hover_tip(text, event, 260)
                return

        # Check OOS markers
        for ox, oy, cond, ts in self._layout.get("oos_info", []):
            if abs(event.x - ox) <= 10 and abs(event.y - oy) <= 10:
                ts_str = ts.strftime("%H:%M") if ts else "?"
                text = f"{cond}: {ts_str}"
                self._draw_hover_tip(text, event, 260)
                return

        has_multi = self._layout.get("has_multi", False)
        for act, y0, y1, blocks, slot_tag in self._layout.get("act_rows", []):
            if not y0 <= event.y <= y1:
                continue
            if not left <= event.x <= left + plot_width:
                continue
            target_sec = (event.x - left) * 86400 / plot_width
            matches = [(s, e) for s, e in blocks if s <= target_sec <= e]
            if not matches:
                continue
            start_s, end_s = matches[-1]
            sh, sm = divmod(start_s // 60, 60)
            eh, em = divmod(end_s // 60, 60)
            dur = (end_s - start_s) // 60
            dh, dm = divmod(dur, 60)
            # Act labels are translated at the display boundary, never stored.
            if has_multi:
                text = (f"{_(slot_tag)}  {_act_label(act)}  "
                        f"[{sh:02d}:{sm:02d} \u2014 {eh:02d}:{em:02d}]  "
                        f"\u00b7  {dh}h {dm:02d}m")
            else:
                text = (f"{_act_label(act)}  "
                        f"[{sh:02d}:{sm:02d} \u2014 {eh:02d}:{em:02d}]  "
                        f"\u00b7  {dh}h {dm:02d}m")
            self._draw_hover_tip(text, event, 300)
            return





# ── Day detail popup ──────────────────────────────────────────────────────



# ── Day detail helpers ───────────────────────────────────────────────────

# Driver/desc starts at _DETAIL_RANGE + _DETAIL_DUR












# ── Drag & drop (optional) ───────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _drop_splitter():
    """Tcl's own list parser, without a display (``tk.Tcl`` opens no window).

    A dropped payload is a *Tcl list*, not whitespace-separated text: a path
    with a space arrives braced (``{/a b/c.ddd}``) and Windows paths carry
    backslashes, so only Tcl's rules can take it apart. The GUI passes
    ``self.tk.splitlist``; this display-less interpreter is the same parser for
    the callers that have no root (tests, batch tools).
    """
    return tk.Tcl().splitlist


def dropped_paths(data, split=None, isfile=None):
    """The existing regular files among a ``<<Drop>>`` payload, in drop order.

    ``data`` is tkdnd's ``%D`` substitution — the raw Tcl list of the dropped
    paths — and this is the only place that interprets it. Directories and
    paths that no longer exist are dropped: a drop must never open something
    that is not a readable file. Nothing usable yields ``[]``.

    ``split`` (a Tcl list splitter) and ``isfile`` (the existence predicate) are
    injectable so the parsing can be tested without a display and without
    touching the disk.
    """
    if not isinstance(data, str) or not data.strip():
        return []
    split = split or _drop_splitter()
    isfile = isfile or os.path.isfile
    try:
        candidates = split(data)
    except Exception:  # unbalanced braces/quotes: not a list we can use
        _log.debug("dropped payload is not a Tcl list: %r", data)
        return []
    if isinstance(candidates, str):
        candidates = [candidates]
    return [path for path in candidates if isinstance(path, str) and path and isfile(path)]


# ── Main application ─────────────────────────────────────────────────────

def _resource_path(rel):
    """Path of a bundled resource (PyInstaller _MEIPASS or repo root)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)














# ── Help: one list of addresses, one About text, two entry points ───────────
#
# macOS has a menu bar, so Help lives in it (and a menu whose Tk name is `help`
# becomes the *native* Help menu, with the search field Aqua puts there).
# Windows and Linux have no menu bar in this app, so they get one Help button at
# the end of the toolbar. Both read the same data below: one list of addresses,
# one About text, so the two entry points cannot drift apart.








#: LaunchServices' URL opener. `/usr/bin/open` is part of macOS itself, so it is
#: always there in practice; the fallback exists for the pathological case.
_MACOS_OPEN = "/usr/bin/open"

#: The only schemes the app ever hands to the system: every address it opens
#: comes from :func:`help_links`, and nothing else may be launched this way.
_OPENABLE_SCHEMES = ("http", "https")


def open_url(url):
    """Open *url* in the user's browser — the only way the app leaves itself.

    macOS: ``/usr/bin/open``, not ``webbrowser``. In the frozen (PyInstaller)
    bundle ``webbrowser`` shells out to ``osascript``, and that helper registers
    with LaunchServices as an application of its own: every Help link added a
    second, bouncing "TachoReader" icon to the Dock. ``/usr/bin/open`` asks
    LaunchServices for the URL's handler directly, from a plain process, so the
    browser comes forward and nothing is added to the Dock. Anything else (a
    missing binary, an OSError) falls through to ``webbrowser`` — a link that
    opens with an extra icon is still better than a link that does nothing.

    Only ``http``/``https`` addresses are opened: the callers pass the fixed list
    from :func:`help_links`, and a ``file:`` or ``javascript:`` URL must never
    reach the system opener on the strength of a wrong argument.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in _OPENABLE_SCHEMES:
        raise ValueError(f"refusing to open a non-web URL: {url!r}")
    if _is_macos():
        try:
            subprocess.Popen([_MACOS_OPEN, url], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
            return
        except OSError:
            _log.warning("could not launch %s, falling back to webbrowser:\n%s",
                         _MACOS_OPEN, traceback.format_exc())
    webbrowser.open(url)


def _is_macos():
    """True on macOS. Read at call time: the menu bar decision is per platform."""
    return sys.platform == "darwin"


class HelpWindow(tk.Toplevel):
    """Help / About over the main window (the Windows and Linux entry point).

    One window at a time: a second Help click lifts the open one instead of
    stacking a copy on top of it. The contents come from :func:`about_text` and
    :func:`help_links`, never from a second copy of the text.
    """

    _open_window = None  # type: "HelpWindow | None"

    def __init__(self, parent):
        super().__init__(parent)
        HelpWindow._open_window = self
        self.title(_("Help"))
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=SURFACE_ALT)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        body = tk.Frame(self, background=SURFACE_ALT, padx=_px(18), pady=_px(16))
        body.pack(fill=tk.BOTH, expand=True)
        self.about_label = ttk.Label(body, text=about_text(), justify=tk.LEFT,
                                     font=FONT_BODY, wraplength=_px(520))
        self.about_label.pack(anchor=tk.W, fill=tk.X)

        links = ttk.Frame(body)
        links.pack(anchor=tk.W, fill=tk.X, pady=(_px(12), 0))
        self.link_buttons = []
        for label, url in _live.help_links():
            button = ttk.Button(links, text=label,
                                command=lambda target=url: open_url(target))
            button.pack(side=tk.LEFT, padx=(0, _px(8)))
            self.link_buttons.append(button)

        self.close_button = ttk.Button(body, text=_("Close"),
                                       command=self._on_close)
        self.close_button.pack(anchor=tk.E, pady=(_px(14), 0))

        self.bind("<Escape>", lambda _event: self._on_close())
        self._centre_on(parent)
        self.focus_set()

    def _centre_on(self, parent):
        """Place the dialog over *parent*, never off screen."""
        try:
            self.update_idletasks()
            width, height = self.winfo_reqwidth(), self.winfo_reqheight()
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 3)
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:                     # no geometry yet: let Tk place it
            _log.debug("help window placement not available")

    def _on_close(self):
        if HelpWindow._open_window is self:
            HelpWindow._open_window = None
        self.destroy()


def show_help(parent):
    """Open the one Help window for *parent* (lifting the open one)."""
    existing = HelpWindow._open_window
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return existing
        except tk.TclError:                     # a Tk interpreter that is gone
            pass
        HelpWindow._open_window = None
    return HelpWindow(parent)


def _gc_pause():
    """Stop the collector (a pass over the previous file's big graph stalls every thread)."""
    was_enabled = gc.isenabled()
    gc.unfreeze()
    gc.disable()
    return was_enabled


def _gc_resume(was_enabled):
    """Park the finished result graph in the permanent generation and restore the GC."""
    try:
        gc.freeze()
    finally:
        if was_enabled:
            gc.enable()
