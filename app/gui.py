"""Tacho Explorer — DDD viewer, regedit-style.

Layout:
    ┌────────────────────────┬─────────────────────────────────────┐
    │  Section tree          │  Section content (table)             │
    │  (regedit-style)       │  headers · rows · sortable           │
    └────────────────────────┴─────────────────────────────────────┘

On the left, the hierarchical section tree; on the right, the selected
section's content shown in table form (one row per record, one column per
field), with column sorting and text filtering.
"""
from app.gui_base import (  # noqa: F401  (re-exported: app.gui.<name> stays valid)
    ACCENT,
    ACTIVE_BG,
    ACTIVITY_AVAILABLE,
    ACTIVITY_COLORS,
    ACTIVITY_DRIVE,
    ACTIVITY_DRIVE_TINT,
    ACTIVITY_EVENT,
    ACTIVITY_FERRY,
    ACTIVITY_LABEL,
    ACTIVITY_REST,
    ACTIVITY_ROWS,
    ACTIVITY_UNKNOWN,
    ACTIVITY_WORK,
    ActivityTimelineChart,
    BORDER,
    BUTTON_PRESSED_BG,
    BytesEncoder,
    CARD_BORDER,
    CARD_ENVELOPE_NOTICE,
    CARD_HEADER_NOTICE,
    CAUTION,
    CHART_GRID_MAJOR,
    CHART_GRID_MINOR,
    CONTROL_HOVER_BG,
    DAILY_DRIVE_LIMIT_MIN,
    DANGER,
    DANGER_BAND,
    DANGER_STRONG,
    DASHBOARD_TOOLTIP_BG,
    DONATION_URL,
    DataTable,
    DayDetailWindow,
    DetailedSpeedChart,
    ExportManager,
    FIELD_BG,
    FONT_BADGE,
    FONT_BODY,
    FONT_CANVAS_TITLE,
    FONT_CAPTION,
    FONT_CAPTION_BOLD,
    FONT_HEADING,
    FONT_KPI_VALUE,
    FONT_MONO,
    FONT_MONO_BOLD,
    FONT_MONO_ITALIC,
    FONT_MONO_LARGE,
    FONT_MONO_NORMAL,
    FONT_MONO_SMALL,
    FONT_PAGE_TITLE,
    FONT_SMALL,
    FONT_SUBTITLE,
    FONT_SUBTITLE_BOLD,
    FONT_TITLE,
    GAP_BAND,
    GEN_COLORS,
    HEADER_BG,
    HIDDEN_KEYS,
    HOVER_BG,
    HelpWindow,
    LANGUAGES,
    LEADING_KEYS,
    LINK_BUTTON_BG,
    MUTED,
    NATION_COLS,
    PROJECT_URL,
    ROW_EVEN,
    ROW_ODD,
    SASH_START,
    SCROLLBAR_BG,
    SCROLLBAR_HOVER_BG,
    SHOW_DRIVING_INFRACTIONS,
    SLATE,
    SPEED_DAY_SECONDS,
    SPEED_GAP_SECONDS,
    SPEED_LIMIT_KMH,
    SPEED_MIN_VIEW_SECONDS,
    SUCCESS,
    SURFACE,
    SURFACE_ALT,
    SURFACE_RAISED,
    SURFACE_SUNKEN,
    SpeedBin,
    TEXT_FAINT,
    TEXT_FAINT_TEXT,
    TEXT_LABEL,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_STRONG,
    TEXT_SUBTLE,
    TOGGLE_BG,
    TOOLTIP_BG,
    TOOLTIP_BORDER,
    TOOLTIP_FG,
    TRAILING_KEYS,
    TachoParser,
    UNKNOWN_ACTIVITY_ROW,
    VERDICT_CORRUPT,
    VERDICT_PARTIAL,
    VERDICT_VERIFIED,
    WARNING,
    WHITE,
    _,
    _BADGE_WORDS,
    _BAR_MAX_TICKS,
    _BAR_TICK,
    _DETAIL_DUR,
    _DETAIL_RANGE,
    _ICON_FAILURE_LOGGED,
    _KPI_CARD_BORDER,
    _KPI_CARD_PADX,
    _KPI_CARD_PADY,
    _KPI_GRID_PAD,
    _KPI_WIDTH_SLACK,
    _LEGEND_GLYPH_WIDTH,
    _LiveGuiNames,
    _MACOS_OPEN,
    _OPENABLE_SCHEMES,
    _PUMP_USES_EVENTS,
    _RENDER_PUMP_INTERVAL,
    _RENDER_PUMP_MAX_GAP,
    _ROW_ICON_PADDING,
    _RenderAbandoned,
    _SCALE_PER_TK_UNIT,
    _SUMMARY_ICON_GUTTER,
    _SUMMARY_ICON_MARGIN,
    _SummaryHeader,
    _TREE_ROW_HEIGHT,
    _TableRow,
    _WARN_POLL_MS,
    _WIN_DPI,
    _WIN_SCALE,
    __version__,
    _act_label,
    _activity_days,
    _activity_label,
    _activity_to_iso,
    _attach_day_distance,
    _autohide,
    _bool_text,
    _bring_to_front,
    _calibration_days_left,
    _changes_for_slot,
    _columns_for,
    _compute_activity_totals,
    _condition_label,
    _driver_names_by_date,
    _driving_rule_explanation,
    _drop_empty_values,
    _drop_splitter,
    _elide_to_width,
    _envelope_notice,
    _flow_rows,
    _flush,
    _fmt_dict,
    _fmt_duration_minutes,
    _fmt_empty_prefix,
    _fmt_range_dur,
    _fmt_seconds_duration,
    _format_duration,
    _gc_pause,
    _gc_resume,
    _header_notice,
    _hhmm_to_min,
    _icon,
    _icon_px,
    _integrity_bullets,
    _is_macos,
    _kpi_card,
    _kv_rows,
    _live,
    _log,
    _pack_padx,
    _parse_iso,
    _pump_uses_events,
    _px,
    _resource_path,
    _right_padding,
    _rows_for,
    _signature_verdict_clause,
    _summary_block,
    _summary_icon_gutter,
    _tree_row_height,
    _ui_scale,
    _utc_speed_block,
    _without_indicator,
    _wrap_at_underscores,
    about_text,
    add_recent_file,
    datetime,
    default_speed_view,
    detailed_speed_blocks_by_day,
    detailed_speed_by_day,
    dropped_paths,
    envelope_fill_pieces,
    evaluate_driving_rules,
    filedialog,
    fmt_known_structure,
    fmt_scalar,
    fmt_val,
    functools,
    gc,
    help_links,
    icons,
    install,
    integrity_verdict,
    json,
    load_trace,
    logging,
    messagebox,
    nation_full_name,
    open_url,
    os,
    queue,
    re,
    recorded_until_seconds,
    report_format,
    save_language,
    save_translate_data,
    saved_language,
    saved_recent_files,
    saved_translate_data,
    show_help,
    speed_envelope_runs,
    subprocess,
    sys,
    threading,
    time,
    timedelta,
    timezone,
    tk,
    tkfont,
    traceback,
    ttk,
    ui_text,
    urlparse,
    webbrowser,
)
from app.gui_explorer_shell import ShellMixin
from app.gui_explorer_load import LoadMixin
from app.gui_explorer_export import ExportMixin
from app.gui_explorer_status import StatusMixin
from app.gui_explorer_tree import TreeMixin
from app.gui_explorer_dashboard import DashboardMixin
from app.gui_explorer_summary import SummaryMixin


