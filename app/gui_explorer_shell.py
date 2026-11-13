"""``TachoExplorer`` — window shell: layout, empty state, recent files, language, drag & drop and shutdown.

Methods moved unchanged out of ``app/gui.py``; ``TachoExplorer`` inherits them
from :class:`ShellMixin`. Names the test-suite replaces on ``app.gui`` are read
through ``_live`` (see ``app.gui_base._LiveGuiNames``).
"""
from app.gui_base import (  # noqa: F401
    ACCENT,
    ActivityTimelineChart,
    DataTable,
    DetailedSpeedChart,
    FONT_BODY,
    FONT_HEADING,
    FONT_PAGE_TITLE,
    FONT_SMALL,
    FONT_SUBTITLE_BOLD,
    LANGUAGES,
    MUTED,
    SASH_START,
    SLATE,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WHITE,
    _,
    _RenderAbandoned,
    _autohide,
    _icon,
    _is_macos,
    _live,
    _log,
    _px,
    _wrap_at_underscores,
    load_trace,
    open_url,
    os,
    save_translate_data,
    saved_recent_files,
    show_help,
    tk,
    tkfont,
    traceback,
    ttk,
    ui_text,
)


class ShellMixin:
    """Window shell: layout, empty state, recent files, language, drag & drop and shutdown."""

    def _enable_dnd(self):
        """Register this window as a drop target for files, if tkdnd loads.

        ``tkinterdnd2`` is optional *and* its ``tkdnd`` extension is a native
        library that can fail to load (unsupported platform, Tcl build, frozen
        bundle without the binaries). Every failure is one debug log line and a
        no-op: the window and every other feature keep working, only drag &
        drop is missing.
        """
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            version = TkinterDnD._require(self)  # loads tkdnd into this interp
            # The window is a tk.Tk, not a tkinter.BaseWidget, so the DnDWrapper
            # mixin methods the package injects there are absent on the root
            # (verified on tkdnd 2.10.3). These are the same two Tcl commands
            # the mixin issues, plus the binding it would create.
            self._drop_command = self.register(self._on_drop)
            self.tk.call("tkdnd::drop_target", "register", self._w, (DND_FILES,))
            # tkdnd substitutes %D in the bind script and quotes the payload as
            # a single word, so the handler always receives one Tcl list string.
            self.tk.call("bind", self._w, "<<Drop>>",
                         f"{self._drop_command} %D")
        except Exception as exc:  # ImportError, RuntimeError, TclError, ...
            _log.debug("drag & drop not available: %s", exc)
            return
        self._dnd_enabled = True
        _log.debug("drag & drop enabled (tkdnd %s)", version)

    def _on_drop(self, data="", *extra):
        """``<<Drop>>`` handler: open the first dropped file, like the picker.

        ``data`` is the whole ``%D`` payload, one Tcl list. A tkdnd build that
        handed the payload over as several Tcl words would land in ``extra``:
        each word is then treated as its own payload, so the drop is not lost
        to an argument-count error out of the Tcl command. (A path that was
        split on its own space cannot be recovered from that — it simply is not
        found, and the status bar says nothing could be opened.)

        Returns the action tkdnd expects. It is always ``copy``: the dropped
        file is only ever read, never moved or deleted, whatever the drag
        source's default action was. Dropping several files opens the first one
        through the same entry point as the dialog, so recent files, the busy
        guard and the error reporting are shared, not reimplemented.
        """
        if self._parsing or self._rendering:
            # Mid-parse, or mid-render: the drop is refused rather than queued,
            # and never opens a second render on top of the one running.
            return "copy"
        paths = []
        for part in (data, *extra):
            paths.extend(_live.dropped_paths(part, split=self.tk.splitlist))
        if not paths:
            self.status.config(text=_("Nothing to open in that drop"))
            return "copy"
        self._open_source = "drop"  # read by the load trace only
        self._start_parse(paths[0])
        if len(paths) > 1:
            # After _start_parse: it writes its own "Parsing ..." status, which
            # a note written first would never be seen under.
            self.status.config(
                text=_("Several files dropped \u2014 opened the first one"))
        return "copy"

    def _install_macos_help_menu(self):
        """macOS: a real menu bar whose Help menu Aqua adopts as its own.

        Only Aqua has a menu bar, and only a menu whose Tk *name* is ``help``
        becomes the native Help menu — Aqua adds its search field to that menu
        and to no other. The Tk widget path is therefore ``<menubar>.help``.

        About is deliberately *not* one of our items: Tk 8.6 already puts
        "About <app>" in the application menu, and its handler is the Tcl
        command ``tk::mac::standardAboutPanel``. Publishing that command with
        :meth:`createcommand` is the documented way to supply the panel's
        content, so the About panel shows our text (name, version, licence,
        credits) instead of Tk's bare one — and shows the same text the Windows
        and Linux dialog does.

        ``tk::mac::ShowHelp`` is what Cmd+? and the "<app> Help" item Tk adds to
        this menu call (``tkMacOSXMenus.c``: ``showHelp:`` evaluates
        ``::tk::mac::ShowHelp`` when that command exists). Without it ``[super
        showHelp:]`` runs, and since the bundle ships no Help Book (no
        ``CFBundleHelpBookFolder``) Aqua answers with "Help isn't available for
        <app>" — the popup the owner saw. Publishing the command routes both the
        shortcut and the item to the app's own Help/About dialog, which is the
        same window the Windows and Linux Help button opens.
        """
        menubar = tk.Menu(self, tearoff=0)
        self.configure(menu=menubar)
        help_menu = tk.Menu(menubar, name="help", tearoff=0)
        for label, url in _live.help_links():
            help_menu.add_command(label=label,
                                  command=lambda target=url: open_url(target))
        menubar.add_cascade(label=_("Help"), menu=help_menu)
        self.createcommand("tk::mac::standardAboutPanel", lambda: show_help(self))
        # Tk 8.6 Aqua runs the Tcl proc `tkAboutDialog` for the application menu's
        # "About" item; `standardAboutPanel` alone is not what it calls.
        self.createcommand("tkAboutDialog", lambda: show_help(self))
        self.createcommand("tk::mac::ShowHelp", lambda: show_help(self))

    def _show_help(self):
        """Open the Help / About dialog (the Windows and Linux entry point)."""
        show_help(self)

    def _build_ui(self):
        # A menu bar exists on macOS only; elsewhere Help is a toolbar button.
        if _is_macos():
            self._install_macos_help_menu()
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill=tk.X)
        # The three toolbar controls lead with an icon from the commissioned
        # set, in front of their label (compound=LEFT). This is the fix for the
        # decorated glyphs that used to sit here: those were characters drawn
        # from a platform font, and a missing fallback left an empty box ahead
        # of the label. A PNG cannot go missing that way.
        self.btn_open = ttk.Button(top, text=_("Open DDD file"),
                                   image=_icon("toolbar-open", 20, top) or "",
                                   compound=tk.LEFT,
                                   command=self._open_file)
        self.btn_open.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_export = ttk.Menubutton(top, text=_("Export"),
                                         image=_icon("toolbar-export", 20, top) or "",
                                         compound=tk.LEFT,
                                         state=tk.DISABLED)
        export_menu = tk.Menu(self.btn_export, tearoff=0,
                              background=WHITE, foreground=TEXT_PRIMARY,
                              activebackground=ACCENT, activeforeground=WHITE,
                              borderwidth=0)
        export_menu.add_command(label=_("PDF (.pdf)"), command=self._export_pdf)
        export_menu.add_command(label=_("Excel (.xlsx)"), command=self._export_excel)
        export_menu.add_command(label=_("CSV (.csv)"), command=self._export_csv)
        export_menu.add_command(label=_("JSON (.json)"), command=self._export_json)
        export_menu.add_separator()
        export_menu.add_command(label=_("GPX (.gpx)"), command=self._export_gpx)
        export_menu.add_command(label=_("KML (.kml)"), command=self._export_kml)
        self.btn_export["menu"] = export_menu
        self.btn_export.pack(side=tk.LEFT, padx=(0, 14))
        # The Help entry point for the platforms without a menu bar. It is the
        # last control of the bar, so it is packed RIGHT *here* — ahead of the
        # language button: pack gives the first RIGHT-packed child the outermost
        # slot, and this one is meant to sit at the very end. On macOS the Help
        # menu is in the menu bar instead, so no button is created there.
        self.btn_help = None
        if not _is_macos():
            # Text only: at the minimum window size the icon's width would cost
            # the verdict label its room (the verdict elides, the bar must not).
            self.btn_help = ttk.Button(top, text=_("Help"), width=0,
                                       command=self._show_help)
            self.btn_help.pack(side=tk.RIGHT, padx=(8, 0))
        # The language menu: two entries only. The 34 languages live in their own
        # submenu (they are a long list and would otherwise bury the preference
        # below them), and the "translate file contents" choice sits under a
        # separator so the two decisions never read as one.
        # The button leads with the globe icon and keeps the language's own name
        # beside it — the name alone is what identifies the language, the icon
        # only tells it apart from the other two controls.
        self.btn_lang = ttk.Menubutton(top, text=LANGUAGES[self._language],
                                       image=_icon("toolbar-language", 20, top) or "",
                                       compound=tk.LEFT)
        lang_menu = tk.Menu(self.btn_lang, tearoff=0,
                            background=WHITE, foreground=TEXT_PRIMARY,
                            activebackground=ACCENT, activeforeground=WHITE,
                            borderwidth=0)
        languages = tk.Menu(lang_menu, tearoff=0,
                            background=WHITE, foreground=TEXT_PRIMARY,
                            activebackground=ACCENT, activeforeground=WHITE,
                            borderwidth=0)
        # Explicit master: a variable created without one binds to whatever
        # Tk root happens to be the default (a stale one in tests), and the
        # menu would then toggle a variable this window cannot read back.
        self._language_var = tk.StringVar(master=self, value=self._language)
        for index, (code, name) in enumerate(LANGUAGES.items()):
            # Names are never translated (each one is already in its own
            # language). 34 entries in a single column would run past the
            # bottom of a small screen, so every dozen starts a new column.
            languages.add_radiobutton(
                label=name, value=code, variable=self._language_var,
                columnbreak=1 if index and index % 12 == 0 else 0,
                command=lambda selected=code: self._switch_language(selected))
        lang_menu.add_cascade(label=_("Language"), menu=languages)
        lang_menu.add_separator()
        # Independent preference: it does not change the UI language — it
        # decides whether the *values decoded from the file* are translated
        # too, or shown exactly as the file names them.
        self._translate_data_var = tk.BooleanVar(master=self, value=self._translate_data)
        lang_menu.add_checkbutton(
            label=_("Translate file contents"), variable=self._translate_data_var,
            command=self._toggle_translate_data)
        self.btn_lang["menu"] = lang_menu
        self.btn_lang.pack(side=tk.RIGHT, padx=(8, 0))
        self.lbl_file = ttk.Label(top, text=_("No file loaded"),
                                  font=FONT_SUBTITLE_BOLD)
        self.lbl_file.pack(side=tk.LEFT)
        # The integrity verdict is as long as its wording, and the bar runs out
        # of room long before the longest translated one does at the 900 px
        # minimum: with a file open the label has ~100-230 px left of the
        # generation badge, where the English "Certificate chain not anchored
        # to a trusted root" needs 317 px and the Greek one 462. Tk clips a
        # label without a mark of its own, so the label keeps the full string,
        # shows an elided one that ends in an ellipsis when it does not fit,
        # and hands the whole verdict to a tooltip. See _fit_status.
        self._status_text = ""
        self._status_icon = None
        self._status_tip = None
        self._status_font = None
        self.lbl_status = ttk.Label(top, text="", font=FONT_BODY)
        self.lbl_status.pack(side=tk.LEFT, padx=(6, 0))
        # Two triggers, because either side can change without the other: a
        # wider window moves the right-hand block (the top level's event), and
        # a new file name moves this label's own left edge (its own event).
        self.bind("<Configure>",
                  lambda event: self._fit_status() if event.widget is self else None)
        self.lbl_status.bind("<Configure>", lambda _e: self._fit_status())
        self.lbl_status.bind("<Enter>", self._show_status_tip)
        self.lbl_status.bind("<Leave>", lambda _e: self._hide_status_tip())
        self.lbl_gen = ttk.Label(top, text="")
        self.lbl_gen.pack(side=tk.RIGHT, padx=8)

        pw = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        # ttk starts a two-pane window with the sash in the middle, which gave the
        # tree (whose widest label is ~175 px) 47 % of the window at the minimum
        # size and left the data table 411 px. Place it once, on first layout;
        # after that the user's drag is never overridden.
        self._sash_bind = pw.bind("<Configure>", lambda e, pw=pw: self._place_sash(pw, e))

        # Left: tree
        left = ttk.Frame(pw)
        pw.add(left, weight=0)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL)
        hscroll = ttk.Scrollbar(left, orient=tk.HORIZONTAL)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.configure(
            yscrollcommand=_autohide(
                scroll,
                lambda: scroll.pack(side=tk.RIGHT, fill=tk.Y, before=self.tree),
                scroll.pack_forget),
            # Shown only for a node whose label is wider than the pane (see
            # _fit_tree_column): a fixed pane width cannot fit every file's
            # node names in every language.
            xscrollcommand=_autohide(
                hscroll,
                lambda: hscroll.pack(side=tk.BOTTOM, fill=tk.X, before=self.tree),
                hscroll.pack_forget))
        scroll.config(command=self.tree.yview)
        hscroll.config(command=self.tree.xview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.column("#0", width=_px(200), minwidth=_px(200))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Return>", self._on_tree_return)
        # Right: table
        right = ttk.Frame(pw)
        pw.add(right, weight=1)
        self.table = DataTable(right)
        self.table.pack(fill=tk.BOTH, expand=True)
        self.speed_chart = DetailedSpeedChart(right)
        self.activity_chart = ActivityTimelineChart(right)
        self.empty_state = self._build_empty_state(right)

        self.bind("<Control-f>", lambda e: self._focus_filter())

        status_bar = ttk.Frame(self, relief=tk.SUNKEN)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = ttk.Label(status_bar, text=_("Ready \u2014 open a .ddd file"),
                                anchor=tk.W, padding=(6, 2))
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # The warning icon is the banner's, and arrives with the warnings
        # (see _check_integrity): a banner with no text shows no icon either.
        # A label that opens a dialog on click is a button, and a button the
        # keyboard cannot reach is one only the mouse can use. It takes focus
        # while it is showing a warning (see _check_integrity: with no text it
        # is not in the tab chain at all), draws the focus with the palette's
        # active-background colour, and opens the same dialog on Return or
        # space as on a click.
        self.integrity_banner = ttk.Label(status_bar, text="", anchor=tk.E,
                                           padding=(6, 2), cursor="hand2",
                                           compound=tk.LEFT, takefocus=False)
        self.integrity_banner.pack(side=tk.RIGHT)
        self.integrity_banner.bind(
            "<Button-1>", lambda _e: self._show_integrity_details())
        self.integrity_banner.bind(
            "<Return>", lambda _e: self._activate_integrity_banner())
        self.integrity_banner.bind(
            "<space>", lambda _e: self._activate_integrity_banner())
        self.integrity_banner.bind("<FocusIn>", self._on_banner_focus_in)
        self.integrity_banner.bind("<FocusOut>", self._on_banner_focus_out)
        self._integrity_warnings = []
        self.progress = ttk.Progressbar(status_bar, mode="indeterminate", length=_px(160))
        # packed only while a parse is running \u2014 see _start_parse/_finish_parse

        # Nothing is loaded yet: the right pane opens on the empty state
        # instead of an empty table.
        if not self.current_data:
            self._show_empty_state()

        if self._initial_file and os.path.isfile(self._initial_file):
            self.after(100, self._open_initial_file)

    def _fit_tree_column(self):
        """Make the tree's column as wide as its widest node, in near-constant cost.

        The pane is a fixed width, and node names are not: a G2.2 card has
        "Driver Card Application Identification V 2" and the Greek catalog
        "Τοποθεσία κάρτας και επαλήθευση για ημερήσια περίοδο εργασίας". A
        column at least as wide as the widest label, collapsed nodes included,
        lets the horizontal scrollbar reach the end of any of them (it only
        appears when one overflows) instead of cutting the name off.

        Cost: the old version measured every node (a Tk round trip for the text, one
        for the image and one ``Font.measure`` each), which dominated the render of a
        G2 download with a node per day. Now each node is read with **one**
        ``tree.item`` call, the width of a label is bounded exactly by
        ``len(text) * w_max`` (``w_max`` = the widest single glyph among the
        characters that actually occur), and candidates are measured widest-bound
        first and pruned as soon as the next bound cannot beat the best exact width.
        The result is the same width to the pixel — the test suite compares it with
        the old algorithm on the mocks, five scripts, a 5000-day tree and the real
        files.
        """
        measures = [0]   # font.measure calls, reported by the load trace
        try:
            style = ttk.Style(self)
            font = tkfont.Font(font=style.lookup("Treeview", "font") or "TkDefaultFont")
            if load_trace.ENABLED:
                real_measure = font.measure

                def _counted(*args, **kwargs):
                    measures[0] += 1
                    return real_measure(*args, **kwargs)
                font.measure = _counted
            indent = int(float(style.lookup("Treeview", "indent") or 20))
            pad = _px(8)
            image_pad = _px(4)

            # ── 1. one Tcl call per node: (text, image) come back together ──
            nodes = []
            visited = 0

            def collect(parent, depth):
                nonlocal visited
                for iid in self.tree.get_children(parent):
                    visited += 1
                    if visited % 256 == 0:
                        # Thousands of day nodes: keep the busy bar turning while
                        # they are collected.
                        self._pump_render()
                    # One round trip: `item` with no option returns every value.
                    # Tk hands it back as a dict on the Tk 8.6/9 builds we ship and
                    # as a positional tuple on older ones — read both shapes.
                    values = self.tree.item(iid)
                    if isinstance(values, dict):
                        text = values.get("text", "")
                        image = values.get("image", "")
                    else:
                        text = values[0] if values else ""
                        image = values[1] if len(values) > 1 else ""
                    if isinstance(image, (tuple, list)):   # Tk hands back a 1-tuple
                        image = image[0] if image else ""
                    nodes.append((depth, text, image))
                    collect(iid, depth + 1)

            collect("", 0)
            if not nodes:
                width = _px(200)
                self.tree.column("#0", width=width, minwidth=width)
                return

            # ── 2. one measure per distinct character ──
            # A label's width is the sum of its characters' widths (this is how Tk
            # measures a string; kerning only ever makes it narrower, so the sum is
            # also a safe upper bound), so glyph widths are measured once and the
            # per-node bound becomes a pure-Python lookup — no Tcl round trip per
            # node, and it is tight enough to prune even equal-length labels.
            glyph_width = {}
            for (_depth, text, _image) in nodes:
                for char in text:
                    if char not in glyph_width:
                        glyph_width[char] = font.measure(char)

            def text_bound(text):
                return sum(glyph_width[char] for char in text)

            # ── 3. bound per node, widest first, measure exactly, prune ──
            image_widths = {}

            def upper_bound(depth, text, image):
                bound = indent * (depth + 1) - 1 + text_bound(text) + pad
                if image:
                    if image not in image_widths:
                        image_widths[image] = int(self.tk.call("image", "width",
                                                               str(image)))
                    bound += image_widths[image] + image_pad
                return bound

            candidates = sorted(
                ((upper_bound(depth, text, image), depth, text, image)
                 for (depth, text, image) in nodes), reverse=True)
            text_widths = {}
            needed = 0
            for index, (bound, depth, text, image) in enumerate(candidates):
                if bound <= needed:
                    break                      # nothing left can be wider
                if index and index % 64 == 0:
                    self._pump_render()
                if text not in text_widths:
                    text_widths[text] = font.measure(text)
                width = indent * (depth + 1) - 1 + text_widths[text] + pad
                if image:
                    width += image_widths[image] + image_pad
                needed = max(needed, width)

            width = max(needed, _px(200))
            self.tree.column("#0", width=width, minwidth=width)
        except Exception:
            # Cosmetic: a tree that could not be measured keeps its column
            # width and must never turn a file that parsed into a render error.
            _log.debug("tree column not fitted: %s", traceback.format_exc())
        load_trace.event("fit_tree_column.measure_calls", measure_calls=measures[0])

    def _place_sash(self, pw, event):
        """Give the tree its natural width once the panes have a real size."""
        if event.width < _px(400):
            return
        pw.unbind("<Configure>", self._sash_bind)
        pw.sashpos(0, _px(SASH_START))

    def _build_empty_state(self, parent):
        """The placeholder the right pane shows while no file is loaded.

        Built once, next to the table and the charts, and packed/unpacked by
        :meth:`_show_empty_state` / :meth:`_hide_empty_state`: opening a file
        must not rebuild it, and a failed first open must bring it back. It
        carries the same open action as the top bar (never a second
        implementation) plus the recently opened files.
        """
        outer = ttk.Frame(parent, padding=(16, 12))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        centre = ttk.Frame(outer)
        centre.grid(row=1, column=0)

        title = ttk.Label(centre, text=_("Open a DDD file"),
                          font=FONT_PAGE_TITLE, anchor=tk.CENTER,
                          justify=tk.CENTER, wraplength=_px(420))
        title.pack(fill=tk.X)
        # The same control as the toolbar's open button, so it leads with the
        # same icon: an iconless twin of a button that has one reads as a
        # different action.
        self.btn_open_empty = ttk.Button(
            centre, text=_("Open DDD file"),
            image=_icon("toolbar-open", 20, centre) or "", compound=tk.LEFT,
            command=self._open_file)
        self.btn_open_empty.pack(pady=(_px(12), _px(20)))

        # Advertised only when the drop target really registered: a hint that
        # nothing can honour is worse than no hint at all.
        if self._dnd_enabled:
            self.drop_hint = ttk.Label(centre, text=_("or drop it here"),
                                       font=FONT_SMALL, foreground=MUTED,
                                       anchor=tk.CENTER, wraplength=_px(420))
            self.drop_hint.pack(fill=tk.X)

        # "Recent files" is filled by _refresh_recent_files(); with no history
        # (or nothing left on disk) the whole section stays hidden.
        self.recent_section = ttk.Frame(centre)
        self.recent_heading = ttk.Label(self.recent_section,
                                        text=_("Recent files"),
                                        font=FONT_HEADING, foreground=TEXT_MUTED,
                                        anchor=tk.W, wraplength=_px(420))
        self.recent_heading.pack(fill=tk.X, pady=(0, _px(4)))
        self.recent_list = ttk.Frame(self.recent_section)
        self.recent_list.pack(fill=tk.X)

        # German/Finnish/Greek titles and long paths are wider than the pane at
        # the minimum window size, so every text block wraps to the space it
        # actually has instead of pushing the sash or being clipped.
        self._wrap_labels = [title]
        if self.drop_hint is not None:
            self._wrap_labels.append(self.drop_hint)
        self._wrap_labels.append(self.recent_heading)
        # What comes after this is rebuilt by _refresh_recent_files().
        self._fixed_wrap_labels = len(self._wrap_labels)
        outer.bind("<Configure>", self._wrap_empty_state)
        return outer

    def _wrap_empty_state(self, event):
        """Re-wrap the empty state's text to the width the pane really has."""
        wrap = max(_px(160), event.width - _px(48))
        for label in self._wrap_labels:
            try:
                if label.winfo_exists():
                    label.configure(wraplength=wrap)
                    full = getattr(label, "_full_name", None)
                    if full:
                        label.configure(text=_wrap_at_underscores(
                            full, FONT_SUBTITLE_BOLD, wrap))
            except tk.TclError:
                continue  # a row destroyed by _refresh_recent_files

    def _show_empty_state(self):
        """Show the no-file placeholder instead of the table/charts."""
        for widget in (self.table, self.speed_chart, self.activity_chart):
            widget.pack_forget()
        self._refresh_recent_files()
        if not self.empty_state.winfo_manager():
            self.empty_state.pack(fill=tk.BOTH, expand=True)

    def _hide_empty_state(self):
        """Give the right pane back to the table/charts."""
        if self.empty_state.winfo_manager():
            self.empty_state.pack_forget()

    def _refresh_recent_files(self):
        """Rebuild the recent-files list from the settings file.

        Entries are read as stored (the settings helper never looks at the
        disk) and only the ones that still exist are shown: a file on an
        unplugged drive disappears from the list without being forgotten, so it
        is back the next time the drive is mounted.
        """
        for child in self.recent_list.winfo_children():
            child.destroy()
        del self._wrap_labels[self._fixed_wrap_labels:]  # the rows being rebuilt
        paths = [path for path in saved_recent_files() if os.path.isfile(path)]
        if not paths:
            self.recent_section.pack_forget()
            return
        if not self.recent_section.winfo_manager():
            self.recent_section.pack(fill=tk.X)
        for path in paths:
            self._add_recent_row(path)

    def _add_recent_row(self, path):
        """One recent file: bold file name, muted directory, click to open."""
        row = ttk.Frame(self.recent_list, cursor="hand2")
        row.pack(fill=tk.X, pady=_px(2))
        wrap = self._wrap_labels[0].cget("wraplength")
        base = os.path.basename(path)
        name = ttk.Label(row, text=_wrap_at_underscores(base, FONT_SUBTITLE_BOLD, wrap),
                         font=FONT_SUBTITLE_BOLD, anchor=tk.W, wraplength=wrap)
        name._full_name = base  # re-broken when the pane is resized
        name.pack(fill=tk.X)
        directory = ttk.Label(row, text=os.path.dirname(path), font=FONT_SMALL,
                              foreground=SLATE, anchor=tk.W, wraplength=wrap)
        directory.pack(fill=tk.X)
        self._wrap_labels.extend((name, directory))
        for widget in (row, name, directory):
            widget.bind("<Button-1>",
                        lambda _event, target=path: self._open_recent(target))

    def _open_recent(self, path):
        """Open a recent file through the very same route as the file picker.

        ``_open_file`` is the only other caller of :meth:`_start_parse`, and it
        refuses to start while a parse — or the render of its result — runs; the
        same guard applies here.
        """
        load_trace.event("recent.click", refused="yes" if self._parsing or self._rendering else "no")
        if self._parsing or self._rendering:
            return
        self._open_source = "recent"
        self._start_parse(path)

    def _toggle_translate_data(self):
        """Apply the "translate file contents" preference without a restart.

        Unlike the language itself, this preference changes only the text that
        was decoded from the file (activity names, nations, record labels), so
        the window does not have to be rebuilt. The rows of every section were
        formatted when the tree was populated, though, so re-selecting the node
        is not enough: the tree is repopulated from the already-parsed data and
        the same node is selected again. A settings write that fails leaves the
        previous choice in place, tells the user, and puts the menu tick back
        where it was — the same contract as a failed language switch.

        Refused while a render owns the tree, and *before* anything is written:
        the preference is process-global, and the rebuild that applies it is
        refused in that state, so a toggle delivered by the render's own pump
        would leave the setting and the menu tick on the new value with every
        row still formatted the old way. Refusing the toggle keeps the two in
        step.

        ``_parsing`` alone is not enough to refuse it: while the worker runs
        there is no render yet, ``_refresh_data_text`` deliberately does nothing
        (the render that ends the parse formats every row with the live flag),
        so the toggle is honoured there and applied by the coming render. Only
        if that parse then *fails* does the retained tree keep the previous
        formatting under the new tick — a pre-existing edge this guard does not
        make worse, and not worth refusing a click the successful case applies.
        """
        if self._rendering:
            self._translate_data_var.set(self._translate_data)
            return
        flag = bool(self._translate_data_var.get())
        if flag == self._translate_data:
            return
        if not save_translate_data(flag):
            self._translate_data_var.set(self._translate_data)
            _live.messagebox.showwarning(_("Language"),
                                   _("Could not save the language setting."))
            return
        self._translate_data = flag
        ui_text.configure_translate_data(flag)
        self._refresh_data_text()

    def _refresh_data_text(self):
        """Re-populate the tree so cached rows follow the new data preference.

        ``_populate_tree`` formats every cell once, at parse time, so the only
        way to re-render them is to build the tree again from ``current_data``.
        The selected node is remembered by its path of labels and selected
        again, so the visible section does not jump to the top.
        """
        if not self.current_data or self._parsing or self._rendering:
            # A running parse repopulates with the new flag when it ends, and a
            # running render owns the tree: a second toggle arriving through the
            # render's own event-loop pump would nest one rebuild in another.
            return
        path = self._selected_path()
        # Same deal as a parse render: the tree is rebuilt from scratch, so the
        # selection is this method's to set at the end and a <<TreeviewSelect>>
        # delivered by the pump below must not render a half-built tree.
        self._rendering = True
        try:
            self._populate_tree(self.current_data)
            self._fit_tree_column()
        except _RenderAbandoned:
            return  # the window was closed while the tree was being rebuilt
        finally:
            self._rendering = False
        self._update_top_bar(self.current_data)
        target = self._node_by_path(path) or getattr(self, "_auto_select_iid", None)
        if not (target and self.tree.exists(target)):
            children = self.tree.get_children("")
            target = children[0] if children else None
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)

    def _selected_path(self):
        """Labels from the root to the selected node (empty when nothing is selected)."""
        selection = self.tree.selection()
        if not selection:
            return ()
        labels, iid = [], selection[0]
        while iid:
            labels.append(self.tree.item(iid, "text"))
            iid = self.tree.parent(iid)
        return tuple(reversed(labels))

    def _node_by_path(self, path):
        """The node at ``path``, opening its ancestors; ``None`` when it is gone."""
        parent = ""
        for depth, label in enumerate(path):
            for child in self.tree.get_children(parent):
                if self.tree.item(child, "text") == label:
                    if depth < len(path) - 1:
                        self.tree.item(child, open=True)
                    parent = child
                    break
            else:
                return None
        return parent or None

    def _switch_language(self, code):
        """Persist ``code`` and rebuild the window in the new language.

        A live window cannot change language in place: every widget string is
        created once, and some are embedded in stored tree payloads. So the
        window is destroyed and rebuilt by the main loop (:func:`main`), which
        makes this an in-process restart: no ``execv``, therefore identical
        behaviour for ``python app/gui.py``, ``python -m app.gui`` and the
        frozen bundle, and no terminal is dropped on the floor. The file that is
        open right now is reopened; the original command line is not replayed
        (the file it named may have been closed or replaced long ago).

        A restart while a parse or an export is running would abort the worker
        and lose its result, so the current language is kept and the menu radio
        silently returns to it. A settings write that fails does the same, after
        telling the user.

        A render is busy time too, and it is not always a parse: the
        translate-data rebuild (:meth:`_refresh_data_text`) raises
        ``_rendering`` without ever setting ``_parsing``, and it pumps the event
        loop while it rebuilds the tree. The pump delivers this menu command
        exactly like any other, so the guard has to name ``_rendering`` as well
        — otherwise the scheduled restart would run ``_shutdown`` and
        ``destroy`` on top of a rebuild that is still walking the widgets.
        """
        if code == self._language:
            return
        if self._parsing or self._exporting or self._rendering:
            self._restore_language_choice()
            return
        if not _live.save_language(code):
            self._restore_language_choice()
            _live.messagebox.showwarning(_("Language"),
                                   _("Could not save the language setting."))
            return
        self._restart_file = self.current_file
        self._restart_requested = True
        # Tear the window down from the idle loop, not from inside the menu
        # command: destroying a menu's owner while the menu is still posting
        # makes Tcl complain about an invalid command name.
        self.after_idle(self._finish_restart)

    def _finish_restart(self):
        """Stop this window so ``main()`` can rebuild it in the new language."""
        self._shutdown()
        self.destroy()

    def _shutdown(self):
        """Release the state this window owns and end its main loop.

        A bare ``destroy()`` releases only some of it:

        * the day-detail reuse registry is a class attribute, so it survives the
          window and would hand the *next* window Tcl objects from a dead
          interpreter;
        * ``after`` callbacks already queued in this interpreter keep firing at
          widgets that no longer exist, which Tk reports on stderr as
          "invalid command name ...". They are cancelled here;
        * ``mainloop()`` waits for *every* Tk main window in the thread, not
          only this one (e.g. a stray root another component made), so the loop
          must be told to ``quit()`` or an in-process restart would never
          return.

        Only this app's own Tcl interpreter is touched: each ``tk.Tk`` root has
        its own, so other windows' timers are unaffected.
        """
        self._destroyed = True
        self._resume_gc()       # the poll stops on _destroyed, so no _finish_parse may come
        _live.DayDetailWindow.forget_all()
        try:
            # Cancel at Tcl level: `Misc.after_cancel` also deletes the callback's
            # Tcl command from *this* widget's registry, but a child widget (e.g.
            # the table's own fit timer) registered it, and its later destroy()
            # would then raise "can't delete Tcl command".
            for after_id in self.tk.call("after", "info"):
                self.tk.call("after", "cancel", after_id)
        except tk.TclError:
            pass
        try:
            self.quit()
        except tk.TclError:
            pass

    def _restore_language_choice(self):
        """Put the menu radio back on the language that is actually active."""
        try:
            self._language_var.set(self._language)
        except tk.TclError:
            pass

    def _focus_filter(self):
        """Focus the table filter box only when it is actually visible
        (summary and dashboard views hide the filter bar)."""
        if self.table.winfo_manager() and self.table.filt_bar.winfo_manager():
            self.table.filter_entry.focus_set()

    def _on_close(self):
        self._shutdown()
        self.destroy()
