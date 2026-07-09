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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Windows High-DPI ────────────────────────────────────────────────────────
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
            dpi = windll.gdi32.GetDeviceCaps(hdc, 88) or 96  # LOGPIXELSX
            windll.user32.ReleaseDC(0, hdc)
            _WIN_SCALE = dpi / 96.0
    except Exception:
        _WIN_SCALE = 1.5  # fallback guess for >96 dpi

import tkinter as tk  # noqa: E402
from tkinter import ttk, filedialog, messagebox  # noqa: E402

from app.engine import TachoParser  # noqa: E402
from core.utils.encoding import BytesEncoder  # noqa: E402
from core.registry.models import _clean_tag_name  # noqa: E402
from core.utils.version import __version__  # noqa: E402
from core.utils.report_format import humanize_key, _NOT_AVAILABLE_INTS, _ISO_RE  # noqa: E402

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


# ── Section definitions (data-driven) ─────────────────────────────────────
#
# Each parser dict list entry becomes a table. Groups give the tree its
# regedit-style folder structure.

GROUPS = [
    ("g1", "\U0001f4e6  Generation 1 \u2014 Annex 1B"),
    ("g2", "\U0001f4e6  Generation 2 \u2014 Annex 1C"),
    ("g22", "\U0001f4e6  Generation 2.2 \u2014 Smart V2"),
]

# data_key → (label, group, optional transformer)
LIST_SECTIONS = [
    # "activities" handled separately (day hierarchy) — see _populate_activities

    # ── Generation 1 (Annex 1B) ──
    ("vehicle_sessions", "Vehicles Used", "g1", None),
    ("events", "Events", "g1", None),
    ("overspeeding_events", "Overspeeding Events", "g1", None),
    ("faults", "Faults", "g1", None),
    ("places", "Places", "g1", None),
    ("locations", "GPS Locations", "g1", None),
    ("specific_conditions", "Specific Conditions", "g1", None),
    ("calibrations", "Calibrations", "g1", None),
    ("card_downloads", "Card Downloads", "g1", None),
    ("control_activities", "Control Activities", "g1", None),
    ("workshops", "Calibration Workshops", "g1", None),
    ("previous_vehicle", "Previous Vehicle", "g1", None),
    ("company_holders", "Company Holders", "g1", None),

    ("vu_identifications", "VU Identification", "g1", None),
    ("sensor_pairings", "Sensor Pairing", "g1", None),
    ("sensor_gnss_couplings", "Sensor GNSS Coupling", "g1", None),
    ("card_iw_records", "Card Insertion / Withdrawal", "g1", None),
    ("card_records", "Card Records", "g1", None),
    ("time_adjustments", "Time Adjustments", "g1", None),
    ("company_locks", "Company Locks", "g1", None),
    ("download_activities", "Downloads", "g1", None),
    ("power_interruptions", "Power Supply Interruptions", "g1", None),
    ("overspeeding_control", "Overspeeding Control", "g1", None),
    ("its_consents", "ITS Consents", "g1", None),
    ("signed_daily_records", "Signed Daily Records", "g1", None),
    ("inserted_drivers", "Inserted Drivers", "g1", None),
    ("card_numbers", "Card Numbers Seen", "g1", "card_numbers"),
    ("speed_blocks", "Detailed Speed Blocks", "g1", None),
    ("vu_record_arrays", "VU Record Array (raw)", "g1", None),
    ("sensor_daily_records", "Sensor Daily Records", "g1", None),

    # ── Generation 2 (Annex 1C) ──
    ("vehicle_units", "Vehicle Units Used", "g2", None),

    # ── Generation 2.2 (Smart V2) ──
    ("gnss_ad_records", "GNSS \u2014 Accumulated Driving", "g22", None),
    ("gnss_places", "GNSS \u2014 Places", "g22", None),
    ("border_crossings", "Border Crossings", "g22", None),
    ("load_unload_records", "Load / Unload", "g22", None),
    ("load_sensor_data", "Load Sensor", "g22", None),
    ("trailer_registrations", "Trailers", "g22", None),
]