class TachoExplorer(ShellMixin, LoadMixin, ExportMixin, StatusMixin, TreeMixin, DashboardMixin, SummaryMixin, tk.Tk):
    #: Idle defaults for the busy/render state read by ``_parse_done``,
    #: ``_start_parse`` and ``_pump_render``. They exist on the class as well as
    #: on the instance because a tkinter widget resolves a missing attribute
    #: through ``Misc.__getattr__``, which forwards to ``self.tk`` — and on the
    #: widget-less ``object.__new__(TachoExplorer)`` twins the GUI tests build
    #: there is no ``self.tk``, so a *missing* attribute recurses until the
    #: interpreter gives up. An attribute that always answers keeps them alive.
    _destroyed = False

    _rendering = False

    _parsing = False

    _gc_was_enabled = None      # None: the GC is not paused by a parse

    _pump_due = 0.0

    _bar_at = 0.0               # last manual busy-bar step (idle pump mode)

    _open_pending = False       # a picked file waits for its deferred parse start

    def __init__(self, initial_file=None):
        super().__init__()
        # The saved UI language must be loaded before the first _() call below.
        self._language = install(saved_language())
        # Whether labels decoded from the file are translated: read once here,
        # cached in the display-text layer, toggled from the Language menu.
        self._translate_data = saved_translate_data()
        ui_text.configure_translate_data(self._translate_data)
        self._initial_file = initial_file
        # Set when the user picks another language: ``main()`` reads these to
        # rebuild the window in the new language (see _switch_language).
        self._restart_requested = False
        self._restart_file = None
        self.title(f"Tacho Explorer v{__version__}")
        load_trace.header(self, __version__)
        self.geometry(f"{_px(1280)}x{_px(760)}")
        self.minsize(_px(900), _px(560))

        try:
            icon_png = _resource_path(os.path.join("AppIcons", "256.png"))
            if not os.path.exists(icon_png):
                icon_png = _resource_path(os.path.join(
                    "AppIcons", "Assets.xcassets", "AppIcon.appiconset", "256.png"))
            if os.path.exists(icon_png):
                self.iconphoto(True, tk.PhotoImage(file=icon_png))
        except Exception:
            _log.debug("window icon not available")

        try:
            if sys.platform == "win32":
                # Tk sizes fonts in points; "tk scaling" is pixels-per-point.
                # The correct value is DPI/72 (not DPI/96), otherwise every
                # point-sized font renders ~25% too small at 100% and worse at
                # higher DPI. This is what made the UI look tiny on Windows.
                self.call("tk", "scaling", _WIN_DPI / 72.0)
            elif sys.platform == "darwin":
                # macOS handles Retina scaling natively; forcing 1.0 avoids
                # double-scaling of fonts and widgets.
                self.call("tk", "scaling", 1.0)
            else:
                # Linux/other: derive a scaling factor from the actual screen
                # DPI so HiDPI displays are not rendered tiny.
                try:
                    dpi = self.winfo_fpixels("1i")
                    scale = max(1.0, min(dpi / 72.0, 3.0)) if dpi else 1.0
                except Exception:
                    scale = 1.0
                self.call("tk", "scaling", scale)
        except Exception:
            _log.debug("tk scaling not available")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            _log.debug("clam theme not available")
        # Force light appearance on macOS dark mode. This call may raise on
        # some Tk builds; it must NOT fall back to the native (aqua) theme,
        # otherwise all clam styling below is silently ignored.
        if sys.platform == "darwin":
            for args in (("useDarkMode", "0"), ("appearance", "aqua")):
                try:
                    self.tk.call("::tk::unsupported::MacWindowStyle", "style",
                                 self._w, *args)
                except Exception:
                    _log.debug("MacWindowStyle %s not available", args)

        # Force a light title bar on Windows 10/11 dark mode so it matches the
        # (light) client area. DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (or 19 on
        # older builds); setting it to 0 requests the light title bar.
        if sys.platform == "win32":
            try:
                from ctypes import windll, byref, c_int, sizeof
                self.update_idletasks()
                hwnd = windll.user32.GetParent(self.winfo_id())
                value = c_int(0)
                for attr in (20, 19):
                    windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, byref(value), sizeof(value))
            except Exception:
                _log.debug("light title bar not available")

        # A coherent light palette so the whole window matches the (light)
        # data tables even when the OS is in dark mode. Without this, macOS
        # dark mode leaves ttk frames/labels dark while the explicitly-styled
        # Treeview rows stay light, producing a jarring split appearance.
        self.configure(background=SURFACE)

        # tk_setPalette recolours classic (non-ttk) widgets: menus, canvases,
        # message boxes. Do this first, then override ttk styles below so the
        # palette cannot clobber ttk-specific element colours (e.g. the tree
        # expand/collapse indicator).
        self.tk_setPalette(background=SURFACE, foreground=TEXT_PRIMARY,
                           activeBackground=ACTIVE_BG, activeForeground=TEXT_PRIMARY,
                           highlightBackground=SURFACE,
                           highlightColor=ACCENT,
                           selectBackground=ACCENT, selectForeground=WHITE)

        # Root style: kills clam's grey 3D borders/shading everywhere at once.
        style.configure(".", background=SURFACE, foreground=TEXT_PRIMARY,
                        fieldbackground=FIELD_BG, bordercolor=BORDER,
                        darkcolor=SURFACE, lightcolor=SURFACE,
                        troughcolor=ACTIVE_BG, arrowcolor=TEXT_PRIMARY,
                        insertcolor=TEXT_PRIMARY, focuscolor=ACCENT,
                        selectbackground=ACCENT, selectforeground=WHITE)

        for cls in ("TFrame", "TLabelframe", "TPanedWindow"):
            style.configure(cls, background=SURFACE)
        style.configure("TLabelframe.Label", background=SURFACE, foreground=TEXT_PRIMARY)
        style.configure("TLabel", background=SURFACE, foreground=TEXT_PRIMARY)
        style.configure("TButton", background=HEADER_BG, foreground=TEXT_PRIMARY,
                        bordercolor=BORDER)
        style.map("TButton",
                  background=[("active", CONTROL_HOVER_BG), ("pressed", BUTTON_PRESSED_BG)])
        style.configure("TMenubutton", background=HEADER_BG, foreground=TEXT_PRIMARY,
                        arrowcolor=TEXT_PRIMARY)
        style.map("TMenubutton", background=[("active", CONTROL_HOVER_BG)])
        style.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT_PRIMARY,
                        insertcolor=TEXT_PRIMARY, bordercolor=BORDER)
        style.configure("TCombobox", fieldbackground=FIELD_BG, foreground=TEXT_PRIMARY)
        style.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG,
                        foreground=TEXT_PRIMARY, bordercolor=BORDER)
        style.map("Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", WHITE)])
        # Restore a dark, visible expand/collapse arrow on the light tree.
        style.configure("Treeview.Item", indicatorforeground=TEXT_PRIMARY)
        style.configure("Treeview.Heading", background=HEADER_BG,
                        foreground=TEXT_PRIMARY, font=FONT_HEADING,
                        bordercolor=BORDER, relief=tk.FLAT)
        style.map("Treeview.Heading", background=[("active", CONTROL_HOVER_BG)])
        style.configure("TScrollbar", background=SCROLLBAR_BG, troughcolor=SURFACE,
                        bordercolor=BORDER, arrowcolor=TEXT_PRIMARY)
        style.map("TScrollbar", background=[("active", SCROLLBAR_HOVER_BG)])
        # PanedWindow divider (sash) between the tree and the table.
        style.configure("Sash", background=SURFACE, bordercolor=BORDER,
                        lightcolor=SURFACE, darkcolor=SURFACE)
        style.configure("TProgressbar", background=ACCENT, troughcolor=ACTIVE_BG)
        # The row height must hold the row icon at this display's scale, which
        # is why it is derived from the image rather than written down: a
        # 16 px icon in a 24 px row is today's layout (16 + 8 == _px(24)), and
        # at 200 % the 32 px file gets a 40 px row instead of being clipped by
        # the one it is drawn in. "Summary.Treeview" inherits this value.
        style.configure("Treeview", rowheight=_tree_row_height(self))

        self.current_data = None
        self.current_file = None
        self._payloads = {}  # iid -> (title, columns, rows, meta)
        # Reveal label for a summary cell wider than its column, and its
        # <Motion>/<Leave> bindings (see _bind_summary_reveal).
        self._summary_tip_lbl = None
        self._summary_motion_bind = None
        self._summary_leave_bind = None
        self._summary_header_font = None
        self._destroyed = False
        self._parsing = False
        # True while the tree is being rebuilt from scratch: the render owns the
        # tree (and the selection) until it ends, so an open, a drop or a
        # <<TreeviewSelect>> delivered by the render's own event-loop pump is
        # refused instead of running a second render on top of the first.
        self._rendering = False
        # monotonic() timestamp of the next event-loop pump (see _pump_render).
        self._pump_due = 0.0
        self._exporting = False
        self._parse_queue = queue.Queue()
        self._export_queue = queue.Queue()

        # Optional feature, registered before the UI is built: the empty state
        # only advertises a drop target when the registration really happened.
        self._dnd_enabled = False
        self._drop_command = None
        self.drop_hint = None
        self._enable_dnd()

        self._build_ui()
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            _log.debug("WM_DELETE_WINDOW not supported")


