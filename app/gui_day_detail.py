"""Day-detail window of the GUI and the small activity/time helpers it uses.

Moved out of ``app/gui.py`` unchanged; ``app.gui`` re-exports every name, so
``app.gui.DayDetailWindow`` and the helpers keep working for callers and tests.
It depends only on the theme, the translation layer and Tk.
"""

import tkinter as tk
from app import ui_text
from app.i18n import _
from app.theme import (
    ACCENT,
    ACTIVITY_EVENT,
    FONT_BODY,
    FONT_HEADING,
    FONT_MONO,
    FONT_MONO_BOLD,
    FONT_MONO_ITALIC,
    FONT_MONO_LARGE,
    FONT_MONO_NORMAL,
    FONT_MONO_SMALL,
    FONT_PAGE_TITLE,
    FONT_SUBTITLE,
    HOVER_BG,
    LINK_BUTTON_BG,
    SLATE,
    SURFACE_ALT,
    TEXT_FAINT_TEXT,
    TEXT_SECONDARY,
    TEXT_STRONG,
    TEXT_SUBTLE,
    WHITE,
)
from core.decoders.common import get_nation, nation_full_name
from datetime import datetime, timezone
from tkinter import ttk


def _activity_to_iso(date_str):
    """Convert dd/mm/yyyy to yyyy-mm-dd for matching card_iw records."""
    try:
        day, month, year = date_str.split("/")
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except (ValueError, AttributeError):
        return date_str


