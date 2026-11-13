"""``TachoExplorer`` — right-hand views: tables, charts and the daily/speed dashboards.

Methods moved unchanged out of ``app/gui.py``; ``TachoExplorer`` inherits them
from :class:`DashboardMixin`. Names the test-suite replaces on ``app.gui`` are read
through ``_live`` (see ``app.gui_base._LiveGuiNames``).
"""
from app.gui_base import (  # noqa: F401
    ACCENT,
    ACTIVE_BG,
    ACTIVITY_AVAILABLE,
    ACTIVITY_DRIVE,
    ACTIVITY_REST,
    ACTIVITY_WORK,
    DAILY_DRIVE_LIMIT_MIN,
    DANGER,
    DANGER_BAND,
    DANGER_STRONG,
    DASHBOARD_TOOLTIP_BG,
    FONT_BODY,
    FONT_HEADING,
    FONT_SMALL,
    HEADER_BG,
    SLATE,
    SURFACE,
    SURFACE_SUNKEN,
    TEXT_SECONDARY,
    TOGGLE_BG,
    _,
    _activity_to_iso,
    _attach_day_distance,
    _changes_for_slot,
    _compute_activity_totals,
    _driver_names_by_date,
    _driving_rule_explanation,
    _flush,
    _fmt_duration_minutes,
    _fmt_seconds_duration,
    _kpi_card,
    _live,
    _parse_iso,
    _px,
    datetime,
    recorded_until_seconds,
    timedelta,
    timezone,
    tk,
)