def _row_activities(rec):
    """Expands each day into single activity-change rows (Rest, Drive, etc.)."""
    changes = rec.get("changes", [])
    driver = rec.get("driver", "")
    daily_counter = rec.get("daily_counter", "")

    base = {
        "Date": rec.get("date", rec.get("timestamp", "?")),
        "Odometer km": rec.get("odometer_km", 0),
        "Driver": fmt_val(driver) if driver else "",
        "Day #": str(daily_counter) if daily_counter != "" else "",
    }
    empty = {**base, "Time": "\u2014", "Activity": "(no event)",
             "Slot": "", "Crew": ""}

    if not isinstance(changes, list) or not changes:
        return empty

    rows = []
    for ev in changes:
        if isinstance(ev, dict):
            slot = ev.get("slot", "")
            if isinstance(slot, int):
                slot = f"Slot {slot}"
            rows.append({**base,
                "Time": ev.get("time", "?"),
                "Activity": ev.get("activity", "?"),
                "Slot": fmt_val(slot) if slot else "",
                "Crew": fmt_val(ev.get("crew", "")),
            })
    return rows if rows else empty


def _row_card_number(num):
    """Card numbers arrive as plain strings — wrap for a one-column table."""
    return {"Card Number": num}


TRANSFORMERS = {
    "activities": _row_activities,
    "card_numbers": _row_card_number,
}


# ── Value formatting ───────────────────────────────────────────────────────



def _fmt_iso(s):
    """Convert ISO timestamp (2025-04-23T08:37:00+00:00) to 2025-04-23 08:37."""
    m = _ISO_RE.match(s)
    return f"{m.group(1)} {m.group(2)}" if m else s


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