def _emit(line):
    """Report a smoke/version line. The Windows bundle is windowed
    (``console=False``): ``print`` is a silent no-op there, so the line is
    also appended to the file named by ``TACHO_SMOKE_LOG`` for CI to read."""
    print(line)
    log = os.environ.get("TACHO_SMOKE_LOG")
    if log:
        try:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def _smoke_check(path):
    """Headless self-check used by CI on the frozen bundle: parse *path*
    end-to-end (decoders, certificates, signature verification) without
    opening a window. Returns a process exit code."""
    _emit(f"SMOKE START: v{__version__} file={path}")
    try:
        from app.engine import TachoParser
        parser = TachoParser(path)
        result = parser.parse()
    except Exception:
        _emit(f"SMOKE FAIL: parse raised\n{traceback.format_exc()}")
        return 1
    meta = result.get("metadata") or {}
    parse_error = meta.get("parse_error")
    if parse_error:
        message = (parse_error.get("message", "Unknown parse error")
                   if isinstance(parse_error, dict) else str(parse_error))
        _emit(f"SMOKE FAIL: parse error {message}")
        return 1
    if not result.get("raw_tags"):
        _emit("SMOKE FAIL: no structures decoded")
        return 1
    # QA-FROZEN-CERT-GATE (I-F5): a frozen bundle must ship a usable ERCA root
    # store. A missing/corrupt ``certs/`` directory leaves the signature
    # validator with an empty root store (core/crypto/signature.py only logs a
    # warning), so every chain is silently unverifiable while the parse still
    # succeeds — the old smoke test returned 0 in that case. Fail the gate so a
    # bundle that cannot anchor signatures is never released.
    validator = getattr(parser, "validator", None)
    roots = getattr(validator, "root_certificates", None)
    if not roots:
        _emit("SMOKE FAIL: ERCA root store empty (missing/broken certs/)")
        return 1
    _emit(f"SMOKE OK: v{__version__} gen={meta.get('generation')} "
          f"sections={len(result.get('raw_tags') or {})} "
          f"erca_roots={len(roots)}")
    return 0


def main():
    # Minimal CLI surface so CI can exercise the frozen GUI bundle headless.
    args = sys.argv[1:]
    if args[:1] == ["--version"]:
        _emit(f"TachoReader {__version__}")
        sys.exit(0)
    if args[:1] == ["--smoke"]:
        # GUI-SMOKE-LAUNCH (H-F6): a bare "--smoke" (no file) must not fall
        # through to launching the GUI — a headless CI runner would hang. Emit
        # a usage message and exit non-zero; only "--smoke <file>" self-checks.
        if len(args) != 2:
            _emit("usage: --smoke <file.ddd>")
            sys.exit(2)
        sys.exit(_smoke_check(args[1]))
    initial = args[0] if args and os.path.isfile(args[0]) else None
    while True:
        app = TachoExplorer(initial_file=initial)
        app.mainloop()
        if not app._restart_requested:
            return
        # Language switch: rebuild the window from scratch (see
        # TachoExplorer._switch_language) and reopen the file that was showing.
        initial = app._restart_file


if __name__ == "__main__":
    main()