class DashboardMixin:
    """Right-hand views: tables, charts and the daily/speed dashboards."""

    def _show_dashboard(self, title, date_range, kpis, columns, rows,
                        row_tags=None, tooltips=None, ev_tooltips=None,
                        rule_tips=None):
        """Render a summary dashboard with KPI cards and sortable table.

        ``tooltips`` (driver/vehicle column), ``ev_tooltips`` (Ev column) and
        ``rule_tips`` (Drive column, the driving-time-rule explanation) are all
        keyed by *row key*, not by display position: the table is sortable and
        filterable, and a positional key handed the tooltip of the day that
        happened to sit at that index after the reorder. ``rule_tips`` is empty
        while :data:`SHOW_DRIVING_INFRACTIONS` is off.
        """
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
        self.table.count_lbl.config(text=date_range)
        self.table.filter_var.set("")
        self.table._cols = list(columns)
        self.table._sort_state = {}
        self.table._fitted = False
        self.table._summary_mode = False
        self.table.tv["show"] = "headings"

        self.table.filt_bar.pack_forget()

        kpi_frame = tk.Frame(self.table, bg=SURFACE_SUNKEN)
        kpi_frame.pack(fill=tk.X, padx=8, pady=(4, 12), before=self.table.tv.master)
        self._kpi_frame = kpi_frame

        num_cols = min(len(kpis), 4)
        for i, (label, value, accent) in enumerate(kpis):
            row_idx = i // num_cols
            col_idx = i % num_cols
            card, _caption, _value = _kpi_card(kpi_frame, label, value, accent)
            card.grid(row=row_idx, column=col_idx, padx=5, pady=5,
                      sticky="nsew")

        for c in range(num_cols):
            kpi_frame.columnconfigure(c, weight=1, uniform="kpi")
        for r in range((len(kpis) + num_cols - 1) // num_cols):
            kpi_frame.rowconfigure(r, weight=1)

        self.table.tv["columns"] = self.table._cols
        for c in self.table._cols:
            anchor = tk.W if c == _("Date") else tk.CENTER
            self.table.tv.heading(c, text=str(c), anchor=anchor,
                                  command=lambda col=c: self.table._sort_by(col))
            min_w = max(len(str(c)) * _px(9) + _px(20), _px(60))
            self.table.tv.column(c, minwidth=min_w, anchor=anchor, stretch=True)

        self.table.tv.tag_configure("total",
                                    font=FONT_HEADING,
                                    foreground=ACCENT,
                                    background=HEADER_BG)
        self.table.tv.tag_configure("separator", background=SURFACE_SUNKEN)
        # A day that breaks a driving-time rule (Reg. (EC) 561/2006 art. 6(1)
        # or art. 7). ttk.Treeview can only style a whole row, so the violation
        # tints the row; the Drive cell additionally carries the warning glyph
        # so the day is recognisable without relying on colour. Both are hidden
        # while :data:`SHOW_DRIVING_INFRACTIONS` is off — the tag is not even
        # configured then, so the tint cannot reappear on a stale row either.
        if _live.SHOW_DRIVING_INFRACTIONS:
            self.table.tv.tag_configure("flagged", background=DANGER_BAND)

        # Render with row tags. The rows carry their tag and a stable key from
        # here on, so a header click or a filter change cannot drop the tint of
        # a flagged day, the month-total emphasis, or a row's tooltip.
        self.table.set_rows(rows, tags=row_tags,
                            keys=list(range(len(rows))))

        # Tooltips for # Drivers / # Vehicles column
        self._dashboard_tooltips = tooltips or {}
        self._dashboard_drv_col = -1
        for name in (_("# Drivers"), _("# Vehicles")):
            if name in columns:
                self._dashboard_drv_col = columns.index(name)
                break
        # Tooltips for Ev column
        ev_column = _("Ev")
        self._dashboard_ev_col = columns.index(ev_column) if ev_column in columns else -1
        self._dashboard_ev_tips = ev_tooltips or {}
        # Tooltips for the Drive column: the violation marker sits in that cell, so the
        # explanation of what it means has to be reachable there and not only
        # on the driver/vehicle cell. With :data:`SHOW_DRIVING_INFRACTIONS` off
        # there is no marker and ``rule_tips`` is empty, so the handler below
        # shows nothing for that column.
        drive_column = _("Drive")
        self._dashboard_drive_col = (columns.index(drive_column)
                                     if drive_column in columns else -1)
        self._dashboard_rule_tips = rule_tips or {}
        self._dashboard_motion_bind = self.table.tv.bind(
            "<Motion>", self._on_dashboard_motion, add="+")
        self._tooltip_lbl = tk.Label(self.table.tv, text="", bg=DASHBOARD_TOOLTIP_BG,
                                     relief=tk.SOLID, borderwidth=1, font=FONT_SMALL,
                                     fg=TEXT_SECONDARY, padx=6, pady=2)

        self.table.tv.update_idletasks()
        self.table._fit_columns()
        _flush(self.table.tv)
        self.table._sync_xscroll()
        if self.table._fit_after_id is not None:
            self.table.tv.after_cancel(self.table._fit_after_id)
            self.table._fit_after_id = None

    def _on_dashboard_double_click(self, event):
        is_vu = getattr(self, "_dashboard_is_vu", False)
        row_id = self.table.tv.identify_row(event.y)
        if not row_id:
            return
        values = self.table.tv.item(row_id, "values")
        if not values:
            return
        date_str = values[0]
        activity_list = getattr(self, "_dashboard_activity_list", [])
        data = getattr(self, "_dashboard_data", {}) or {}
        day_data = None
        for d in activity_list:
            if isinstance(d, dict) and d.get("date", d.get("timestamp", "")) == date_str:
                day_data = d
                break
        if not day_data:
            return
        # GUI-DASHBOARD-SLOT2-POPUP (G-F2/H-F4): hand the popup the day's FULL
        # change set. The dashboard is a per-slot view, but the popup re-splits
        # by slot itself (via _changes_for_slot) and opens on the dashboard's
        # slot; filtering here to that slot stripped the popup's other slot and
        # made it show "No data for this day.". The unfiltered set still carries
        # the slot-less heuristic changes, so a slot-less day is not empty
        # either.
        changes = day_data.get("changes") or []
        # GUI-DISTANCE-FALLBACK (XG-F9): the day-detail popup must show the
        # day's distance, not the absolute odometer. For a VU the day distance
        # is precomputed in "_day_km"; for a card file reuse the odometer-delta
        # the dashboard computes for the very same day (stored by
        # _show_daily_summary) rather than falling back to "odometer_km", which
        # is the absolute reading and produced a huge, misleading "Distance".
        if is_vu:
            day_km = day_data.get("_day_km", 0) or 0
        else:
            # __dict__ lookup (not getattr): on a Tk widget a missing attribute
            # falls through to tkinter.Misc.__getattr__. The mapping is always
            # set by _show_daily_summary before the dashboard is clickable, so a
            # missing entry simply means "no known distance" -> 0, never the
            # absolute odometer.
            day_km = (self.__dict__.get("_dashboard_card_day_km") or {}).get(
                id(day_data), 0)
        changes_count = day_data.get("changes_count") or len(changes)

        drv = data.get("driver") or {}
        driver_name = f"{drv.get('firstname','')} {drv.get('surname','')}".strip()
        if not driver_name or driver_name == "N/A N/A":
            driver_name = drv.get("card_number", "") or ""

        # Build slot_schedule/markers/vehicles for the day
        iso_date = _activity_to_iso(date_str)
        vehicles = []
        for sess in (data.get("vehicle_sessions") or []):
            if not isinstance(sess, dict):
                continue
            # GUI-VEHICLES-PER-DAY (H-F9): the dashboard's "# Vehicles" column
            # fills every day a session spans (start -> end), but the day detail
            # only took sessions ANCHORED on the day (start, else end). A session
            # running 01/05 -> 03/05 was counted on 02 and 03 by the dashboard
            # yet the detail for those days listed no vehicle. Include a session
            # when the day falls inside [start, end] (whichever bounds exist) so
            # the two views agree.
            sd = _parse_iso(sess.get("start"))
            ed = _parse_iso(sess.get("end"))
            if sd is None and ed is None:
                continue
            start_iso = (sd or ed).date().isoformat()
            end_iso = (ed or sd).date().isoformat()
            if iso_date and start_iso <= iso_date <= end_iso:
                vehicles.append(sess)

        # Build markers and schedule from card_iw_records
        markers = []
        slot_schedule = {}
        for rec in (data.get("card_iw_records") or []):
            if not isinstance(rec, dict):
                continue
            ins_ts = rec.get("insertion_time", "")
            ins_dt = _parse_iso(ins_ts)
            if not ins_dt or ins_dt.date().isoformat() != iso_date:
                continue
            sec_of_day = ins_dt.hour * 3600 + ins_dt.minute * 60 + ins_dt.second
            # GUI-NAME-ORDER (H-F8): the popup markers/schedule must show
            # "First names Surname" like every other view, not the reversed
            # "Surname First names".
            name = f"{rec.get('holder_first_names','')} {rec.get('holder_surname','')}".strip()
            if not name or name == "N/A N/A":
                # GUI-DISTANCE-FALLBACK (XG-F9): the UI is English; the
                # previous hard-coded Italian "Sconosciuto" was the only
                # untranslated string in app/.
                name = rec.get("card_number", "") or "Unknown"
            slot = rec.get("card_slot", 0)
            slot_label = "Slot 1" if not slot else "Slot 2"
            markers.append((sec_of_day, slot_label, name, True))

            # Build schedule: start/end times for display
            wit_ts = rec.get("withdrawal_time", "")
            if not wit_ts:
                continue
            wit_dt = _parse_iso(wit_ts)
            end_hhmm = wit_dt.strftime("%H:%M") if wit_dt else None
            start_hhmm = ins_dt.strftime("%H:%M")
            slot_schedule.setdefault(slot_label, []).append((start_hhmm, end_hhmm, name))

        # Build oos_events
        oos_events = []
        for sc in (data.get("specific_conditions") or []):
            if not isinstance(sc, dict):
                continue
            ts = sc.get("timestamp", "")
            try:
                sc_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if sc_dt.date().isoformat() != iso_date:
                    continue
                sec_of_day = sc_dt.hour * 3600 + sc_dt.minute * 60 + sc_dt.second
                cond = sc.get("condition", "")
                oos_events.append((sec_of_day, cond, sc_dt.astimezone(timezone.utc)))
            except (ValueError, AttributeError):
                continue

        day_vehicles = self._day_vehicles_info(vehicles)

        initial_slot = 2 if (is_vu and getattr(
            self, "_vu_slot_filter", "Slot 1") == "Slot 2") else 1
        _live.DayDetailWindow(self, date_str, changes, day_km, changes_count,
                        driver_name, slot_schedule, markers, oos_events,
                        day_vehicles, data, is_vu=is_vu, initial_slot=initial_slot,
                        recorded_until=recorded_until_seconds(day_data))

    def _on_dashboard_motion(self, event):
        drv_col = getattr(self, "_dashboard_drv_col", -1)
        ev_col = getattr(self, "_dashboard_ev_col", -1)
        drive_col = getattr(self, "_dashboard_drive_col", -1)
        if drv_col < 0 and ev_col < 0 and drive_col < 0:
            return
        # The label is owned by the current dashboard and destroyed when that
        # view goes away (see _cleanup_dashboard): a motion event delivered
        # after the switch has nothing to show and must not raise.
        tooltip_lbl = getattr(self, "_tooltip_lbl", None)
        if tooltip_lbl is None:
            return
        row_id = self.table.tv.identify_row(event.y)
        col_id = self.table.tv.identify_column(event.x)
        col_idx = int(col_id.replace("#", "")) - 1 if col_id else -1
        if not row_id or col_idx not in (drv_col, ev_col, drive_col):
            tooltip_lbl.place_forget()
            return
        # Look the row up by its stable key, never by its display position: the
        # table is sortable and filterable, so position i after a header click
        # is a different day than position i when the tooltips were built.
        key = self.table.row_key(row_id)
        if col_idx == drv_col:
            tip = self._dashboard_tooltips.get(key, "")
        elif col_idx == ev_col:
            ev_tips = getattr(self, "_dashboard_ev_tips", {}) or {}
            tip = ev_tips.get(key, "")
        else:
            rule_tips = getattr(self, "_dashboard_rule_tips", {}) or {}
            tip = rule_tips.get(key, "")
        if tip:
            tooltip_lbl.config(text=tip, justify=tk.LEFT, wraplength=380)
            tooltip_lbl.place(x=event.x + 16, y=event.y + 16)
        else:
            tooltip_lbl.place_forget()

    def _cleanup_dashboard(self):
        """Drop what only the previous view (dashboard or summary) needed."""
        if getattr(self, "_kpi_frame", None) is not None:
            self._kpi_frame.destroy()
            self._kpi_frame = None
        if getattr(self, "_slot_toggle_frame", None) is not None:
            self._slot_toggle_frame.destroy()
            self._slot_toggle_frame = None
        # Destroy the row tooltip, do not just hide it: the label is a child of
        # the treeview, so a dashboard visited n times used to leave n labels
        # behind (the summary panel's own label is destroyed the same way, see
        # _cleanup_summary_tooltip).
        tooltip_lbl = getattr(self, "_tooltip_lbl", None)
        if tooltip_lbl is not None:
            try:
                tooltip_lbl.destroy()
            except tk.TclError:      # widget already destroyed
                pass
            self._tooltip_lbl = None
        bind_id = getattr(self, "_dashboard_motion_bind", None)
        if bind_id is not None:
            try:
                self.table.tv.unbind("<Motion>", bind_id)
            except Exception:
                pass
            self._dashboard_motion_bind = None
        # The day-detail handler is bound by _show_daily_summary and used to
        # outlive the dashboard: it stayed armed on every later table, closing
        # over the previous dashboard's _dashboard_data and day list, so a
        # double-click in an ordinary table of another file ran the handler
        # against the file that was open before. Drop it (and the state it
        # reads) with the view that created it.
        if getattr(self, "_dashboard_double_click_bound", False):
            try:
                self.table.tv.unbind("<Double-1>")
            except Exception:
                pass
            self._dashboard_double_click_bound = False
        for attribute, empty in (("_dashboard_activity_list", None),
                                 ("_dashboard_data", None),
                                 ("_dashboard_is_vu", None),
                                 ("_dashboard_tooltips", {}),
                                 ("_dashboard_ev_tips", {}),
                                 ("_dashboard_rule_tips", {}),
                                 ("_dashboard_card_day_km", {}),
                                 ("_dashboard_drv_col", -1),
                                 ("_dashboard_ev_col", -1),
                                 ("_dashboard_drive_col", -1)):
            if hasattr(self, attribute):
                setattr(self, attribute, empty)
        # Every view switch comes through here, so the summary panel's own
        # reveal label (and its bindings on the table) is dropped here too.
        self._cleanup_summary_tooltip()

    def _show_daily_summary(self, activity_list, data, _fast_refresh=False):
        """Dashboard for the 'Daily Activities' parent node.
        When ``_fast_refresh=True``, skips the full layout rebuild and only
        updates table rows and KPI labels in place (used by the slot toggle)."""
        valid = [d for d in activity_list if isinstance(d, dict)]
        if not valid:
            self._show_empty(_("Daily Activities"), _("No activity data available."))
            return
        is_vu = (data.get("metadata") or {}).get("is_vu", False)

        # ── Slot filter for VU files ──
        slot_label = getattr(self, "_vu_slot_filter", "Slot 1")
        slot_name = "First" if slot_label == "Slot 1" else "Second"

        # Build a filtered view: each day's changes limited to the chosen slot.
        # Changes that carry no slot at all (heuristic G1 VU TREP 02 activities,
        # see core/decoders/vu_g1.py) are kept in every slot view rather than
        # dropped: excluding them zeroed every activity total of the day while
        # the same rows stayed visible in the day tree. No slot is invented for
        # them; they are simply treated as unassigned and still counted.
        if is_vu:
            filtered = []
            for day_data in valid:
                all_changes = day_data.get("changes") or []
                # Keep the selected slot's changes and any change that carries
                # no slot at all (heuristic G1 VU TREP 02, see
                # core/decoders/vu_g1.py): dropping the slot-less ones zeroed
                # every activity total of the day. Handled by the shared helper
                # so the day-detail view filters identically.
                filtered_changes = _changes_for_slot(all_changes, slot_name)
                copy = dict(day_data)
                copy["changes"] = filtered_changes
                filtered.append(copy)
            valid = filtered

        # Per-day driver names from card_iw, filtered by selected slot
        iw_by_date = (_driver_names_by_date(activity_list,
                                            data.get("card_iw_records") or [],
                                            slot_name)
                      if is_vu else {})

        # Global driver names for KPI count
        driver_names = set()
        for names in iw_by_date.values():
            driver_names.update(names)
        slot_idx = 0 if slot_name == "First" else 1
        if not driver_names:
            inserted = data.get("inserted_drivers") or []
            if slot_idx < len(inserted):
                d = inserted[slot_idx]
                name = f"{d.get('firstname','')} {d.get('surname','')}".strip()
                if name and name != "N/A N/A":
                    driver_names.add(name)
            else:
                for d in inserted:
                    name = f"{d.get('firstname','')} {d.get('surname','')}".strip()
                    if name and name != "N/A N/A":
                        driver_names.add(name)
        if not driver_names:
            drv = data.get("driver") or {}
            name = f"{drv.get('firstname','')} {drv.get('surname','')}".strip()
            if name and name != "N/A N/A":
                driver_names.add(name)
        if not driver_names:
            card_recs = data.get("card_records") or []
            if is_vu and slot_idx < len(card_recs):
                cn = card_recs[slot_idx].get("card_number", "") if isinstance(card_recs[slot_idx], dict) else ""
                if cn:
                    driver_names.add(cn)
            else:
                for cr in card_recs[:2]:
                    cn = cr.get("card_number", "") if isinstance(cr, dict) else ""
                    if cn:
                        driver_names.add(cn)

        # Vehicle info for card files
        card_vehicle_plate = ""
        card_vehicle_tip = ""
        if not is_vu:
            veh = data.get("vehicle") or {}
            plate = (veh.get("plate") or "").strip()
            nation = (veh.get("registration_nation") or "").strip()
            vin = (veh.get("vin") or "").strip()
            if plate and plate != "N/A":
                card_vehicle_plate = plate
                parts = [f"{nation} {plate}" if nation else plate]
                if vin and vin != "N/A":
                    parts.append(f"VIN {vin}")
                card_vehicle_tip = "  ·  ".join(parts)
        n_veh = 1 if card_vehicle_plate else 0

        # Per-day events for warning indicator and tooltips
        event_dates = set()
        events_by_date = {}  # iso_date -> [list of descriptions]
        for ev in (data.get("events") or []):
            if not isinstance(ev, dict):
                continue
            begin_ts = ev.get("begin") or ev.get("begin_time") or ""
            dt = _parse_iso(begin_ts)
            if not dt:
                continue
            iso = dt.date().isoformat()
            event_dates.add(iso)
            desc = ev.get("description", _("Unknown event"))
            time_str = dt.strftime("%H:%M")
            events_by_date.setdefault(iso, []).append(f"{time_str}  {desc}")

        # Per-day vehicles from vehicle_sessions (driver cards)
        veh_by_date = {}
        if not is_vu:
            for sess in (data.get("vehicle_sessions") or []):
                if not isinstance(sess, dict):
                    continue
                plate = (sess.get("vehicle_plate") or "").strip()
                if not plate:
                    continue
                start_dt = _parse_iso(sess.get("start"))
                end_dt = _parse_iso(sess.get("end"))
                if start_dt:
                    veh_by_date.setdefault(start_dt.date().isoformat(), set()).add(plate)
                if end_dt:
                    veh_by_date.setdefault(end_dt.date().isoformat(), set()).add(plate)
            # Fill gaps: a session spans from start date to end date
            for sess in (data.get("vehicle_sessions") or []):
                if not isinstance(sess, dict):
                    continue
                plate = (sess.get("vehicle_plate") or "").strip()
                if not plate:
                    continue
                start_dt = _parse_iso(sess.get("start"))
                end_dt = _parse_iso(sess.get("end"))
                if start_dt and end_dt and start_dt.date() != end_dt.date():
                    current = start_dt.date() + timedelta(days=1)
                    while current <= end_dt.date():
                        veh_by_date.setdefault(current.isoformat(), set()).add(plate)
                        current += timedelta(days=1)

        # Monthly grouping
        MONTH_NAMES = {1: _("Jan"), 2: _("Feb"), 3: _("Mar"), 4: _("Apr"),
                       5: _("May"), 6: _("Jun"), 7: _("Jul"), 8: _("Aug"),
                       9: _("Sep"), 10: _("Oct"), 11: _("Nov"), 12: _("Dec")}

        sort_key = lambda d: _activity_to_iso(str(d.get("date", "")))
        sorted_asc = sorted(valid, key=sort_key)

        # Daily km (chronological). The tree has already stored the same figure
        # on every day ("_day_km"): a VU day's distance is the delta of its
        # midnight odometer readings, while a driver-card day carries the
        # kilometres driven that day itself.
        card_day_km = {}
        if not is_vu:
            card_day_km = _attach_day_distance(sorted_asc, is_vu)
        # GUI-DISTANCE-FALLBACK (XG-F9): expose the per-day card distance the
        # dashboard shows, so the day-detail popup (opened by double-click) can
        # display the SAME number instead of falling back to the absolute
        # odometer.
        self._dashboard_card_day_km = card_day_km

        months = {}
        for day_data in sorted_asc:
            date_str = str(day_data.get("date", ""))
            try:
                day, month, year = date_str.split("/")
                month_key = f"{year}-{int(month):02d}"
            except ValueError:
                month_key = "unknown"
            months.setdefault(month_key, []).append(day_data)

        totals_global = {"DRIVE": 0, "WORK": 0, "REST": 0, "AVAILABLE": 0}
        max_drive = 0
        # Days of the file that break a driving-time rule (see day_rules below).
        # Counted only while the infractions are shown: the count exists for the
        # "Days over {hours} h" KPI card, which :data:`SHOW_DRIVING_INFRACTIONS`
        # hides as a whole (the evaluation itself still runs, every day).
        flagged_days = 0
        table_rows = []
        row_tags = []
        tooltips = {}
        ev_tooltips = {}
        # Drive-cell tooltips: the driving-time-rule explanation, keyed like the
        # others by row key so it follows the day through sorting/filtering.
        # Empty while :data:`SHOW_DRIVING_INFRACTIONS` is off — the Drive cell
        # then has nothing to explain, and the tooltip handler finds no text.
        rule_tips = {}
        row_idx = 0

        for month_key in reversed(list(months.keys())):
            m_days = months[month_key]
            m_tot = {"DRIVE": 0, "WORK": 0, "REST": 0, "AVAILABLE": 0, "KM": 0,
                     "drivers": set()}
            try:
                y, m = month_key.split("-")
                m_label = f"\u25b8 {MONTH_NAMES.get(int(m), m)} {y}"
            except ValueError:
                m_label = month_key

            for day_data in reversed(m_days):
                date_str = str(day_data.get("date", day_data.get("timestamp", "?")))
                changes = day_data.get("changes") or []
                if is_vu:
                    day_km = day_data.get("_day_km", 0) or 0
                    odo = day_data.get("odometer_km", 0) or 0
                else:
                    day_km = card_day_km.get(id(day_data), 0)
                    odo = 0
                day_cut = recorded_until_seconds(day_data)
                day_tots = _compute_activity_totals(changes, day_cut,
                                                    one_driver=not is_vu)
                # Driving-time rules of Reg. (EC) 561/2006: art. 6(1) (more than
                # 9 h of daily driving) and art. 7 (more than 4 h 30 min of
                # continuous driving without a qualifying break). A crew day is
                # judged per driver inside the helper, so the flag never comes
                # from summing two drivers' independent driving time.
                # Evaluated unconditionally — hiding the infractions
                # (:data:`SHOW_DRIVING_INFRACTIONS`) must not stop the
                # computation, so flipping the switch back is one line and the
                # verdict is already there.
                day_rules = _live.evaluate_driving_rules(changes, day_cut,
                                                         one_driver=not is_vu)
                for act in totals_global:
                    totals_global[act] += day_tots[act]
                for act in m_tot:
                    if act in day_tots:
                        m_tot[act] += day_tots[act]
                m_tot["KM"] += day_km
                if day_tots["DRIVE"] > max_drive:
                    max_drive = day_tots["DRIVE"]
                iso_date = _activity_to_iso(date_str)
                drivers = iw_by_date.get(iso_date, set())
                if not drivers and not is_vu:
                    drivers = driver_names
                m_tot["drivers"].update(drivers)
                names = ", ".join(sorted(drivers))
                n_drv = len(drivers) if drivers else 0

                km_str = f"{day_km:,}".replace(",", " ") if day_km else ""
                # A table cell cannot hold an image (this is a headings-only
                # Treeview), so both markers are ASCII: "!" for a day with an
                # event and "!" next to the Drive total of a day that breaks a
                # driving-time rule. The tooltip on the cell still explains
                # which rule and by how much, and the flagged row keeps its
                # tint — the mark is the shape signal for a colour-blind user.
                # The driving-rule half of that is behind
                # :data:`SHOW_DRIVING_INFRACTIONS` (off: the rule's thresholds
                # are not final yet); the event marker is not, it is about the
                # file's own events.
                ev_str = "!" if iso_date in event_dates else ""
                drive_str = _fmt_duration_minutes(day_tots["DRIVE"])
                if _live.SHOW_DRIVING_INFRACTIONS and day_rules.flagged:
                    drive_str += "  !"
                    flagged_days += 1
                if is_vu:
                    odo_str = f"{odo:,}".replace(",", " ") if odo else ""
                    table_rows.append([
                        date_str, f"{n_drv}\u2002\u25be", ev_str, km_str, odo_str,
                        drive_str,
                        _fmt_duration_minutes(day_tots["WORK"]),
                        _fmt_duration_minutes(day_tots["REST"]),
                        _fmt_duration_minutes(day_tots["AVAILABLE"]),
                    ])
                else:
                    day_vehicles = veh_by_date.get(iso_date, set())
                    n_day_veh = len(day_vehicles) or n_veh
                    table_rows.append([
                        date_str, f"{n_day_veh}\u2002\u25be", ev_str, km_str,
                        drive_str,
                        _fmt_duration_minutes(day_tots["WORK"]),
                        _fmt_duration_minutes(day_tots["REST"]),
                        _fmt_duration_minutes(day_tots["AVAILABLE"]),
                    ])
                row_tags.append("flagged"
                                if _live.SHOW_DRIVING_INFRACTIONS and day_rules.flagged
                                else None)
                if is_vu and names:
                    tooltips[row_idx] = names
                elif not is_vu and card_vehicle_tip:
                    tooltips[row_idx] = card_vehicle_tip
                if _live.SHOW_DRIVING_INFRACTIONS and day_rules.flagged:
                    # Say which rule and by how much, on the row's own tooltip
                    # (driver/vehicle column) and on the Drive cell that carries
                    # the marker in the Drive cell: a red row alone tells the user nothing they
                    # can verify.
                    explanation = _driving_rule_explanation(day_rules.breaches)
                    rule_tips[row_idx] = explanation
                    existing_tip = tooltips.get(row_idx)
                    tooltips[row_idx] = (f"{existing_tip}\n\n{explanation}"
                                         if existing_tip else explanation)
                if iso_date in event_dates:
                    ev_list = events_by_date.get(iso_date, [])
                    ev_text = "\n".join(ev_list)
                    # No info icon in the set: a tooltip is plain text
                    # anyway, and "Double-click for full details" needs no
                    # decoration to be understood.
                    ev_text += "\n\n" + _("Double-click for full details")
                    ev_tooltips[row_idx] = ev_text
                row_idx += 1

            # Monthly total row
            km_month = f"{m_tot['KM']:,}".replace(",", " ") if m_tot["KM"] else ""
            if is_vu:
                table_rows.append([
                    m_label, str(len(m_tot["drivers"])), "", km_month, "",
                    _fmt_duration_minutes(m_tot["DRIVE"]),
                    _fmt_duration_minutes(m_tot["WORK"]),
                    _fmt_duration_minutes(m_tot["REST"]),
                    _fmt_duration_minutes(m_tot["AVAILABLE"]),
                ])
            else:
                m_veh = len({p for day in m_days
                              for p in veh_by_date.get(
                                  _activity_to_iso(str(day.get("date", ""))), set())})
                m_n_veh = m_veh or n_veh
                table_rows.append([
                    m_label, str(m_n_veh) if m_n_veh else "", "", km_month,
                    _fmt_duration_minutes(m_tot["DRIVE"]),
                    _fmt_duration_minutes(m_tot["WORK"]),
                    _fmt_duration_minutes(m_tot["REST"]),
                    _fmt_duration_minutes(m_tot["AVAILABLE"]),
                ])
            row_tags.append("total")
            row_idx += 1

            num_cols = 9 if is_vu else 8
            table_rows.append([""] * num_cols)
            row_tags.append("separator")
            row_idx += 1

        # Remove trailing separator
        if table_rows and row_tags and row_tags[-1] == "separator":
            table_rows.pop()
            row_tags.pop()

        day_count = len(sorted_asc)
        avg_drive = totals_global["DRIVE"] // day_count if day_count else 0
        driver_count = len(driver_names)

        date_range = _("{first}  \u2192  {last}  \u00b7  {days} days").format(
            first=sorted_asc[0].get("date", "?"),
            last=sorted_asc[-1].get("date", "?"), days=day_count)

        kpis = [
            (_("Drive"), _fmt_duration_minutes(totals_global["DRIVE"]), ACTIVITY_DRIVE),
            (_("Work"), _fmt_duration_minutes(totals_global["WORK"]), ACTIVITY_WORK),
            (_("Rest"), _fmt_duration_minutes(totals_global["REST"]), ACTIVITY_REST),
            (_("Available"), _fmt_duration_minutes(totals_global["AVAILABLE"]), ACTIVITY_AVAILABLE),
            (_("Days"), str(day_count), TEXT_SECONDARY),
            (_("Avg Drive / day"), _fmt_duration_minutes(avg_drive), ACTIVITY_DRIVE),
            (_("Max Drive / day"), _fmt_duration_minutes(max_drive), ACTIVITY_DRIVE),
        ]
        if _live.SHOW_DRIVING_INFRACTIONS:
            # Days over the daily driving limit of Reg. (EC) 561/2006 art. 6(1).
            # The count is of every *flagged* day, so a day flagged by art. 7
            # alone (continuous driving, with a daily total under 9 h) is
            # counted too: it broke the driving-time rules, and its own tooltip
            # names the rule that fired rather than this caption.
            kpis.append(
                (_("Days over {hours} h").format(
                    hours=DAILY_DRIVE_LIMIT_MIN // 60),
                 str(flagged_days),
                 DANGER if flagged_days else TEXT_SECONDARY))
        if is_vu:
            kpis.append((_("Drivers"), str(driver_count), TEXT_SECONDARY))
        else:
            all_vehicles = set()
            for plates in veh_by_date.values():
                all_vehicles.update(plates)
            kpis.append((_("Vehicles"), str(len(all_vehicles) or n_veh), TEXT_SECONDARY))

        if is_vu:
            columns = [_("Date"), _("# Drivers"), _("Ev"), _("Km"), _("Odometer"),
                       _("Drive"), _("Work"), _("Rest"), _("Available")]
        else:
            columns = [_("Date"), _("# Vehicles"), _("Ev"), _("Km"),
                       _("Drive"), _("Work"), _("Rest"), _("Available")]
        if _fast_refresh:
            self._update_dashboard_in_place(
                date_range, kpis, table_rows, row_tags,
                columns, tooltips, ev_tooltips, activity_list, data,
                rule_tips=rule_tips)
        else:
            self._show_dashboard(_("Daily Activities"),
                                 date_range, kpis, columns, table_rows,
                                 row_tags=row_tags, tooltips=tooltips,
                                 ev_tooltips=ev_tooltips, rule_tips=rule_tips)

            self._dashboard_activity_list = activity_list
            self._dashboard_data = data
            self._dashboard_is_vu = is_vu
            self.table.tv.unbind("<Double-1>")
            self.table.tv.bind("<Double-1>",
                               lambda e: self._on_dashboard_double_click(e))
            # Remembered so _cleanup_dashboard unbinds it when this view goes
            # away: the handler closes over this dashboard's day list and data.
            self._dashboard_double_click_bound = True

            # ── Slot toggle for VU files ──
            if is_vu:
                self._build_vu_slot_toggle(activity_list, data)

    def _update_dashboard_in_place(
            self, date_range, kpis, table_rows, row_tags,
            columns, tooltips, ev_tooltips, activity_list, data,
            rule_tips=None):
        """Update just the table rows, KPI labels, and toggle without destroying layout."""
        self.table.count_lbl.config(text=date_range)

        # Update KPI cards
        kpi_frame = getattr(self, "_kpi_frame", None)
        if kpi_frame is not None:
            for child in kpi_frame.winfo_children():
                if isinstance(child, tk.Frame):
                    labels = [w for w in child.winfo_children() if isinstance(w, tk.Label)]
                    if len(labels) >= 2:
                        label_text = labels[0].cget("text")
                        for lbl, val, accent in kpis:
                            if lbl == label_text:
                                # The value colour can depend on the value ("Days
                                # over 9 h" is DANGER only while a day is
                                # flagged), so keep both in sync. That card is
                                # only built while :data:`SHOW_DRIVING_INFRACTIONS`
                                # is on; the loop simply finds nothing for it
                                # otherwise.
                                labels[1].config(text=val, fg=accent)
                                break

        # Refresh table (tags and stable row keys travel with the rows, so the
        # tint and the tooltips survive a later sort or filter)
        self.table.set_rows(table_rows, tags=row_tags,
                            keys=list(range(len(table_rows))))

        # Tooltips
        self._dashboard_tooltips = tooltips or {}
        self._dashboard_ev_tips = ev_tooltips or {}
        self._dashboard_rule_tips = rule_tips or {}

        # Update slot label in toggle bar
        slot_frame = getattr(self, "_slot_toggle_frame", None)
        if slot_frame is not None:
            slot_label = getattr(self, "_vu_slot_filter", "Slot 1")
            for child in slot_frame.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(text=_(slot_label))
                    break

    def _build_vu_slot_toggle(self, activity_list, data):
        """Add a Slot 1 / Slot 2 toggle button above the daily activities table."""
        slot_label = getattr(self, "_vu_slot_filter", "Slot 1")
        if getattr(self, "_slot_toggle_frame", None) is not None:
            self._slot_toggle_frame.destroy()
        btn_frame = tk.Frame(self.table, bg=SURFACE)
        self._slot_toggle_frame = btn_frame
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 4), before=self.table.tv.master)

        tk.Label(btn_frame, text=_(slot_label), font=FONT_HEADING,
                 fg=ACCENT, bg=SURFACE).pack(side=tk.LEFT)

        def _toggle():
            current = getattr(self, "_vu_slot_filter", "Slot 1")
            new_slot = "Slot 2" if current == "Slot 1" else "Slot 1"
            self._vu_slot_filter = new_slot
            self._show_daily_summary(activity_list, data, _fast_refresh=True)

        tk.Button(btn_frame, text="\u21c4", font=FONT_BODY,
                  bg=TOGGLE_BG, fg=TEXT_SECONDARY, relief=tk.FLAT,
                  padx=8, pady=0, activebackground=ACTIVE_BG,
                  activeforeground=ACCENT, cursor="hand2",
                  command=_toggle).pack(side=tk.RIGHT)

    def _show_speed_summary(self, raw_blocks, data):
        """Dashboard for the 'Detailed Speed' parent node."""
        all_blocks = list(raw_blocks or [])
        all_blocks += list(data.get("speed_blocks") or [])

        by_day = _live.detailed_speed_by_day(data)
        if not by_day:
            self._show_empty(_("Detailed Speed"), _("No detailed speed samples available."))
            return

        total_samples = 0
        global_max = 0
        total_speed_sum = 0
        overspeed_seconds = 0
        overspeed_events = 0
        max_daily_avg = 0.0
        min_daily_avg = float("inf")
        table_rows = []

        for day_iso in sorted(by_day, reverse=True):
            samples = by_day[day_iso]
            if not samples:
                continue
            speeds = [sample for _second, sample in samples if isinstance(sample, (int, float))]
            if not speeds:
                continue
            n = len(speeds)
            total_samples += n
            day_max = max(speeds)
            if day_max > global_max:
                global_max = day_max
            day_avg = sum(speeds) / n
            total_speed_sum += sum(speeds)
            if day_avg > max_daily_avg:
                max_daily_avg = day_avg
            if day_avg < min_daily_avg:
                min_daily_avg = day_avg

            # Overspeed (>90 km/h)
            over_secs = sum(1 for _s, sample in samples
                            if isinstance(sample, (int, float)) and sample > 90)
            overspeed_seconds += over_secs

            # Overspeed events (contiguous runs > 90)
            events = 0
            in_over = False
            for _s, s in samples:
                if isinstance(s, (int, float)) and s > 90:
                    if not in_over:
                        events += 1
                        in_over = True
                else:
                    in_over = False
            overspeed_events += events

            # Format date: yyyy-mm-dd → dd/mm/yyyy
            try:
                parts = day_iso.split("-")
                date_fmt = f"{parts[2]}/{parts[1]}/{parts[0]}"
            except (IndexError, ValueError):
                date_fmt = day_iso

            table_rows.append([
                date_fmt,
                f"{day_max:.0f}",
                f"{day_avg:.1f}",
                str(n),
                # GUI-SPEED-ROUNDING (G-F5): seconds, not truncated minutes.
                _fmt_seconds_duration(over_secs),
                str(events),
            ])

        global_avg = total_speed_sum / total_samples if total_samples else 0
        if min_daily_avg == float("inf"):
            min_daily_avg = 0
        days = sorted(by_day, reverse=True)
        day_count = len(days)
        date_range = _("{first}  \u2192  {last}  \u00b7  {days} days").format(
            first=days[-1], last=days[0], days=day_count)

        kpis = [
            (_("Days"), str(day_count), TEXT_SECONDARY),
            (_("Max speed"), f"{global_max:.0f} km/h", ACCENT),
            (_("Avg speed"), f"{global_avg:.1f} km/h", TEXT_SECONDARY),
            (_("Samples"), f"{total_samples:,}".replace(",", " "), TEXT_SECONDARY),
            (_("Time >90 km/h"), _fmt_seconds_duration(overspeed_seconds), DANGER_STRONG),
            (_("Overspeed events"), str(overspeed_events), DANGER_STRONG),
            (_("Max avg / day"), f"{max_daily_avg:.1f} km/h", ACCENT),
            (_("Min avg / day"), f"{min_daily_avg:.1f} km/h", SLATE),
        ]

        columns = [_("Date"), _("Max km/h"), _("Avg km/h"), _("Samples"),
                   _(">90 km/h"), _("Events")]
        self._show_dashboard(_("Detailed Speed"),
                             date_range, kpis, columns, table_rows)

    def _show_table(self, title, cols, rows, meta="", alternate=None):
        self._cleanup_dashboard()
        self._hide_empty_state()
        self.speed_chart.pack_forget()
        self.activity_chart.pack_forget()
        if not self.table.winfo_manager():
            self.table.pack(fill=tk.BOTH, expand=True)
        self.table.show(title, cols, rows, meta, alternate=alternate)

    def _show_empty(self, title, message):
        """Render an explicit empty-state so a data-less node does not leave
        the previously selected table on screen."""
        self._show_table(title, ["Info"], [[message]])

    def _authorised_speed_limit(self):
        """Return the vehicle's authorised speed (km/h) from the most recent
        calibration, or None to fall back to the default SPEED_LIMIT_KMH."""
        if not self.current_data:
            return None
        for cal in reversed(self.current_data.get("calibrations") or []):
            if isinstance(cal, dict):
                spd = cal.get("authorised_speed_kmh")
                if isinstance(spd, (int, float)) and spd > 0:
                    return int(spd)
        return None

    def _show_speed_chart(self, day, samples, overspeeding_events=None):
        self._cleanup_dashboard()
        self._hide_empty_state()
        self.table.pack_forget()
        self.activity_chart.pack_forget()
        self.speed_chart.pack(fill=tk.BOTH, expand=True)
        self.speed_chart.show(day, samples, overspeeding_events,
                              speed_limit=self._authorised_speed_limit())

    def _show_activity_chart(self, day, is_vu, activities, day_km,
                             changes_count, driver_info, slot_schedule, markers,
                             oos_events=None, vehicle_info=None, recorded_until=None):
        self._cleanup_dashboard()
        self._hide_empty_state()
        self.table.pack_forget()
        self.speed_chart.pack_forget()
        self.activity_chart.pack(fill=tk.BOTH, expand=True)
        self.activity_chart.show(day, is_vu, activities, day_km,
                                 changes_count, driver_info, slot_schedule, markers,
                                 vehicle_info, oos_events,
                                 data=getattr(self, "_opened_data", None) or {},
                                 recorded_until=recorded_until)
