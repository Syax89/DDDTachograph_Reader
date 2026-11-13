"""``TachoExplorer`` — opening a file: the parse worker, its queue, the render pump and the post-parse rebuild.

Methods moved unchanged out of ``app/gui.py``; ``TachoExplorer`` inherits them
from :class:`LoadMixin`. Names the test-suite replaces on ``app.gui`` are read
through ``_live`` (see ``app.gui_base._LiveGuiNames``).
"""
from app.gui_base import (  # noqa: F401
    SURFACE,
    _,
    _BAR_MAX_TICKS,
    _BAR_TICK,
    _RENDER_PUMP_INTERVAL,
    _RENDER_PUMP_MAX_GAP,
    _RenderAbandoned,
    __version__,
    _gc_pause,
    _gc_resume,
    _live,
    _log,
    load_trace,
    os,
    queue,
    threading,
    time,
    tk,
    traceback,
)


class LoadMixin:
    """Opening a file: the parse worker, its queue, the render pump and the post-parse rebuild."""

    def _open_file(self):
        """File-picker entry point; ignored while a parse (or its render) runs."""
        if self._parsing or self._rendering or self._open_pending:
            return
        self._open_pending = True
        try:
            path = load_trace.picker(lambda: _live.filedialog.askopenfilename(
                filetypes=[(_("DDD Files"), "*.ddd *.DDD"), (_("All Files"), "*.*")]))
        except BaseException:
            self._open_pending = False
            raise
        if not path:
            self._open_pending = False
            return
        self._open_source = "picker"

        def start():
            self._open_pending = False
            self._start_parse(path)
        # Not inside the picker's call stack: let the real mainloop handle the panel's
        # teardown events first (macOS update() stall after the native panel closed).
        self.after(150, start)

    def _open_initial_file(self):
        self._open_source = "cli"
        self._start_parse(self._initial_file)

    def _start_parse(self, path):
        """Run the parse on a worker thread so the UI stays responsive;
        results are marshalled back via a queue polled on the main loop."""
        if self._parsing or self._rendering:
            # A parse is already running, or the previous result is still being
            # rendered onto the tree. Every entry point checks this before it
            # gets here (_open_file, _open_recent, the drop handler); it is
            # enforced here too because the render pumps the event loop, so a
            # second open can now arrive *while* the tree is being rebuilt.
            return
        self._parsing = True
        load_trace.opened(path, getattr(self, "_open_source", "?"))
        self.btn_open.config(state=tk.DISABLED)
        self.btn_export.config(state=tk.DISABLED)
        self.status.config(text=_("Parsing {filename}\u2026").format(
            filename=os.path.basename(path)))
        self.progress.pack(side=tk.RIGHT, padx=6, pady=1)
        self.progress.start(12)
        self._bar_at = 0.0          # idle pump: step the bar from the render's first pump

        worker = threading.Thread(target=self._parse_worker, args=(path,), daemon=True)
        self._gc_was_enabled = _gc_pause()
        try:
            worker.start()
        except BaseException:
            self._resume_gc()
            raise
        self.after(50, self._poll_parse_queue)

    def _parse_worker(self, path):
        """Worker-thread body: parse and post (path, results, error) to the queue."""
        try:
            with load_trace.span("worker_parse"):
                data = _live.TachoParser(path).parse()
            self._parse_queue.put((path, data, None))
        except Exception as e:
            _log.error("Parse failed: %s\n%s", e, traceback.format_exc())
            self._parse_queue.put((path, None, str(e)))

    def _poll_parse_queue(self):
        """Main-loop poll (50 ms) for the worker result; dispatches to
        _parse_done or _parse_error when it arrives."""
        if self._destroyed:
            return
        try:
            path, data, error = self._parse_queue.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_parse_queue)
            return
        if error is not None:
            self._parse_error(error)
        else:
            load_trace.event("parse_result_delivered")
            self._parse_done(data, path)

    def _resume_gc(self):
        """Undo ``_gc_pause`` once (idempotent)."""
        was_enabled, self._gc_was_enabled = self._gc_was_enabled, None
        if was_enabled is not None:
            _gc_resume(was_enabled)

    def _finish_parse(self):
        """Restore the idle UI state (progress bar, buttons) after a parse."""
        self._parsing = False
        self._resume_gc()
        try:
            self.progress.stop()
            self.progress.pack_forget()
        except Exception:
            pass
        try:
            self.btn_open.config(state=tk.NORMAL)
            if self.current_data:
                # A failed re-open keeps the previously loaded file exportable.
                self.btn_export.config(state=tk.NORMAL)
        except tk.TclError:
            # The render pumps the event loop, so the window can be closed
            # while it runs: there is no button left to re-enable.
            pass

    def _pump_render(self, force=False):
        """Let the event loop turn while a render holds the main thread.

        The render of a parsed file is one synchronous call: ``_parsing`` has to
        stay True until it ends (Open, drop-to-open and the language restart are
        all refused on it) and ``_finish_parse`` has to run in ``_parse_done``'s
        ``finally``, so the work cannot be split into ``after`` slices — the
        loop is pumped from *inside* the render instead. The gap after a pump is
        ``max(_RENDER_PUMP_INTERVAL, 4 * its own duration)`` measured from its
        end and capped at :data:`_RENDER_PUMP_MAX_GAP`, so pumps cost at most
        ~20% of the render even where one ``update()`` is slow (macOS redraws
        the whole tree) instead of turning it pump-bound. That is what keeps the indeterminate
        progress bar animating (it is driven by a Tk timer) instead of freezing
        for the whole render and reading as a hang.

        Pumping processes whatever is pending, so the guards are what make it
        safe: ``_rendering`` is True for the whole rebuild, and the open/drop
        paths plus <<TreeviewSelect>> refuse while it is set. The render itself
        stays on the main thread — nothing here touches Tk from a worker.

        A pump must never break the render it interrupts: a widget-less test
        double (``object.__new__(TachoExplorer)``) has nothing to pump, so that
        failure is swallowed. A window that was *closed* mid-render is a
        different case — there is nothing left to draw and no widget left to
        restore — and is signalled with :class:`_RenderAbandoned` so the render
        stops instead of walking a destroyed widget tree.
        """
        load_trace.pump_call()
        now = time.monotonic()
        if not force and now < self._pump_due:
            return
        self._pump_due = now + _RENDER_PUMP_INTERVAL
        if self._destroyed:
            raise _RenderAbandoned
        gone = False
        try:
            if _live._PUMP_USES_EVENTS:
                self.update()
            else:
                # No timers fire without events: advance the busy bar by the ticks it missed.
                ticks = min(_BAR_MAX_TICKS, int((now - (self._bar_at or now)) / _BAR_TICK))
                self._bar_at = now
                if ticks:
                    self.progress.step(ticks)
                self.update_idletasks()
            gone = self._destroyed or not self.winfo_exists()
        except Exception:  # noqa: BLE001 - a failed pump must not fail a render
            # Two very different cases land here. A widget-less test double has
            # no Tk interpreter at all (AttributeError) and must simply skip the
            # pump; a window closed *inside* ``update()`` raises TclError, and
            # ``_destroyed`` is what tells that apart — the render has to stop.
            gone = self._destroyed
            _log.debug("render pump skipped: %s", traceback.format_exc())
        end = time.monotonic()
        load_trace.pump_update(end - now)
        self._pump_due = end + min(
            _RENDER_PUMP_MAX_GAP, max(_RENDER_PUMP_INTERVAL, 4 * (end - now))
        )
        if gone:
            raise _RenderAbandoned

    def _reset_file_display(self):
        """Clear every per-file display field a successful load sets.

        A fatal parse must not leave the previous file's identity (filename,
        generation badge, integrity banner and collected warnings) on screen,
        or the user attributes them to the file that just failed to open
        (H-F5). The previous downloads' *data* is deliberately retained so it
        stays exportable; only the on-screen identity is reset.
        """
        self.lbl_file.config(text=_("No file loaded"))
        self.lbl_gen.config(text="")
        self._set_status_text("", None)
        self._release_banner_focus()
        self.integrity_banner.config(text="", image="", takefocus=False,
                                     background=SURFACE)
        self._integrity_warnings = []
        self._integrity_file = ""
        self.title(f"Tacho Explorer v{__version__}")

    def _parse_error(self, msg):
        self._finish_parse()
        self._reset_file_display()
        try:
            _live.messagebox.showerror(_("Parsing Error"), str(msg))
        except Exception:
            pass
        if self.current_data:
            # A failed re-open keeps the previously loaded file exportable, but
            # the status must make clear that what is shown is NOT the new file.
            self.status.config(
                text=_("Parsing error \u2014 showing previous file: {filename}").format(
                    filename=os.path.basename(self.current_file or "")))
        else:
            self.status.config(text=_("Ready \u2014 open a .ddd file"))
            # Nothing was loaded before and nothing is loaded now: the pane
            # goes back to the empty state rather than to a blank table.
            self._show_empty_state()

    def _parse_done(self, data, path):
        """Render a parse result. Keeps partial data visible: a fatal error
        (no structural data recovered) shows an error and stops; otherwise the
        tree is rendered even when late phases failed or signatures are bad."""
        if self._rendering:
            # Never rebuild the tree a still-running render is walking. The
            # render pumps the event loop, so a result queued behind it can
            # arrive in the middle of it; the running render restores the UI
            # state in its own finally, and this superseded result is dropped.
            _log.warning("Dropping a parse result: another render is running")
            return
        parse_error = (data.get("metadata") or {}).get("parse_error")
        has_data = bool(data.get("raw_tags") or data.get("generations")
                        or data.get("activities"))
        if parse_error and not has_data:
            message = parse_error.get("message", _("Unknown parsing error")) \
                if isinstance(parse_error, dict) else str(parse_error)
            self._parse_error(message)
            return
        # Rendering's table sizing update() pumps the loop: stay busy until done.
        self._parsing = True
        self._rendering = True
        load_trace.event("parse_done.start", generation=(data.get("metadata") or {}).get("generation"))
        try:
            self.current_data = data
            self.current_file = path
            # Only a *successful* parse reaches this line (a fatal parse error
            # returned above): a mistyped or truncated file must never appear
            # under "Recent files". The path here is the one actually parsed,
            # so a file given on the command line is recorded too.
            _live.add_recent_file(path)
            # One pump before the heavy part: the status line and the busy bar
            # reach the screen before the tree rebuild starts, not after it.
            with load_trace.span("parse_done.first_pump"):
                self._pump_render(force=True)
            with load_trace.span("populate_tree"):
                self._populate_tree(data)
            load_trace.event("populate_tree.nodes", nodes=self._trace_node_count())
            with load_trace.span("fit_tree_column"):
                self._fit_tree_column()
            with load_trace.span("update_top_bar"):
                self._update_top_bar(data)
            self.btn_export.config(state=tk.NORMAL)
            target = getattr(self, "_auto_select_iid", None)
            if target and not self.tree.exists(target):
                target = None  # stale iid from a previous file's tree
            if not target:
                children = self.tree.get_children("")
                target = children[0] if children else None
            # GUI-STALE-TABLE (XG-F4): the node's table is rendered by the
            # deferred <<TreeviewSelect>> event, so between the filename update
            # above and that event the pane still showed the PREVIOUS file's
            # rows under the NEW filename. Replace the pane synchronously with
            # an explicit placeholder (never the old file's data) and keep the
            # single deferred render of the chosen node.
            if target:
                self._show_empty(os.path.basename(path), _("Loading\u2026"))
                # Nothing pumps the loop between here and the end of this
                # method: a pump would deliver this callback while _rendering is
                # still set, and _on_tree_select would refuse it, leaving the
                # pane on the placeholder.
                self.after_idle(
                    lambda tid=target: self.tree.selection_set(tid)
                    if self.tree.exists(tid) else None)
            else:
                # No selectable node: the placeholder stays (no render follows).
                self._show_empty(os.path.basename(path),
                                 _("No sections to display."))
            meta = data.get("metadata", {})
            self.status.config(
                text=_("Loaded: {filename}  |  {generation}").format(
                    filename=os.path.basename(path),
                    generation=meta.get("generation", "?")))
            with load_trace.span("check_integrity"):
                self._check_integrity(data, path)
        except _RenderAbandoned:
            _log.debug("window closed during the render: nothing left to draw")
        except Exception:
            _log.error("GUI render failed: %s", traceback.format_exc())
            self._warn_when_idle(_("Rendering Error"),
                                 _("Failed to display file:\n{detail}").format(
                                     detail=traceback.format_exc()), kind="showerror")
            self.status.config(text=_("Ready \u2014 open a .ddd file"))
        finally:
            self._rendering = False
            self._finish_parse()
            load_trace.event("parse_done.end")
            if load_trace.ENABLED:
                self.after_idle(lambda: self.after_idle(self._trace_idle))

    def _trace_node_count(self):
        """Number of tree nodes (0 unless the load trace is on: it walks the tree)."""
        if not load_trace.ENABLED:
            return 0
        pending, count = list(self.tree.get_children("")), 0
        while pending:
            count += 1
            pending.extend(self.tree.get_children(pending.pop()))
        return count

    def _trace_idle(self):
        """Final trace line once nothing parses or renders and the deferred callbacks ran."""
        if self._destroyed:
            return
        if self._parsing or self._rendering:
            self.after_idle(lambda: self.after_idle(self._trace_idle))
            return
        load_trace.pump_report()
        load_trace.event("idle")
        load_trace.idle_report()