def fmt_val(v):
    """Render any parser value for display: booleans as Yes/No, floats
    trimmed, large ints with thousands spaces, 0xFFFFFF sentinels as N/A,
    bytes as hex, ISO timestamps shortened, dicts/lists flattened."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s if s else "0"
    if isinstance(v, int):
        if v in _NOT_AVAILABLE_INTS:
            return "N/A"
        # Thousands separator (space, not '.', to avoid confusion with decimals)
        # only for large values: small integers / coefficients stay raw.
        return f"{v:,}".replace(",", " ") if abs(v) >= 10000 else str(v)
    if isinstance(v, (bytes, bytearray)):
        h = v.hex()
        return h if len(h) <= 64 else h[:64] + "\u2026"
    if isinstance(v, dict):
        return _fmt_dict(v)
    if isinstance(v, list):
        if not v:
            return ""
        if all(not isinstance(x, (dict, list)) for x in v):
            return ", ".join(fmt_val(x) for x in v)
        return f"[{len(v)} items]"
    if isinstance(v, str):
        return _fmt_iso(v)
    return str(v)


def _columns_for(records, transformer):
    """Derive column order from the union of record keys."""
    if transformer:
        sample = transformer(records[0])
        if isinstance(sample, list):
            sample = sample[0]
        return list(sample.keys())
    cols = []
    for rec in records:
        if not isinstance(rec, dict):
            return ["Value"]
        for k in rec:
            if (k in HIDDEN_KEYS or k in LEADING_KEYS or k in TRAILING_KEYS
                    or k in cols or str(k).startswith("_")):
                continue
            cols.append(k)
    # Leading keys at the front (if present)
    for k in LEADING_KEYS:
        if any(isinstance(r, dict) and k in r for r in records):
            cols.insert(0, k)
    for k in TRAILING_KEYS:
        if any(isinstance(r, dict) and k in r for r in records):
            cols.append(k)
    return cols


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
                rows.append([fmt_val(item.get(c)) for c in cols])
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
                rows.append([subfield, fmt_val(sv)])
        else:
            rows.append([field, fmt_val(v)])
    return (["Field", "Value"], rows)


def _clean_tag_name_display(name):
    """Readable raw tag name for GUI display (wraps core _clean_tag_name)."""
    if not name or name.startswith("BER_") or "_BER_" in name:
        return "(uninterpreted)"
    return _clean_tag_name(name)


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

    def show(self, title, columns, rows, meta=""):
        """Display a table: sets headers (click to sort), sizes columns,
        resets the filter and renders all rows."""
        self.filt_bar.pack(fill=tk.X, padx=8, pady=(0, 4), before=self.tv.master)
        self.title_lbl.config(text=title)
        self.count_lbl.config(
            text=f"{len(rows)} rows \u00b7 {len(columns)} columns"
            + (f"   \u2014   {meta}" if meta else ""))
        self.filter_var.set("")

        self._cols = list(columns)
        self._all_rows = [list(r) for r in rows]
        self._sort_state = {}

        self.tv["columns"] = self._cols
        for c in self._cols:
            self.tv.heading(c, text=str(c),
                            command=lambda col=c: self._sort_by(col))
            self.tv.column(c, minwidth=60, anchor=tk.W, stretch=True)

        self._fit_columns()
        self.tv.bind("<Configure>", lambda e: self._schedule_fit())

        self._render(self._all_rows)

    def _fit_columns(self):
        """Distribute available width proportionally to content length."""
        if not self._cols:
            return
        available = self.tv.winfo_width()
        if available < 50:
            self.tv.after(200, self._fit_columns)
            return
        weights = [max(self._content_width(c) + 24, 70) for c in self._cols]
        total_weight = sum(weights)
        if total_weight == 0:
            return
        # Leave room for scrollbar
        usable = max(available - 20, 100)
        for c, w in zip(self._cols, weights, strict=False):
            self.tv.column(c, width=max(int(usable * w / total_weight), 60))

    def _content_width(self, col):
        idx = self._cols.index(col)
        longest = len(str(col))
        for r in self._all_rows[:200]:
            if idx < len(r):
                longest = max(longest, len(str(r[idx])))
        return longest * 8

    def _schedule_fit(self):
        if self._fit_after_id is not None:
            self.tv.after_cancel(self._fit_after_id)
        self._fit_after_id = self.tv.after(300, self._fit_columns)

    def _col_width(self, col, rows):
        idx = self._cols.index(col)
        longest = len(str(col))
        for r in rows[:200]:
            if idx < len(r):
                longest = max(longest, len(str(r[idx])))
        return min(max(longest * 8 + 24, 70), 460)

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
        self.geometry("1280x760")
        self.minsize(900, 560)

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
                self.call("tk", "scaling", max(_WIN_SCALE, 1.25))
            else:
                self.call("tk", "scaling", 1.0)
        except Exception:
            _log.debug("tk scaling not available")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            try:
                style.theme_use("aqua")
            except Exception:
                pass
        style.configure("Treeview.Heading", background=HEADER_BG,
                        font=("", 10, "bold"))
        style.configure("Treeview", rowheight=int(24 * max(_WIN_SCALE, 1.25)) if sys.platform == "win32" else 24)

        self.current_data = None
        self.current_file = None
        self._payloads = {}  # iid -> (title, columns, rows, meta)
        self._destroyed = False
        self._parsing = False
        self._parse_queue = queue.Queue()

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
        export_menu = tk.Menu(self.btn_export, tearoff=0)
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
        self.lbl_cov = ttk.Label(top, text="")
        self.lbl_cov.pack(side=tk.RIGHT, padx=8)

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
        self.tree.column("#0", width=340, minwidth=200)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Right: table
        right = ttk.Frame(pw)
        pw.add(right, weight=3)
        self.table = DataTable(right)
        self.table.pack(fill=tk.BOTH, expand=True)

        self.bind_all("<Control-f>", lambda e: self.table.filter_entry.focus_set())

        status_bar = ttk.Frame(self, relief=tk.SUNKEN)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = ttk.Label(status_bar, text="Ready \u2014 open a .ddd file",
                                anchor=tk.W, padding=(6, 2))
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress = ttk.Progressbar(status_bar, mode="indeterminate", length=160)
        # packed only while a parse is running \u2014 see _start_parse/_finish_parse

        if self._initial_file and os.path.isfile(self._initial_file):
            self.after(100, lambda: self._start_parse(self._initial_file))

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
        self._finish_parse()
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
        import threading
        self.status.config(text=f"Exporting to {kind}\u2026")
        self.progress.pack(side=tk.RIGHT)
        self.progress.start(12)

        def _worker():
            try:
                export_fn(self.current_data, path)
                self.after(0, lambda: self._export_done(kind, path))
            except Exception as exc:
                self.after(0, lambda e=exc: self._export_error(kind, requirement, e))

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()

    def _export_done(self, kind, path):
        try:
            self.progress.stop()
            self.progress.pack_forget()
        except Exception:
            pass
        self.status.config(text=f"Exported: {os.path.basename(path)}")
        messagebox.showinfo("Export Complete", f"{kind} saved to:\n{path}")

    def _export_error(self, kind, requirement, exc):
        try:
            self.progress.stop()
            self.progress.pack_forget()
        except Exception:
            pass
        if isinstance(exc, ImportError):
            self.status.config(text="Export failed")
            messagebox.showwarning("Export Unavailable",
                                   f"{kind} export requires an extra package:\n{exc}\n{requirement}")
        else:
            self.status.config(text="Export failed")
            messagebox.showerror("Export Error", str(exc))

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
        try:
            self.status.config(text="Exporting to JSON\u2026")
            self.update_idletasks()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.current_data, f, indent=2, ensure_ascii=False,
                          cls=BytesEncoder)
            self.status.config(text=f"Exported: {os.path.basename(path)}")
            messagebox.showinfo("Export Complete", f"JSON saved to:\n{path}")
        except Exception as e:
            self.status.config(text="Export failed")
            messagebox.showerror("Export Error", str(e))

    def _on_close(self):
        self._destroyed = True
        self.destroy()

    def _parse_done(self, data, path):
        """Render a successful parse: rebuild the tree, top bar and status."""
        try:
            self.current_data = data
            self.current_file = path
            self._populate_tree(data)
            self._update_top_bar(data)
            # Clear right panel so stale data from previous file is not shown
            self.table.tv.delete(*self.table.tv.get_children())
            self.table.title_lbl.config(text="")
            self.table.count_lbl.config(text="")
            self.btn_export.config(state=tk.NORMAL)
            meta = data.get("metadata", {})
            self.status.config(
                text=f"Loaded: {os.path.basename(path)}  |  "
                     f"{meta.get('generation', '?')}  |  "
                     f"Coverage: {meta.get('coverage_pct', 0)}%")
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

        cov = meta.get("coverage_pct", 0)
        if cov < 100:
            warnings.append(
                f"\u2022 Structural coverage: {cov:.1f}% \u2014 "
                f"{100 - cov:.1f}% of bytes could not be parsed")

        cov_report = data.get("coverage") or {}
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
        trep_failed = sum(1 for t in (sv.get("treps") or []) if not t.get("signature_valid", True))
        if trep_failed:
            warnings.append(f"\u2022 VU signatures: {trep_failed} TREP section(s) failed")

        if warnings:
            header = (f"The file may be incomplete or corrupted.\n\n"
                      f"{os.path.basename(path)}\n\n")
            messagebox.showwarning("File Integrity Warning",
                                   header + "\n".join(warnings))

    def _update_top_bar(self, data):
        """Refresh filename, generation badge, coverage badge and status badge."""
        meta = data.get("metadata", {})
        gen = meta.get("generation", "Unknown")
        cov = meta.get("coverage_pct", 0)
        self.lbl_file.config(text=os.path.basename(self.current_file))
        self.lbl_gen.config(text=f"\u25cf {gen}",
                            foreground=GEN_COLORS.get(gen, GEN_COLORS["Unknown"]))
        cov_color = "#2e7d32" if cov >= 100 else ("#f57c00" if cov >= 80 else "#c62828")
        self.lbl_cov.config(text=f"Coverage: {cov:.0f}%", foreground=cov_color)
        self._update_status_badge(data)

    def _integrity_label(self, data):
        """Return a human-readable integrity summary for File Info and status bar."""
        integrity = (data.get("metadata") or {}).get("integrity_check", "")
        efv = data.get("ef_signature_verification") or {}
        sv = data.get("signature_verification") or {}

        ef_ok = efv.get("failed", 1) == 0 and efv.get("verified", 0) > 0
        sv_ok = sv.get("all_treps_valid") is True
        chain_ok = "Verified" in integrity

        if chain_ok and ef_ok:
            return "All signatures verified"
        if sv_ok and sv.get("root_anchored"):
            return "VU signatures verified (root anchored)"
        if sv_ok:
            return "VU TREP signatures verified"
        if chain_ok:
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
        """Compose the colour-coded integrity label from the certificate
        chain outcome plus EF/TREP signature verification results."""
        integrity = (data.get("metadata") or {}).get("integrity_check", "")
        efv = data.get("ef_signature_verification") or {}
        sv = data.get("signature_verification") or {}

        ef_ok = efv.get("failed", 1) == 0 and efv.get("verified", 0) > 0
        sv_ok = sv.get("all_treps_valid") is True
        chain_ok = "Verified" in integrity

        label = self._integrity_label(data)

        if chain_ok and ef_ok:
            text = "\u2705  " + label
            color = "#2e7d32"
        elif sv_ok and sv.get("root_anchored"):
            text = "\u2705  " + label
            color = "#2e7d32"
        elif sv_ok:
            text = "\u2705  " + label
            color = "#2e7d32"
        elif chain_ok:
            text = "\u2705  " + label
            color = "#2e7d32"
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
        # Also update the window title with a compact status.
        parts = [f"Tacho Explorer v{__version__}", text[:1],
                 os.path.basename(self.current_file or "")]
        self.title("  ".join(p for p in parts if p))

    # ── Tree construction ───────────────────────────────────

    def _add_section(self, parent, label, columns, rows, meta="", summary=False):
        n = len(rows)
        text = f"{label}  ({n})" if columns != ["Field", "Value"] else label
        iid = self.tree.insert(parent, tk.END, text=text)
        self._payloads[iid] = (label, columns, rows, meta, summary)
        return iid

    def _populate_tree(self, data):
        """Rebuild the section tree from a results dict: Overview, identity,
        grouped list sections (only those present in the file), activities
        day hierarchy, security and raw tags."""
        self.tree.delete(*self.tree.get_children())
        self._payloads.clear()
        meta = data.get("metadata", {})

        # ── File Info (key/value) ──
        is_vu = meta.get("is_vu", False)
        info = {
            "Filename": os.path.basename(self.current_file),
            "Size": f"{meta.get('file_size_bytes', 0):,} bytes".replace(",", " "),
            "Origin": "Vehicle Unit (VU)" if is_vu else "Driver Card",
            "Generation": meta.get("generation", "?"),
            "Coverage": f"{meta.get('coverage_pct', 0)}%",
            "Integrity": self._integrity_label(data),
            "Decoder failures": meta.get("decoder_failure_count", 0),
            "Parsed at": meta.get("parsed_at", ""),
            "App version": meta.get("app_version", ""),
        }
        cols, rows = _kv_rows(info)
        self._add_section("", "\U0001f4c4  File Info", cols, rows)

        drv = data.get("driver", {})

        # Driver card: show holder summary.
        if not is_vu and any(drv.values()):
            cols, rows = self._build_driver_summary(data)
            self._add_section("", "\U0001f464  Driver / Cardholder", cols, rows, summary=True)

        if is_vu:
            try:
                sensor = data.get("sensor_info") or {}
                if sensor:
                    cols, rows = self._build_sensor_summary(data)
                    self._add_section("", "\U0001f4e1  Sensor", cols, rows, summary=True)
                else:
                    cols, rows = self._build_vehicle_summary(data)
                    self._add_section("", "\U0001f69a  Vehicle", cols, rows, summary=True)
            except Exception:
                _log.debug("Vehicle section render failed: %s", traceback.format_exc())

        # ── List groups ──
        sections_by_group = {}

        # Single-record dicts → Field/Value
        _DICT_SECTIONS = [
            ("card_issuer", "Card Issuer", "g1"),
            ("card_application", "Card Application Info", "g1"),
            ("sensor_info", "Sensor Identification", "g1"),
            ("vu_info", "VU Identification & Sensor", "g1"),
            ("vu_overview", "VU Overview", "g1"),
            ("company_info", "Company Info", "g1"),
        ]
        for dk, dl, dg in _DICT_SECTIONS:
            dv = data.get(dk) or {}
            if isinstance(dv, dict) and dv:
                cols, rows = _kv_rows(dv)
                sections_by_group.setdefault(dg, []).append((dl, cols, rows))

        for key, label, group, tname in LIST_SECTIONS:
            records = data.get(key) or []
            if not records:
                continue
            # Single-record dicts (like vu_identifications) → Field/Value
            if key == "vu_identifications" and isinstance(records, list) and len(records) == 1:
                cols, rows = _kv_rows(records[0])
            else:
                transformer = TRANSFORMERS.get(tname) if tname else None
                cols, rows = _rows_for(records, transformer)
            sections_by_group.setdefault(group, []).append((label, cols, rows))

        # ── Filter VU-only sections for card files ──
        actual_is_vu = meta.get("is_vu", False)
        if not actual_is_vu:
            for group_key in sections_by_group:
                sections_by_group[group_key] = [
                    (label, cols, rows)
                    for label, cols, rows in sections_by_group[group_key]
                    if label not in {
                        "VU Identification & Sensor", "VU Overview", "Company Info",
                        "VU Identification", "Sensor Pairing", "Sensor GNSS Coupling",
                        "Card Insertion / Withdrawal", "Card Records",
                        "Time Adjustments", "Company Locks", "Downloads",
                        "Power Supply Interruptions", "Overspeeding Control",
                        "ITS Consents", "Signed Daily Records", "Detailed Speed Blocks",
                        "VU Record Array (raw)",
                    }
                ]

        # ── Activities: day hierarchy (G1 section) ──
        activities = data.get("activities") or []

        for group_key, group_label in GROUPS:
            entries = sections_by_group.get(group_key, [])
            # Add activities under G1
            if group_key == "g1" and activities:
                entries = list(entries)
            # Skip empty groups
            if not entries and not (group_key == "g1" and activities):
                continue
            gnode = self.tree.insert("", tk.END, text=group_label, open=False)
            if group_key == "g1" and activities:
                self._populate_activities(gnode, activities)
            for label, cols, rows in entries:
                self._add_section(gnode, label, cols, rows)

        # ── Security ──
        self._populate_security(data)

        # ── Raw tags ──
        # In VU files the BER-TLV walk is an artifact: it walks inside records,
        # certificates and signatures already decoded (100% coverage), inventing
        # tags from cryptographic bytes. Show raw tags only for cards, where
        # they are the actual EF/structural identifiers.
        raw = data.get("raw_tags", {})
        is_vu_raw = bool(data.get("vu_record_arrays"))
        if raw and not is_vu_raw:
            self._populate_raw_tags(raw)

        # ── Detected generations ──
        gens = data.get("generations", {})
        if gens:
            flat = {g: ", ".join(v.keys()) if isinstance(v, dict) else str(v)
                    for g, v in gens.items()}
            cols, rows = _kv_rows(flat)
            self._add_section("", "\U0001f4e6  Detected Generations", cols, rows)

    def _populate_activities(self, parent, activities):
        """Create an expandable 'Activities' node with days as children."""
        act_node = self.tree.insert(parent, tk.END, text="Daily Activities")
        for day in reversed(activities):
            if not isinstance(day, dict):
                continue
            changes = day.get("changes", [])
            date_str = day.get("date", day.get("timestamp", "?"))
            km = day.get("odometer_km", 0)
            driver = day.get("driver", "")
            daily_counter = day.get("daily_counter", "")

            if isinstance(changes, list) and changes:
                rows = []
                for ev in changes:
                    if isinstance(ev, dict):
                        slot = ev.get("slot", "")
                        if isinstance(slot, int):
                            slot = f"Slot {slot}"
                        rows.append([
                            fmt_val(ev.get("time", "?")),
                            fmt_val(ev.get("activity", "?")),
                            fmt_val(slot) if slot else "",
                            fmt_val(ev.get("crew", "")),
                            fmt_val(km),
                        ])
                cols = ["Time", "Activity", "Slot", "Crew", "Odometer km"]
            else:
                cols = ["Time", "Activity"]
                rows = [[fmt_val("\u2014"), "(no event)"]]

            label = date_str
            extras = []
            if driver:
                extras.append(str(driver))
            if daily_counter != "":
                extras.append(f"#{daily_counter}")
            if extras:
                label = f"{date_str}  [{', '.join(extras)}]"

            self._add_section(act_node, label, cols, rows)

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
        gnode = self.tree.insert("", tk.END,
                                 text="\U0001f510  Security & Certificates",
                                 open=False)
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

    def _populate_raw_tags(self, raw):
        """Summary table of tags traversed by BER-TLV parser but not decoded.
        Aggregated per tag (one record per tag), so thousands of repeated
        occurrences are not listed individually."""
        agg = {}
        for occs in raw.values():
            for o in occs if isinstance(occs, list) else [occs]:
                if not isinstance(o, dict):
                    continue
                tid = o.get("tag_id", "")
                a = agg.get(tid)
                if a is None:
                    a = {"tid": tid, "name": _clean_tag_name_display(o.get("tag_name", "")),
                         "count": 0, "bytes": 0, "offset": o.get("offset", ""),
                         "gen": o.get("generation", ""), "hex": o.get("data_hex", "")}
                    agg[tid] = a
                a["count"] += 1
                try:
                    a["bytes"] += int(o.get("length", 0) or 0)
                except (TypeError, ValueError):
                    pass
        if not agg:
            return

        cols = ["Tag", "Name", "Occurrences", "Total Bytes", "1st Offset",
                "Gen", "Hex (1st occ.)"]
        rows = []
        for a in sorted(agg.values(), key=lambda r: r["tid"]):
            h = a["hex"]
            rows.append([
                a["tid"], a["name"], fmt_val(a["count"]), fmt_val(a["bytes"]),
                a["offset"], a["gen"],
                h[:48] + "\u2026" if len(h) > 48 else h,
            ])
        self._add_section(
            "", "\U0001f9e9  Raw Tags", cols, rows,
            meta="tags traversed by BER-TLV parser but not decoded \u00b7 "
                 "\"(uninterpreted)\" = no known structure associated")

    # ── Selection → table ──────────────────────────────────

    def _on_tree_select(self, _event):
        """Tree selection → show the node's stored payload in the table."""
        sel = self.tree.selection()
        if not sel:
            return
        payload = self._payloads.get(sel[0])
        if payload:
            if len(payload) >= 5 and payload[4]:
                label, cols, rows, meta, _ = payload
                self._show_summary(label, cols, rows, meta)
            else:
                label, cols, rows, meta = payload[:4]
                self.table.show(label, cols, rows, meta)
        else:
            children = self.tree.get_children(sel[0])
            rows = [[self.tree.item(c, "text")] for c in children]
            self.table.show(self.tree.item(sel[0], "text").strip(),
                            ["Sub-section"], rows)

    def _show_summary(self, title, cols, rows, meta):
        """Render a rich info panel with section headers instead of a data table."""
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
        self.table.tv.column("Field", width=220, minwidth=140, anchor=tk.W, stretch=False)
        self.table.tv.column("Value", width=100, minwidth=60, anchor=tk.W, stretch=True)
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
            rows.append(("  Registration", nation, False))
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
            rows.append(("\U0001f527  " + icon + "LAST CALIBRATION", "", True))
            workshop = cal.get("workshop_name", "")
            if workshop:
                rows.append(("  Workshop", workshop, False))
            purpose = cal.get("calibration_purpose_label", "")
            if purpose:
                rows.append(("  Purpose", purpose, False))
            cal_date = cal.get("old_time", "")
            if cal_date:
                rows.append(("  Date", fmt_val(cal_date), False))
            if next_date:
                date_str = fmt_val(next_date)
                if cal_expired:
                    date_str += f"  \u274c EXPIRED ({abs(days_left)} days ago)"
                elif cal_soon:
                    date_str += f"  \u26a0\ufe0f  Due in {days_left} days"
                else:
                    date_str += "  \u2705 Valid"
                rows.append(("  Next calibration", date_str, False))
            tyre = cal.get("tyre_size", "")
            speed = cal.get("authorised_speed_kmh", "")
            if tyre:
                rows.append(("  Tyre size", tyre, False))
            if speed:
                rows.append(("  Authorised speed", f"{speed} km/h", False))
            load = cal.get("by_default_load_type_label", "")
            if load:
                rows.append(("  Default load type", load, False))
            country_ts = cal.get("calibration_country_timestamp", "")
            country = cal.get("calibration_country", "")
            if country and country_ts:
                rows.append(("  Calibration country", f"{country} ({fmt_val(country_ts)})", False))
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
            rows.append(("  Nation", nation, False))
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
            rows.append(("  Issuing nation", nation, False))
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
    if meta.get("parse_error"):
        _emit(f"SMOKE FAIL: parse error {meta['parse_error']}")
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
