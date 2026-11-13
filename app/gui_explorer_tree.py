"""``TachoExplorer`` — the section tree: building it from a parse result and reacting to it.

Methods moved unchanged out of ``app/gui.py``; ``TachoExplorer`` inherits them
from :class:`TreeMixin`. Names the test-suite replaces on ``app.gui`` are read
through ``_live`` (see ``app.gui_base._LiveGuiNames``).
"""
from app.gui_base import (  # noqa: F401
    HIDDEN_KEYS,
    TRAILING_KEYS,
    _,
    _activity_to_iso,
    _attach_day_distance,
    _icon,
    _kv_rows,
    _live,
    _log,
    _parse_iso,
    _rows_for,
    datetime,
    detailed_speed_blocks_by_day,
    fmt_val,
    load_trace,
    os,
    recorded_until_seconds,
    report_format,
    timedelta,
    timezone,
    tk,
    traceback,
    ui_text,
)


class TreeMixin:
    """The section tree: building it from a parse result and reacting to it."""

    def _add_section(self, parent, label, columns, rows, meta="", summary=False,
                     icon=None):
        """Add a tree node for a section; *icon* names its row icon."""
        text = label
        iid = self.tree.insert(parent, tk.END, text=text,
                               image=_icon(icon, 16, self.tree) or "")
        self._payloads[iid] = (label, columns, rows, meta, summary)
        return iid

    def _add_speed_chart_day(self, parent, day, samples, oes=None):
        iid = self.tree.insert(parent, tk.END, text=day)
        self._payloads[iid] = ("__speed_chart__", day, samples, oes)
        return iid

    def _populate_detailed_speed(self, parent, data, raw_blocks):
        """Add daily UTC graph and raw-record children under Detailed Speed."""
        node = self.tree.insert(parent, tk.END, text=_("Detailed Speed"))
        self._payloads[node] = ("__speed_summary__", raw_blocks, data)
        raw_by_day = detailed_speed_blocks_by_day(
            raw_blocks, on_progress=self._pump_render)

        # Per-day overspeeding events from file data
        oes_by_day = {}
        for evt in data.get("overspeeding_events") or []:
            if not isinstance(evt, dict):
                continue
            ts = evt.get("begin", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                day_iso = dt.astimezone(timezone.utc).date().isoformat()
                oes_by_day.setdefault(day_iso, []).append(evt)
            except (ValueError, AttributeError):
                continue

        for day, samples in sorted(
                _live.detailed_speed_by_day(data, on_progress=self._pump_render).items(),
                reverse=True):
            self._pump_render()
            day_node = self._add_speed_chart_day(node, day, samples, oes_by_day.get(day))
            blocks = raw_by_day.get(day, [])
            cols, rows = _rows_for(blocks, None) if blocks else ([_("Value")], [])
            self._add_section(day_node, _("Detailed Speed {day}").format(day=day), cols, rows)

    def _add_activity_day(self, parent, day, is_vu, activities, day_km,
                          changes_count, driver_info, slot_schedule, markers,
                          oos_events=None, vehicle_info=None, recorded_until=None):
        iid = self.tree.insert(parent, tk.END, text=day)
        self._payloads[iid] = ("__activity_chart__", day, is_vu, activities,
                               day_km, changes_count, driver_info, slot_schedule,
                               markers, oos_events, vehicle_info, recorded_until)
        return iid

    @staticmethod
    def _day_vehicles_info(sessions):
        """Build the vehicles-driven summary for one day (driver cards).

        Merges sessions per plate and returns a list of dicts with the plate,
        nation and the day's first-start / last-end times. Ordered by first
        use so a multi-vehicle day reads chronologically.
        """
        by_plate = {}
        for s in sessions:
            plate = s.get("vehicle_plate") or s.get("plate", "")
            nation = s.get("vehicle_nation") or s.get("nation", "")
            entry = by_plate.setdefault(plate, {
                "plate": plate, "nation": nation,
                "start": s.get("start"), "end": s.get("end")})
            start = s.get("start")
            end = s.get("end")
            if start and (entry["start"] is None or start < entry["start"]):
                entry["start"] = start
            if end and (entry["end"] is None or end > entry["end"]):
                entry["end"] = end
        result = list(by_plate.values())
        result.sort(key=lambda e: (e["start"] is None, e["start"]))
        return result

    def _populate_daily_activities(self, parent, data, activity_list):
        """Add per-day activity timeline and raw-record children."""
        is_vu = (data.get("metadata") or {}).get("is_vu", False)
        drv = data.get("driver") or {}
        driver_name = f"{drv.get('firstname','')} {drv.get('surname','')}".strip()
        driver_info = driver_name if driver_name and driver_name != "N/A N/A" else ""
        if not driver_info:
            card = drv.get("card_number", "")
            if card and card != "N/A":
                driver_info = card
        if not driver_info:
            inserted = data.get("inserted_drivers") or []
            if inserted:
                d = inserted[0]
                dn = f"{d.get('firstname','')} {d.get('surname','')}".strip()
                driver_info = dn if dn and dn != "N/A N/A" else d.get("card_number", "")
                if driver_info and len(driver_info) > 40:
                    driver_info = driver_info[:40] + "\u2026"
        if not driver_info:
            card_recs = data.get("card_records") or []
            if card_recs:
                card_num = card_recs[0].get("card_number", "") if isinstance(card_recs[0], dict) else ""
                if card_num:
                    driver_info = card_num

        # ── Global slot_labels (default, from inserted_drivers) ──
        global_slots = {}
        # ── Per-day vehicles driven (driver cards only) ──
        vehicles_by_date = {}
        if not is_vu:
            for sess in (data.get("vehicle_sessions") or []):
                if not isinstance(sess, dict):
                    continue
                plate = (sess.get("vehicle_plate") or "").strip()
                if not plate:
                    continue
                start_dt = _parse_iso(sess.get("start"))
                end_dt = _parse_iso(sess.get("end"))
                if start_dt is None and end_dt is None:
                    continue
                # GUI-VEHICLES-PER-DAY (H-F9): a multi-day session must appear on
                # EVERY day it spans, exactly like the dashboard's gap-fill. The
                # tree's day nodes feed the SAME day-detail popup as the
                # dashboard, so anchoring on start/end alone made the two routes
                # disagree for the middle/end days.
                current = (start_dt or end_dt).date()
                last = (end_dt or start_dt).date()
                while current <= last:
                    vehicles_by_date.setdefault(current.isoformat(), []).append({
                        "plate": plate,
                        "nation": sess.get("vehicle_nation", ""),
                        "start": start_dt,
                        "end": end_dt,
                    })
                    current += timedelta(days=1)
        if is_vu:
            inserted_all = data.get("inserted_drivers") or []
            for idx, d in enumerate(inserted_all[:2]):
                slot_name = f"Slot {idx + 1}"
                name = f"{d.get('firstname','')} {d.get('surname','')}".strip()
                if not name or name == "N/A N/A":
                    name = d.get("card_number", "")
                if name:
                    global_slots[slot_name] = name
            card_recs = data.get("card_records") or []
            for idx, cr in enumerate(card_recs[:2]):
                slot_name = f"Slot {idx + 1}"
                if slot_name in global_slots:
                    continue
                card_num = cr.get("card_number", "") if isinstance(cr, dict) else ""
                if card_num:
                    global_slots[slot_name] = card_num

        # ── Gather card_iw records per ISO date ──
        iw_records = data.get("card_iw_records") or []
        # (date_iso, second, name, is_insertion) for markers
        iw_events_by_date = {}
        # (date_iso, slot, start_hhmm, end_hhmm, name) for slot schedule
        iw_schedule_by_date = {}
        for iw in iw_records:
            if not isinstance(iw, dict):
                continue
            ins_str = iw.get("insertion_time", "")
            wit_str = iw.get("withdrawal_time", "")
            if not isinstance(ins_str, str) or "T" not in ins_str:
                continue
            try:
                ins_dt = datetime.fromisoformat(ins_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            wit_dt = None
            if isinstance(wit_str, str) and "T" in wit_str:
                try:
                    wit_dt = datetime.fromisoformat(wit_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
            name = f"{iw.get('holder_first_names','')} {iw.get('holder_surname','')}".strip()
            if not name or name == "N/A N/A":
                name = ""
            if not name:
                continue
            # Authoritative slot from the record's cardSlot field (0=driver,
            # 1=co-driver). Used instead of inferring the slot from a time/name
            # heuristic, which mislabelled Slot 2 drivers' markers as Slot 1.
            raw_slot = iw.get("card_slot")
            rec_slot = None if raw_slot is None else ("Slot 2" if raw_slot else "Slot 1")
            # Clamp to day boundaries
            if wit_dt is None:
                wit_dt = ins_dt.replace(hour=23, minute=59, second=59)
            current = ins_dt
            while current.date() <= wit_dt.date():
                day_iso = current.date().isoformat()
                start_sec = ins_dt.hour * 3600 + ins_dt.minute * 60 + ins_dt.second if current.date() == ins_dt.date() else 0
                end_sec = wit_dt.hour * 3600 + wit_dt.minute * 60 + wit_dt.second if current.date() == wit_dt.date() else 86399
                sh, sm = divmod(start_sec // 60, 60)
                eh, em = divmod(end_sec // 60, 60)
                start_hhmm = f"{sh:02d}:{sm:02d}"
                end_hhmm = f"{eh:02d}:{em:02d}"
                # Markers — only on the actual insertion/withdrawal day
                if current.date() == ins_dt.date():
                    iw_events_by_date.setdefault(day_iso, []).append(
                        (start_sec, name, True, rec_slot))
                if current.date() == wit_dt.date():
                    iw_events_by_date.setdefault(day_iso, []).append(
                        (end_sec, name, False, rec_slot))
                # Schedule
                iw_schedule_by_date.setdefault(day_iso, []).append((start_hhmm, end_hhmm, name,
                                                                     ins_dt, wit_dt, rec_slot))
                current = datetime(current.year, current.month, current.day,
                                   tzinfo=timezone.utc) + timedelta(days=1)

        # Compute daily km for VU (chronological order).
        def _date_sort_key(day_data):
            date_str = str(day_data.get("date", ""))
            try:
                day, month, year = date_str.split("/")
                return (int(year), int(month), int(day))
            except (ValueError, AttributeError):
                return (0, 0, 0)
        chronological = sorted(
            [d for d in activity_list if isinstance(d, dict)], key=_date_sort_key)
        _attach_day_distance(chronological, is_vu)

        node = self.tree.insert(parent, tk.END, text=_("Daily Activities"))
        self._payloads[node] = ("__daily_summary__", activity_list, data)
        for day_data in reversed(activity_list):
            self._pump_render()
            if not isinstance(day_data, dict):
                continue
            date_str = day_data.get("date", day_data.get("timestamp", "?"))
            changes = day_data.get("changes") or []
            day_km = day_data.get("_day_km", 0)
            changes_count = (day_data.get("changes_count")
                             or len(changes))
            iso_date = _activity_to_iso(date_str)

            # ── Per-day slot resolution with time ranges ──
            day_slots = dict(global_slots) if is_vu else {}
            day_schedule = {}
            day_markers = []
            if is_vu and iso_date in iw_schedule_by_date:
                # Build activity card_inserted events: (minute, slot_label)
                act_insertions = []
                for ch in changes:
                    if isinstance(ch, dict) and ch.get("card_inserted"):
                        t = ch.get("time", "")
                        slot = ch.get("slot", "")
                        if isinstance(t, str) and ":" in t and slot:
                            try:
                                h, m = t.split(":")[:2]
                                minute = int(h) * 60 + int(m)
                                slot_label = "Slot 1" if slot == "First" else "Slot 2"
                                act_insertions.append((minute, slot_label))
                            except ValueError:
                                pass

                # For each schedule entry, match to a slot
                for entry in iw_schedule_by_date[iso_date]:
                    start_hhmm, end_hhmm, name, ins_dt, _wit_dt, rec_slot = entry
                    # Prefer the record's authoritative cardSlot; only fall back
                    # to the time/name heuristic when it is unknown.
                    slot = rec_slot or ""
                    if not slot and act_insertions:
                        ins_min = ins_dt.hour * 60 + ins_dt.minute
                        best = min(act_insertions,
                                   key=lambda ai: abs(ai[0] - ins_min),
                                   default=None)
                        if best and abs(best[0] - ins_min) <= 2:
                            slot = best[1]
                            day_slots[best[1]] = name
                    if not slot:
                        # Fallback: use slot from global assignment if name matches
                        for sk, sn in global_slots.items():
                            if name.upper() == sn.upper():
                                slot = sk
                                break
                    if not slot:
                        slot = "Slot 1"
                    day_schedule.setdefault(slot, []).append((start_hhmm, end_hhmm, name))

                # Markers from split events
                for sec, name, is_ins, rec_slot in iw_events_by_date.get(iso_date, []):
                    # Resolve slot for the marker: the record's cardSlot is
                    # authoritative; the name→schedule scan is only a fallback.
                    m_slot = rec_slot or ""
                    if not m_slot:
                        for sk, ranges in day_schedule.items():
                            for _sh, _eh, rn in ranges:
                                if rn.upper() == name.upper():
                                    m_slot = sk
                                    break
                            if m_slot:
                                break
                    day_markers.append((sec, m_slot or "Slot 1", name, is_ins))

            # ── Per-day driver_info ──
            if is_vu and day_schedule:
                all_names = sorted(set(n for ranges in day_schedule.values() for _s, _e, n in ranges))
                day_di = _("{count} drivers").format(count=len(all_names)) if all_names else ""
            else:
                day_di = driver_info if not is_vu else ""

            # Out-of-scope events for this day
            oos_events = []
            sc_conds = data.get("specific_conditions") or []
            for sc in sc_conds:
                if not isinstance(sc, dict):
                    continue
                ts = sc.get("timestamp", "")
                try:
                    sc_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    sc_day_iso = sc_dt.astimezone(timezone.utc).date().isoformat()
                except (ValueError, AttributeError):
                    continue
                if sc_day_iso != iso_date:
                    continue
                sec_of_day = sc_dt.hour * 3600 + sc_dt.minute * 60 + sc_dt.second
                cond = sc.get("condition", "")
                oos_events.append((sec_of_day, cond, sc_dt.astimezone(timezone.utc)))

            # ── Vehicles driven this day (driver cards only) ──
            day_vehicles = []
            if not is_vu:
                day_vehicles = self._day_vehicles_info(
                    vehicles_by_date.get(iso_date, []))

            day_node = self._add_activity_day(node, date_str, is_vu, changes,
                                              day_km, changes_count, day_di,
                                              day_schedule, day_markers,
                                              oos_events, day_vehicles,
                                              recorded_until_seconds(day_data))
            # A card day has no odometer reading, only its own distance
            # (Annex 1B ActivityDayDistance); a VU day carries a reading.
            # Show whichever value the row actually has, under a header that
            # says which of the two it is.
            reading = day_data.get("odometer_km")
            distance = day_data.get("day_distance_km")
            odometer = reading or distance or 0
            km_header = (_("Odometer km") if reading or distance is None
                         else _("Distance km"))
            if changes:
                rows = [[fmt_val(ev.get("time", "?")),
                         ui_text.activity(ev.get("activity", "?")),
                         fmt_val(ev.get("slot", "")) if ev.get("slot") else "",
                         fmt_val(ev.get("crew", "")),
                         fmt_val(odometer)] for ev in changes if isinstance(ev, dict)]
                cols = [_("Time"), _("Activity"), _("Slot"), _("Crew"), km_header]
            else:
                cols, rows = ([_("Time"), _("Activity")],
                              [[fmt_val("\u2014"), _("(no changes)")]])
            self._add_section(day_node, _("Daily Activities {date}").format(date=date_str),
                              cols, rows)

    def _build_file_info(self, data):
        """Return the File Info rows as a ``{label: value}`` dict.

        One builder for the two places that show the same facts: the File Info
        section (rendered through :func:`_kv_rows`) and the file overview's
        FILE / INTEGRITY blocks, which read the entries they need out of it.
        """
        meta = data.get("metadata", {})
        is_vu = meta.get("is_vu", False)
        origin = meta.get("origin", "")
        if origin == "vehicle_unit" or (not origin and is_vu):
            origin_label = _("Vehicle Unit (VU)")
        elif meta.get("origin_note"):
            origin_label = _("Driver Card (from VU download)")
        else:
            origin_label = _("Driver Card")
        info = {
            _("Filename"): os.path.basename(self.current_file),
            _("Size"): _("{count} bytes").format(
                count=f"{meta.get('file_size_bytes', 0):,}".replace(",", " ")),
            _("Origin"): origin_label,
            _("Generation"): meta.get("generation", "?"),
            _("Integrity"): self._integrity_label(data),
        }
        coverage = data.get("coverage") or {}
        if "byte_accounted_pct" in coverage:
            info[_("Byte-accounted coverage")] = (
                f"{coverage['byte_accounted_pct']}% "
                f"({coverage.get('byte_accounted_bytes', 0):,} / "
                f"{meta.get('file_size_bytes', 0):,} bytes)"
            ).replace(",", " ")
            info[_("Unknown bytes")] = (
                f"{coverage.get('unknown_bytes', 0):,} "
                f"({coverage.get('unknown_pct', 0)}%)"
            ).replace(",", " ")
            info[_("Structurally identified coverage")] = (
                f"{coverage.get('structurally_identified_pct', 0)}% "
                + _("(not a semantic decoding rate)")
            )
        if meta.get("origin_note"):
            info[_("Origin details")] = meta["origin_note"]
        if meta.get("decoder_failure_count", 0) > 0:
            info[_("Decoder failures")] = meta["decoder_failure_count"]
        info[_("Parsed at")] = meta.get("parsed_at", "")
        info[_("App version")] = meta.get("app_version", "")
        return info

    def _populate_tree(self, data):
        """Rebuild the section tree from the generations dict produced by
        :func:`build_generations_tree`.  File info, driver/vehicle summary,
        security and activities (day hierarchy) are handled separately."""
        with load_trace.span("tree_delete_previous", nodes=self._trace_node_count()):
            self.tree.delete(*self.tree.get_children())
        self._payloads.clear()
        self._auto_select_iid = None
        self._opened_data = data
        meta = data.get("metadata", {})
        # A file with many sections and days spends hundreds of milliseconds
        # here; the pumps below (and the ones inside the per-day and per-speed
        # builders) are what keeps the busy bar moving instead of freezing.
        self._pump_render()

        # ── Summary (first node: the view a freshly parsed file opens on) ──
        summary_iid = None
        try:
            cols, rows = self._build_overview_summary(data)
        except Exception:
            _log.debug("Summary section render failed: %s", traceback.format_exc())
        else:
            summary_iid = self._add_section(
                "", _("Summary"), cols, rows, summary=True, icon="summary")

        # ── File Info (key/value) ──
        is_vu = meta.get("is_vu", False)
        info = self._build_file_info(data)
        cols, rows = _kv_rows(info)
        self._add_section("", _("File Info"), cols, rows, icon="file-info")

        # ── Decoder failures detail ──
        failures = meta.get("decoder_failures") or []
        if failures:
            cols, rows = _rows_for(failures, None)
            self._add_section("", _("Decoder Failures"), cols, rows,
                              icon="status-warning")

        # The file's own structure is the base of the tree when its bytes are
        # at hand; the generation groups below are only the fallback for a
        # result without them.
        units = self._file_layout(data)

        # ── Empirical / manufacturer extensions ──
        # Data outside the regulation is SHOWN like everything else, with the
        # informational note in the section's meta line (never a warning).
        for key, label, icon in (
                *(() if units else (("vu_units", _("Decode units"), "generation"),)),
                ("co_driver_activities", _("Co-Driver Activities"), "events"),
                ("unmapped_record_types", _("Manufacturer Extensions"),
                 "status-unknown")):
            records = data.get(key) or []
            if not records:
                continue
            cols = [c for c in report_format.visible_columns(records)]
            rows = [[report_format.fmt_value(record.get(col), )
                     for col in cols] for record in records]
            self._add_section("", label, cols, rows,
                              meta=report_format.section_description(key),
                              icon=icon)

        # ── Raw / Unparsed Data (only when bytes could not be decoded) ──
        self._populate_unparsed(data)

        drv = data.get("driver", {})

        # Driver card: show holder summary. GUI-BOGUS-DRIVER (G-F8): an
        # untouched TachoResult.driver keeps every field at the literal "N/A"
        # (core/registry/models.py), which is a *truthy* string. Testing
        # ``any(drv.values())`` therefore created — and auto-selected — a
        # phantom "Driver / Cardholder" section for files with no driver data,
        # where every row read "N/A". Require a *useful* value, matching the
        # "N/A" filter _build_driver_summary already applies to the other fields.
        if not is_vu and any(v and v != "N/A" for v in drv.values()):
            cols, rows = self._build_driver_summary(data)
            self._auto_select_iid = self._add_section(
                "", _("Driver / Cardholder"), cols, rows, summary=True,
                icon="driver")

        if is_vu:
            try:
                sensor = data.get("sensor_info") or {}
                if sensor:
                    cols, rows = self._build_sensor_summary(data)
                    self._auto_select_iid = self._add_section(
                        "", _("Sensor"), cols, rows, summary=True, icon="sensor")
                else:
                    cols, rows = self._build_vehicle_summary(data)
                    self._auto_select_iid = self._add_section(
                        "", _("Vehicle"), cols, rows, summary=True, icon="vehicle")
            except Exception:
                _log.debug("Vehicle section render failed: %s", traceback.format_exc())
            trep_report = meta.get("trep_report")
            if trep_report and trep_report.get("is_partial"):
                cols, rows = self._build_trep_summary(trep_report, meta)
                self._auto_select_iid = self._add_section(
                    "", _("CORRUPTED / PARTIAL FILE"), cols, rows,
                    summary=True, icon="status-warning")

        generations = data.get("generations", {})
        if units:
            self._populate_views(data, generations)
            self._populate_structure(units)
            generations = {"Security": generations.get("Security")}

        # ── Generations tree (fallback without the file's bytes) ──
        for gen_name, gen_items in generations.items():
            if gen_name == "Security":
                continue  # handled by _populate_security
            if not isinstance(gen_items, dict) or not gen_items:
                continue

            annex_map = {
                "Generation 1": _("Annex 1B"),
                "Generation 2": _("Annex 1C"),
                "Generation 2.2": _("Annex 1C \u00b7 2023/980"),
            }
            annex = annex_map.get(gen_name, "")
            annex_suffix = f" [{annex}]" if annex else ""
            gnode = self.tree.insert(
                "", tk.END,
                text=_("{generation}{annex}").format(
                    generation=_(gen_name), annex=annex_suffix),
                image=_icon("generation", 16, self.tree) or "")

            for item_name, item_data in gen_items.items():
                self._pump_render()
                if item_name == "_RawTags":
                    continue
                if item_name in ("DriverActivityData", "Daily Activities") and isinstance(item_data, list):
                    with load_trace.span("populate_daily_activities", days=len(item_data)):
                        self._populate_daily_activities(gnode, data, item_data)
                    continue
                if item_name in ("DetailedSpeed", "Detailed Speed (0x052C)"):
                    self._populate_detailed_speed(gnode, data, item_data)
                    continue

                # Convert item to (cols, rows)
                if isinstance(item_data, list) and item_data:
                    # VU Identification is a single descriptive record: show it
                    # vertically (Field / Value) instead of one wide row.
                    if (item_name == "VU Identifications"
                            and len(item_data) == 1
                            and isinstance(item_data[0], dict)):
                        vu_id = {k: v for k, v in item_data[0].items()
                                 if k not in HIDDEN_KEYS and k not in TRAILING_KEYS
                                 and not str(k).startswith("_")}
                        cols, rows = _kv_rows(vu_id)
                    elif isinstance(item_data[0], dict):
                        cols, rows = _rows_for(item_data, None)
                    else:
                        cols, rows = ([_("Value")], [[fmt_val(v)] for v in item_data])
                elif isinstance(item_data, dict) and item_data:
                    if item_name == "ECDSA Signature Verification":
                        # certificate_temporal_validity has its own section
                        item_data = {k: v for k, v in item_data.items()
                                     if k != "certificate_temporal_validity"}
                    cols, rows = _kv_rows(item_data)
                else:
                    continue

                self._add_section(gnode, ui_text.label(item_name), cols, rows)

        # ── Security ──
        self._pump_render()
        self._populate_security(data)

        # Security section from generations tree (EF verification)
        sec = generations.get("Security") or {}
        if isinstance(sec, dict):
            for item_name, item_data in sec.items():
                if isinstance(item_data, dict) and item_data:
                    cols, rows = _kv_rows(item_data)
                    # Not the shield of the "Security & Certificates" group
                    # above: this node reports the data-integrity check, and the
                    # set's integrity glyph says so. (The overview's INTEGRITY
                    # block carries the same one, for the same reason.)
                    self._add_section("", ui_text.label(item_name),
                                      cols, rows, icon="integrity-locked")

        # The overview is the view a freshly parsed file opens on — for a card
        # and for a VU alike. It is set last on purpose: the section-specific
        # auto-selection above stays untouched and becomes the fallback for a
        # file whose overview could not be built (see the try/except at the top
        # of this method, and _parse_done's "first child" fallback), so a failed
        # overview never leaves the pane blank.
        if summary_iid and self.tree.exists(summary_iid):
            self._auto_select_iid = summary_iid

    def _populate_views(self, data, generations):
        """Daily activities and detailed speed: views over the whole file.

        They sit above the file structure, at the top level, and are built from
        the same lists the generation groups carried.
        """
        daily = speed = None
        for gen_items in (generations or {}).values():
            if not isinstance(gen_items, dict):
                continue
            for item_name, item_data in gen_items.items():
                if (daily is None and item_name in ("DriverActivityData", "Daily Activities")
                        and isinstance(item_data, list)):
                    daily = item_data
                elif speed is None and item_name in ("DetailedSpeed", "Detailed Speed (0x052C)"):
                    speed = item_data
        if daily:
            self._pump_render()
            with load_trace.span("populate_daily_activities", days=len(daily)):
                self._populate_daily_activities("", data, daily)
            self._icon_last_top_node("date-range")
        if speed:
            self._pump_render()
            self._populate_detailed_speed("", data, speed)
            self._icon_last_top_node("statistics")

    def _icon_last_top_node(self, icon):
        top = self.tree.get_children("")
        if top:
            self.tree.item(top[-1], image=_icon(icon, 16, self.tree) or "")

    def _populate_unparsed(self, data):
        """Surface bytes the structural walk could not decode.

        Shown only for corrupt/partial/non-standard files. Padding runs are
        excluded (they are expected filler, not data loss); this lists the
        "Unparsed Data" byte ranges with their file offset, length and a hex
        preview so nothing is silently hidden.
        """
        unparsed = (data.get("raw_tags") or {}).get("Unparsed Data") or []
        if not unparsed:
            return
        cov = data.get("coverage") or {}
        unknown_bytes = cov.get(
            "unknown_bytes", (cov.get("classifications") or {}).get("Unknown", 0)
        )
        total = (data.get("metadata") or {}).get("file_size_bytes", 0)
        has_container = any(isinstance(e, dict) and e.get("container")
                            for e in unparsed)
        rows = []
        for entry in unparsed:
            if not isinstance(entry, dict):
                continue
            row = [
                entry.get("offset", ""),
                fmt_val(entry.get("length", 0)),
                entry.get("data_hex", ""),
            ]
            if has_container:
                row.insert(0, entry.get("container", "file"))
            rows.append(row)
        pct = cov.get("unknown_pct", (unknown_bytes / total * 100) if total else 0)
        meta = _("{count} bytes undecoded").format(
            count=f"{unknown_bytes:,}".replace(",", " "))
        if total:
            meta += _("  \u00b7  {percent:.2f}% of file").format(percent=pct)
        # File-level coverage may report 0 unknown bytes when the undecoded
        # ranges live inside a decoded container (e.g. a VU CardDownload). Fall
        # back to the sum of the listed ranges so the count is never misleading.
        if not unknown_bytes:
            listed = sum(e.get("length", 0) for e in unparsed
                         if isinstance(e, dict))
            meta = _("{count} bytes undecoded").format(
                count=f"{listed:,}".replace(",", " "))
            if total:
                meta += _("  \u00b7  {percent:.2f}% of file").format(
                    percent=listed / total * 100)
        columns = ([ui_text.label(c) for c in ("Location", "Offset", "Length", "Hex")]
                   if has_container
                   else [ui_text.label(c) for c in ("Offset", "Length", "Hex")])
        self._add_section("", _("Raw / Unparsed Data"),
                          columns, rows, meta=meta, icon="raw-data")

    def _populate_security(self, data):
        """Security group: signature verification summaries (card EF + VU
        TREP) and decoded VU certificates."""
        sv = data.get("signature_verification")
        efv = data.get("ef_signature_verification")
        certs = data.get("certificates") or []
        cvc = data.get("vu_certificates") or []
        chip = data.get("card_chip") or {}
        icc = data.get("card_icc") or {}
        if not sv and not efv and not certs and not cvc and not chip and not icc:
            return
        gnode = self.tree.insert("", tk.END, text=_("Security & Certificates"),
                                 image=_icon("security", 16, self.tree) or "")
        if efv:
            ef_summary = {
                _("Summary"): efv.get("summary", ""),
                _("Verified"): efv.get("verified"),
                _("Failed"): efv.get("failed"),
                _("Skipped"): efv.get("skipped"),
                _("Total"): efv.get("total"),
            }
            cols, rows = _kv_rows(ef_summary)
            self._add_section(gnode, _("EF Signatures (Card Data Integrity)"), cols, rows)
            ef_results = efv.get("ef_results") or []
            if ef_results:
                cols, rows = _rows_for(ef_results, None)
                self._add_section(gnode, _("EF Signature Details"), cols, rows)
        if cvc:
            cols, rows = _rows_for(cvc, None)
            self._add_section(gnode, _("CVC Certificates (decoded)"), cols, rows,
                              meta=_("Appendix 11 \u00b7 CAR=issuing authority, "
                                     "CHR=holder, validity from TimeReal"))
        if sv:
            summary = {
                _("Available"): sv.get("available"),
                _("MSCA\u2192VU chain"): sv.get("msca_to_vu"),
                _("Anchored to ERCA root"): sv.get("root_anchored"),
                _("All TREP signatures valid"): sv.get("all_treps_valid"),
                _("Summary"): sv.get("summary", ""),
            }
            cols, rows = _kv_rows(summary)
            self._add_section(gnode, _("Signature Verification"), cols, rows)
            treps = sv.get("treps") or []
            if treps:
                cols, rows = _rows_for(treps, None)
                self._add_section(gnode, _("Section Signatures (TREP)"), cols, rows)
        if certs:
            cols, rows = _rows_for(certs, None)
            self._add_section(gnode, _("Certificates"), cols, rows)
        if chip:
            cols, rows = _kv_rows(chip)
            self._add_section(gnode, _("IC Chip (EF_ICC / EF_IC)"), cols, rows)
        if icc:
            cols, rows = _kv_rows(icc)
            self._add_section(gnode, _("ICC Identification"), cols, rows)
        for auth_key, auth_label in [("gnss_auth", "GNSS Authentication (0x960F)"),
                                      ("load_unload_auth", "Load/Unload Authentication (0x6399)")]:
            auth_data = data.get(auth_key) or []
            if auth_data:
                cols, rows = _rows_for(auth_data, None)
                self._add_section(gnode, _(auth_label), cols, rows,
                                  meta=_("BER-TLV walk \u00b7 spec Appendix 11 not public"))

    def _on_tree_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        self._open_day_detail(iid)

    def _on_tree_return(self, _event=None):
        """Return on a day node opens the day detail, like a double click.

        Every other node keeps the treeview's own Return — it opens or closes
        the row — so this handler only claims the key for the nodes that have
        a window behind them, and lets the class binding have the rest by
        *not* returning ``"break"``.
        """
        sel = self.tree.selection()
        if not sel:
            return None
        return "break" if self._open_day_detail(sel[0]) else None

    def _open_day_detail(self, iid):
        """Open the day-detail window for *iid*; ``False`` when it has none."""
        payload = self._payloads.get(iid)
        if not payload or payload[0] != "__activity_chart__":
            return False
        (day, is_vu, activities, day_km, changes_count, driver_info, slot_schedule,
         markers, oos_events, vehicle_info, *rest) = payload[1:]
        data = getattr(self, "_opened_data", None) or {}
        _live.DayDetailWindow(self, day, activities, day_km, changes_count,
                        driver_info, slot_schedule, markers, oos_events,
                        vehicle_info, data, is_vu=is_vu,
                        recorded_until=rest[0] if rest else None)
        return True

    def _on_tree_select(self, _event):
        """Tree selection → show the node's payload (timed when the load trace is on)."""
        if not load_trace.ENABLED or self._rendering:
            return self._on_tree_select_impl(_event)
        sel = self.tree.selection()
        payload = self._payloads.get(sel[0]) if sel else None
        kind = ("group" if not payload else payload[0].strip("_") if payload[0].startswith("__")
                else "summary" if len(payload) >= 5 and payload[4] else "section")
        with load_trace.span("tree_select", kind=kind):
            return self._on_tree_select_impl(_event)

    def _on_tree_select_impl(self, _event):
        """Tree selection → show the node's stored payload in the table."""
        if self._rendering:
            # A <<TreeviewSelect>> can arrive *during* a render: it pumps the
            # event loop, and a click lands in a tree that is being rebuilt.
            # The render owns the selection and sets it when it ends, so a
            # mid-render selection is ignored rather than rendered on top.
            return
        sel = self.tree.selection()
        if not sel:
            return
        payload = self._payloads.get(sel[0])
        if payload:
            if payload[0] == "__unit__":
                self._show_unit(payload[1], payload[2])
                return
            if payload[0] == "__unit_index__":
                self._show_unit_index(payload[1])
                return
            if payload[0] == "__speed_chart__":
                self._show_speed_chart(payload[1], payload[2],
                                       payload[3] if len(payload) > 3 else None)
                return
            if payload[0] == "__activity_chart__":
                self._show_activity_chart(*payload[1:])
                return
            if payload[0] == "__daily_summary__":
                self._show_daily_summary(payload[1], payload[2])
                return
            if payload[0] == "__speed_summary__":
                self._show_speed_summary(payload[1], payload[2])
                return
            if len(payload) >= 5 and payload[4]:
                label, cols, rows, meta, _unused = payload
                self._show_summary(label, cols, rows, meta)
            else:
                label, cols, rows, meta = payload[:4]
                self._show_table(label, cols, rows, meta)
        else:
            children = self.tree.get_children(sel[0])
            rows = [[self.tree.item(c, "text")] for c in children]
            self._show_table(self.tree.item(sel[0], "text").strip(),
                             [_("Sub-section")], rows)
