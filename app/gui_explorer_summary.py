"""``TachoExplorer`` — the one-page summary panels (overview, vehicle, driver, TREP, sensor) and their tooltips.

Methods moved unchanged out of ``app/gui.py``; ``TachoExplorer`` inherits them
from :class:`SummaryMixin`. Names the test-suite replaces on ``app.gui`` are read
through ``_live`` (see ``app.gui_base._LiveGuiNames``).
"""
from app.gui_base import (  # noqa: F401
    DASHBOARD_TOOLTIP_BG,
    FONT_HEADING,
    FONT_SMALL,
    TEXT_SECONDARY,
    _,
    _SummaryHeader,
    _activity_days,
    _calibration_days_left,
    _compute_activity_totals,
    _drop_empty_values,
    _fmt_duration_minutes,
    _px,
    _summary_block,
    _summary_icon_gutter,
    fmt_val,
    nation_full_name,
    recorded_until_seconds,
    tk,
    tkfont,
    ui_text,
)


class SummaryMixin:
    """The one-page summary panels (overview, vehicle, driver, TREP, sensor) and their tooltips."""

    def _show_summary(self, title, cols, rows, meta):
        """Render a rich info panel with section headers instead of a data table."""
        self._cleanup_dashboard()
        self._hide_empty_state()
        self.speed_chart.pack_forget()
        self.activity_chart.pack_forget()
        if not self.table.winfo_manager():

            self.table.pack(fill=tk.BOTH, expand=True)
        if self.table._fit_after_id is not None:
            self.table.tv.after_cancel(self.table._fit_after_id)
            self.table._fit_after_id = None
        if self.table._filter_after_id is not None:
            self.table.tv.after_cancel(self.table._filter_after_id)
            self.table._filter_after_id = None
        self.table.title_lbl.config(text=title)
        self.table.count_lbl.config(
            text=meta if meta else "")
        self.table.filter_var.set("")
        self.table._cols = ["Field", "Value"]
        self.table._all_rows = rows
        self.table._sort_state = {}
        self.table.tv["columns"] = ["Field", "Value"]
        # No heading bar at all: the panel is labelled rows, not a two-column
        # table, and an empty grey strip above it reads as a loading glitch.
        #
        # "tree" (not "") because the tree column is the only place a Treeview
        # can draw an image, and the section headers carry one: a narrow gutter
        # holds each block's icon. The gutter is taken out of the Field column's
        # width, so the Value column keeps exactly the width it had.
        self.table.tv["show"] = "tree"
        # The gutter is the *image's* width plus its margin at this display's
        # scale (22 px at 100 %, where the icon is 16 px), and the Field column
        # gives up exactly that much, so the value column keeps its width.
        gutter = _summary_icon_gutter(self)
        self.table.tv.column("#0", width=gutter, minwidth=gutter,
                             stretch=False)
        self.table.tv.heading("Field", text="")
        self.table.tv.heading("Value", text="")
        self.table.tv.column("Field", width=_px(220) - gutter,
                             minwidth=_px(140), anchor=tk.W, stretch=False)
        # A stretch column only grows on a *resize*. The table comes back from a
        # chart at the width it left with, so no resize fires and the Value
        # column stayed at the 100 px placeholder until the node was clicked a
        # second time. Settle the layout and give it its width now.
        self.table.tv.update_idletasks()
        value_w = _px(100)
        available = self.table.tv.winfo_width()
        if available > _px(220) + _px(100):
            value_w = available - _px(220) - 4
        self.table.tv.column("Value", width=value_w, minwidth=_px(60), anchor=tk.W, stretch=True)
        self.table._fitted = True
        self.table._summary_mode = True
        self.table._render(self.table._all_rows, summary=True)
        self.table._sync_xscroll()
        self.table.filt_bar.pack_forget()
        self._bind_summary_reveal()

    def _bind_summary_reveal(self):
        """Let a summary cell that does not fit its column be read in full.

        The panel's two columns are deliberately fixed and never auto-fit (see
        :meth:`_show_summary`), and Tk *clips* an overlong cell instead of
        wrapping it — so a value longer than the column was cut off with no way
        to read the rest. That is not a wording problem to shorten away: the
        values belong to the code that owns them, and they are long in ways the
        panel cannot bound. The translated integrity verdicts are the worst case
        — 11 of the 15 ``_integrity_label`` verdicts exceed the 187 px value
        column in at least one of the 34 catalogs at the minimum window, and 5
        of them in all 34 — and a period with no activity days, the VU origin
        and the translated block headers can be just as wide.

        So the value keeps its wording and the panel gains a reveal: hovering a
        cell whose text does not fit shows the whole of it. This is the pattern
        the activity dashboard already uses for its row tooltips — a ``Label``
        placed over the treeview and driven by ``<Motion>`` (see
        :meth:`_on_dashboard_motion`) — applied to the one panel that clips.
        """
        self._cleanup_summary_tooltip()
        self._summary_tip_lbl = tk.Label(
            self.table.tv, text="", bg=DASHBOARD_TOOLTIP_BG, relief=tk.SOLID,
            borderwidth=1, font=FONT_SMALL, fg=TEXT_SECONDARY, padx=6, pady=2,
            justify=tk.LEFT)
        self._summary_motion_bind = self.table.tv.bind(
            "<Motion>", self._on_summary_motion, add="+")
        self._summary_leave_bind = self.table.tv.bind(
            "<Leave>", self._on_summary_leave, add="+")

    def _on_summary_motion(self, event):
        """Reveal the full text of the summary cell under the pointer."""
        text = self._clipped_summary_cell(event.x, event.y)
        if text is None:
            self._hide_summary_tooltip()
            return
        tip = self._summary_tip_lbl
        tip.config(text=text, wraplength=_px(420))
        # Keep the reveal inside the panel (the Value column, the one that
        # clips, is the right-hand one): a label placed past the edge would be
        # clipped by the treeview — the very problem it exists to solve.
        tip.update_idletasks()
        tip.place(x=min(event.x + 16,
                        max(0, self.table.tv.winfo_width() - tip.winfo_reqwidth() - _px(4))),
                  y=min(event.y + 16,
                        max(0, self.table.tv.winfo_height() - tip.winfo_reqheight() - _px(4))))

    def _on_summary_leave(self, _event):
        """Hide the reveal when the pointer leaves the panel.

        Tk raises ``<Leave>`` for the treeview both when the pointer leaves it
        and when it moves onto the reveal label (a child of the treeview), and
        tkinter does not expose the ``detail`` field that would tell the two
        apart. Hiding on both is the safe half of that ambiguity: the worst case
        is the reveal reappearing on the next ``<Motion>`` over a clipped cell,
        and it never leaves the label stranded over an unrelated row.
        """
        self._hide_summary_tooltip()

    def _clipped_summary_cell(self, x, y):
        """The text of the cell at (x, y), when it is wider than its column.

        ``None`` when there is no cell there, or when its text fits: the reveal
        must never cover a value the panel already shows in full.
        """
        tv = self.table.tv
        row_id = tv.identify_row(y)
        col_id = tv.identify_column(x)
        if not row_id or not col_id.startswith("#"):
            return None
        index = int(col_id[1:]) - 1
        values = tv.item(row_id, "values")
        if index < 0 or index >= len(values):
            return None
        text = str(values[index])
        box = tv.bbox(row_id, col_id)
        if not text or not box:
            return None
        if self._summary_cell_font(row_id).measure(text) <= box[2]:
            return None
        return text

    def _summary_cell_font(self, row_id):
        """The font the row's cells are drawn with.

        Summary block headers are drawn with ``FONT_HEADING`` (see
        :meth:`_DataTable._render`), so measuring a header with the body font
        would report a clipped header as fitting — and leave a translated block
        title that does not fit (bold is wider than the body font, and some
        catalogs state a block name in a third more width than English does)
        with no way to read it.
        """
        if "summary_header" in (self.table.tv.item(row_id, "tags") or ()):
            if self._summary_header_font is None:
                self._summary_header_font = tkfont.Font(font=FONT_HEADING)
            return self._summary_header_font
        return tkfont.nametofont("TkDefaultFont")

    def _hide_summary_tooltip(self):
        """Hide the reveal label, if one is showing."""
        if self._summary_tip_lbl is not None:
            self._summary_tip_lbl.place_forget()

    def _cleanup_summary_tooltip(self):
        """Drop the reveal label and its bindings: the panel is being replaced."""
        self._hide_summary_tooltip()
        for sequence, attribute in (("<Motion>", "_summary_motion_bind"),
                                    ("<Leave>", "_summary_leave_bind")):
            bind_id = getattr(self, attribute, None)
            if bind_id is None:
                continue
            try:
                self.table.tv.unbind(sequence, bind_id)
            except tk.TclError:  # widget already destroyed
                pass
            setattr(self, attribute, None)
        if self._summary_tip_lbl is not None:
            try:
                self._summary_tip_lbl.destroy()
            except tk.TclError:  # widget already destroyed
                pass
            self._summary_tip_lbl = None

    def _build_overview_summary(self, data):
        """One-page overview of the file: the view a freshly opened file shows.

        Answers "what is this file" before any per-generation detail: which file
        it is and what period it covers, whose card and/or which vehicle
        recorded it, what it totals and how far the file verifies.

        Nothing here is computed twice. Every block reuses the code that owns
        the fact — the File Info dict (:meth:`_build_file_info`),
        :meth:`_build_driver_summary`, :meth:`_build_vehicle_summary`,
        ``_compute_activity_totals`` and :meth:`_integrity_label` — so the
        overview cannot drift from the section it summarises. Rows use the
        ``(label, value, is_header)`` shape the other summary panels already
        render.

        The driving-time rules used to state a fourth block here (how many days
        the rules flag, and the three limits applied). It was removed on the
        owner's decision: for a file *analyzer* the rules are not needed yet —
        the limits behind them (9 h daily, 4 h 30 continuous, 45 min break) are
        still being decided — and a page that reports a verdict nobody has
        finalised is worse than one that stays silent. The evaluation itself is
        untouched (``core.utils.activity_stats.evaluate_driving_rules``): the
        Daily-Activities dashboard still computes it, behind
        :data:`SHOW_DRIVING_INFRACTIONS`.

        Rows whose value would not fit the panel's fixed value column are not
        shortened here except where the value repeats itself (see the INTEGRITY
        block); everything else stays the owning code's own wording and is
        readable in full through the panel's hover reveal
        (:meth:`_bind_summary_reveal`).

        Returns:
            tuple: ``(columns, rows)`` for ``_add_section(..., summary=True)``.
        """
        info = self._build_file_info(data)
        sep = ("", "", True)
        rows = []
        days = _activity_days(data.get("activities"))

        # ── FILE: identity of the file and the period it covers ──
        rows.append(_SummaryHeader(_("FILE"), icon="file-info"))
        rows.append((_("  Filename"), info.get(_("Filename"), ""), False))
        rows.append((_("  Generation"), info.get(_("Generation"), "?"), False))
        rows.append((_("  Origin"), info.get(_("Origin"), ""), False))
        period = _("No activity data available.")
        if days:
            # Single spaces around the arrow (the dashboards' ranges keep their
            # double): this panel's value column does not fit itself, so the row
            # buys margin on purpose — 168 px in 187 px at 900x560, not 176 px.
            period = _("{first} \u2192 {last}").format(
                first=days[0][1], last=days[-1][1])
        rows.append((_("  Period covered"), period, False))
        rows.append(sep)

        # ── INTEGRITY: the same verdict (and coverage, when reported) the
        # File Info section and the status badge already show. ──
        rows.append(_SummaryHeader(_("INTEGRITY"), icon="integrity-locked"))
        rows.append((_("  Status"), info.get(_("Integrity"), ""), False))
        # The percentage alone, not File Info's "100.0% (1 234 567 / 1 234 567
        # bytes)": that string states the same number three times and is 241 px
        # wide, which does not fit this panel's 187 px value column in *any* of
        # the 34 catalogs (the percentage is 48 px and fits in all of them).
        # File Info is the detail page — its columns auto-fit — so the byte
        # arithmetic stays there, on the row the overview is summarising.
        coverage_pct = (data.get("coverage") or {}).get("byte_accounted_pct")
        if coverage_pct is not None:
            rows.append((_("  Byte-accounted coverage"), f"{coverage_pct}%",
                         False))
        rows.append(sep)

        # ── DRIVER / CARDHOLDER: card files only, and only when the card
        # carries something worth showing (GUI-BOGUS-DRIVER, G-F8: an untouched
        # TachoResult keeps every driver field at the truthy "N/A" sentinel).
        driver = data.get("driver") or {}
        if not (data.get("metadata") or {}).get("is_vu") and \
                any(value and value != "N/A" for value in driver.values()):
            block = _drop_empty_values(
                _summary_block(self._build_driver_summary(data)[1]))
            if len(block) > 1:
                rows.extend(block)
                rows.append(sep)

        # ── VEHICLE: a VU always recorded one; a card only when it was used
        # in a vehicle (the decoders fill ``vehicle`` for both, see
        # core/decoders/card_ef.py and core/parser/vu_dispatcher.py). ──
        vehicle = data.get("vehicle") or {}
        if any(str(vehicle.get(key) or "").strip() not in ("", "N/A")
               for key in ("plate", "vin", "registration_nation")):
            block = _drop_empty_values(
                _summary_block(self._build_vehicle_summary(data)[1]))
            if len(block) > 1:
                rows.extend(block)
                rows.append(sep)

        # ── TOTALS, day by day (one pass) ──
        totals = {"DRIVE": 0, "WORK": 0, "REST": 0, "AVAILABLE": 0}
        for record in data.get("activities") or []:
            changes = record.get("changes") if isinstance(record, dict) else None
            if not isinstance(changes, list) or not changes:
                continue
            day_totals = _compute_activity_totals(
                changes, recorded_until_seconds(record))
            for activity in totals:
                totals[activity] += day_totals[activity]

        rows.append(_SummaryHeader(_("TOTALS"), icon="statistics"))
        rows.append((_("  Drive"), _fmt_duration_minutes(totals["DRIVE"]), False))
        rows.append((_("  Work"), _fmt_duration_minutes(totals["WORK"]), False))
        rows.append((_("  Rest"), _fmt_duration_minutes(totals["REST"]), False))
        rows.append((_("  Available"),
                     _fmt_duration_minutes(totals["AVAILABLE"]), False))
        rows.append((_("  Days with activity"), str(len(days)), False))

        return [_("Field"), _("Value")], rows

    def _build_vehicle_summary(self, data):
        """Rich vehicle panel for fleet manager / mechanic."""
        veh = data.get("vehicle", {})
        calibrations = data.get("calibrations") or []
        sensors = data.get("sensor_pairings") or []
        vu_info = data.get("vu_info") or {}

        plate = veh.get("plate", "N/A")
        vin = veh.get("vin", "N/A")
        nation = veh.get("registration_nation", "")

        rows = []
        sep = ("", "", True)

        rows.append(_SummaryHeader(_("VEHICLE"), icon="vehicle"))
        rows.append((_("  Plate"), plate, False))
        rows.append((_("  VIN"), vin, False))
        if nation and nation not in ("N/A", ""):
            rows.append((_("  Registration"), ui_text.data_text(nation_full_name(nation)), False))
        rows.append(sep)

        if calibrations:
            cal = calibrations[0] if isinstance(calibrations[0], dict) else {}
            # Check if calibration is expired for the header icon
            cal_expired = False
            cal_soon = False
            days_left = 0
            next_date = cal.get("next_calibration_date")
            if next_date:
                days_left = _calibration_days_left(next_date)
                if days_left is not None:
                    cal_expired = days_left < 0
                    cal_soon = 0 <= days_left < 90
                else:
                    days_left = 0
            # Untranslated, exactly as before: the label was a composed
            # string, never a msgid, and inventing one would mean asking
            # 33 catalogs for a translation nobody has written.
            rows.append(_SummaryHeader("TACHOGRAPH", icon="tachograph"))
            # Tachograph device identity (from VuIdentification, fallback vu_info).
            vu_id = (data.get("vu_identifications") or [{}])[0] if data.get("vu_identifications") else {}
            tacho_make = (vu_id.get("manufacturer_name") or vu_info.get("manufacturer")
                          or vu_info.get("manufacturer_name") or "")
            tacho_sw = vu_id.get("software_version") or vu_info.get("software_version") or ""
            tacho_serial = (vu_id.get("serial_number") or vu_info.get("serial_number")
                            or vu_info.get("sensor_serial_number") or "")
            if tacho_make:
                rows.append((_("  Make"), tacho_make, False))
            if tacho_sw:
                rows.append((_("  Software version"), tacho_sw, False))
            if tacho_serial:
                rows.append((_("  Serial number"), tacho_serial, False))
            if next_date:
                date_str = fmt_val(next_date)
                if cal_expired:
                    # The warning is a word here, not a glyph: this is a value
                    # cell of a table, where no image can be drawn.
                    date_str += _("  EXPIRED ({days} days ago)").format(days=abs(days_left))
                elif cal_soon:
                    date_str += _("  Due in {days} days").format(days=days_left)
                rows.append((_("  Next calibration"), date_str, False))
            tyre = cal.get("tyre_size", "")
            speed = cal.get("authorised_speed_kmh", "")
            if tyre:
                rows.append((_("  Tyre size"), tyre, False))
            if speed:
                rows.append((_("  Authorised speed"), f"{speed} km/h", False))
            rows.append(sep)

        if sensors:
            s = sensors[0] if isinstance(sensors[0], dict) else {}
            rows.append(_SummaryHeader(_("SENSOR"), icon="sensor"))
            serial = s.get("sensor_serial", "")
            if serial:
                rows.append((_("  Serial"), serial, False))
            approval = s.get("sensor_approval", "")
            if approval:
                rows.append((_("  Approval"), approval, False))
            pairing = s.get("pairing_date", "")
            if pairing:
                rows.append((_("  Paired"), fmt_val(pairing), False))

            gnss_sensors = data.get("sensor_gnss_couplings") or []
            if gnss_sensors:
                g = gnss_sensors[0] if isinstance(gnss_sensors[0], dict) else {}
                gserial = g.get("sensor_gnss_serial", g.get("sensor_serial", ""))
                if gserial:
                    rows.append((_("  GNSS Serial"), gserial, False))
            rows.append(sep)

        if vu_info:
            rows.append(_SummaryHeader(_("VU INFO"), icon="vu-info"))
            # G1 VU keys (Mass Memory / old Continental VDO format)
            manufacturer = vu_info.get("manufacturer", vu_info.get("manufacturer_name", ""))
            if manufacturer:
                rows.append((_("  Manufacturer"), manufacturer, False))
            part = vu_info.get("part_number", "")
            if part:
                rows.append((_("  Part number"), part, False))
            serial = vu_info.get("serial_number", vu_info.get("sensor_serial_number", ""))
            if serial:
                rows.append((_("  Serial"), serial, False))
            sw = vu_info.get("software_version", "")
            if sw:
                rows.append((_("  Software version"), sw, False))
            approval = vu_info.get("approval_number", "")
            if approval:
                rows.append((_("  Approval"), approval, False))
            gen = vu_info.get("vu_generation", "")
            if gen and gen not in ("N/A", "", None):
                rows.append((_("  Generation"), str(gen), False))
            ability = vu_info.get("vu_ability", "")
            if ability and ability not in ("N/A", "", None):
                rows.append((_("  Ability"), str(ability), False))
            map_ver = vu_info.get("digital_map_version", "")
            if map_ver and map_ver not in ("N/A", ""):
                rows.append((_("  Digital map"), map_ver, False))
            mfg_date = vu_info.get("manufacturing_date", "")
            if mfg_date:
                rows.append((_("  Manufactured"), mfg_date, False))
            sw_date = vu_info.get("software_install_date", vu_info.get("software_installation_date", ""))
            if sw_date:
                rows.append((_("  SW installed"), sw_date, False))
            sensor_serial = vu_info.get("sensor_serial_number", "")
            if sensor_serial and sensor_serial != serial:
                rows.append((_("  Sensor serial"), sensor_serial, False))
            sensor_approval = vu_info.get("sensor_approval_number", "")
            if sensor_approval:
                rows.append((_("  Sensor approval"), sensor_approval, False))
            sensor_pairing = vu_info.get("sensor_pairing_date", "")
            if sensor_pairing:
                rows.append((_("  Sensor paired"), sensor_pairing, False))
            rows.append(sep)

        # Current company lock
        locks = data.get("company_locks") or []
        active_lock = None
        for lock in locks:
            if isinstance(lock, dict) and lock.get("lock_out_time") is None:
                active_lock = lock
                break
        if active_lock:
            rows.append(_SummaryHeader(_("CURRENT LOCK"), icon="integrity-locked"))
            name = active_lock.get("company_name", "")
            if name:
                rows.append((_("  Company"), name, False))
            addr = active_lock.get("company_address", "")
            if addr:
                rows.append((_("  Address"), addr, False))
            lock_in = active_lock.get("lock_in_time", "")
            if lock_in:
                rows.append((_("  Locked since"), fmt_val(lock_in), False))
            card = active_lock.get("company_card", "")
            if isinstance(card, dict):
                card_str = card.get("card_number", "")
                if card_str:
                    rows.append((_("  Lock card"), card_str, False))
        elif locks:
            rows.append(_SummaryHeader(_("CURRENT LOCK"), icon="integrity-unlocked"))
            rows.append((_("  Status"), _("Not locked"), False))

        # Activity summary
        activities = len(data.get("activities") or [])
        events = len(data.get("events") or [])
        faults = len(data.get("faults") or [])
        if activities or events:
            if rows and rows[-1] != sep:
                rows.append(sep)
            rows.append(_SummaryHeader(_("STATISTICS"), icon="statistics"))
            rows.append((_("  Days with activities"), str(activities), False))
            rows.append((_("  Events"), str(events), False))
            rows.append((_("  Faults"), str(faults), False))

        cols = ["Field", "Value"]
        return cols, rows

    def _build_trep_summary(self, trep_report, meta=None):
        """Warning page shown only for corrupted/partial downloads: explains
        what is present, what is missing/corrupted, and that only the listed
        parts of the file could be recovered."""
        meta = meta or {}
        rows = []
        sep = ("", "", True)

        rows.append(_SummaryHeader(_("THIS FILE IS INCOMPLETE OR CORRUPTED"),
                                   icon="status-warning"))
        rows.append((_("  Only the sections listed below could be read."), "", False))
        rows.append((_("  Missing or corrupted data is NOT shown."), "", False))
        rows.append(sep)

        rows.append(_SummaryHeader(_("COMPLETENESS"), icon="completeness"))
        rows.append((
            _("  Mandatory sections read"),
            f"{trep_report['mandatory_ok']}/{trep_report['mandatory_total']} "
            f"({trep_report['completeness_pct']}%)", False))
        if not trep_report.get("complete_walk", True):
            rows.append((_("  File structure"),
                         _("Truncated (did not reach end of file)"), False))
        rows.append(sep)

        present = trep_report.get("present") or []
        rows.append(_SummaryHeader(_("SECTIONS PRESENT"), icon="status-ok"))
        if present:
            for t in present:
                rows.append((f"  {t['name']}", t["trep"], False))
        else:
            rows.append((_("  (none)"), "", False))
        rows.append(sep)

        missing = trep_report.get("mandatory_missing") or []
        if missing:
            rows.append(_SummaryHeader(_("MISSING MANDATORY SECTIONS"), icon="status-error"))
            for t in missing:
                rows.append((f"  {t['name']}", t["trep"], False))
            rows.append(sep)

        suspect = trep_report.get("decoded_suspect") or []
        if suspect:
            rows.append(_SummaryHeader(_("CORRUPTED SECTIONS (data discarded)"),
                                       icon="status-warning"))
            for t in suspect:
                rows.append((f"  {t['name']}", t["trep"], False))
            rows.append(sep)

        salvaged = meta.get("salvage_recovered") or []
        if salvaged:
            rows.append(_SummaryHeader(_("RECOVERED FROM DAMAGED DATA"), icon="recovered"))
            rows.append((_("  Low-confidence recovery"), ", ".join(salvaged), False))

        cols = ["Field", "Value"]
        return cols, rows

    def _build_sensor_summary(self, data):
        """Rich sensor panel for workshop / mechanic."""
        sensor = data.get("sensor_info", {})
        veh = data.get("vehicle", {})
        daily = data.get("sensor_daily_records") or []

        plate = veh.get("plate", "N/A")
        vin = veh.get("vin", "N/A")

        rows = []
        sep = ("", "", True)

        rows.append(_SummaryHeader(_("SENSOR"), icon="sensor"))
        approval = sensor.get("sensor_approval", "")
        nation = sensor.get("approval_nation", "")
        if approval:
            rows.append((_("  Approval"), f"{approval}", False))
        if nation:
            rows.append((_("  Nation"), ui_text.data_text(nation_full_name(nation)), False))
        prefix = sensor.get("approval_prefix", "")
        if prefix:
            rows.append((_("  Prefix"), prefix, False))
        rows.append(sep)

        rows.append(_SummaryHeader(_("ASSOCIATED VEHICLE"), icon="vehicle"))
        rows.append((_("  Plate"), plate, False))
        rows.append((_("  VIN"), vin, False))
        rows.append(sep)

        rows.append(_SummaryHeader(_("DATE RANGE"), icon="date-range"))
        first = sensor.get("first_date", "N/A")
        last = sensor.get("last_date", "N/A")
        rows.append((_("  First date"), first, False))
        rows.append((_("  Last date"), last, False))
        if daily:
            unique = sorted(set(d.get("date", "") for d in daily))
            rows.append((_("  Days recorded"), str(len(unique)), False))
            if len(unique) >= 2:
                rows.append((_("  Actual range"), f"{unique[0]} \u2192 {unique[-1]}", False))
        rows.append(sep)

        rows.append(_SummaryHeader(_("PARAMETERS"), icon="parameters"))
        spd_max = sensor.get("param_speed_max_kmh", "")
        spd_avg = sensor.get("param_speed_avg_kmh", "")
        dist = sensor.get("param_distance_km", "")
        if spd_max:
            rows.append((_("  Max speed"), f"{spd_max} km/h", False))
        if spd_avg:
            rows.append((_("  Avg speed"), f"{spd_avg} km/h", False))
        if dist:
            rows.append((_("  Distance"), f"{dist} km", False))

        cols = ["Field", "Value"]
        return cols, rows

    def _build_driver_summary(self, data):
        """Rich driver panel for fleet manager."""
        driver = data.get("driver", {})
        activities = data.get("activities") or []
        events = data.get("events") or []
        efv = data.get("ef_signature_verification") or {}
        cards = data.get("card_downloads") or []

        rows = []
        sep = ("", "", True)

        rows.append(_SummaryHeader(_("CARDHOLDER"), icon="driver"))
        surname = driver.get("surname", "")
        firstname = driver.get("firstname", "")
        name = f"{firstname} {surname}".strip()
        if name:
            rows.append((_("  Name"), name, False))
        rows.append((_("  Card number"), driver.get("card_number", "N/A"), False))
        rows.append(sep)

        rows.append(_SummaryHeader(_("CARD DETAILS"), icon="card-details"))
        nation = driver.get("issuing_nation", "")
        if nation:
            rows.append((_("  Issuing nation"), ui_text.data_text(nation_full_name(nation)), False))
        authority = driver.get("issuing_authority", "")
        if authority and authority != "N/A":
            rows.append((_("  Issuing authority"), authority, False))
        issue_date = driver.get("issue_date", "")
        if issue_date:
            rows.append((_("  Issue date"), issue_date, False))
        validity_begin = driver.get("validity_begin", "")
        if validity_begin:
            rows.append((_("  Valid from"), validity_begin, False))
        expiry = driver.get("expiry_date", "")
        if expiry:
            rows.append((_("  Expiry date"), expiry, False))
        birth = driver.get("birth_date", "")
        if birth:
            rows.append((_("  Birth date"), birth, False))
        licence = driver.get("licence_number", "")
        if licence and licence != "N/A":
            rows.append((_("  Licence number"), licence, False))
        language = driver.get("preferred_language", "")
        if language and language != "N/A":
            rows.append((_("  Language"), language, False))
        rows.append(sep)

        rows.append(_SummaryHeader(_("STATISTICS"), icon="statistics"))
        act_days = len(activities)
        total_changes = sum(len(a.get("changes") or [])
                            for a in activities if isinstance(a, dict))
        rows.append((_("  Days with activity"), str(act_days), False))
        rows.append((_("  Activity changes"), str(total_changes), False))
        rows.append((_("  Events"), str(len(events)), False))
        if cards:
            rows.append((_("  Card downloads"), str(len(cards)), False))

        if efv.get("summary"):
            rows.append(sep)
            rows.append(_SummaryHeader(_("SIGNATURES"), icon="security"))
            rows.append((_("  EF verification"), efv["summary"], False))

        cols = ["Field", "Value"]
        return cols, rows
