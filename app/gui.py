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

import os
import sys
import re
import json
import queue
import threading
import traceback
import logging
from bisect import bisect_left
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    """
    if sys.platform == "win32" and _WIN_SCALE > 1.0:
        return int(round(value * _WIN_SCALE))
    return int(value)

import tkinter as tk  # noqa: E402
from tkinter import ttk, filedialog, messagebox  # noqa: E402

from app.engine import TachoParser  # noqa: E402
from core.utils.encoding import BytesEncoder  # noqa: E402

from core.utils.version import __version__  # noqa: E402
from core.utils.report_format import fmt_scalar, humanize_key, visible_columns  # noqa: E402
from core.decoders.common import nation_full_name, get_nation  # noqa: E402

_log = logging.getLogger("tacho_gui")

try:
    from app.export import ExportManager
except ImportError:
    ExportManager = None  # type: ignore[assignment,misc]


# ── Palette ────────────────────────────────────────────────────────────────

GEN_COLORS = {
    "G1 (Digital)": "#2e7d32",
    "G2 (Smart)": "#1565c0",
    "G2.2 (Smart V2)": "#6a1b9a",
    "Unknown": "#757575",
}

ROW_EVEN = "#ffffff"
ROW_ODD = "#f2f6fb"
HEADER_BG = "#e3e9f2"

# Internal keys to hide from columns (service noise). Keys starting with "_"
# (e.g. "_key" dedup markers) are always hidden — see _columns_for.
HIDDEN_KEYS = {"source", "raw_tail_hex", "name", "size", "confidence"}
# Descriptive columns pushed to table start.
LEADING_KEYS = ["description", "purpose", "control_type_label", "calibration_purpose_label"]
# Technical columns pushed to table end.
TRAILING_KEYS = ["record_type"]
SPEED_LIMIT_KMH = 90


# ── Section definitions ──
# The tree is now driven directly by :func:`build_generations_tree` output.
# See ``_populate_tree`` and ``core/registry/models.py``.


# ── Value formatting ───────────────────────────────────────────────────────



def _fmt_coords(lat, lon):
    if lat is None or lon is None:
        return ""
    return f"{lat:.5f}, {lon:.5f}"


def _fmt_dict(d):
    """Readable summary of known tachograph nested structures."""
    # Card slot absent
    if d.get("present") is False:
        return "\u2014"
    # GNSS coordinates (gnss_place → geo, or direct geo)
    geo = d.get("geo") if isinstance(d.get("geo"), dict) else None
    if geo and ("latitude_deg" in geo or "longitude_deg" in geo):
        return _fmt_coords(geo.get("latitude_deg"), geo.get("longitude_deg"))
    if "latitude_deg" in d or "longitude_deg" in d:
        return _fmt_coords(d.get("latitude_deg"), d.get("longitude_deg"))
    # Card number (FullCardNumber) — empty number means no card in slot
    if "card_number" in d:
        return str(d["card_number"]).strip() or "—"
    # Vehicle registration
    if "plate" in d:
        plate = (d.get("plate") or "").strip() if d.get("plate") is not None else ""
        nation = (d.get("nation") or "").strip() if d.get("nation") is not None else ""
        if not plate or set(plate) <= {"?"}:
            return "\u2014"
        return f"{nation} {plate}".strip() if "No information" not in nation else plate
    # Compact generic fallback
    items = ", ".join(f"{k}={fmt_val(val)}" for k, val in d.items())
    return items if len(items) <= 120 else items[:120] + "\u2026"


def fmt_val(v, key=None):
    """Render any parser value for display: booleans as Yes/No, floats
    trimmed, large ints with thousands spaces, 0xFFFFFF sentinels as N/A,
    bytes as hex, ISO timestamps shortened, dicts/lists flattened. Nation
    code columns are expanded to the full English country name."""
    if isinstance(v, dict):
        return _fmt_dict(v)
    if isinstance(v, list):
        if not v:
            return ""
        if all(not isinstance(x, (dict, list)) for x in v):
            return ", ".join(fmt_val(x) for x in v)
        return f"[{len(v)} items]"
    return fmt_scalar(v, key=key, include_code_label=True)


def _columns_for(records, transformer):
    """Derive column order from the union of record keys."""
    if transformer:
        sample = transformer(records[0])
        if isinstance(sample, list):
            sample = sample[0]
        return list(sample.keys())
    # Reversed leading keys preserve this view's historical front-insertion
    # order while the shared helper performs visibility filtering.
    return visible_columns(
        records,
        hidden_keys=HIDDEN_KEYS,
        leading_keys=tuple(reversed(LEADING_KEYS)),
        trailing_keys=TRAILING_KEYS,
        value_column_for_non_dict=True,
    )


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
    # Transformer output keys are already display labels; raw record keys are
    # humanised + translated for display (rows above keep the raw key order).
    headers = cols if transformer else [humanize_key(c) for c in cols]
    return headers, rows


def _kv_rows(d):
    """Convert a dict to (Field, Value) rows, flattening nested dicts one level."""
    rows = []
    for k, v in d.items():
        field = humanize_key(k) if isinstance(k, str) else str(k)
        if isinstance(v, dict) and v:
            for sk, sv in v.items():
                subfield = f"{field} \u203a {humanize_key(sk) if isinstance(sk, str) else str(sk)}"
                rows.append([subfield, fmt_val(sv, key=sk)])
        else:
            rows.append([field, fmt_val(v, key=k)])
    return (["Field", "Value"], rows)


def _utc_speed_block(block):
    """Return a block's UTC start and raw samples, or ``None`` if invalid."""
    if not isinstance(block, dict):
        return None
    timestamp = block.get("timestamp") or block.get("begin")
    samples = block.get("_chart_speeds_kmh", block.get("speeds_kmh"))
    if not isinstance(timestamp, str) or not isinstance(samples, list):
        return None
    try:
        start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (start.replace(tzinfo=timezone.utc) if start.tzinfo is None
            else start.astimezone(timezone.utc)), samples


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


def _compute_activity_totals(changes):
    """Return dict {ACTIVITY: total_minutes} from a list of activity changes.

    Changes are grouped per card slot (driver) first, so crew days (two
    drivers recording simultaneously in slots ``First``/``Second``) keep
    their timelines independent.

    Drive/Work durations are summed across slots (each driver accumulates
    independently).  Rest/Available durations are kept at the **maximum**
    across slots because they share the same 24h day and cannot exceed it.
    """
    ACCUM_BY_SUM = {"DRIVE", "WORK"}
    per_slot: dict[str, dict[str, int]] = {}
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        t = ActivityTimelineChart._parse_time(ch.get("time", ""))
        act = str(ch.get("activity", "")).upper()
        if t is not None and act in ACTIVITY_COLORS:
            slot = str(ch.get("slot") or "First")
            per_slot.setdefault(slot, []).append((t, act))

    totals = {a: 0 for a in ACTIVITY_COLORS}
    for parsed in per_slot.values():
        parsed.sort(key=lambda item: item[0])
        slot_tot: dict[str, int] = {}
        for i, (start, act) in enumerate(parsed):
            end = parsed[i + 1][0] if i + 1 < len(parsed) else 86400
            slot_tot[act] = slot_tot.get(act, 0) + (end - start) // 60
        for act, mins in slot_tot.items():
            if act in ACCUM_BY_SUM:
                totals[act] += mins
            else:
                if mins > totals[act]:
                    totals[act] = mins
    return totals


def _fmt_duration_minutes(mins):
    """Render a minute count as 'Xh Ym'."""
    return f"{mins // 60}h {mins % 60:02d}m"


def detailed_speed_by_day(data):
    """Return UTC detailed-speed samples grouped by ISO date."""
    grouped = {}
    blocks = list(data.get("speed_blocks") or [])
    for block in blocks:
        decoded = _utc_speed_block(block)
        if decoded is None:
            continue
        start, samples = decoded
        for offset, speed in enumerate(samples):
            if not isinstance(speed, int) or speed == 0xFF:
                continue
            moment = start + timedelta(seconds=offset)
            day = moment.date().isoformat()
            grouped.setdefault(day, {})[moment.hour * 3600 + moment.minute * 60 + moment.second] = speed
    return {day: sorted(samples.items()) for day, samples in grouped.items()}


def detailed_speed_blocks_by_day(blocks):
    """Group raw records by every UTC day for which they contain a sample."""
    grouped = {}
    for block in blocks if isinstance(blocks, list) else []:
        decoded = _utc_speed_block(block)
        if decoded is None:
            continue
        start, samples = decoded
        days = set()
        for offset, speed in enumerate(samples):
            if isinstance(speed, int) and speed != 0xFF:
                days.add((start + timedelta(seconds=offset)).date().isoformat())
        for day in days:
            grouped.setdefault(day, []).append(block)
    return grouped





# ── Excel-style data table ─────────────────────────────────────────────────

class DataTable(ttk.Frame):
    """Header-only treeview: grid with sortable columns and filter."""

    def __init__(self, parent):
        super().__init__(parent)

        head = ttk.Frame(self)
        head.pack(fill=tk.X, padx=8, pady=(8, 2))
        self.title_lbl = ttk.Label(head, text="", font=("", 13, "bold"))
        self.title_lbl.pack(side=tk.LEFT)
        self.count_lbl = ttk.Label(head, text="", foreground="gray")
        self.count_lbl.pack(side=tk.LEFT, padx=(8, 0))
        filt = ttk.Frame(self)
        self.filt_bar = filt
        filt.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(filt, text="\U0001f50e").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._schedule_filter())
        self.filter_entry = ttk.Entry(filt, textvariable=self.filter_var)
        self.filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.tv = ttk.Treeview(body, show="headings", selectmode="browse")
        ysb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.tv.yview)
        xsb = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.tv.xview)
        self.tv.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self.tv.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.tv.tag_configure("even", background=ROW_EVEN)
        self.tv.tag_configure("odd", background=ROW_ODD)
        self.tv.tag_configure("summary_header",
                              font=("", 10, "bold"),
                              background="#e3e9f2")

        self._cols = []
        self._all_rows = []
        self._sort_state = {}
        self._fit_after_id = None
        self._filter_after_id = None
        self._fitted = False
        # When True the table shows a fixed-width summary (Field/Value) and the
        # content-proportional auto-fit must never run, or a late <Configure>
        # timer would resize its columns inconsistently between visits.
        self._summary_mode = False

        self.tv.bind("<Configure>", lambda e: self._schedule_fit())

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
            text=f"{len(rows)} rows \u00b7 {len(columns)} columns"
            + (f"   \u2014   {meta}" if meta else ""))
        self.filter_var.set("")

        self._cols = list(columns)
        self._all_rows = [list(r) for r in rows]
        self._sort_state = {}
        self._fitted = False
        self._summary_mode = False

        self.tv["columns"] = self._cols
        for c in self._cols:
            self.tv.heading(c, text=str(c),
                            command=lambda col=c: self._sort_by(col))
            min_w = max(len(str(c)) * _px(9) + _px(24), _px(60))
            self.tv.column(c, minwidth=min_w, anchor=tk.W, stretch=False)

        self._render(self._all_rows)
        self.tv.update_idletasks()
        self._fit_columns()
        self.tv.update()
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

    def _render(self, rows, summary=False):
        self.tv.delete(*self.tv.get_children())
        for i, r in enumerate(rows):
            if summary and len(r) >= 3 and r[2]:
                tag = "summary_header"
                vals = list(r[:2])
            else:
                tag = "even" if i % 2 == 0 else "odd"
                vals = list(r)
            self.tv.insert("", tk.END, values=vals, tags=(tag,))

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
        """Toggle-sort by column; dd/mm/yyyy dates sort chronologically and
        numeric strings numerically, everything else alphabetically."""
        idx = self._cols.index(col)
        descending = self._sort_state.get(col, False)
        date_re = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

        def key(row):
            v = row[idx] if idx < len(row) else ""
            s = str(v)
            m = date_re.match(s)
            if m:  # dd/mm/yyyy → chronological
                return (0, int(m.group(3)) * 10000 + int(m.group(2)) * 100 + int(m.group(1)))
            try:
                # thousands are rendered with spaces (fmt_val)
                num = float(s.replace(" ", "").replace(",", "."))
                return (0, num)
            except (ValueError, TypeError):
                return (1, s.lower())

        self._all_rows.sort(key=key, reverse=descending)
        self._sort_state[col] = not descending
        for c in self._cols:
            self.tv.heading(c, text=str(c) + (" \u25be" if c == col and descending
                                              else " \u25b4" if c == col else ""))
        self._apply_filter()


