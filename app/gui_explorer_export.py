"""``TachoExplorer`` — the Export menu: PDF, Excel, CSV, JSON, GPX and KML.

Methods moved unchanged out of ``app/gui.py``; ``TachoExplorer`` inherits them
from :class:`ExportMixin`. Names the test-suite replaces on ``app.gui`` are read
through ``_live`` (see ``app.gui_base._LiveGuiNames``).
"""
from app.gui_base import (  # noqa: F401
    BytesEncoder,
    ExportManager,
    _,
    _live,
    json,
    os,
    queue,
    threading,
    tk,
)


class ExportMixin:
    """The Export menu: PDF, Excel, CSV, JSON, GPX and KML."""

    def _run_export(self, kind, extension, filetypes, export_fn, requirement=""):
        """Shared export flow: pick the destination, run, report the outcome.

        Refused while a render runs: the destination picker opens a modal dialog,
        which would hold the render (and the busy bar) for as long as the user
        leaves it open — the very freeze the render pump exists to remove. The
        toolbar disables Export for a parse, but the translate-data rebuild
        (:meth:`_refresh_data_text`) leaves it enabled, so the guard is here.
        Like every other busy refusal (Open, drop, the language menu) it is
        silent: the window is busy for a fraction of a second, and the click can
        simply be repeated.
        """
        if self._rendering:
            return
        if not self.current_data:
            return
        if ExportManager is None:
            _live.messagebox.showwarning(_("Export Unavailable"),
                                   _("{kind} export is unavailable. {requirement}").format(
                                       kind=kind, requirement=requirement).strip())
            return
        path = _live.filedialog.asksaveasfilename(
            defaultextension=extension,
            filetypes=filetypes + [(_("All Files"), "*.*")],
            initialfile=os.path.splitext(os.path.basename(self.current_file))[0]
            + "_export" + extension)
        if not path:
            return
        self.status.config(text=_("Exporting to {kind}\u2026").format(kind=kind))
        self.progress.pack(side=tk.RIGHT)
        self.progress.start(12)
        self.update_idletasks()
        self._exporting = True

        # Capture on the main thread: the worker must serialize the data this
        # export was started with, not whatever _parse_done assigns to
        # self.current_data while the worker is running.
        data = self.current_data

        def _worker():
            try:
                export_fn(data, path)
                self._export_queue.put((kind, requirement, None, path))
            except Exception as exc:
                self._export_queue.put((kind, requirement, exc, path))

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        def _poll():
            if self._destroyed:
                return
            try:
                kind_err, req, exc, export_path = self._export_queue.get_nowait()
            except queue.Empty:
                self.after(50, _poll)
                return
            self.progress.stop()
            self.progress.pack_forget()
            self._exporting = False
            if exc is not None:
                if isinstance(exc, ImportError):
                    self.status.config(text=_("Export failed"))
                    _live.messagebox.showwarning(_("Export Unavailable"),
                                           _("{kind} export requires an extra package:\n"
                                             "{error}\n{requirement}").format(
                                               kind=kind_err, error=exc, requirement=req))
                else:
                    self.status.config(text=_("Export failed"))
                    _live.messagebox.showerror(_("Export Error"), str(exc))
            else:
                self.status.config(text=_("Exported: {filename}").format(
                    filename=os.path.basename(export_path)))
                _live.messagebox.showinfo(_("Export Complete"),
                                    _("{kind} saved to:\n{path}").format(
                                        kind=kind_err, path=export_path))

        self.after(50, _poll)

    def _export_pdf(self):
        self._run_export("PDF", ".pdf", [(_("PDF Document"), "*.pdf")],
                         lambda d, p: ExportManager.export_to_pdf(d, p),
                         requirement="pip install reportlab")

    def _export_excel(self):
        self._run_export("Excel", ".xlsx", [(_("Excel Workbook"), "*.xlsx")],
                         lambda d, p: ExportManager.export_to_excel(d, p),
                         requirement="pip install openpyxl")

    def _export_csv(self):
        self._run_export("CSV", ".csv", [(_("CSV Files"), "*.csv")],
                         lambda d, p: ExportManager.export_to_csv(d, p))

    def _export_gpx(self):
        """GNSS positions (route + places + border crossings) as GPX."""
        from app.geo_export import export_positions
        self._run_export("GPX", ".gpx", [(_("GPX (.gpx)"), "*.gpx")],
                         lambda d, p: export_positions(d, p, "gpx"))

    def _export_kml(self):
        """GNSS positions as KML (Google Earth and most map tools)."""
        from app.geo_export import export_positions
        self._run_export("KML", ".kml", [(_("KML (.kml)"), "*.kml")],
                         lambda d, p: export_positions(d, p, "kml"))

    def _export_json(self):
        if self._rendering:
            # Same reason as _run_export: no modal picker on top of a render.
            return
        if not self.current_data:
            return
        path = _live.filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[(_("JSON Files"), "*.json"), (_("All Files"), "*.*")],
            initialfile=os.path.splitext(os.path.basename(self.current_file))[0] + "_export.json")
        if not path:
            return
        self.status.config(text=_("Exporting to JSON\u2026"))
        self.progress.pack(side=tk.RIGHT)
        self.progress.start(12)
        self.update_idletasks()
        self._exporting = True

        # Capture on the main thread (see _run_export): the worker must not
        # read self.current_data, which _parse_done may reassign concurrently.
        data = self.current_data

        def _worker():
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False,
                              cls=BytesEncoder)
                self._export_queue.put(("JSON", "", None, path))
            except Exception as exc:
                self._export_queue.put(("JSON", "", exc, path))

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

        def _poll():
            if self._destroyed:
                return
            try:
                kind_err, _req, exc, export_path = self._export_queue.get_nowait()
            except queue.Empty:
                self.after(50, _poll)
                return
            self.progress.stop()
            self.progress.pack_forget()
            self._exporting = False
            if exc is not None:
                self.status.config(text=_("Export failed"))
                _live.messagebox.showerror(_("Export Error"), str(exc))
            else:
                self.status.config(text=_("Exported: {filename}").format(
                    filename=os.path.basename(export_path)))
                _live.messagebox.showinfo(_("Export Complete"),
                                    _("{kind} saved to:\n{path}").format(
                                        kind=kind_err, path=export_path))

        self.after(50, _poll)