def _parse_iso(value):
    """Parse an ISO-8601 timestamp string to a UTC datetime, or None."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _changes_for_slot(changes, slot_name):
    """Return the changes for one VU slot view (``"First"``/``"Second"``).

    Keeps the selected slot's changes **and** any change that carries no slot at
    all (heuristic G1 VU TREP 02 activities have no ``slot`` — see
    ``core/decoders/vu_g1.py``). Slot-less changes are treated as unassigned and
    shown in every slot view rather than being dropped, which silently zeroed
    every daily total. No slot is invented for them. The Daily-Activities
    dashboard and the day-detail view both filter through this one helper so
    they can never disagree.
    """
    return [c for c in changes
            if isinstance(c, dict) and str(c.get("slot") or "") in ("", slot_name)]


ACTIVITY_LABEL = {"DRIVE": "Drive", "WORK": "Work", "REST": "Rest",
                  "AVAILABLE": "Available", "UNKNOWN": "Unknown"}


def _act_label(activity):
    """Display name of an activity code.

    This is chart and tree chrome, not a table cell: it always follows the
    selected language. The same word inside a table obeys the "translate file
    contents" preference instead — see ``fmt_val``.
    """
    return _(ACTIVITY_LABEL.get(activity, activity))


class DayDetailWindow(tk.Toplevel):
    """Chronological log of all events for a single day (driver card / VU)."""

    _open_windows: dict[tuple, "DayDetailWindow"] = {}

    def __init__(self, parent, day, activities, day_km, changes_count,
                 driver_info, slot_schedule, markers, oos_events,
                 vehicle_info, data, is_vu=False, initial_slot=1,
                 recorded_until=None):
        # GUI-STALE-DAY-POPUP (G-F1/XG-F5): the reuse key must carry the FILE
        # identity, not just the day label. Two different files can share a
        # ``dd/mm/yyyy`` day (e.g. two downloads covering the same date); keying
        # only on the day made the second file lift the FIRST file's window and
        # show the wrong file's data under the new file's load. ``parent`` is
        # the TachoExplorer (directly, or via ``winfo_toplevel``) and carries
        # ``current_file``; tests pass a bare Tk root without it (-> None).
        key = (getattr(parent, "current_file", None), day)
        existing = DayDetailWindow._open_windows.get(key)
        if existing is not None:
            try:
                alive = bool(existing.winfo_exists())
            except tk.TclError:
                # Left over from a Tk interpreter that is already gone (an
                # in-process language restart builds a new root); it can never
                # be reused, so forget it and open a fresh window below.
                alive = False
            if alive:
                existing.lift()
                existing.focus_force()
                return
            DayDetailWindow._open_windows.pop(key, None)
        super().__init__(parent)
        self._reuse_key = key
        DayDetailWindow._open_windows[key] = self
        self.title(_("Daily Detail — {day} (UTC)").format(day=day))
        self.geometry("900x580")
        self.resizable(True, True)
        self.configure(bg=SURFACE_ALT)
        self.transient(parent)

        self._day = day
        self._day_km = day_km
        self._driver_info = driver_info
        self._vehicle_info = vehicle_info or []
        self._iso_date = _activity_to_iso(day)
        self._is_vu = is_vu
        self._data = data
        # Seconds at which the recording of this (most recent) day ends, or
        # None: the last entry then lasts until 24:00, as on every other day.
        self._recorded_until = recorded_until
        self._slot_schedule = slot_schedule or {}
        self._markers = markers or []
        self._oos_events = oos_events or []
        self._changes_count = changes_count

        # Split activities by slot (VU files have two slots) with the SAME
        # unassigned semantics as the dashboard: _changes_for_slot keeps the
        # selected slot's changes plus any change that carries no slot at all.
        # A slot-less change belongs to neither slot, is shown in BOTH tabs
        # (never invented into slot 1, never dropped), and each tab renders
        # exactly one of these lists — never slot1 + slot2 — so an unassigned
        # change visible in both tabs cannot inflate a total.
        self._act_slot1 = _changes_for_slot(activities or [], "First")
        self._act_slot2 = _changes_for_slot(activities or [], "Second")
        # Open on the slot the caller asked for (the dashboard's selected slot).
        # Both tabs always hold the full split, so the toggle can switch freely.
        self._current_slot = initial_slot if (is_vu and initial_slot == 2) else 1

        # ── Header ──
        hdr = tk.Frame(self, bg=SURFACE_ALT)
        hdr.pack(fill=tk.X, padx=14, pady=(12, 6))
        title_row = tk.Frame(hdr, bg=SURFACE_ALT)
        title_row.pack(fill=tk.X)
        tk.Label(title_row, text=_("Daily Detail"),
                 font=FONT_PAGE_TITLE, fg=TEXT_STRONG, bg=SURFACE_ALT,
                 anchor=tk.W).pack(side=tk.LEFT)
        if is_vu:
            self._slot_btn = tk.Label(title_row,
                                      text=_("Slot 2") if self._current_slot == 1 else _("Slot 1"),
                                      font=FONT_HEADING,
                                      fg=ACCENT, bg=LINK_BUTTON_BG,
                                      padx=10, pady=2,
                                      cursor="hand2", relief=tk.FLAT, bd=1)
            self._slot_btn.pack(side=tk.RIGHT)
            self._slot_btn.bind("<Enter>", lambda e: e.widget.configure(bg=HOVER_BG))
            self._slot_btn.bind("<Leave>", lambda e: e.widget.configure(bg=LINK_BUTTON_BG))
            self._slot_btn.bind("<Button-1>", lambda e: self._toggle_slot())
        else:
            self._slot_btn = None
        tk.Label(hdr, text=_("{day} (UTC)").format(day=day),
                 font=FONT_SUBTITLE, fg=TEXT_SUBTLE, bg=SURFACE_ALT,
                 anchor=tk.W).pack(anchor=tk.W, pady=(1, 6))
        self._header_info = tk.Label(hdr, text="",
                                     font=FONT_BODY, fg=SLATE, bg=SURFACE_ALT,
                                     anchor=tk.W)
        self._header_info.pack(anchor=tk.W, pady=(0, 2))
        self._refresh_header()

        # ── Body: scrolled text ──
        text_frame = ttk.Frame(self)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        scroll_y = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        scroll_x = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL)
        self.text = tk.Text(text_frame, font=FONT_MONO, wrap=tk.NONE,
                            bg=WHITE, fg=TEXT_STRONG, padx=14, pady=10,
                            yscrollcommand=scroll_y.set,
                            xscrollcommand=scroll_x.set, cursor="arrow",
                            borderwidth=1, relief=tk.SOLID)
        scroll_y.config(command=self.text.yview)
        scroll_x.config(command=self.text.xview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.pack(fill=tk.BOTH, expand=True)

        self.text.tag_configure("t_label", foreground=TEXT_STRONG,
                                font=FONT_MONO_BOLD)
        self.text.tag_configure("t_marker", foreground=TEXT_STRONG,
                                font=FONT_MONO_NORMAL)
        self.text.tag_configure("t_event", foreground=TEXT_STRONG,
                                font=FONT_MONO_ITALIC)
        self.text.tag_configure("t_sub", foreground=ACTIVITY_EVENT,
                                font=FONT_MONO_SMALL)
        self.text.tag_configure("t_hdr", foreground=TEXT_SECONDARY,
                                font=FONT_MONO_LARGE)
        self.text.tag_configure("t_time", foreground=TEXT_FAINT_TEXT,
                                font=FONT_MONO_SMALL)
        self.text.tag_configure("t_count", foreground=SLATE,
                                font=FONT_MONO_SMALL)
        self.text.tag_configure("t_odo", foreground=SLATE,
                                font=FONT_MONO_SMALL)

        self._render()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _refresh_header(self):
        info = []
        if self._driver_info:
            info.append(_("Driver: {name}").format(name=self._driver_info))
        if self._vehicle_info:
            plates = [v.get("plate", "?") for v in self._vehicle_info[:3]]
            info.append(_("Vehicle: {plates}").format(plates=", ".join(plates)))
        if self._day_km:
            info.append(_("Distance: {km} km").format(km=self._day_km))
        slot_label = _("Slot {number}").format(number=self._current_slot) if self._is_vu else ""
        n_act = len(self._act_slot1) if self._current_slot == 1 else len(self._act_slot2)
        info.append(_("{count} activity changes").format(count=n_act)
                    + (f" ({slot_label})" if slot_label else ""))
        self._header_info.config(text="  |  ".join(info))

    # ── Slot toggle ────────────────────────────────────────────────────

    def _toggle_slot(self):
        if self._current_slot == 1:
            self._current_slot = 2
            self._slot_btn.config(text=_("Slot 1"))
        else:
            self._current_slot = 1
            self._slot_btn.config(text=_("Slot 2"))
        self._refresh_header()
        self._render()

    def _render(self):
        activities = (self._act_slot1 if self._current_slot == 1
                      else self._act_slot2)
        shared = self._build_shared_timeline()
        act_timeline = self._build_activity_timeline(activities)
        timeline = act_timeline + shared
        timeline.sort(key=lambda e: (e[0], e[1]))

        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self._write_timeline(timeline)
        self._write_summary(timeline)
        self.text.config(state=tk.DISABLED)

    def _on_close(self):
        DayDetailWindow._open_windows.pop(getattr(self, "_reuse_key", None), None)
        self.destroy()

    @classmethod
    def forget_all(cls):
        """Drop every known popup from the reuse registry.

        The registry is plain Python state and outlives the Tcl interpreter that
        owned the windows, so the root must clear it when it goes away (close or
        language restart); otherwise a later window finds dead objects.
        """
        cls._open_windows.clear()

    # ── Timeline construction ──────────────────────────────────────────

    def _build_shared_timeline(self):
        """Non-activity entries shared across slots: card I/W, events, faults,
        places, conditions, overspeeding, power interruptions, border crossings,
        load/unload."""
        entries = []
        data = self._data

        # 2. Card I/W from slot_schedule (only if no card_iw_records available)
        if not (data.get("card_iw_records") or []):
            for _slot_key, ranges in (self._slot_schedule or {}).items():
                for start_hhmm, end_hhmm, name in ranges:
                    if start_hhmm:
                        sm = _hhmm_to_min(start_hhmm)
                        detail = _fmt_empty_prefix() + name
                        entries.append((sm, 500, "CARD_IN", start_hhmm,
                                        _("Card inserted"), detail, 0, ""))
                    if end_hhmm and end_hhmm != "24:00":
                        em = _hhmm_to_min(end_hhmm)
                        detail = _fmt_empty_prefix() + name
                        entries.append((em, 510, "CARD_OUT", end_hhmm,
                                        _("Card withdrawn"), detail, 0, ""))

        # Card I/W records from data
        for rec in (data.get("card_iw_records") or []):
            if not isinstance(rec, dict):
                continue
            ins_ts = rec.get("insertion_time", "")
            ins_dt = _parse_iso(ins_ts)
            if not ins_dt or ins_dt.date().isoformat() != self._iso_date:
                continue
            hhmm = ins_dt.strftime("%H:%M")
            im = _hhmm_to_min(hhmm)
            if rec.get("manual_input"):
                label = _("Manual entry")
                slot = rec.get("card_slot")
                slot_str = f"[{_('Slot 2') if slot else _('Slot 1')}]" if slot is not None else ""
                detail = _fmt_empty_prefix() + slot_str
                odo = rec.get("odometer_insertion_km")
                odo_str = str(odo) if odo else ""
                entries.append((im, 520, "MANUAL", hhmm, label,
                                detail, 0, odo_str))
            else:
                # GUI-NAME-ORDER (H-F8): render "First names Surname", as the
                # dashboard table and _populate_daily_activities already do —
                # not the reversed "Surname First names".
                name = f"{rec.get('holder_first_names','')} {rec.get('holder_surname','')}".strip()
                if not name or name == "N/A N/A":
                    name = rec.get("card_number", "") or "Unknown"
                label = _("Card inserted")
                slot = rec.get("card_slot")
                slot_str = f"[{_('Slot 2') if slot else _('Slot 1')}]" if slot is not None else ""
                detail = _fmt_empty_prefix() + f"{name} {slot_str}" if slot_str else _fmt_empty_prefix() + name
                odo = rec.get("odometer_insertion_km")
                odo_str = str(odo) if odo else ""
                entries.append((im, 490, "CARD_IN", hhmm, label,
                                detail, 0, odo_str))
            wit_ts = rec.get("withdrawal_time", "")
            if wit_ts:
                wit_dt = _parse_iso(wit_ts)
                if wit_dt and wit_dt.date().isoformat() == self._iso_date:
                    whhmm = wit_dt.strftime("%H:%M")
                    wm = _hhmm_to_min(whhmm)
                    odo = rec.get("odometer_withdrawal_km")
                    odo_str = str(odo) if odo else ""
                    entries.append((wm, 510, "CARD_OUT", whhmm,
                                    _("Card withdrawn"), "", 0, odo_str))

        # Events
        for ev in (data.get("events") or []):
            if not isinstance(ev, dict):
                continue
            begin_ts = ev.get("begin") or ev.get("begin_time") or ""
            dt = _parse_iso(begin_ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            desc = ev.get("description", _("Unknown event"))
            plate_str = ""
            plate = ev.get("vehicle_plate", "")
            if plate:
                plate_str = "  " + _("Plate: {plate}").format(plate=plate)
            detail = _fmt_empty_prefix() + desc + plate_str
            entries.append((_hhmm_to_min(hhmm), 800, "EVENT", hhmm,
                            _("Event"), detail, 0, ""))

        # Faults
        for flt in (data.get("faults") or []):
            if not isinstance(flt, dict):
                continue
            begin_ts = flt.get("begin") or flt.get("begin_time") or ""
            dt = _parse_iso(begin_ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            desc = flt.get("description", _("Unknown fault"))
            detail = _fmt_empty_prefix() + desc
            entries.append((_hhmm_to_min(hhmm), 810, "FAULT", hhmm,
                            _("Fault"), detail, 0, ""))

        # Specific conditions
        for sec_of_day, cond, _dt in (self._oos_events or []):
            hh, mm = divmod(sec_of_day, 3600)
            mm //= 60
            hhmm = f"{hh:02d}:{mm:02d}"
            label = _condition_label(cond)
            entries.append((sec_of_day // 60, 900, "CONDITION", hhmm,
                            label, "", 0, ""))

        # Places
        for pl in (data.get("places") or []):
            if not isinstance(pl, dict):
                continue
            ts = pl.get("timestamp", "")
            dt = _parse_iso(ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            entry_type = pl.get("entry_type", "")
            nation_code = pl.get("nation", "")
            if isinstance(nation_code, int):
                nation_code = get_nation(nation_code)
            country = ui_text.data_text(nation_full_name(nation_code)) if nation_code else ""
            if not country:
                country = nation_code or "Unknown"
            if entry_type == "START":
                label = _("Place: Begin")
            elif entry_type == "END":
                label = _("Place: End")
            else:
                label = _("Place")
            detail = country
            odo = pl.get("odometer_km")
            odo_str = str(odo) if odo else ""
            entries.append((_hhmm_to_min(hhmm), 850, "PLACES", hhmm,
                            label, detail, 0, odo_str))
        # VU-specific: overspeeding events
        for oe in (data.get("overspeeding_events") or []):
            if not isinstance(oe, dict):
                continue
            begin_ts = oe.get("begin") or oe.get("begin_time") or ""
            dt = _parse_iso(begin_ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            max_s = oe.get("max_speed_kmh")
            avg_s = oe.get("average_speed_kmh")
            speed_parts = []
            if max_s is not None:
                speed_parts.append(_("Max {speed} km/h").format(speed=max_s))
            if avg_s is not None:
                speed_parts.append(_("Avg {speed} km/h").format(speed=avg_s))
            speed_str = "  |  ".join(speed_parts) if speed_parts else ""
            detail = _fmt_empty_prefix() + speed_str
            entries.append((_hhmm_to_min(hhmm), 820, "OVERSPEED", hhmm,
                            _("Overspeeding"), detail, 0, ""))

        # VU-specific: power interruptions
        for pi in (data.get("power_interruptions") or []):
            if not isinstance(pi, dict):
                continue
            begin_ts = pi.get("begin") or pi.get("begin_time") or ""
            dt = _parse_iso(begin_ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            entries.append((_hhmm_to_min(hhmm), 830, "POWER", hhmm,
                            _("Power interruption"), "", 0, ""))

        # VU-specific (G2.2): border crossings
        for bc in (data.get("border_crossings") or []):
            if not isinstance(bc, dict):
                continue
            ts = bc.get("timestamp", bc.get("begin_time", ""))
            dt = _parse_iso(ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            left = bc.get("country_left", "")
            entered = bc.get("country_entered", "")
            if left and entered:
                desc = f"{left} \u2192 {entered}"
            elif left:
                desc = _("Left: {country}").format(country=left)
            elif entered:
                desc = _("Entered: {country}").format(country=entered)
            else:
                desc = ""
            odo = bc.get("odometer_km")
            odo_str = str(odo) if odo else ""
            entries.append((_hhmm_to_min(hhmm), 840, "BORDER", hhmm,
                            _("Border crossing"),
                            _fmt_empty_prefix() + desc, 0, odo_str))

        # VU-specific (G2.2): load/unload
        for lu in (data.get("load_unload_records") or []):
            if not isinstance(lu, dict):
                continue
            ts = lu.get("timestamp", "")
            dt = _parse_iso(ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            op = (lu.get("operation_type") or "").capitalize()
            odo = lu.get("odometer_km")
            odo_str = str(odo) if odo else ""
            entries.append((_hhmm_to_min(hhmm), 845, "LOADUNLD", hhmm,
                            _("Load/Unload: {operation}").format(operation=op) if op
                            else _("Load/Unload"),
                            "", 0, odo_str))

        return entries

    def _build_activity_timeline(self, activities):
        """Build timeline entries from activity changes only."""
        # Build driver presence map for VU files
        driver_by_slot = self._driver_presence() if self._is_vu else {}

        entries = []
        for i, ch in enumerate(activities):
            if not isinstance(ch, dict):
                continue
            act = (ch.get("activity") or "").upper()
            if act not in ("DRIVE", "WORK", "REST", "AVAILABLE"):
                act = "UNKNOWN"
            start_time = ch.get("time", "")
            if not isinstance(start_time, str) or ":" not in start_time:
                continue
            start_min = _hhmm_to_min(start_time)
            next_time = "24:00"
            open_ended = False
            if i + 1 < len(activities):
                nt = activities[i + 1].get("time", "")
                if isinstance(nt, str) and ":" in nt:
                    next_time = nt
            elif self._recorded_until is not None:
                # The download's most recent day: the recording ends here, so
                # the last entry's duration is unknown rather than "until
                # midnight" (core.utils.activity_stats._cut_at).
                cut_min = self._recorded_until // 60
                if cut_min > start_min:
                    next_time = f"{cut_min // 60:02d}:{cut_min % 60:02d}"
                else:
                    open_ended = True
            end_min = _hhmm_to_min(next_time)
            dur_min = max(0, end_min - start_min)
            if dur_min <= 0 and not open_ended:
                continue
            dur_str = _format_duration(dur_min) if not open_ended else "\u2014"

            slot = ch.get("slot", "")
            crew = ch.get("crew", False)
            card_in = ch.get("card_inserted", True)
            time_range = (f"{start_time} \u2192 ?" if open_ended
                          else f"{start_time} \u2192 {next_time}")
            detail = _fmt_range_dur(time_range, dur_str)

            # Driver / slot info
            if self._is_vu:
                slot_key = 0 if self._current_slot == 1 else 1
                active_name = self._find_driver(start_min, driver_by_slot.get(slot_key, []))
                if active_name:
                    detail += active_name
                elif not card_in:
                    detail += _("No card present")
                else:
                    detail += _("Slot {number}").format(number=self._current_slot)
                if crew and active_name:
                    detail += "  " + _("Crew")
            else:
                if slot and slot != "First":
                    detail += _("Slot {number}").format(number=slot)
                if crew:
                    detail += "  " + _("Crew")
                if not card_in:
                    detail += "  " + _("No card present")

            entries.append((start_min, 1000, act, start_time,
                            _activity_label(act), detail, dur_min, ""))

            if not card_in:
                entries.append((start_min, 999, "CARD_OUT", start_time,
                                _("Card not inserted"),
                                _("Card absent from the tachograph as of {time}").format(time=start_time),
                                0, ""))
        return entries

    def _driver_presence(self):
        """Build {slot: [(start_min, end_min, name), ...]} from card_iw_records."""
        result = {}
        for rec in (self._data.get("card_iw_records") or []):
            if not isinstance(rec, dict):
                continue
            ins_dt = _parse_iso(rec.get("insertion_time", ""))
            if not ins_dt or ins_dt.date().isoformat() != self._iso_date:
                continue
            # GUI-NAME-ORDER (H-F8): "First names Surname", not reversed.
            name = f"{rec.get('holder_first_names','')} {rec.get('holder_surname','')}".strip()
            if not name or name == "N/A N/A":
                name = rec.get("card_number", "") or "Unknown"
            start_min = ins_dt.hour * 60 + ins_dt.minute
            wit_dt = _parse_iso(rec.get("withdrawal_time", "") or "")
            if wit_dt and wit_dt.date().isoformat() == self._iso_date:
                end_min = wit_dt.hour * 60 + wit_dt.minute
            else:
                end_min = 1440
            slot = rec.get("card_slot", 0)
            result.setdefault(slot, []).append((start_min, end_min, name))
        return result

    @staticmethod
    def _find_driver(minute, ranges):
        for start_min, end_min, name in ranges:
            if start_min <= minute < end_min:
                return name
        return None

    # ── Write to Text widget ───────────────────────────────────────────

    def _write_timeline(self, timeline):
        ACTIVITY_KINDS = {"DRIVE", "WORK", "REST", "AVAILABLE", "UNKNOWN"}
        LABEL_W = 22
        LABEL_W = 22

        if not timeline:
            self.text.insert(tk.END, _("No data for this day.\n"), "t_sub")
            return

        self.text.insert(tk.END, _("Activity Timeline\n"), "t_hdr")

        for entry in timeline:
            if len(entry) < 8:
                continue
            _sk, _rk, kind, time_str, label, detail, _dur, odo_str = entry
            is_activity = kind in ACTIVITY_KINDS
            display_label = label if is_activity else f"\u2014\u2014 {label}"
            padded = display_label.ljust(LABEL_W)

            prefix = f"  {time_str}  {padded}"
            body = f"{detail}"

            line = f"{prefix}{body}\n"
            self.text.insert(tk.END, line)

            # Italic for events/faults
            if kind in ("EVENT", "FAULT"):
                line_start = self.text.index(tk.END + "-1c linestart")
                label_start = f"{line_start} + {len(f'  {time_str}  ')}c"
                label_end = f"{line_start} + {len(prefix)}c"
                self.text.tag_add("t_event", label_start, label_end)

    def _write_summary(self, timeline):
        self.text.insert(tk.END, "\n")
        self.text.insert(tk.END,
                         "\u2500" * 52 + "\n", "t_sub")
        self.text.insert(tk.END, _("Summary\n"), "t_hdr")

        totals = {"DRIVE": 0, "WORK": 0, "REST": 0, "AVAILABLE": 0, "UNKNOWN": 0}
        for entry in timeline:
            if len(entry) < 8:
                continue
            _sk, _rk, kind, _t, _l, _d, dur, _odo = entry
            if kind in totals:
                totals[kind] += dur

        for act, label in [("DRIVE", _("Drive")), ("WORK", _("Work")),
                           ("AVAILABLE", _("Available")), ("REST", _("Rest"))]:
            self.text.insert(tk.END,
                             f"  {label:12s} {_format_duration(totals[act])}\n",
                             f"t_{act}")

        counts = [
            (_("Events"), "EVENT"), (_("Faults"), "FAULT"),
            (_("Conditions"), "CONDITION"), (_("Places"), "PLACES"),
            (_("Overspeeding"), "OVERSPEED"), (_("Power interruptions"), "POWER"),
            (_("Border crossings"), "BORDER"), (_("Load/Unload"), "LOADUNLD"),
            (_("Manual entries"), "MANUAL"),
        ]
        self.text.insert(tk.END, "\n")
        for label, kind in counts:
            n = sum(1 for entry in timeline if entry[2] == kind)
            if n > 0 or kind in ("EVENT", "FAULT", "CONDITION", "PLACES", "MANUAL"):
                self.text.insert(tk.END,
                                 f"  {label:20s} {n}\n",
                                 "t_count")

        card_in_times = sorted({e[0] for e in timeline if e[2] == "CARD_IN"})
        card_out_times = sorted({e[0] for e in timeline if e[2] == "CARD_OUT"})
        act_entries = [e for e in timeline
                       if e[2] in ("DRIVE", "WORK", "REST", "AVAILABLE")]
        act_card_present = sorted({e[0] for e in act_entries})

        # G-F3/XG-F8: only *estimate* a card-presence window when the timeline
        # carries no explicit "Card not inserted" marker, and end that window at
        # the END of the last activity (start + duration), never at its start.
        card_explicitly_absent = any(
            e[2] == "CARD_OUT" and e[4] == _("Card not inserted") for e in timeline)
        if not card_in_times and act_card_present and not card_explicitly_absent:
            card_in_times = [act_card_present[0]]
            card_out_times = [max(e[0] + e[6] for e in act_entries)]

        if card_in_times:
            h1, m1 = divmod(card_in_times[0], 60)
            h2, m2 = divmod(card_out_times[-1] if card_out_times else 1440, 60)
            self.text.insert(tk.END,
                             _("  Card present: {from_time} \u2013 {to_time}\n").format(
                                 from_time=f"{h1:02d}:{m1:02d}",
                                 to_time=f"{h2:02d}:{m2:02d}"),
                             "t_count")


# Column widths for timeline detail line (used by both activity and shared builders)
_DETAIL_RANGE = 15   # "00:00 → 04:15  "


_DETAIL_DUR   = 12   # "(4h 15m)     "  


def _fmt_range_dur(time_range, dur_str):
    """Return the range+duration prefix with fixed column widths."""
    return time_range.ljust(_DETAIL_RANGE) + f"({dur_str})".ljust(_DETAIL_DUR)


def _fmt_empty_prefix():
    """Return empty range+duration reserved space for non-activity lines."""
    return " " * _DETAIL_RANGE + " " * _DETAIL_DUR


def _hhmm_to_min(s):
    try:
        h, m = s.split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def _format_duration(minutes):
    h, m = divmod(minutes, 60)
    if h == 0:
        return f"{m}m"
    return f"{h}h {m:02d}m"


def _activity_label(act):
    return _act_label(act)


def _condition_label(cond):
    m = {
        "1": _("Out of scope \u2014 Begin"),
        "2": _("Out of scope \u2014 End"),
        "3": _("Ferry / Train \u2014 Begin"),
        "4": _("Ferry / Train \u2014 End"),
        "OutOfScope Begin": _("Out of scope \u2014 Begin"),
        "OutOfScope End": _("Out of scope \u2014 End"),
        "Ferry/Train crossing": _("Ferry / Train crossing"),
        "FerryTrain Begin": _("Ferry / Train \u2014 Begin"),
        "FerryTrain End": _("Ferry / Train \u2014 End"),
    }
    return m.get(str(cond), _("Condition: {condition}").format(condition=cond))