class DetailedSpeedChart(ttk.Frame):
    """Canvas chart for one UTC day of per-second speed samples."""

    def __init__(self, parent):
        super().__init__(parent)
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=8, pady=(8, 2))
        self.title_lbl = ttk.Label(header, font=("", 13, "bold"))
        self.title_lbl.pack(side=tk.LEFT)
        self.zoom_in_btn = ttk.Button(header, text="+", width=3, command=self._zoom_in)
        self.zoom_in_btn.pack(side=tk.RIGHT)
        self.zoom_out_btn = ttk.Button(header, text="-", width=3, command=self._zoom_out)
        self.zoom_out_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 2))
        self.canvas.bind("<Configure>", lambda _event: self._schedule_draw())
        self.canvas.bind("<Motion>", self._show_hover)
        self.canvas.bind("<Leave>", lambda _event: self.canvas.delete("speed_hover"))
        self.canvas.bind("<ButtonPress-1>", self._start_selection)
        self.canvas.bind("<B1-Motion>", self._extend_selection)
        self.canvas.bind("<ButtonRelease-1>", self._finish_selection)
        self.summary_lbl = ttk.Label(self, foreground="gray", anchor=tk.W)
        self.summary_lbl.pack(fill=tk.X, padx=8, pady=(2, 8))
        self._day = ""
        self._samples = []
        self._sample_seconds = []
        self._plot = None
        self._view_start = 0
        self._view_end = 86400
        self._selection_start = None
        self._selection_moved = False
        self._y_scale = None
        self._draw_after_id = None
        self._overspeeding_events = []
        self._oes_dots = []
        self._speed_limit = SPEED_LIMIT_KMH

    def show(self, day, samples, overspeeding_events=None, speed_limit=None):
        self._day = day
        self._speed_limit = speed_limit or SPEED_LIMIT_KMH
        self._samples = samples
        self._sample_seconds = [second for second, _ in samples]
        self._view_start, self._view_end = 0, 86400
        self._selection_start = None
        self._selection_moved = False
        self._overspeeding_events = overspeeding_events or []
        speeds = [speed for _, speed in samples]
        recorded = len(speeds)
        moving = sum(speed > 0 for speed in speeds)
        above_limit = sum(speed > self._speed_limit for speed in speeds)
        internal_gaps = sum(max(0, second - previous - 1)
                            for (previous, _), (second, _) in zip(samples, samples[1:], strict=False))
        self.title_lbl.config(text=f"Detailed Speed - {day} (UTC)")
        self.summary_lbl.config(
            text=(f"{recorded:,} s recorded | max {max(speeds)} km/h | "
                  f"avg {sum(speeds) / recorded:.1f} km/h | "
                  f"{above_limit // 60} min above {self._speed_limit} km/h | "
                  f"{moving // 60} min moving | {internal_gaps // 60} min internal gaps")
            if speeds else "No valid speed samples")
        self._schedule_draw()

    def _zoom_in(self):
        self._set_zoom((self._view_start + self._view_end) / 2, (self._view_end - self._view_start) / 2)

    def _zoom_out(self):
        self._set_zoom((self._view_start + self._view_end) / 2, (self._view_end - self._view_start) * 2)

    def _set_zoom(self, center, span):
        """Set a bounded UTC view window; 60 seconds is the closest zoom."""
        span = min(86400, max(60, span))
        start = max(0, min(center - span / 2, 86400 - span))
        self._view_start, self._view_end = start, start + span
        self._schedule_draw()

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
        # The 90 km/h label needs enough dedicated y-axis space on all scales.
        left, right, top, bottom = 76, 18, 28, height - 34
        plot_width, plot_height = width - left - right, bottom - top
        first = bisect_left(self._sample_seconds, self._view_start)
        last = bisect_left(self._sample_seconds, self._view_end)
        visible_samples = self._samples[first:last]
        speeds = [speed for _, speed in visible_samples]
        max_speed = max(speeds, default=self._speed_limit)
        ceiling = max(100, ((max_speed + 19) // 20) * 20)

        def y_for(speed):
            return bottom - speed * plot_height / ceiling

        self._plot = (left, right, top, bottom, plot_width, self._view_start, self._view_end)
        self._y_scale = (bottom, ceiling, plot_height)

        for value in (0, self._speed_limit, ceiling):
            y = y_for(value)
            color = "#d32f2f" if value == self._speed_limit else "#d9e1ea"
            dash = (4, 3) if value == self._speed_limit else None
            canvas.create_line(left, y, width - right, y, fill=color, dash=dash)
            label = f"{value} km/h" if value == self._speed_limit else str(value)
            canvas.create_text(left - 7, y, text=label, anchor=tk.E, fill=color)

        span = self._view_end - self._view_start
        tick_step = self._tick_step(span)
        first_tick = int(self._view_start // tick_step) * tick_step
        for second in range(first_tick, int(self._view_end) + tick_step, tick_step):
            if second < self._view_start or second > self._view_end:
                continue
            x = left + plot_width * (second - self._view_start) / span
            canvas.create_line(x, top, x, bottom, fill="#edf1f5")
            canvas.create_text(x, bottom + 16, text=self._time_label(second, span), anchor=tk.N,
                               fill="#536273")
        canvas.create_text(left, 10, text="Speed (km/h)", anchor=tk.W, fill="#536273")

        # Aggregate to screen pixels. Missing pixels remain blank, so chart
        # resolution never invents a continuous speed trace across a gap.
        bins = {}
        for second, speed in visible_samples:
            x = int(left + (second - self._view_start) * plot_width / span)
            total, count, low, high = bins.get(x, (0, 0, speed, speed))
            bins[x] = (total + speed, count + 1, min(low, speed), max(high, speed))
        previous_x = None
        previous_y = None
        for x in sorted(bins):
            total, count, low, high = bins[x]
            average_y = y_for(total / count)
            color = "#c62828" if high > self._speed_limit else "#1565c0"
            canvas.create_line(x, y_for(low), x, y_for(high), fill=color)
            if previous_x is not None and x == previous_x + 1:
                canvas.create_line(previous_x, previous_y, x, average_y, fill="#1565c0")
            previous_x, previous_y = x, average_y

        # Overspeed zone shading (stipple)
        overspeed_runs = []
        run_start = None
        for second, speed in visible_samples:
            if speed > self._speed_limit:
                if run_start is None:
                    run_start = second
            else:
                if run_start is not None:
                    overspeed_runs.append((run_start, second))
                    run_start = None
        if run_start is not None:
            overspeed_runs.append((run_start, visible_samples[-1][0]))
        for rs_start, rs_end in overspeed_runs:
            x0 = left + (rs_start - self._view_start) * plot_width / span
            x1 = left + (rs_end - self._view_start) * plot_width / span
            if x1 - x0 < 1:
                continue
            canvas.create_rectangle(x0, top, x1, bottom,
                                    fill="#ffcdd2", outline="", stipple="gray25",
                                    tags="speed_overspeed")

        # Overspeeding event markers (red dots from file data)
        self._oes_dots = []
        for evt in self._overspeeding_events:
            ts = evt.get("begin", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                sec_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second
            except (ValueError, AttributeError):
                continue
            if sec_of_day < self._view_start or sec_of_day > self._view_end:
                continue
            x = left + (sec_of_day - self._view_start) * plot_width / span
            y_center = y_for(evt.get("max_speed_kmh", ""))
            r = 4
            canvas.create_oval(x - r, y_center - r, x + r, y_center + r,
                               fill="#d32f2f", outline="#ffffff", width=1,
                               tags="speed_oes")
            self._oes_dots.append((x, y_center, evt))

    @staticmethod
    def _tick_step(span):
        if span >= 43200:
            return 10800
        if span >= 14400:
            return 3600
        if span >= 7200:
            return 1800
        if span >= 3600:
            return 900
        if span >= 1800:
            return 300
        if span >= 600:
            return 60
        return 30

    @staticmethod
    def _time_label(second, span):
        hours, remainder = divmod(int(second), 3600)
        minutes, seconds = divmod(remainder, 60)
        return (f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                if span < 600 else f"{hours:02d}:{minutes:02d}")

    def _show_hover(self, event):
        """Show the closest recorded sample under the cursor in UTC."""
        if not self._plot or not self._samples:
            return
        left, _right, top, bottom, plot_width, view_start, view_end = self._plot
        if not left <= event.x <= left + plot_width or not top <= event.y <= bottom:
            self.canvas.delete("speed_hover")
            return

        # Check overspeeding event dots first
        for ox, oy, evt in self._oes_dots:
            if abs(event.x - ox) <= 8 and abs(event.y - oy) <= 8:
                b = evt.get("begin", "")[:16]
                e = evt.get("end", "")[:16]
                mx = evt.get("max_speed_kmh", "?")
                av = evt.get("average_speed_kmh", "?")
                cd = evt.get("card_driver", {})
                drv = ""
                if isinstance(cd, dict):
                    drv = (cd.get("card_number") or "").strip()
                text = f"Overspeeding: {b} \u2192 {e} | max {mx} | avg {av}"
                if drv:
                    text += f" | {drv}"
                self.canvas.delete("speed_hover")
                label_x = min(event.x + 12, self.canvas.winfo_width() - 290)
                label_y = max(event.y - 24, 4)
                text_id = self.canvas.create_text(label_x, label_y, text=text,
                                                  anchor=tk.NW, fill="#17212b",
                                                  tags="speed_hover")
                x1, yb1, x2, yb2 = self.canvas.bbox(text_id)
                bg = self.canvas.create_rectangle(x1 - 5, yb1 - 3, x2 + 5, yb2 + 3,
                                                  fill="#fffde7", outline="#9e9e9e",
                                                  tags="speed_hover")
                self.canvas.tag_lower(bg, text_id)
                return

        span = view_end - view_start
        target_second = round(view_start + (event.x - left) * span / plot_width)
        index = bisect_left(self._sample_seconds, target_second)
        candidates = self._samples[max(0, index - 1):index + 1]
        if not candidates:
            return
        second, speed = min(candidates, key=lambda sample: abs(sample[0] - target_second))
        # At day scale, one screen pixel represents several seconds. Do not
        # pretend a distant sample belongs to a long unrecorded gap.
        if abs(second - target_second) > max(2, round(span / plot_width) * 2):
            self.canvas.delete("speed_hover")
            return
        hours, remainder = divmod(second, 3600)
        minutes, seconds = divmod(remainder, 60)
        text = f"{hours:02d}:{minutes:02d}:{seconds:02d} UTC  |  {speed} km/h"
        self.canvas.delete("speed_hover")
        if self._y_scale:
            dot_y, dot_ceiling, dot_h = self._y_scale
            dot_x = left + (second - view_start) * plot_width / (view_end - view_start)
            dot_py = dot_y - speed * dot_h / dot_ceiling
            r = 4
            self.canvas.create_oval(dot_x - r, dot_py - r, dot_x + r, dot_py + r,
                                    fill="#c62828" if speed > self._speed_limit else "#1565c0",
                                    outline="#ffffff", width=1, tags="speed_hover")
        label_x = min(event.x + 12, self.canvas.winfo_width() - 190)
        label_y = max(event.y - 24, 4)
        text_id = self.canvas.create_text(label_x, label_y, text=text, anchor=tk.NW,
                                          fill="#17212b", tags="speed_hover")
        x1, y1, x2, y2 = self.canvas.bbox(text_id)
        background = self.canvas.create_rectangle(x1 - 5, y1 - 3, x2 + 5, y2 + 3,
                                                  fill="#fffde7", outline="#9e9e9e",
                                                  tags="speed_hover")
        self.canvas.tag_lower(background, text_id)

    def _start_selection(self, event):
        if not self._plot:
            return
        left, _right, top, bottom, _width, _start, _end = self._plot
        if left <= event.x <= self.canvas.winfo_width() - 18 and top <= event.y <= bottom:
            self._selection_start = event.x
            self._selection_moved = False
            self.canvas.delete("speed_hover")

    def _extend_selection(self, event):
        if self._selection_start is None or not self._plot:
            return
        left, _right, top, bottom, plot_width, _start, _end = self._plot
        current = min(max(event.x, left), left + plot_width)
        if abs(current - self._selection_start) > 3:
            self._selection_moved = True
        self.canvas.delete("speed_hover")
        self.canvas.delete("speed_selection")
        self.canvas.create_rectangle(self._selection_start, top, current, bottom,
                                     outline="#1565c0", dash=(4, 3), width=2,
                                     tags="speed_selection")

    def _finish_selection(self, event):
        if self._selection_start is None or not self._plot:
            return
        left, _right, _top, _bottom, plot_width, view_start, view_end = self._plot
        current = min(max(event.x, left), left + plot_width)
        start_x, self._selection_start = self._selection_start, None
        moved = self._selection_moved
        self._selection_moved = False
        self.canvas.delete("speed_selection")
        # Click without drag: re-center the view on the clicked time.
        if not moved:
            span = view_end - view_start
            target = view_start + (start_x - left) * span / plot_width
            self._set_zoom(target, span)
            return
        # Drag: zoom to the selected region.
        if abs(current - start_x) < 5:
            return
        span = view_end - view_start
        start = view_start + (min(start_x, current) - left) * span / plot_width
        end = view_start + (max(start_x, current) - left) * span / plot_width
        self._set_zoom((start + end) / 2, end - start)


# ── Activity timeline chart ─────────────────────────────────────────────
ACTIVITY_COLORS = {
    "DRIVE": "#1565c0",
    "WORK": "#ef6c00",
    "REST": "#78909c",
    "AVAILABLE": "#f9a825",
}
ACTIVITY_LABEL = {"DRIVE": "Drive", "WORK": "Work", "REST": "Rest",
                  "AVAILABLE": "Available"}


class ActivityTimelineChart(ttk.Frame):
    """Gantt timeline for one UTC day of driver activity changes."""

    def __init__(self, parent):
        super().__init__(parent)
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=8, pady=(8, 2))
        self.title_lbl = ttk.Label(header, font=("", 13, "bold"))
        self.title_lbl.pack(side=tk.LEFT)
        self.detail_btn = tk.Label(header, text="?", font=("", 12, "bold"),
                                   fg="#1565C0", bg="#E3F2FD", padx=6, pady=0,
                                   cursor="hand2", relief=tk.FLAT,
                                   bd=1, highlightthickness=0)
        self.detail_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.detail_btn.bind("<Enter>", lambda e: e.widget.configure(bg="#BBDEFB"))
        self.detail_btn.bind("<Leave>", lambda e: e.widget.configure(bg="#E3F2FD"))
        self.info_lbl = ttk.Label(self, foreground="#37474f", anchor=tk.W)
        self.info_lbl.pack(fill=tk.X, padx=8, pady=(0, 4))
        self.canvas = tk.Canvas(self, background="#ffffff", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 2))
        self.canvas.bind("<Configure>", lambda _event: self._schedule_draw())
        self.canvas.bind("<Motion>", self._show_hover)
        self.canvas.bind("<Leave>", lambda _event: self.canvas.delete("act_hover"))
        self.summary_lbl = ttk.Label(self, foreground="gray", anchor=tk.W,
                                     justify=tk.LEFT)
        self.summary_lbl.pack(fill=tk.X, padx=8, pady=(2, 8))
        self._day = ""
        self._slots = {}      # slot_label -> [(start_s, end_s, activity), ...]
        self._slot_schedule = {}
        self._markers = []
        self._oos_events = []
        self._driver_name = ""
        self._draw_after_id = None
        self._layout = None
        self._info_parts = []
        self._activities = []
        self._day_km = 0
        self._changes_count = 0
        self._vehicle_info = []
        self._details_data = {}

    def show(self, day, is_vu, activities, day_km=0, changes_count=0,
             driver_info="", slot_schedule=None, markers=None,
             vehicle_info=None, oos_events=None, data=None):
        self._day = day
        self._slots = self._build_blocks(activities, is_vu)
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
            DayDetailWindow(self.winfo_toplevel(), self._day,
                            self._activities, self._day_km,
                            self._changes_count, self._driver_name,
                            self._slot_schedule, self._markers,
                            self._oos_events, self._vehicle_info,
                            self._details_data, is_vu=self._is_vu)

        self.detail_btn.unbind("<Button-1>")
        self.detail_btn.bind("<Button-1>", _open_detail)
        self.title_lbl.config(text=f"Daily Activities - {day} (UTC)")
        info_parts = [f"\U0001f4c5 {day}"]
        if is_vu:
            info_parts.append(f"\U0001f6e3 {day_km} km")
        if changes_count:
            info_parts.append(f"{changes_count} changes")
        if driver_info:
            info_parts.append(f"\U0001f464 {driver_info}")
        vehicle_info = vehicle_info or []
        if not is_vu and vehicle_info:
            info_parts.append(self._format_vehicles(vehicle_info))
        self._info_parts = info_parts
        self.info_lbl.config(text="  |  ".join(info_parts))
        self._schedule_draw()

    @staticmethod
    def _format_vehicles(vehicles):
        """Format the vehicles-driven label for a day.

        One vehicle → just the plate. Multiple → each plate with its
        start–end time window so the switch-over is visible.
        """
        def _hhmm(dt):
            return dt.strftime("%H:%M") if dt is not None else "?"

        if len(vehicles) == 1:
            return f"\U0001f69b {vehicles[0]['plate']}"
        parts = [f"{v['plate']} ({_hhmm(v['start'])}\u2013{_hhmm(v['end'])})"
                 for v in vehicles]
        return "\U0001f69b " + ", ".join(parts)

    @staticmethod
    def _parse_time(time_str):
        parts = str(time_str).split(":")
        if len(parts) != 2:
            return None
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60
        except ValueError:
            return None

    @staticmethod
    def _build_blocks(changes, is_vu):
        """Convert a list of activity changes to per-slot block lists."""
        slots = {}
        # Recognise slots by the card slot label stored in the change record.
        for ch in changes:
            if not isinstance(ch, dict):
                continue
            slot = str(ch.get("slot") or "First")
            if is_vu:
                slot = "Slot 1" if slot == "First" else "Slot 2"
            else:
                slot = "Cardholder"
            slots.setdefault(slot, []).append(ch)

        blocks = {}
        for slot_label, entries in slots.items():
            blocks[slot_label] = []
            # Sort by time, then build continuous blocks.
            parsed = []
            for entry in entries:
                t = ActivityTimelineChart._parse_time(entry.get("time", ""))
                act = str(entry.get("activity", "")).upper()
                if t is not None and act in ACTIVITY_COLORS:
                    parsed.append((t, act))
            parsed.sort(key=lambda item: item[0])
            if not parsed:
                continue
            # First block starts at its time; the next block's time closes it.
            for i, (start, act) in enumerate(parsed):
                end = parsed[i + 1][0] if i + 1 < len(parsed) else 86400
                blocks[slot_label].append((start, end, act))
        return blocks

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

        rows = ["DRIVE", "WORK", "REST", "AVAILABLE"]
        left, right, top, bottom = 100, 14, 64, height - 32
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
            canvas.create_line(x, top, x, bottom, fill="#edf1f5")
            canvas.create_text(x, top - 22, text=f"{hour:02d}:00",
                               anchor=tk.S, fill="#536273")

        # Out-of-scope / ferry-train markers (between card markers and activity rows)
        OOS_COLORS = {
            "OutOfScope Begin": "#ef6c00",
            "OutOfScope End": "#ef6c00",
            "Ferry/Train Begin": "#7b1fa2",
            "Ferry/Train End": "#7b1fa2",
        }
        # Section header height (slot label + markers, above activity rows)
        header_h = 56 if has_multi else 24
        oos_info = []
        for sec, cond, ts in self._oos_events:
            x = left + sec * usable_width / 86400
            color = OOS_COLORS.get(cond, "#bdbdbd")
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
        row_h = max(18, min(30, (usable_h - 3 * gap) // 4))

        totals_lines = []

        for sidx, slot_name in enumerate(slot_order):
            section_top = top + sidx * (per_section_h + section_gap)

            # Divider line between sections
            if sidx > 0:
                dy = section_top - section_gap // 2
                canvas.create_line(left - 8, dy, left + usable_width + 8, dy,
                                   fill="#90a4ae", width=1)

            slot_blocks = self._slots.get(slot_name, [])

            # Slot label
            if slot_name == "Cardholder" and self._driver_name:
                label_text = f"\U0001f464 {self._driver_name}"
            else:
                label_text = slot_name
            canvas.create_text(left, section_top + header_h // 3,
                               text=label_text, anchor=tk.W,
                               fill="#263238", font=("TkDefaultFont", 11, "bold"))

            # Per-slot totals
            totals = {}
            for start_s, end_s, act in slot_blocks:
                totals[act] = totals.get(act, 0) + (end_s - start_s)
            parts = []
            for act in rows:
                seconds = totals.get(act, 0)
                if seconds:
                    h, m = divmod(seconds // 60, 60)
                    parts.append(f"{h}h {m:02d}m {ACTIVITY_LABEL[act]}")
            totals_lines.append(f"  {slot_name}:  " + "  |  ".join(parts) if parts else f"  {slot_name}:  —")

            # Activity rows start after the header
            rows_top = section_top + header_h
            for ridx, act in enumerate(rows):
                y0 = rows_top + ridx * (row_h + gap)
                y1 = y0 + row_h
                color = ACTIVITY_COLORS.get(act, "#bdbdbd")

                # Activity label on the left
                canvas.create_text(left - 8, (y0 + y1) / 2,
                                   text=ACTIVITY_LABEL.get(act, act),
                                   anchor=tk.E, fill="#37474f",
                                   font=("", 8, "bold"))

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
                                   anchor=tk.W, fill="#536273", font=("", 8))

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
                color = "#2e7d32" if is_ins else "#c62828"
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

    def _show_hover(self, event):
        if not self._layout or not self._slots:
            return
        self.canvas.delete("act_hover")
        left = self._layout["left"]
        plot_width = self._layout["plot_width"]

        # Check markers first
        for mx, my, m_slot, m_name, is_ins, _sec in self._layout.get("markers_info", []):
            if abs(event.x - mx) <= 10 and abs(event.y - my) <= 10:
                kind = "\u25bc Insertion" if is_ins else "\u25b2 Withdrawal"
                text = f"{kind}: {m_name} ({m_slot})"
                label_x = min(event.x + 12, self.canvas.winfo_width() - 260)
                label_y = max(event.y - 24, 4)
                text_id = self.canvas.create_text(
                    label_x, label_y, text=text, anchor=tk.NW,
                    fill="#17212b", tags="act_hover")
                x1, yb1, x2, yb2 = self.canvas.bbox(text_id)
                bg = self.canvas.create_rectangle(
                    x1 - 5, yb1 - 3, x2 + 5, yb2 + 3,
                    fill="#fffde7", outline="#9e9e9e", tags="act_hover")
                self.canvas.tag_lower(bg, text_id)
                return

        # Check OOS markers
        for ox, oy, cond, ts in self._layout.get("oos_info", []):
            if abs(event.x - ox) <= 10 and abs(event.y - oy) <= 10:
                ts_str = ts.strftime("%H:%M") if ts else "?"
                text = f"{cond}: {ts_str}"
                label_x = min(event.x + 12, self.canvas.winfo_width() - 260)
                label_y = max(event.y - 24, 4)
                text_id = self.canvas.create_text(
                    label_x, label_y, text=text, anchor=tk.NW,
                    fill="#17212b", tags="act_hover")
                x1, yb1, x2, yb2 = self.canvas.bbox(text_id)
                bg = self.canvas.create_rectangle(
                    x1 - 5, yb1 - 3, x2 + 5, yb2 + 3,
                    fill="#fffde7", outline="#9e9e9e", tags="act_hover")
                self.canvas.tag_lower(bg, text_id)
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
            if has_multi:
                text = (f"{slot_tag}  {ACTIVITY_LABEL.get(act, act)}  "
                        f"[{sh:02d}:{sm:02d} \u2014 {eh:02d}:{em:02d}]  "
                        f"\u00b7  {dh}h {dm:02d}m")
            else:
                text = (f"{ACTIVITY_LABEL.get(act, act)}  "
                        f"[{sh:02d}:{sm:02d} \u2014 {eh:02d}:{em:02d}]  "
                        f"\u00b7  {dh}h {dm:02d}m")
            label_x = min(event.x + 12, self.canvas.winfo_width() - 300)
            label_y = max(event.y - 24, 4)
            text_id = self.canvas.create_text(
                label_x, label_y, text=text, anchor=tk.NW,
                fill="#17212b", tags="act_hover")
            x1, yb1, x2, yb2 = self.canvas.bbox(text_id)
            bg = self.canvas.create_rectangle(
                x1 - 5, yb1 - 3, x2 + 5, yb2 + 3,
                fill="#fffde7", outline="#9e9e9e", tags="act_hover")
            self.canvas.tag_lower(bg, text_id)
            return





# ── Day detail popup ──────────────────────────────────────────────────────

class DayDetailWindow(tk.Toplevel):
    """Chronological log of all events for a single day (driver card / VU)."""

    _open_windows: dict[str, "DayDetailWindow"] = {}

    COLORS = {
        "DRIVE":      "#1565C0",
        "WORK":       "#546E7A",
        "REST":       "#78909C",
        "AVAILABLE":  "#90A4AE",
        "UNKNOWN":    "#78909C",
        "CARD_IN":    "#2E7D32",
        "CARD_OUT":   "#B71C1C",
        "MANUAL":     "#6A1B9A",
        "EVENT":      "#5D4037",
        "FAULT":      "#5D4037",
        "CONDITION":  "#5D4037",
        "PLACES":     "#5D4037",
        "OVERSPEED":  "#5D4037",
        "POWER":      "#5D4037",
        "BORDER":     "#5D4037",
        "LOADUNLD":   "#5D4037",
    }

    def __init__(self, parent, day, activities, day_km, changes_count,
                 driver_info, slot_schedule, markers, oos_events,
                 vehicle_info, data, is_vu=False):
        existing = DayDetailWindow._open_windows.get(day)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        super().__init__(parent)
        DayDetailWindow._open_windows[day] = self
        self.title(f"Daily Detail — {day} (UTC)")
        self.geometry("900x580")
        self.resizable(True, True)
        self.configure(bg="#FAFAFA")
        self.transient(parent)

        self._day = day
        self._day_km = day_km
        self._driver_info = driver_info
        self._vehicle_info = vehicle_info or []
        self._iso_date = _activity_to_iso(day)
        self._is_vu = is_vu
        self._data = data
        self._slot_schedule = slot_schedule or {}
        self._markers = markers or []
        self._oos_events = oos_events or []
        self._changes_count = changes_count

        # Split activities by slot (VU files have two slots)
        self._act_slot1 = [c for c in (activities or [])
                           if isinstance(c, dict)
                           and c.get("slot", "First") == "First"]
        self._act_slot2 = [c for c in (activities or [])
                           if isinstance(c, dict)
                           and c.get("slot", "") == "Second"]
        self._current_slot = 1

        # ── Header ──
        hdr = tk.Frame(self, bg="#FAFAFA")
        hdr.pack(fill=tk.X, padx=14, pady=(12, 6))
        title_row = tk.Frame(hdr, bg="#FAFAFA")
        title_row.pack(fill=tk.X)
        tk.Label(title_row, text="Daily Detail",
                 font=("", 16, "bold"), fg="#263238", bg="#FAFAFA",
                 anchor=tk.W).pack(side=tk.LEFT)
        if is_vu:
            self._slot_btn = tk.Label(title_row, text="Slot 2",
                                      font=("", 10, "bold"),
                                      fg="#1565C0", bg="#E3F2FD",
                                      padx=10, pady=2,
                                      cursor="hand2", relief=tk.FLAT, bd=1)
            self._slot_btn.pack(side=tk.RIGHT)
            self._slot_btn.bind("<Enter>", lambda e: e.widget.configure(bg="#BBDEFB"))
            self._slot_btn.bind("<Leave>", lambda e: e.widget.configure(bg="#E3F2FD"))
            self._slot_btn.bind("<Button-1>", lambda e: self._toggle_slot())
        else:
            self._slot_btn = None
        tk.Label(hdr, text=f"{day} (UTC)",
                 font=("", 11), fg="#607D8B", bg="#FAFAFA",
                 anchor=tk.W).pack(anchor=tk.W, pady=(1, 6))
        self._header_info = tk.Label(hdr, text="",
                                     font=("", 10), fg="#78909C", bg="#FAFAFA",
                                     anchor=tk.W)
        self._header_info.pack(anchor=tk.W, pady=(0, 2))
        self._refresh_header()

        # ── Body: scrolled text ──
        text_frame = ttk.Frame(self)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        scroll_y = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        scroll_x = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL)
        self.text = tk.Text(text_frame, font=("Menlo", 11), wrap=tk.NONE,
                            bg="#FFFFFF", fg="#263238", padx=14, pady=10,
                            yscrollcommand=scroll_y.set,
                            xscrollcommand=scroll_x.set, cursor="arrow",
                            borderwidth=1, relief=tk.SOLID)
        scroll_y.config(command=self.text.yview)
        scroll_x.config(command=self.text.xview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.pack(fill=tk.BOTH, expand=True)

        self.text.tag_configure("t_label", foreground="#263238",
                                font=("Menlo", 11, "bold"))
        self.text.tag_configure("t_marker", foreground="#263238",
                                font=("Menlo", 11, "normal"))
        self.text.tag_configure("t_event", foreground="#263238",
                                font=("Menlo", 11, "italic"))
        self.text.tag_configure("t_sub", foreground="#5D4037",
                                font=("Menlo", 10))
        self.text.tag_configure("t_hdr", foreground="#37474F",
                                font=("Menlo", 12, "bold"))
        self.text.tag_configure("t_time", foreground="#90A4AE",
                                font=("Menlo", 10))
        self.text.tag_configure("t_count", foreground="#78909C",
                                font=("Menlo", 10))
        self.text.tag_configure("t_odo", foreground="#78909C",
                                font=("Menlo", 10))

        self._render()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _refresh_header(self):
        info = []
        if self._driver_info:
            info.append(f"Driver: {self._driver_info}")
        if self._vehicle_info:
            plates = [v.get("plate", "?") for v in self._vehicle_info[:3]]
            info.append(f"Vehicle: {', '.join(plates)}")
        if self._day_km:
            info.append(f"Distance: {self._day_km} km")
        slot_label = f"Slot {self._current_slot}" if self._is_vu else ""
        n_act = len(self._act_slot1) if self._current_slot == 1 else len(self._act_slot2)
        info.append(f"{n_act} activity changes"
                    + (f" ({slot_label})" if slot_label else ""))
        self._header_info.config(text="  |  ".join(info))

    # ── Slot toggle ────────────────────────────────────────────────────

    def _toggle_slot(self):
        if self._current_slot == 1:
            self._current_slot = 2
            self._slot_btn.config(text="Slot 1")
        else:
            self._current_slot = 1
            self._slot_btn.config(text="Slot 2")
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
        DayDetailWindow._open_windows.pop(self._day, None)
        self.destroy()

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
                                        "Card inserted", detail, 0, ""))
                    if end_hhmm and end_hhmm != "24:00":
                        em = _hhmm_to_min(end_hhmm)
                        detail = _fmt_empty_prefix() + name
                        entries.append((em, 510, "CARD_OUT", end_hhmm,
                                        "Card withdrawn", detail, 0, ""))

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
                label = "Manual entry"
                slot = rec.get("card_slot")
                slot_str = f"[Slot {'2' if slot else '1'}]" if slot is not None else ""
                detail = _fmt_empty_prefix() + slot_str
                odo = rec.get("odometer_insertion_km")
                odo_str = str(odo) if odo else ""
                entries.append((im, 520, "MANUAL", hhmm, label,
                                detail, 0, odo_str))
            else:
                name = f"{rec.get('holder_surname','')} {rec.get('holder_first_names','')}".strip()
                if not name or name == "N/A N/A":
                    name = rec.get("card_number", "") or "Unknown"
                label = "Card inserted"
                slot = rec.get("card_slot")
                slot_str = f"[Slot {'2' if slot else '1'}]" if slot is not None else ""
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
                                    "Card withdrawn", "", 0, odo_str))

        # Events
        for ev in (data.get("events") or []):
            if not isinstance(ev, dict):
                continue
            begin_ts = ev.get("begin") or ev.get("begin_time") or ""
            dt = _parse_iso(begin_ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            desc = ev.get("description", "Unknown event")
            plate_str = ""
            plate = ev.get("vehicle_plate", "")
            if plate:
                plate_str = f"  Plate: {plate}"
            detail = _fmt_empty_prefix() + desc + plate_str
            entries.append((_hhmm_to_min(hhmm), 800, "EVENT", hhmm,
                            "Event", detail, 0, ""))

        # Faults
        for flt in (data.get("faults") or []):
            if not isinstance(flt, dict):
                continue
            begin_ts = flt.get("begin") or flt.get("begin_time") or ""
            dt = _parse_iso(begin_ts)
            if not dt or dt.date().isoformat() != self._iso_date:
                continue
            hhmm = dt.strftime("%H:%M")
            desc = flt.get("description", "Unknown fault")
            detail = _fmt_empty_prefix() + desc
            entries.append((_hhmm_to_min(hhmm), 810, "FAULT", hhmm,
                            "Fault", detail, 0, ""))

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
            country = nation_full_name(nation_code) if nation_code else ""
            if not country:
                country = nation_code or "Unknown"
            if entry_type == "START":
                label = "Place: Begin"
            elif entry_type == "END":
                label = "Place: End"
            else:
                label = "Place"
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
                speed_parts.append(f"Max {max_s} km/h")
            if avg_s is not None:
                speed_parts.append(f"Avg {avg_s} km/h")
            speed_str = "  |  ".join(speed_parts) if speed_parts else ""
            detail = _fmt_empty_prefix() + speed_str
            entries.append((_hhmm_to_min(hhmm), 820, "OVERSPEED", hhmm,
                            "Overspeeding", detail, 0, ""))

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
                            "Power interruption", "", 0, ""))

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
                desc = f"Left: {left}"
            elif entered:
                desc = f"Entered: {entered}"
            else:
                desc = ""
            odo = bc.get("odometer_km")
            odo_str = str(odo) if odo else ""
            entries.append((_hhmm_to_min(hhmm), 840, "BORDER", hhmm,
                            "Border crossing",
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
                            f"Load/Unload: {op}" if op else "Load/Unload",
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
            if i + 1 < len(activities):
                nt = activities[i + 1].get("time", "")
                if isinstance(nt, str) and ":" in nt:
                    next_time = nt
            end_min = _hhmm_to_min(next_time)
            dur_min = max(0, end_min - start_min)
            if dur_min <= 0:
                continue
            dur_str = _format_duration(dur_min)

            slot = ch.get("slot", "")
            crew = ch.get("crew", False)
            card_in = ch.get("card_inserted", True)
            time_range = f"{start_time} \u2192 {next_time}"
            detail = _fmt_range_dur(time_range, dur_str)

            # Driver / slot info
            if self._is_vu:
                slot_key = 0 if self._current_slot == 1 else 1
                active_name = self._find_driver(start_min, driver_by_slot.get(slot_key, []))
                if active_name:
                    detail += active_name
                elif not card_in:
                    detail += "No card present"
                else:
                    detail += f"Slot {self._current_slot}"
                if crew and active_name:
                    detail += "  Crew"
            else:
                if slot and slot != "First":
                    detail += f"Slot {slot}"
                if crew:
                    detail += "  Crew"
                if not card_in:
                    detail += "  No card present"

            entries.append((start_min, 1000, act, start_time,
                            _activity_label(act), detail, dur_min, ""))

            if not card_in:
                entries.append((start_min, 999, "CARD_OUT", start_time,
                                "Card not inserted",
                                f"Card absent from the tachograph as of {start_time}",
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
            name = f"{rec.get('holder_surname','')} {rec.get('holder_first_names','')}".strip()
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
            self.text.insert(tk.END, "No data for this day.\n", "t_sub")
            return

        self.text.insert(tk.END, "Activity Timeline\n", "t_hdr")

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
        self.text.insert(tk.END, "Summary\n", "t_hdr")

        totals = {"DRIVE": 0, "WORK": 0, "REST": 0, "AVAILABLE": 0, "UNKNOWN": 0}
        for entry in timeline:
            if len(entry) < 8:
                continue
            _sk, _rk, kind, _t, _l, _d, dur, _odo = entry
            if kind in totals:
                totals[kind] += dur

        for act, label in [("DRIVE", "Drive"), ("WORK", "Work"),
                           ("AVAILABLE", "Available"), ("REST", "Rest")]:
            self.text.insert(tk.END,
                             f"  {label:12s} {_format_duration(totals[act])}\n",
                             f"t_{act}")

        counts = [
            ("Events", "EVENT"), ("Faults", "FAULT"),
            ("Conditions", "CONDITION"), ("Places", "PLACES"),
            ("Overspeeding", "OVERSPEED"), ("Power interruptions", "POWER"),
            ("Border crossings", "BORDER"), ("Load/Unload", "LOADUNLD"),
            ("Manual entries", "MANUAL"),
        ]
        self.text.insert(tk.END, "\n")
        for label, kind in counts:
            n = sum(1 for _s, _r, k, *_ in timeline if k == kind)
            if n > 0 or kind in ("EVENT", "FAULT", "CONDITION", "PLACES", "MANUAL"):
                self.text.insert(tk.END,
                                 f"  {label:20s} {n}\n",
                                 "t_count")

        card_in_times = sorted({sk for sk, _rk, k, *_ in timeline
                                if k == "CARD_IN"})
        card_out_times = sorted({sk for sk, _rk, k, *_ in timeline
                                 if k == "CARD_OUT"})
        act_card_present = sorted({e[0] for e in timeline
                                   if e[2] in ("DRIVE", "WORK", "REST", "AVAILABLE")})

        if not card_in_times and act_card_present:
            card_in_times = [act_card_present[0]]
            card_out_times = [act_card_present[-1]]

        if card_in_times:
            h1, m1 = divmod(card_in_times[0], 60)
            h2, m2 = divmod(card_out_times[-1] if card_out_times else 1440, 60)
            self.text.insert(tk.END,
                             f"  Card present: {h1:02d}:{m1:02d}"
                             f" \u2013 {h2:02d}:{m2:02d}\n",
                             "t_count")


# ── Day detail helpers ───────────────────────────────────────────────────

# Column widths for timeline detail line (used by both activity and shared builders)
_DETAIL_RANGE = 15   # "00:00 → 04:15  "
_DETAIL_DUR   = 12   # "(4h 15m)     "  
# Driver/desc starts at _DETAIL_RANGE + _DETAIL_DUR

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
    return {"DRIVE": "Drive", "WORK": "Work",
            "REST": "Rest", "AVAILABLE": "Available"}.get(act, act)


def _condition_label(cond):
    m = {
        "1": "Out of scope \u2014 Begin",
        "2": "Out of scope \u2014 End",
        "3": "Ferry / Train \u2014 Begin",
        "4": "Ferry / Train \u2014 End",
        "OutOfScope Begin": "Out of scope \u2014 Begin",
        "OutOfScope End": "Out of scope \u2014 End",
        "FerryTrain Begin": "Ferry / Train \u2014 Begin",
        "FerryTrain End": "Ferry / Train \u2014 End",
    }
    return m.get(str(cond), f"Condition: {cond}")


def _ts_to_hhmm(ts):
    dt = _parse_iso(str(ts))
    if dt:
        return dt.strftime("%H:%M")
    return str(ts)[:5]


# ── Main application ─────────────────────────────────────────────────────

def _resource_path(rel):
    """Path of a bundled resource (PyInstaller _MEIPASS or repo root)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


class TachoExplorer(tk.Tk):
    def __init__(self, initial_file=None):
        super().__init__()
        self._initial_file = initial_file
        self.title(f"Tacho Explorer v{__version__}")
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
        APP_BG = "#f4f6f9"
        APP_FG = "#1c2733"
        FIELD_BG = "#ffffff"
        BORDER = "#c5cfdb"
        self.configure(background=APP_BG)

        # tk_setPalette recolours classic (non-ttk) widgets: menus, canvases,
        # message boxes. Do this first, then override ttk styles below so the
        # palette cannot clobber ttk-specific element colours (e.g. the tree
        # expand/collapse indicator).
        self.tk_setPalette(background=APP_BG, foreground=APP_FG,
                           activeBackground="#dbe4f0", activeForeground=APP_FG,
                           highlightBackground=APP_BG,
                           highlightColor="#1565c0",
                           selectBackground="#1565c0", selectForeground="#ffffff")

        # Root style: kills clam's grey 3D borders/shading everywhere at once.
        style.configure(".", background=APP_BG, foreground=APP_FG,
                        fieldbackground=FIELD_BG, bordercolor=BORDER,
                        darkcolor=APP_BG, lightcolor=APP_BG,
                        troughcolor="#dbe4f0", arrowcolor=APP_FG,
                        insertcolor=APP_FG, focuscolor="#1565c0",
                        selectbackground="#1565c0", selectforeground="#ffffff")

        for cls in ("TFrame", "TLabelframe", "TPanedWindow"):
            style.configure(cls, background=APP_BG)
        style.configure("TLabelframe.Label", background=APP_BG, foreground=APP_FG)
        style.configure("TLabel", background=APP_BG, foreground=APP_FG)
        style.configure("TButton", background="#e3e9f2", foreground=APP_FG,
                        bordercolor=BORDER)
        style.map("TButton",
                  background=[("active", "#d2ddec"), ("pressed", "#c3d1e6")])
        style.configure("TMenubutton", background="#e3e9f2", foreground=APP_FG,
                        arrowcolor=APP_FG)
        style.map("TMenubutton", background=[("active", "#d2ddec")])
        style.configure("TEntry", fieldbackground=FIELD_BG, foreground=APP_FG,
                        insertcolor=APP_FG, bordercolor=BORDER)
        style.configure("TCombobox", fieldbackground=FIELD_BG, foreground=APP_FG)
        style.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG,
                        foreground=APP_FG, bordercolor=BORDER)
        style.map("Treeview",
                  background=[("selected", "#1565c0")],
                  foreground=[("selected", "#ffffff")])
        # Restore a dark, visible expand/collapse arrow on the light tree.
        style.configure("Treeview.Item", indicatorforeground=APP_FG)
        style.configure("Treeview.Heading", background=HEADER_BG,
                        foreground=APP_FG, font=("", 10, "bold"),
                        bordercolor=BORDER, relief=tk.FLAT)
        style.map("Treeview.Heading", background=[("active", "#d2ddec")])
        style.configure("TScrollbar", background="#cdd7e4", troughcolor=APP_BG,
                        bordercolor=BORDER, arrowcolor=APP_FG)
        style.map("TScrollbar", background=[("active", "#b6c3d6")])
        # PanedWindow divider (sash) between the tree and the table.
        style.configure("Sash", background=APP_BG, bordercolor=BORDER,
                        lightcolor=APP_BG, darkcolor=APP_BG)
        style.configure("TProgressbar", background="#1565c0", troughcolor="#dbe4f0")
        style.configure("Treeview", rowheight=_px(24))

        self.current_data = None
        self.current_file = None
        self._payloads = {}  # iid -> (title, columns, rows, meta)
        self._destroyed = False
        self._parsing = False
        self._parse_queue = queue.Queue()
        self._export_queue = queue.Queue()

        self._build_ui()
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            _log.debug("WM_DELETE_WINDOW not supported")

    # ── Layout ──────────────────────────────────────────────

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill=tk.X)
        self.btn_open = ttk.Button(top, text="\U0001f4c2  Open DDD file",
                                   command=self._open_file)
        self.btn_open.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_export = ttk.Menubutton(top, text="\U0001f4e4  Export",
                                         state=tk.DISABLED)
        export_menu = tk.Menu(self.btn_export, tearoff=0,
                              background="#ffffff", foreground="#1c2733",
                              activebackground="#1565c0", activeforeground="#ffffff",
                              borderwidth=0)
        export_menu.add_command(label="PDF (.pdf)", command=self._export_pdf)
        export_menu.add_command(label="Excel (.xlsx)", command=self._export_excel)
        export_menu.add_command(label="CSV (.csv)", command=self._export_csv)
        export_menu.add_command(label="JSON (.json)", command=self._export_json)
        self.btn_export["menu"] = export_menu
        self.btn_export.pack(side=tk.LEFT, padx=(0, 14))
        self.lbl_file = ttk.Label(top, text="No file loaded",
                                  font=("", 11, "bold"))
        self.lbl_file.pack(side=tk.LEFT)
        self.lbl_status = ttk.Label(top, text="", font=("", 10))
        self.lbl_status.pack(side=tk.LEFT, padx=(6, 0))
        self.lbl_gen = ttk.Label(top, text="")
        self.lbl_gen.pack(side=tk.RIGHT, padx=8)

        pw = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Left: tree
        left = ttk.Frame(pw)
        pw.add(left, weight=1)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL)
        self.tree = ttk.Treeview(left, show="tree", yscrollcommand=scroll.set,
                                  selectmode="browse")
        scroll.config(command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.column("#0", width=_px(340), minwidth=_px(200))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        # Right: table
        right = ttk.Frame(pw)
        pw.add(right, weight=3)
        self.table = DataTable(right)
        self.table.pack(fill=tk.BOTH, expand=True)
        self.speed_chart = DetailedSpeedChart(right)
        self.activity_chart = ActivityTimelineChart(right)

        self.bind("<Control-f>", lambda e: self._focus_filter())

        status_bar = ttk.Frame(self, relief=tk.SUNKEN)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = ttk.Label(status_bar, text="Ready \u2014 open a .ddd file",
                                anchor=tk.W, padding=(6, 2))
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.integrity_banner = ttk.Label(status_bar, text="", anchor=tk.E,
                                           padding=(6, 2), cursor="hand2")
        self.integrity_banner.pack(side=tk.RIGHT)
        self.integrity_banner.bind(
            "<Button-1>", lambda _e: self._show_integrity_details())
        self._integrity_warnings = []
        self.progress = ttk.Progressbar(status_bar, mode="indeterminate", length=_px(160))
        # packed only while a parse is running \u2014 see _start_parse/_finish_parse

        if self._initial_file and os.path.isfile(self._initial_file):
            self.after(100, lambda: self._start_parse(self._initial_file))

    def _focus_filter(self):
        """Focus the table filter box only when it is actually visible
        (summary and dashboard views hide the filter bar)."""
        if self.table.winfo_manager() and self.table.filt_bar.winfo_manager():
            self.table.filter_entry.focus_set()

    # ── File open ──────────────────────────────────────────

    def _open_file(self):
        """File-picker entry point; ignored while a parse is running."""
        if self._parsing:
            return
        path = filedialog.askopenfilename(
            filetypes=[("DDD Files", "*.ddd *.DDD"), ("All Files", "*.*")])
        if not path:
            return
        self._start_parse(path)

    def _start_parse(self, path):
        """Run the parse on a worker thread so the UI stays responsive;
        results are marshalled back via a queue polled on the main loop."""
        self._parsing = True
        self.btn_open.config(state=tk.DISABLED)
        self.btn_export.config(state=tk.DISABLED)
        self.status.config(text=f"Parsing {os.path.basename(path)}\u2026")
        self.progress.pack(side=tk.RIGHT, padx=6, pady=1)
        self.progress.start(12)

        worker = threading.Thread(target=self._parse_worker, args=(path,), daemon=True)
        worker.start()
        self.after(50, self._poll_parse_queue)

    def _parse_worker(self, path):
        """Worker-thread body: parse and post (path, results, error) to the queue."""
        try:
            data = TachoParser(path).parse()
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
            self._parse_done(data, path)

    def _finish_parse(self):
        """Restore the idle UI state (progress bar, buttons) after a parse."""
        self._parsing = False
        try:
            self.progress.stop()
            self.progress.pack_forget()
        except Exception:
            pass
        self.btn_open.config(state=tk.NORMAL)
        if self.current_data:
            # A failed re-open keeps the previously loaded file exportable.
            self.btn_export.config(state=tk.NORMAL)

    def _parse_error(self, msg):
        self._finish_parse()
        try:
            messagebox.showerror("Parsing Error", str(msg))
        except Exception:
            pass
        self.status.config(text="Ready \u2014 open a .ddd file")

    # ── Export ────────────────────────────────────────────

    def _run_export(self, kind, extension, filetypes, export_fn, requirement=""):
        """Shared export flow: pick the destination, run, report the outcome."""
        if not self.current_data:
            return
        if ExportManager is None:
            messagebox.showwarning("Export Unavailable",
                                   f"{kind} export is unavailable. {requirement}".strip())
            return
        path = filedialog.asksaveasfilename(
            defaultextension=extension,
            filetypes=filetypes + [("All Files", "*.*")],
            initialfile=os.path.splitext(os.path.basename(self.current_file))[0]
            + "_export" + extension)
        if not path:
            return
        self.status.config(text=f"Exporting to {kind}\u2026")
        self.progress.pack(side=tk.RIGHT)
        self.progress.start(12)
        self.update_idletasks()

        def _worker():
            try:
                export_fn(self.current_data, path)
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
            if exc is not None:
                if isinstance(exc, ImportError):
                    self.status.config(text="Export failed")
                    messagebox.showwarning("Export Unavailable",
                                           f"{kind_err} export requires an extra package:\n{exc}\n{req}")
                else:
                    self.status.config(text="Export failed")
                    messagebox.showerror("Export Error", str(exc))
            else:
                self.status.config(text=f"Exported: {os.path.basename(export_path)}")
                messagebox.showinfo("Export Complete", f"{kind_err} saved to:\n{export_path}")

        self.after(50, _poll)

    def _export_pdf(self):
        self._run_export("PDF", ".pdf", [("PDF Document", "*.pdf")],
                         lambda d, p: ExportManager.export_to_pdf(d, p),
                         requirement="pip install reportlab")

    def _export_excel(self):
        self._run_export("Excel", ".xlsx", [("Excel Workbook", "*.xlsx")],
                         lambda d, p: ExportManager.export_to_excel(d, p),
                         requirement="pip install openpyxl")

    def _export_csv(self):
        self._run_export("CSV", ".csv", [("CSV Files", "*.csv")],
                         lambda d, p: ExportManager.export_to_csv(d, p))

    def _export_json(self):
        if not self.current_data:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            initialfile=os.path.splitext(os.path.basename(self.current_file))[0] + "_export.json")
        if not path:
            return
        self.status.config(text="Exporting to JSON\u2026")
        self.progress.pack(side=tk.RIGHT)
        self.progress.start(12)
        self.update_idletasks()

        def _worker():
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.current_data, f, indent=2, ensure_ascii=False,
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
            if exc is not None:
                self.status.config(text="Export failed")
                messagebox.showerror("Export Error", str(exc))
            else:
                self.status.config(text=f"Exported: {os.path.basename(export_path)}")
                messagebox.showinfo("Export Complete", f"{kind_err} saved to:\n{export_path}")

        self.after(50, _poll)

    def _on_close(self):
        self._destroyed = True
        self.destroy()

    def _parse_done(self, data, path):
        """Render a parse result. Keeps partial data visible: a fatal error
        (no structural data recovered) shows an error and stops; otherwise the
        tree is rendered even when late phases failed or signatures are bad."""
        parse_error = (data.get("metadata") or {}).get("parse_error")
        has_data = bool(data.get("raw_tags") or data.get("generations")
                        or data.get("activities"))
        if parse_error and not has_data:
            message = parse_error.get("message", "Unknown parsing error") \
                if isinstance(parse_error, dict) else str(parse_error)
            self._parse_error(message)
            return
        self._finish_parse()
        try:
            self.current_data = data
            self.current_file = path
            self._populate_tree(data)
            self._update_top_bar(data)
            self.btn_export.config(state=tk.NORMAL)
            target = getattr(self, "_auto_select_iid", None)
            if not target:
                children = self.tree.get_children("")
                target = children[0] if children else None
            if target:
                self.after_idle(
                    lambda tid=target: self.tree.selection_set(tid)
                    if self.tree.exists(tid) else None)
            meta = data.get("metadata", {})
            self.status.config(
                text=f"Loaded: {os.path.basename(path)}  |  "
                     f"{meta.get('generation', '?')}")
            self._check_integrity(data, path)
        except Exception:
            _log.error("GUI render failed: %s", traceback.format_exc())
            messagebox.showerror("Rendering Error",
                                  f"Failed to display file:\n{traceback.format_exc()}")
            self.status.config(text="Ready \u2014 open a .ddd file")
            self._finish_parse()

    def _check_integrity(self, data, path):
        """Warn the user when a file shows signs of corruption or data loss."""
        meta = data.get("metadata", {})
        warnings = []

        trep = meta.get("trep_report") or {}
        if trep and trep.get("is_partial"):
            warnings.append(
                f"\u2022 Download completeness: "
                f"{trep.get('mandatory_ok', 0)}/{trep.get('mandatory_total', 0)} "
                f"mandatory section(s) read ({trep.get('completeness_pct', 0)}%)")
            missing = trep.get("mandatory_missing") or []
            if missing:
                warnings.append(
                    "\u2022 Missing mandatory section(s): "
                    + ", ".join(t["name"] for t in missing))
            suspect = trep.get("decoded_suspect") or []
            if suspect:
                warnings.append(
                    "\u2022 Corrupted/implausible section(s) (data discarded): "
                    + ", ".join(t["name"] for t in suspect))
            if not trep.get("complete_walk", True):
                warnings.append(
                    "\u2022 The structural walk did not reach the end of file")

        salvaged = meta.get("salvage_recovered")
        if salvaged:
            warnings.append(
                "\u2022 Data recovered from damaged regions (low confidence): "
                + ", ".join(salvaged))

        for pw in meta.get("parse_warnings") or []:
            if isinstance(pw, dict):
                warnings.append(
                    f"\u2022 Parsing phase '{pw.get('phase', '?')}' failed: "
                    f"{pw.get('message', 'unknown error')} "
                    f"(partial data shown)")

        heuristic = meta.get("heuristic_fields") or {}
        if heuristic:
            sections = ", ".join(sorted(heuristic.keys()))
            warnings.append(
                f"\u2022 Some values were recovered heuristically (low "
                f"confidence), not by deterministic spec parsing: {sections}")

        cov_report = data.get("coverage") or {}

        # Cryptographic validation: how much of the decoded data is signature-
        # verified vs. not (more meaningful than raw byte coverage).
        sv = data.get("signature_verification") or {}
        treps = sv.get("treps") or []
        if treps:
            valid = sum(1 for t in treps if t.get("signature_valid") is True)
            total = len(treps)
            if valid < total:
                warnings.append(
                    f"\u2022 VU sections validated: {valid}/{total} "
                    f"signature(s) verified; {total - valid} NOT validated")
        elif sv.get("available") is False:
            warnings.append(
                "\u2022 VU sections validated: 0 \u2014 signatures could not be "
                "verified (VU public key unavailable)")

        efv = data.get("ef_signature_verification") or {}
        ef_results = efv.get("ef_results") or []
        if ef_results:
            ef_ok = sum(1 for e in ef_results if e.get("status") == "verified")
            ef_total = len(ef_results)
            if ef_ok < ef_total:
                warnings.append(
                    f"\u2022 Card data validated: {ef_ok}/{ef_total} EF "
                    f"signature(s) verified; {ef_total - ef_ok} NOT validated")

        unknown = cov_report.get("classifications", {}).get("Unknown", 0)
        if unknown > 0:
            warnings.append(
                f"\u2022 {unknown:,} bytes classified as Unknown (unparseable)")

        uncovered = cov_report.get("uncovered_ranges") or []
        if uncovered:
            warnings.append(
                f"\u2022 {len(uncovered)} uncovered byte range(s) in the file")

        decoder_failures = meta.get("decoder_failure_count", 0)
        if decoder_failures > 0:
            warnings.append(
                f"\u2022 {decoder_failures} decoder(s) failed during parsing")

        integrity = meta.get("integrity_check", "")
        if "Error" in integrity:
            warnings.append(f"\u2022 Integrity check: {integrity}")
        elif "Incomplete" in integrity:
            warnings.append(f"\u2022 Certificate chain: {integrity}")

        efv = data.get("ef_signature_verification") or {}
        ef_failed = efv.get("failed", 0)
        if ef_failed:
            warnings.append(f"\u2022 EF data signatures: {ef_failed} failed verification")

        sv = data.get("signature_verification") or {}
        if sv.get("available") and not sv.get("msca_to_vu"):
            warnings.append("\u2022 VU signature: MSCA\u2192VU chain NOT verified")
        if sv.get("available") and not sv.get("root_anchored"):
            warnings.append("\u2022 VU signature: root ERCA key absent (not anchored)")
        trep_failed = sum(1 for t in (sv.get("treps") or []) if t.get("signature_valid") is False)
        if trep_failed:
            warnings.append(f"\u2022 VU signatures: {trep_failed} TREP section(s) failed")

        self._integrity_warnings = warnings
        self._integrity_file = os.path.basename(path)
        if warnings:
            self.integrity_banner.config(
                text=f"\u26a0\ufe0f  {len(warnings)} integrity warning(s) \u2014 click for details",
                foreground="#e65100")
            header = (f"The file may be incomplete or corrupted.\n\n"
                      f"{os.path.basename(path)}\n\n")
            messagebox.showwarning("File Integrity Warning",
                                   header + "\n".join(warnings))
        else:
            # Valid file: no green tick, no banner — the absence of a warning
            # is the "all good" signal.
            self.integrity_banner.config(text="")

    def _show_integrity_details(self):
        """Show the collected integrity warnings on demand (banner click)."""
        if not self._integrity_warnings:
            messagebox.showinfo(
                "File Integrity",
                f"{getattr(self, '_integrity_file', '')}\n\n"
                "No integrity issues detected.")
            return
        header = (f"The file may be incomplete or corrupted.\n\n"
                  f"{getattr(self, '_integrity_file', '')}\n\n")
        messagebox.showwarning("File Integrity Warning",
                               header + "\n".join(self._integrity_warnings))

    def _update_top_bar(self, data):
        """Refresh filename, generation badge and status badge."""
        meta = data.get("metadata", {})
        gen = meta.get("generation", "Unknown")
        self.lbl_file.config(text=os.path.basename(self.current_file))
        self.lbl_gen.config(text=f"\u25cf {gen}",
                            foreground=GEN_COLORS.get(gen, GEN_COLORS["Unknown"]))
        self._update_status_badge(data)

    def _integrity_label(self, data):
        """Return a human-readable integrity summary for File Info and status bar."""
        meta = data.get("metadata") or {}
        integrity = meta.get("integrity_check", "")
        efv = data.get("ef_signature_verification") or {}
        sv = data.get("signature_verification") or {}

        ef_ok = efv.get("failed", 1) == 0 and efv.get("verified", 0) > 0
        sv_ok = sv.get("all_treps_valid") is True
        vu_chain_ok = sv.get("msca_to_vu") is True
        is_vu = meta.get("is_vu") is True
        chain_ok = "Verified" in integrity

        if chain_ok and ef_ok and not is_vu:
            return "All signatures verified"
        if sv_ok and vu_chain_ok and sv.get("root_anchored"):
            return "VU signatures verified (root anchored)"
        if sv_ok and vu_chain_ok:
            return "VU TREP signatures verified (chain partial)"
        if sv_ok:
            return "VU TREP signatures valid (chain unverified)"
        if chain_ok and not is_vu:
            return "Certificate chain verified"
        if ef_ok:
            return "EF signatures verified"
        if integrity.startswith("Partial"):
            return "Partial verification"
        if integrity == "Invalid Certificate Chain":
            return "Certificate chain invalid"
        if "Missing ERCA" in integrity:
            return "ERCA root not available"
        if "Incomplete" in integrity:
            return "Incomplete certificates"
        if "Error" in integrity:
            return "Verification error"
        return integrity or "N/A"

    def _update_status_badge(self, data):
        """Compose the colour-coded integrity label. Only problems are shown;
        a fully valid file displays no badge (its absence is the OK signal)."""
        integrity = (data.get("metadata") or {}).get("integrity_check", "")
        efv = data.get("ef_signature_verification") or {}
        sv = data.get("signature_verification") or {}

        ef_ok = efv.get("failed", 1) == 0 and efv.get("verified", 0) > 0
        sv_ok = sv.get("all_treps_valid") is True
        vu_chain_ok = sv.get("msca_to_vu") is True
        is_vu = (data.get("metadata") or {}).get("is_vu") is True
        chain_ok = "Verified" in integrity

        label = self._integrity_label(data)

        if chain_ok and ef_ok and not is_vu:
            text = ""
            color = "#757575"
        elif sv_ok and vu_chain_ok and sv.get("root_anchored"):
            text = ""
            color = "#757575"
        elif sv_ok:
            text = "\u26a0\ufe0f  " + label
            color = "#e65100"
        elif chain_ok and not is_vu:
            text = ""
            color = "#757575"
        elif ef_ok:
            text = "\u26a0\ufe0f  " + label
            color = "#e65100"
        elif integrity.startswith("Partial"):
            text = "\u26a0\ufe0f  " + label
            color = "#e65100"
        elif integrity == "Invalid Certificate Chain":
            text = "\u274c  " + label
            color = "#c62828"
        elif "Missing ERCA" in integrity:
            text = "\u26a0\ufe0f  " + label
            color = "#f57c00"
        elif "Incomplete" in integrity:
            text = "\u2753  Incomplete certificates"
            color = "#757575"
        elif "Error" in integrity:
            text = "\u274c  Parse error"
            color = "#c62828"
        else:
            text = ""
            color = "#757575"

        self.lbl_status.config(text=text, foreground=color)
        # Also update the window title with a compact status (problems only).
        parts = [f"Tacho Explorer v{__version__}", text[:1].strip(),
                 os.path.basename(self.current_file or "")]
        self.title("  ".join(p for p in parts if p))

    # ── Tree construction ───────────────────────────────────

    def _add_section(self, parent, label, columns, rows, meta="", summary=False):
        text = label
        iid = self.tree.insert(parent, tk.END, text=text)
        self._payloads[iid] = (label, columns, rows, meta, summary)
        return iid

    def _add_speed_chart_day(self, parent, day, samples, oes=None):
        iid = self.tree.insert(parent, tk.END, text=day)
        self._payloads[iid] = ("__speed_chart__", day, samples, oes)
        return iid

    def _populate_detailed_speed(self, parent, data, raw_blocks):
        """Add daily UTC graph and raw-record children under Detailed Speed."""
        node = self.tree.insert(parent, tk.END, text="Detailed Speed")
        self._payloads[node] = ("__speed_summary__", raw_blocks, data)
        raw_by_day = detailed_speed_blocks_by_day(raw_blocks)

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

        for day, samples in sorted(detailed_speed_by_day(data).items(), reverse=True):
            day_node = self._add_speed_chart_day(node, day, samples, oes_by_day.get(day))
            blocks = raw_by_day.get(day, [])
            cols, rows = _rows_for(blocks, None) if blocks else (["Value"], [])
            self._add_section(day_node, f"Detailed Speed {day}", cols, rows)

    def _add_activity_day(self, parent, day, is_vu, activities, day_km,
                          changes_count, driver_info, slot_schedule, markers,
                          oos_events=None, vehicle_info=None):
        iid = self.tree.insert(parent, tk.END, text=day)
        self._payloads[iid] = ("__activity_chart__", day, is_vu, activities,
                               day_km, changes_count, driver_info, slot_schedule,
                               markers, oos_events, vehicle_info)
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
                anchor = start_dt or end_dt
                if anchor is None:
                    continue
                iso = anchor.date().isoformat()
                vehicles_by_date.setdefault(iso, []).append({
                    "plate": plate,
                    "nation": sess.get("vehicle_nation", ""),
                    "start": start_dt,
                    "end": end_dt,
                })
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
                    iw_events_by_date.setdefault(day_iso, []).append((start_sec, name, True))
                if current.date() == wit_dt.date():
                    iw_events_by_date.setdefault(day_iso, []).append((end_sec, name, False))
                # Schedule
                iw_schedule_by_date.setdefault(day_iso, []).append((start_hhmm, end_hhmm, name,
                                                                     ins_dt, wit_dt))
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
        for i, day_data in enumerate(chronological):
            day_data["_day_km"] = 0
            if i > 0 and is_vu:
                prev_odo = chronological[i - 1].get("odometer_km", 0) or 0
                cur_odo = day_data.get("odometer_km", 0) or 0
                if prev_odo and cur_odo and cur_odo > prev_odo:
                    day_data["_day_km"] = cur_odo - prev_odo

        node = self.tree.insert(parent, tk.END, text="Daily Activities")
        self._payloads[node] = ("__daily_summary__", activity_list, data)
        for day_data in reversed(activity_list):
            if not isinstance(day_data, dict):
                continue
            date_str = day_data.get("date", day_data.get("timestamp", "?"))
            changes = day_data.get("changes", [])
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
                for start_hhmm, end_hhmm, name, ins_dt, _wit_dt in iw_schedule_by_date[iso_date]:
                    slot = ""
                    if act_insertions:
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
                for sec, name, is_ins in iw_events_by_date.get(iso_date, []):
                    # Resolve slot for marker
                    m_slot = ""
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
                day_di = f"{len(all_names)} drivers" if all_names else ""
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
                                              oos_events, day_vehicles)
            odometer = day_data.get("odometer_km", 0) or 0
            if changes:
                rows = [[fmt_val(ev.get("time", "?")),
                         fmt_val(ev.get("activity", "?")),
                         fmt_val(ev.get("slot", "")) if ev.get("slot") else "",
                         fmt_val(ev.get("crew", "")),
                         fmt_val(odometer)] for ev in changes if isinstance(ev, dict)]
                cols = ["Time", "Activity", "Slot", "Crew", "Odometer km"]
            else:
                cols, rows = (["Time", "Activity"], [[fmt_val("\u2014"), "(no changes)"]])
            self._add_section(day_node, f"Daily Activities {date_str}", cols, rows)

    def _populate_tree(self, data):
        """Rebuild the section tree from the generations dict produced by
        :func:`build_generations_tree`.  File info, driver/vehicle summary,
        security and activities (day hierarchy) are handled separately."""
        self.tree.delete(*self.tree.get_children())
        self._payloads.clear()
        self._opened_data = data
        meta = data.get("metadata", {})

        # ── File Info (key/value) ──
        is_vu = meta.get("is_vu", False)
        origin = meta.get("origin", "")
        if origin == "vehicle_unit" or (not origin and is_vu):
            origin_label = "Vehicle Unit (VU)"
        elif meta.get("origin_note"):
            origin_label = "Driver Card (from VU download)"
        else:
            origin_label = "Driver Card"
        info = {
            "Filename": os.path.basename(self.current_file),
            "Size": f"{meta.get('file_size_bytes', 0):,} bytes".replace(",", " "),
            "Origin": origin_label,
            "Generation": meta.get("generation", "?"),
            "Integrity": self._integrity_label(data),
        }
        coverage = data.get("coverage") or {}
        if "byte_accounted_pct" in coverage:
            info["Byte-accounted coverage"] = (
                f"{coverage['byte_accounted_pct']}% "
                f"({coverage.get('byte_accounted_bytes', 0):,} / "
                f"{meta.get('file_size_bytes', 0):,} bytes)"
            ).replace(",", " ")
            info["Unknown bytes"] = (
                f"{coverage.get('unknown_bytes', 0):,} "
                f"({coverage.get('unknown_pct', 0)}%)"
            ).replace(",", " ")
            info["Structurally identified coverage"] = (
                f"{coverage.get('structurally_identified_pct', 0)}% "
                "(not a semantic decoding rate)"
            )
        if meta.get("origin_note"):
            info["Origin details"] = meta["origin_note"]
        if meta.get("decoder_failure_count", 0) > 0:
            info["Decoder failures"] = meta["decoder_failure_count"]
        info["Parsed at"] = meta.get("parsed_at", "")
        info["App version"] = meta.get("app_version", "")
        cols, rows = _kv_rows(info)
        self._add_section("", "\U0001f4c4  File Info", cols, rows)

        # ── Decoder failures detail ──
        failures = meta.get("decoder_failures") or []
        if failures:
            cols, rows = _rows_for(failures, None)
            self._add_section("", "\u26a0\ufe0f  Decoder Failures", cols, rows)

        # ── Raw / Unparsed Data (only when bytes could not be decoded) ──
        self._populate_unparsed(data)

        drv = data.get("driver", {})

        # Driver card: show holder summary.
        if not is_vu and any(drv.values()):
            cols, rows = self._build_driver_summary(data)
            self._auto_select_iid = self._add_section(
                "", "\U0001f464  Driver / Cardholder", cols, rows, summary=True)

        if is_vu:
            try:
                sensor = data.get("sensor_info") or {}
                if sensor:
                    cols, rows = self._build_sensor_summary(data)
                    self._auto_select_iid = self._add_section(
                        "", "\U0001f4e1  Sensor", cols, rows, summary=True)
                else:
                    cols, rows = self._build_vehicle_summary(data)
                    self._auto_select_iid = self._add_section(
                        "", "\U0001f69a  Vehicle", cols, rows, summary=True)
            except Exception:
                _log.debug("Vehicle section render failed: %s", traceback.format_exc())
            trep_report = meta.get("trep_report")
            if trep_report and trep_report.get("is_partial"):
                cols, rows = self._build_trep_summary(trep_report, meta)
                self._auto_select_iid = self._add_section(
                    "", "\u26a0\ufe0f  CORRUPTED / PARTIAL FILE", cols, rows,
                    summary=True)

        # ── Generations tree (single source of truth) ──
        generations = data.get("generations", {})
        for gen_name, gen_items in generations.items():
            if gen_name == "Security":
                continue  # handled by _populate_security
            if not isinstance(gen_items, dict) or not gen_items:
                continue

            annex_map = {
                "Generation 1": "Annex 1B",
                "Generation 2": "Annex 1C",
                "Generation 2.2": "Annex 1C \u00b7 2023/980",
            }
            annex = annex_map.get(gen_name, "")
            annex_suffix = f"  [{annex}]" if annex else ""
            gnode = self.tree.insert("", tk.END, text=f"\U0001f4e6  {gen_name}{annex_suffix}")

            for item_name, item_data in gen_items.items():
                if item_name == "_RawTags":
                    continue
                if item_name in ("DriverActivityData", "Daily Activities") and isinstance(item_data, list):
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
                        cols, rows = (["Value"], [[fmt_val(v)] for v in item_data])
                elif isinstance(item_data, dict) and item_data:
                    if item_name == "ECDSA Signature Verification":
                        # certificate_temporal_validity has its own section
                        item_data = {k: v for k, v in item_data.items()
                                     if k != "certificate_temporal_validity"}
                    cols, rows = _kv_rows(item_data)
                else:
                    continue

                self._add_section(gnode, item_name, cols, rows)

        # ── Security ──
        self._populate_security(data)

        # Security section from generations tree (EF verification)
        sec = generations.get("Security") or {}
        if isinstance(sec, dict):
            for item_name, item_data in sec.items():
                if isinstance(item_data, dict) and item_data:
                    cols, rows = _kv_rows(item_data)
                    self._add_section("", f"\U0001f510  {item_name}", cols, rows)

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
        meta = f"{unknown_bytes:,} bytes undecoded".replace(",", " ")
        if total:
            meta += f"  \u00b7  {pct:.2f}% of file"
        # File-level coverage may report 0 unknown bytes when the undecoded
        # ranges live inside a decoded container (e.g. a VU CardDownload). Fall
        # back to the sum of the listed ranges so the count is never misleading.
        if not unknown_bytes:
            listed = sum(e.get("length", 0) for e in unparsed
                         if isinstance(e, dict))
            meta = f"{listed:,} bytes undecoded".replace(",", " ")
            if total:
                meta += f"  \u00b7  {listed / total * 100:.2f}% of file"
        columns = (["Location", "Offset", "Length", "Hex"] if has_container
                   else ["Offset", "Length", "Hex"])
        self._add_section("", "\U0001f9e9  Raw / Unparsed Data",
                          columns, rows, meta=meta)

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
        gnode = self.tree.insert("", tk.END, text="\U0001f510  Security & Certificates")
        if efv:
            ef_summary = {
                "Summary": efv.get("summary", ""),
                "Verified": efv.get("verified"),
                "Failed": efv.get("failed"),
                "Skipped": efv.get("skipped"),
                "Total": efv.get("total"),
            }
            cols, rows = _kv_rows(ef_summary)
            self._add_section(gnode, "EF Signatures (Card Data Integrity)", cols, rows)
            ef_results = efv.get("ef_results") or []
            if ef_results:
                cols, rows = _rows_for(ef_results, None)
                self._add_section(gnode, "EF Signature Details", cols, rows)
        if cvc:
            cols, rows = _rows_for(cvc, None)
            self._add_section(gnode, "CVC Certificates (decoded)", cols, rows,
                              meta="Appendix 11 \u00b7 CAR=issuing authority, "
                                   "CHR=holder, validity from TimeReal")
        if sv:
            summary = {
                "Available": sv.get("available"),
                "MSCA\u2192VU chain": sv.get("msca_to_vu"),
                "Anchored to ERCA root": sv.get("root_anchored"),
                "All TREP signatures valid": sv.get("all_treps_valid"),
                "Summary": sv.get("summary", ""),
            }
            cols, rows = _kv_rows(summary)
            self._add_section(gnode, "Signature Verification", cols, rows)
            treps = sv.get("treps") or []
            if treps:
                cols, rows = _rows_for(treps, None)
                self._add_section(gnode, "Section Signatures (TREP)", cols, rows)
        if certs:
            cols, rows = _rows_for(certs, None)
            self._add_section(gnode, "Certificates", cols, rows)
        if chip:
            cols, rows = _kv_rows(chip)
            self._add_section(gnode, "IC Chip (EF_ICC / EF_IC)", cols, rows)
        if icc:
            cols, rows = _kv_rows(icc)
            self._add_section(gnode, "ICC Identification", cols, rows)
        for auth_key, auth_label in [("gnss_auth", "GNSS Authentication (0x960F)"),
                                      ("load_unload_auth", "Load/Unload Authentication (0x6399)")]:
            auth_data = data.get(auth_key) or []
            if auth_data:
                cols, rows = _rows_for(auth_data, None)
                self._add_section(gnode, auth_label, cols, rows,
                                  meta="BER-TLV walk \u00b7 spec Appendix 11 not public")

    # ── Dashboard views ──────────────────────────────────

    def _show_dashboard(self, title, date_range, kpis, columns, rows,
                        row_tags=None, tooltips=None, ev_tooltips=None):
        """Render a summary dashboard with KPI cards and sortable table."""
        self._cleanup_dashboard()
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
        self.table._all_rows = [list(r) for r in rows]
        self.table._sort_state = {}
        self.table._fitted = False
        self.table._summary_mode = False

        self.table.filt_bar.pack_forget()

        kpi_frame = tk.Frame(self.table, bg="#f0f0f0")
        kpi_frame.pack(fill=tk.X, padx=8, pady=(4, 12), before=self.table.tv.master)
        self._kpi_frame = kpi_frame

        num_cols = min(len(kpis), 4)
        for i, (label, value, accent) in enumerate(kpis):
            row_idx = i // num_cols
            col_idx = i % num_cols
            card = tk.Frame(kpi_frame, bg="#f8f9fa",
                            highlightbackground="#d0d0d0",
                            highlightthickness=1, padx=14, pady=10)
            card.grid(row=row_idx, column=col_idx, padx=5, pady=5,
                      sticky="nsew")
            tk.Label(card, text=label, font=("", 9), fg="#6b7280",
                     bg="#f8f9fa", anchor=tk.W).pack(anchor=tk.W)
            tk.Label(card, text=value, font=("", 14, "bold"), fg=accent,
                     bg="#f8f9fa", anchor=tk.W).pack(anchor=tk.W)

        for c in range(num_cols):
            kpi_frame.columnconfigure(c, weight=1, uniform="kpi")

        self.table.tv["columns"] = self.table._cols
        for c in self.table._cols:
            self.table.tv.heading(c, text=str(c),
                                  command=lambda col=c: self.table._sort_by(col))
            min_w = max(len(str(c)) * _px(9) + _px(20), _px(60))
            anchor = tk.W if c == "Date" else tk.CENTER
            self.table.tv.column(c, minwidth=min_w, anchor=anchor, stretch=True)

        self.table.tv.tag_configure("total",
                                    font=("", 10, "bold"),
                                    foreground="#1565c0",
                                    background="#e3e9f2")
        self.table.tv.tag_configure("separator", background="#f0f0f0")

        # Render with row tags
        row_tags = row_tags or [None] * len(rows)
        self.table.tv.delete(*self.table.tv.get_children())
        for i, r in enumerate(self.table._all_rows):
            tag = "even" if i % 2 == 0 else "odd"
            rt = row_tags[i] if i < len(row_tags) else None
            if rt == "total":
                tag = "total"
            elif rt == "separator":
                tag = "separator"
            self.table.tv.insert("", tk.END, values=r, tags=(tag,))

        # Tooltips for # Drivers / # Vehicles column
        self._dashboard_tooltips = tooltips or {}
        self._dashboard_drv_col = -1
        for name in ("# Drivers", "# Vehicles"):
            if name in columns:
                self._dashboard_drv_col = columns.index(name)
                break
        # Tooltips for Ev column
        self._dashboard_ev_col = columns.index("Ev") if "Ev" in columns else -1
        self._dashboard_ev_tips = ev_tooltips or {}
        self._dashboard_motion_bind = self.table.tv.bind(
            "<Motion>", self._on_dashboard_motion, add="+")
        self._tooltip_lbl = tk.Label(self.table.tv, text="", bg="#ffffcc",
                                     relief=tk.SOLID, borderwidth=1, font=("", 9),
                                     fg="#37474f", padx=6, pady=2)

        self.table.tv.update_idletasks()
        self.table._fit_columns()
        self.table.tv.update()
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
        changes = day_data.get("changes", [])
        if is_vu:
            slot_name = "First" if getattr(self, "_vu_slot_filter", "Slot 1") == "Slot 1" else "Second"
            changes = [c for c in changes
                       if isinstance(c, dict) and str(c.get("slot") or "") == slot_name]
        day_km = day_data.get("_day_km", 0) or day_data.get("odometer_km", 0) or 0
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
            sd = _parse_iso(sess.get("start"))
            ed = _parse_iso(sess.get("end"))
            anchor = sd or ed
            if not anchor:
                continue
            if anchor.date().isoformat() == iso_date:
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
            name = f"{rec.get('holder_surname','')} {rec.get('holder_first_names','')}".strip()
            if not name or name == "N/A N/A":
                name = rec.get("card_number", "") or "Sconosciuto"
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

        DayDetailWindow(self, date_str, changes, day_km, changes_count,
                        driver_name, slot_schedule, markers, oos_events,
                        day_vehicles, data, is_vu=is_vu)

    def _on_dashboard_motion(self, event):
        drv_col = getattr(self, "_dashboard_drv_col", -1)
        ev_col = getattr(self, "_dashboard_ev_col", -1)
        if drv_col < 0 and ev_col < 0:
            return
        row_id = self.table.tv.identify_row(event.y)
        col_id = self.table.tv.identify_column(event.x)
        col_idx = int(col_id.replace("#", "")) - 1 if col_id else -1
        if not row_id or (col_idx != drv_col and col_idx != ev_col):
            self._tooltip_lbl.place_forget()
            return
        for i, iid in enumerate(self.table.tv.get_children("")):
            if iid == row_id:
                if col_idx == drv_col:
                    tip = self._dashboard_tooltips.get(i, "")
                else:
                    ev_tips = getattr(self, "_dashboard_ev_tips", {}) or {}
                    tip = ev_tips.get(i, "")
                if tip:
                    self._tooltip_lbl.config(text=tip, justify=tk.LEFT,
                                             wraplength=380)
                    self._tooltip_lbl.place(x=event.x + 16, y=event.y + 16)
                else:
                    self._tooltip_lbl.place_forget()
                return
        self._tooltip_lbl.place_forget()

    def _cleanup_dashboard(self):
        """Destroy any KPI card frame left over from a previous dashboard view."""
        if getattr(self, "_kpi_frame", None) is not None:
            self._kpi_frame.destroy()
            self._kpi_frame = None
        if getattr(self, "_slot_toggle_frame", None) is not None:
            self._slot_toggle_frame.destroy()
            self._slot_toggle_frame = None
        if getattr(self, "_tooltip_lbl", None) is not None:
            self._tooltip_lbl.place_forget()
        bind_id = getattr(self, "_dashboard_motion_bind", None)
        if bind_id is not None:
            try:
                self.table.tv.unbind("<Motion>", bind_id)
            except Exception:
                pass
            self._dashboard_motion_bind = None

    def _show_daily_summary(self, activity_list, data, _fast_refresh=False):
        """Dashboard for the 'Daily Activities' parent node.
        When ``_fast_refresh=True``, skips the full layout rebuild and only
        updates table rows and KPI labels in place (used by the slot toggle)."""
        valid = [d for d in activity_list if isinstance(d, dict)]
        if not valid:
            self._show_empty("Daily Activities", "No activity data available.")
            return
        is_vu = (data.get("metadata") or {}).get("is_vu", False)

        # ── Slot filter for VU files ──
        slot_label = getattr(self, "_vu_slot_filter", "Slot 1")
        slot_name = "First" if slot_label == "Slot 1" else "Second"

        # Build a filtered view: each day's changes limited to the chosen slot
        if is_vu:
            filtered = []
            for day_data in valid:
                all_changes = day_data.get("changes", [])
                filtered_changes = [c for c in all_changes
                                    if isinstance(c, dict) and str(c.get("slot") or "") == slot_name]
                copy = dict(day_data)
                copy["changes"] = filtered_changes
                filtered.append(copy)
            valid = filtered

        # Per-day driver names from card_iw, filtered by selected slot
        iw_by_date = {}
        if is_vu:
            # Build a lookup: (date_iso, minute_of_day) -> slot
            # from the original unfiltered activity changes
            slot_by_minute: dict[tuple[str, int], str] = {}
            for day_data in activity_list:
                if not isinstance(day_data, dict):
                    continue
                date_str = str(day_data.get("date", ""))
                date_iso = _activity_to_iso(date_str)
                for ch in day_data.get("changes", []):
                    if not isinstance(ch, dict):
                        continue
                    if not ch.get("card_inserted"):
                        continue
                    t = ch.get("time", "")
                    if isinstance(t, str) and ":" in t:
                        try:
                            h, m = t.split(":")[:2]
                            minute = int(h) * 60 + int(m)
                            slot = str(ch.get("slot") or "")
                            if slot:
                                slot_by_minute[(date_iso, minute)] = slot
                        except ValueError:
                            pass

            iw_records = data.get("card_iw_records") or []
            for iw in iw_records:
                if not isinstance(iw, dict):
                    continue
                name = f"{iw.get('holder_first_names','')} {iw.get('holder_surname','')}".strip()
                if not name or name == "N/A N/A":
                    continue
                ins_str = iw.get("insertion_time", "")
                ins_dt = None
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        ins_dt = datetime.strptime(ins_str[:19], fmt)
                    except (ValueError, IndexError):
                        pass
                if ins_dt is None:
                    continue
                wit_str = iw.get("withdrawal_time", "")
                wit_dt = None
                if isinstance(wit_str, str) and wit_str:
                    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                        try:
                            wit_dt = datetime.strptime(wit_str[:19], fmt)
                        except (ValueError, IndexError):
                            pass
                if wit_dt is None:
                    wit_dt = ins_dt.replace(hour=23, minute=59, second=59)
                current = ins_dt
                while current.date() <= wit_dt.date():
                    day_iso = current.date().isoformat()
                    # Determine which slot this driver is in on this day
                    ins_minute = ins_dt.hour * 60 + ins_dt.minute if current.date() == ins_dt.date() else 0
                    iw_slot = ""
                    # Look for a card_inserted event within 2 minutes on the insertion day
                    if current.date() == ins_dt.date():
                        for offset in range(-2, 3):
                            check_min = ins_minute + offset
                            if 0 <= check_min < 1440:
                                iw_slot = slot_by_minute.get((day_iso, check_min), "")
                                if iw_slot:
                                    break
                    if not iw_slot:
                        # Fallback: use card_inserted from any time on this day
                        for (d, _m), s in slot_by_minute.items():
                            if d == day_iso:
                                iw_slot = s
                                break
                    iw_slot_name = "First" if iw_slot == "First" else ("Second" if iw_slot == "Second" else "")
                    if iw_slot_name and iw_slot_name == slot_name:
                        iw_by_date.setdefault(day_iso, set()).add(name)
                    current = datetime(current.year, current.month, current.day,
                                        tzinfo=timezone.utc) + timedelta(days=1)

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
            desc = ev.get("description", "Unknown event")
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
        MONTH_NAMES = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                       7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

        sort_key = lambda d: _activity_to_iso(str(d.get("date", "")))
        sorted_asc = sorted(valid, key=sort_key)

        # Daily km from odometer deltas (chronological). VU days already carry
        # a precomputed "_day_km"; for card files derive the distance from the
        # midnight/odometer reading delta between consecutive days rather than
        # showing the absolute odometer as if it were a daily distance.
        card_day_km = {}
        if not is_vu:
            prev_odo = None
            for day_data in sorted_asc:
                cur_odo = (day_data.get("odometer_midnight")
                           or day_data.get("odometer_km") or 0) or 0
                if prev_odo is not None and cur_odo and prev_odo and cur_odo >= prev_odo:
                    card_day_km[id(day_data)] = cur_odo - prev_odo
                if cur_odo:
                    prev_odo = cur_odo

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
        table_rows = []
        row_tags = []
        tooltips = {}
        ev_tooltips = {}
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
                changes = day_data.get("changes", [])
                if is_vu:
                    day_km = day_data.get("_day_km", 0) or 0
                    odo = day_data.get("odometer_km", 0) or 0
                else:
                    day_km = card_day_km.get(id(day_data), 0)
                    odo = 0
                day_tots = _compute_activity_totals(changes)
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
                ev_str = "\u26a0\ufe0f" if iso_date in event_dates else ""
                if is_vu:
                    odo_str = f"{odo:,}".replace(",", " ") if odo else ""
                    table_rows.append([
                        date_str, f"{n_drv}\u2002\u25be", ev_str, km_str, odo_str,
                        _fmt_duration_minutes(day_tots["DRIVE"]),
                        _fmt_duration_minutes(day_tots["WORK"]),
                        _fmt_duration_minutes(day_tots["REST"]),
                        _fmt_duration_minutes(day_tots["AVAILABLE"]),
                    ])
                else:
                    day_vehicles = veh_by_date.get(iso_date, set())
                    n_day_veh = len(day_vehicles) or n_veh
                    table_rows.append([
                        date_str, f"{n_day_veh}\u2002\u25be", ev_str, km_str,
                        _fmt_duration_minutes(day_tots["DRIVE"]),
                        _fmt_duration_minutes(day_tots["WORK"]),
                        _fmt_duration_minutes(day_tots["REST"]),
                        _fmt_duration_minutes(day_tots["AVAILABLE"]),
                    ])
                row_tags.append(None)
                if is_vu and names:
                    tooltips[row_idx] = names
                elif not is_vu and card_vehicle_tip:
                    tooltips[row_idx] = card_vehicle_tip
                if iso_date in event_dates:
                    ev_list = events_by_date.get(iso_date, [])
                    ev_text = "\n".join(ev_list)
                    ev_text += "\n\n\u2139\ufe0f  Double-click for full details"
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

        date_range = f"{sorted_asc[0].get('date', '?')}  \u2192  {sorted_asc[-1].get('date', '?')}  \u00b7  {day_count} days"

        kpis = [
            ("Drive", _fmt_duration_minutes(totals_global["DRIVE"]), "#1565c0"),
            ("Work", _fmt_duration_minutes(totals_global["WORK"]), "#ef6c00"),
            ("Rest", _fmt_duration_minutes(totals_global["REST"]), "#78909c"),
            ("Available", _fmt_duration_minutes(totals_global["AVAILABLE"]), "#f9a825"),
            ("Days", str(day_count), "#37474f"),
            ("Avg Drive / day", _fmt_duration_minutes(avg_drive), "#1565c0"),
            ("Max Drive / day", _fmt_duration_minutes(max_drive), "#1565c0"),
        ]
        if is_vu:
            kpis.append(("Drivers", str(driver_count), "#37474f"))
        else:
            all_vehicles = set()
            for plates in veh_by_date.values():
                all_vehicles.update(plates)
            kpis.append(("Vehicles", str(len(all_vehicles) or n_veh), "#37474f"))

        if is_vu:
            columns = ["Date", "# Drivers", "Ev", "Km", "Odometer",
                       "Drive", "Work", "Rest", "Available"]
        else:
            columns = ["Date", "# Vehicles", "Ev", "Km",
                       "Drive", "Work", "Rest", "Available"]
        if _fast_refresh:
            self._update_dashboard_in_place(
                date_range, kpis, table_rows, row_tags,
                columns, tooltips, ev_tooltips, activity_list, data)
        else:
            self._show_dashboard("Daily Activities",
                                 date_range, kpis, columns, table_rows,
                                 row_tags=row_tags, tooltips=tooltips,
                                 ev_tooltips=ev_tooltips)

            self._dashboard_activity_list = activity_list
            self._dashboard_data = data
            self._dashboard_is_vu = is_vu
            self.table.tv.unbind("<Double-1>")
            self.table.tv.bind("<Double-1>",
                               lambda e: self._on_dashboard_double_click(e))

            # ── Slot toggle for VU files ──
            if is_vu:
                self._build_vu_slot_toggle(activity_list, data)

    def _update_dashboard_in_place(
            self, date_range, kpis, table_rows, row_tags,
            columns, tooltips, ev_tooltips, activity_list, data):
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
                        for lbl, val, _accent in kpis:
                            if lbl == label_text:
                                labels[1].config(text=val)
                                break

        # Refresh table
        self.table._all_rows = [list(r) for r in table_rows]
        self.table.tv.delete(*self.table.tv.get_children())
        for i, r in enumerate(self.table._all_rows):
            tag = "even" if i % 2 == 0 else "odd"
            rt = row_tags[i] if i < len(row_tags) else None
            if rt == "total":
                tag = "total"
            elif rt == "separator":
                tag = "separator"
            self.table.tv.insert("", tk.END, values=r, tags=(tag,))

        # Tooltips
        self._dashboard_tooltips = tooltips or {}
        self._dashboard_ev_tips = ev_tooltips or {}

        # Update slot label in toggle bar
        slot_frame = getattr(self, "_slot_toggle_frame", None)
        if slot_frame is not None:
            slot_label = getattr(self, "_vu_slot_filter", "Slot 1")
            for child in slot_frame.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(text=slot_label)
                    break

    def _build_vu_slot_toggle(self, activity_list, data):
        """Add a Slot 1 / Slot 2 toggle button above the daily activities table."""
        slot_label = getattr(self, "_vu_slot_filter", "Slot 1")
        if getattr(self, "_slot_toggle_frame", None) is not None:
            self._slot_toggle_frame.destroy()
        btn_frame = tk.Frame(self.table, bg="#f4f6f9")
        self._slot_toggle_frame = btn_frame
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 4), before=self.table.tv.master)

        tk.Label(btn_frame, text=slot_label, font=("", 10, "bold"),
                 fg="#1565c0", bg="#f4f6f9").pack(side=tk.LEFT)

        def _toggle():
            current = getattr(self, "_vu_slot_filter", "Slot 1")
            new_slot = "Slot 2" if current == "Slot 1" else "Slot 1"
            self._vu_slot_filter = new_slot
            self._show_daily_summary(activity_list, data, _fast_refresh=True)

        tk.Button(btn_frame, text="\u21c4", font=("", 10),
                  bg="#e8edf2", fg="#37474f", relief=tk.FLAT,
                  padx=8, pady=0, activebackground="#dbe4f0",
                  activeforeground="#1565c0", cursor="hand2",
                  command=_toggle).pack(side=tk.RIGHT)

    def _show_speed_summary(self, raw_blocks, data):
        """Dashboard for the 'Detailed Speed' parent node."""
        all_blocks = list(raw_blocks or [])
        all_blocks += list(data.get("speed_blocks") or [])

        by_day = detailed_speed_by_day(data)
        if not by_day:
            self._show_empty("Detailed Speed", "No detailed speed samples available.")
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
            speeds = [s for _, s in samples if isinstance(s, (int, float))]
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
            over_secs = sum(1 for _, s in samples if isinstance(s, (int, float)) and s > 90)
            overspeed_seconds += over_secs

            # Overspeed events (contiguous runs > 90)
            events = 0
            in_over = False
            for _, s in samples:
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
                _fmt_duration_minutes(over_secs // 60),
                str(events),
            ])

        global_avg = total_speed_sum / total_samples if total_samples else 0
        if min_daily_avg == float("inf"):
            min_daily_avg = 0
        days = sorted(by_day, reverse=True)
        day_count = len(days)
        date_range = f"{days[-1]}  \u2192  {days[0]}  \u00b7  {day_count} days"

        kpis = [
            ("Days", str(day_count), "#37474f"),
            ("Max speed", f"{global_max:.0f} km/h", "#1565c0"),
            ("Avg speed", f"{global_avg:.1f} km/h", "#37474f"),
            ("Samples", f"{total_samples:,}".replace(",", " "), "#37474f"),
            ("Time >90 km/h", _fmt_duration_minutes(overspeed_seconds // 60), "#d32f2f"),
            ("Overspeed events", str(overspeed_events), "#d32f2f"),
            ("Max avg / day", f"{max_daily_avg:.1f} km/h", "#1565c0"),
            ("Min avg / day", f"{min_daily_avg:.1f} km/h", "#78909c"),
        ]

        columns = ["Date", "Max km/h", "Avg km/h", "Samples", ">90 km/h", "Events"]
        self._show_dashboard("Detailed Speed",
                             date_range, kpis, columns, table_rows)

    # ── Selection → table ──────────────────────────────────

    def _on_tree_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        payload = self._payloads.get(iid)
        if not payload or payload[0] != "__activity_chart__":
            return
        day, is_vu, activities, day_km, changes_count, driver_info, slot_schedule, markers, oos_events, vehicle_info = payload[1:]
        data = getattr(self, "_opened_data", None) or {}
        DayDetailWindow(self, day, activities, day_km, changes_count,
                        driver_info, slot_schedule, markers, oos_events,
                        vehicle_info, data, is_vu=is_vu)

    def _on_tree_select(self, _event):
        """Tree selection → show the node's stored payload in the table."""
        sel = self.tree.selection()
        if not sel:
            return
        payload = self._payloads.get(sel[0])
        if payload:
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
                label, cols, rows, meta, _ = payload
                self._show_summary(label, cols, rows, meta)
            else:
                label, cols, rows, meta = payload[:4]
                self._show_table(label, cols, rows, meta)
        else:
            children = self.tree.get_children(sel[0])
            rows = [[self.tree.item(c, "text")] for c in children]
            self._show_table(self.tree.item(sel[0], "text").strip(),
                             ["Sub-section"], rows)

    def _show_table(self, title, cols, rows, meta=""):
        self._cleanup_dashboard()
        self.speed_chart.pack_forget()
        self.activity_chart.pack_forget()
        if not self.table.winfo_manager():
            self.table.pack(fill=tk.BOTH, expand=True)
        self.table.show(title, cols, rows, meta)

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
        self.table.pack_forget()
        self.activity_chart.pack_forget()
        self.speed_chart.pack(fill=tk.BOTH, expand=True)
        self.speed_chart.show(day, samples, overspeeding_events,
                              speed_limit=self._authorised_speed_limit())

    def _show_activity_chart(self, day, is_vu, activities, day_km,
                             changes_count, driver_info, slot_schedule, markers,
                             oos_events=None, vehicle_info=None):
        self._cleanup_dashboard()
        self.table.pack_forget()
        self.speed_chart.pack_forget()
        self.activity_chart.pack(fill=tk.BOTH, expand=True)
        self.activity_chart.show(day, is_vu, activities, day_km,
                                 changes_count, driver_info, slot_schedule, markers,
                                 vehicle_info, oos_events,
                                 data=getattr(self, "_opened_data", None) or {})

    def _show_summary(self, title, cols, rows, meta):
        """Render a rich info panel with section headers instead of a data table."""
        self._cleanup_dashboard()
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
        self.table.tv.heading("Field", text="")
        self.table.tv.heading("Value", text="")
        self.table.tv.column("Field", width=_px(220), minwidth=_px(140), anchor=tk.W, stretch=False)
        self.table.tv.column("Value", width=_px(100), minwidth=_px(60), anchor=tk.W, stretch=True)
        self.table._fitted = True
        self.table._summary_mode = True
        self.table._render(self.table._all_rows, summary=True)
        self.table.filt_bar.pack_forget()

    # ── Summary builders ──────────────────────────────────────

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
        sep = ("\u2500" * 40, "", True)

        rows.append(("\U0001f697  VEHICLE", "", True))
        rows.append(("  Plate", plate, False))
        rows.append(("  VIN", vin, False))
        if nation and nation not in ("N/A", ""):
            rows.append(("  Registration", nation_full_name(nation), False))
        rows.append(sep)

        if calibrations:
            cal = calibrations[0] if isinstance(calibrations[0], dict) else {}
            # Check if calibration is expired for the header icon
            cal_expired = False
            cal_soon = False
            days_left = 0
            next_date = cal.get("next_calibration_date")
            if next_date:
                try:
                    from datetime import datetime, timezone
                    if isinstance(next_date, str):
                        # ISO format (G2): 2025-01-21T09:04:31+00:00
                        # G1 format: 27/01/2018 or 27/01/2018 09:04
                        try:
                            nd = datetime.fromisoformat(next_date.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            try:
                                nd = datetime.strptime(next_date[:10], "%d/%m/%Y")
                                nd = nd.replace(tzinfo=timezone.utc)
                            except (ValueError, TypeError):
                                raise
                    else:
                        nd = next_date
                    days_left = (nd - datetime.now(timezone.utc)).days
                    cal_expired = days_left < 0
                    cal_soon = 0 <= days_left < 90
                except Exception:
                    pass
            icon = "\u274c " if cal_expired else ("\u26a0\ufe0f " if cal_soon else "")
            rows.append(("\U0001f527  " + icon + "TACHOGRAPH", "", True))
            # Tachograph device identity (from VuIdentification, fallback vu_info).
            vu_id = (data.get("vu_identifications") or [{}])[0] if data.get("vu_identifications") else {}
            tacho_make = (vu_id.get("manufacturer_name") or vu_info.get("manufacturer")
                          or vu_info.get("manufacturer_name") or "")
            tacho_sw = vu_id.get("software_version") or vu_info.get("software_version") or ""
            tacho_serial = (vu_id.get("serial_number") or vu_info.get("serial_number")
                            or vu_info.get("sensor_serial_number") or "")
            if tacho_make:
                rows.append(("  Make", tacho_make, False))
            if tacho_sw:
                rows.append(("  Software version", tacho_sw, False))
            if tacho_serial:
                rows.append(("  Serial number", tacho_serial, False))
            if next_date:
                date_str = fmt_val(next_date)
                if cal_expired:
                    date_str += f"  \u274c EXPIRED ({abs(days_left)} days ago)"
                elif cal_soon:
                    date_str += f"  \u26a0\ufe0f  Due in {days_left} days"
                rows.append(("  Next calibration", date_str, False))
            tyre = cal.get("tyre_size", "")
            speed = cal.get("authorised_speed_kmh", "")
            if tyre:
                rows.append(("  Tyre size", tyre, False))
            if speed:
                rows.append(("  Authorised speed", f"{speed} km/h", False))
            rows.append(sep)

        if sensors:
            s = sensors[0] if isinstance(sensors[0], dict) else {}
            rows.append(("\U0001f4e1  SENSOR", "", False))
            serial = s.get("sensor_serial", "")
            if serial:
                rows.append(("  Serial", serial, False))
            approval = s.get("sensor_approval", "")
            if approval:
                rows.append(("  Approval", approval, False))
            pairing = s.get("pairing_date", "")
            if pairing:
                rows.append(("  Paired", fmt_val(pairing), False))

            gnss_sensors = data.get("sensor_gnss_couplings") or []
            if gnss_sensors:
                g = gnss_sensors[0] if isinstance(gnss_sensors[0], dict) else {}
                gserial = g.get("sensor_gnss_serial", g.get("sensor_serial", ""))
                if gserial:
                    rows.append(("  GNSS Serial", gserial, False))
            rows.append(sep)

        if vu_info:
            rows.append(("\U0001f4bb  VU INFO", "", True))
            # G1 VU keys (Mass Memory / old Continental VDO format)
            manufacturer = vu_info.get("manufacturer", vu_info.get("manufacturer_name", ""))
            if manufacturer:
                rows.append(("  Manufacturer", manufacturer, False))
            part = vu_info.get("part_number", "")
            if part:
                rows.append(("  Part number", part, False))
            serial = vu_info.get("serial_number", vu_info.get("sensor_serial_number", ""))
            if serial:
                rows.append(("  Serial", serial, False))
            sw = vu_info.get("software_version", "")
            if sw:
                rows.append(("  Software version", sw, False))
            approval = vu_info.get("approval_number", "")
            if approval:
                rows.append(("  Approval", approval, False))
            gen = vu_info.get("vu_generation", "")
            if gen and gen not in ("N/A", "", None):
                rows.append(("  Generation", str(gen), False))
            ability = vu_info.get("vu_ability", "")
            if ability and ability not in ("N/A", "", None):
                rows.append(("  Ability", str(ability), False))
            map_ver = vu_info.get("digital_map_version", "")
            if map_ver and map_ver not in ("N/A", ""):
                rows.append(("  Digital map", map_ver, False))
            mfg_date = vu_info.get("manufacturing_date", "")
            if mfg_date:
                rows.append(("  Manufactured", mfg_date, False))
            sw_date = vu_info.get("software_install_date", vu_info.get("software_installation_date", ""))
            if sw_date:
                rows.append(("  SW installed", sw_date, False))
            sensor_serial = vu_info.get("sensor_serial_number", "")
            if sensor_serial and sensor_serial != serial:
                rows.append(("  Sensor serial", sensor_serial, False))
            sensor_approval = vu_info.get("sensor_approval_number", "")
            if sensor_approval:
                rows.append(("  Sensor approval", sensor_approval, False))
            sensor_pairing = vu_info.get("sensor_pairing_date", "")
            if sensor_pairing:
                rows.append(("  Sensor paired", sensor_pairing, False))
            rows.append(sep)

        # Current company lock
        locks = data.get("company_locks") or []
        active_lock = None
        for lock in locks:
            if isinstance(lock, dict) and lock.get("lock_out_time") is None:
                active_lock = lock
                break
        if active_lock:
            rows.append(("\U0001f512  CURRENT LOCK", "", True))
            name = active_lock.get("company_name", "")
            if name:
                rows.append(("  Company", name, False))
            addr = active_lock.get("company_address", "")
            if addr:
                rows.append(("  Address", addr, False))
            lock_in = active_lock.get("lock_in_time", "")
            if lock_in:
                rows.append(("  Locked since", fmt_val(lock_in), False))
            card = active_lock.get("company_card", "")
            if isinstance(card, dict):
                card_str = card.get("card_number", "")
                if card_str:
                    rows.append(("  Lock card", card_str, False))
        elif locks:
            rows.append(("\U0001f513  CURRENT LOCK", "", True))
            rows.append(("  Status", "Not locked", False))

        # Activity summary
        activities = len(data.get("activities") or [])
        events = len(data.get("events") or [])
        faults = len(data.get("faults") or [])
        if activities or events:
            if rows and rows[-1] != sep:
                rows.append(sep)
            rows.append(("\U0001f4ca  STATISTICS", "", False))
            rows.append(("  Days with activities", str(activities), False))
            rows.append(("  Events", str(events), False))
            rows.append(("  Faults", str(faults), False))

        cols = ["Field", "Value"]
        return cols, rows

    def _build_trep_summary(self, trep_report, meta=None):
        """Warning page shown only for corrupted/partial downloads: explains
        what is present, what is missing/corrupted, and that only the listed
        parts of the file could be recovered."""
        meta = meta or {}
        rows = []
        sep = ("\u2500" * 40, "", True)

        rows.append(("\u26a0\ufe0f  THIS FILE IS INCOMPLETE OR CORRUPTED", "", True))
        rows.append(("  Only the sections listed below could be read.", "", False))
        rows.append(("  Missing or corrupted data is NOT shown.", "", False))
        rows.append(sep)

        rows.append(("\U0001f4ca  COMPLETENESS", "", True))
        rows.append((
            "  Mandatory sections read",
            f"{trep_report['mandatory_ok']}/{trep_report['mandatory_total']} "
            f"({trep_report['completeness_pct']}%)", False))
        if not trep_report.get("complete_walk", True):
            rows.append(("  File structure", "\u274c  Truncated (did not reach end of file)", False))
        rows.append(sep)

        present = trep_report.get("present") or []
        rows.append(("\u2705  SECTIONS PRESENT", "", True))
        if present:
            for t in present:
                rows.append((f"  {t['name']}", t["trep"], False))
        else:
            rows.append(("  (none)", "", False))
        rows.append(sep)

        missing = trep_report.get("mandatory_missing") or []
        if missing:
            rows.append(("\u274c  MISSING MANDATORY SECTIONS", "", True))
            for t in missing:
                rows.append((f"  {t['name']}", t["trep"], False))
            rows.append(sep)

        suspect = trep_report.get("decoded_suspect") or []
        if suspect:
            rows.append(("\u26a0\ufe0f  CORRUPTED SECTIONS (data discarded)", "", True))
            for t in suspect:
                rows.append((f"  {t['name']}", t["trep"], False))
            rows.append(sep)

        salvaged = meta.get("salvage_recovered") or []
        if salvaged:
            rows.append(("\U0001f6e0\ufe0f  RECOVERED FROM DAMAGED DATA", "", True))
            rows.append(("  Low-confidence recovery", ", ".join(salvaged), False))

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
        sep = ("\u2500" * 40, "", True)

        rows.append(("\U0001f4e1  SENSOR", "", True))
        approval = sensor.get("sensor_approval", "")
        nation = sensor.get("approval_nation", "")
        if approval:
            rows.append(("  Approval", f"{approval}", False))
        if nation:
            rows.append(("  Nation", nation_full_name(nation), False))
        prefix = sensor.get("approval_prefix", "")
        if prefix:
            rows.append(("  Prefix", prefix, False))
        rows.append(sep)

        rows.append(("\U0001f697  ASSOCIATED VEHICLE", "", True))
        rows.append(("  Plate", plate, False))
        rows.append(("  VIN", vin, False))
        rows.append(sep)

        rows.append(("\U0001f4c5  DATE RANGE", "", True))
        first = sensor.get("first_date", "N/A")
        last = sensor.get("last_date", "N/A")
        rows.append(("  First date", first, False))
        rows.append(("  Last date", last, False))
        if daily:
            unique = sorted(set(d.get("date", "") for d in daily))
            rows.append(("  Days recorded", str(len(unique)), False))
            if len(unique) >= 2:
                rows.append(("  Actual range", f"{unique[0]} \u2192 {unique[-1]}", False))
        rows.append(sep)

        rows.append(("\U0001f4ca  PARAMETERS", "", True))
        spd_max = sensor.get("param_speed_max_kmh", "")
        spd_avg = sensor.get("param_speed_avg_kmh", "")
        dist = sensor.get("param_distance_km", "")
        if spd_max:
            rows.append(("  Max speed", f"{spd_max} km/h", False))
        if spd_avg:
            rows.append(("  Avg speed", f"{spd_avg} km/h", False))
        if dist:
            rows.append(("  Distance", f"{dist} km", False))

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
        sep = ("\u2500" * 40, "", True)

        rows.append(("\U0001f464  CARDHOLDER", "", True))
        surname = driver.get("surname", "")
        firstname = driver.get("firstname", "")
        name = f"{firstname} {surname}".strip()
        if name:
            rows.append(("  Name", name, False))
        rows.append(("  Card number", driver.get("card_number", "N/A"), False))
        rows.append(sep)

        rows.append(("\U0001faaa  CARD DETAILS", "", True))
        nation = driver.get("issuing_nation", "")
        if nation:
            rows.append(("  Issuing nation", nation_full_name(nation), False))
        authority = driver.get("issuing_authority", "")
        if authority and authority != "N/A":
            rows.append(("  Issuing authority", authority, False))
        issue_date = driver.get("issue_date", "")
        if issue_date:
            rows.append(("  Issue date", issue_date, False))
        validity_begin = driver.get("validity_begin", "")
        if validity_begin:
            rows.append(("  Valid from", validity_begin, False))
        expiry = driver.get("expiry_date", "")
        if expiry:
            rows.append(("  Expiry date", expiry, False))
        birth = driver.get("birth_date", "")
        if birth:
            rows.append(("  Birth date", birth, False))
        licence = driver.get("licence_number", "")
        if licence and licence != "N/A":
            rows.append(("  Licence number", licence, False))
        language = driver.get("preferred_language", "")
        if language and language != "N/A":
            rows.append(("  Language", language, False))
        rows.append(sep)

        rows.append(("\U0001f4ca  STATISTICS", "", True))
        act_days = len(activities)
        total_changes = sum(len(a.get("changes", [])) for a in activities if isinstance(a, dict))
        rows.append(("  Days with activity", str(act_days), False))
        rows.append(("  Activity changes", str(total_changes), False))
        rows.append(("  Events", str(len(events)), False))
        if cards:
            rows.append(("  Card downloads", str(len(cards)), False))

        if efv.get("summary"):
            rows.append(sep)
            rows.append(("\U0001f510  SIGNATURES", "", True))
            rows.append(("  EF verification", efv["summary"], False))

        cols = ["Field", "Value"]
        return cols, rows


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
        result = TachoParser(path).parse()
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
    _emit(f"SMOKE OK: v{__version__} gen={meta.get('generation')} "
          f"sections={len(result.get('raw_tags') or {})}")
    return 0


def main():
    # Minimal CLI surface so CI can exercise the frozen GUI bundle headless.
    args = sys.argv[1:]
    if args[:1] == ["--version"]:
        _emit(f"TachoReader {__version__}")
        sys.exit(0)
    if args[:1] == ["--smoke"] and len(args) == 2:
        sys.exit(_smoke_check(args[1]))
    initial = args[0] if args and os.path.isfile(args[0]) else None
    TachoExplorer(initial_file=initial).mainloop()


if __name__ == "__main__":
    main()
