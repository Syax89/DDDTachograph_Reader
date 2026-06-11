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

from ddd_parser import TachoParser  # noqa: E402
from core.encoding import BytesEncoder  # noqa: E402
from core.models import _clean_tag_name  # noqa: E402

_log = logging.getLogger("tacho_gui")

try:
    from export_manager import ExportManager
except ImportError:
    ExportManager = None
try:
    import pandas as pd
except ImportError:
    pd = None


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
LEADING_KEYS = ["descrizione"]
# Technical columns pushed to table end.
TRAILING_KEYS = ["record_type"]


# ── Section definitions (data-driven) ─────────────────────────────────────
#
# Each parser dict list entry becomes a table. Groups give the tree its
# regedit-style folder structure.

GROUPS = [
    ("activity", "\U0001f4ca  Activity & Usage"),
    ("g22", "\U0001f6f0\ufe0f  G2.2 \u2014 Smart V2"),
    ("vu", "\U0001f69a  Vehicle Unit (VU)"),
    ("security", "\U0001f510  Security & Certificates"),
    ("raw", "\U0001f9e9  Raw Tags"),
]

# data_key → (label, group, optional transformer)
LIST_SECTIONS = [
    # "activities" handled separately (day hierarchy) — see _populate_activities
    ("vehicle_sessions", "Vehicles Used", "activity", None),
    ("events", "Events", "activity", None),
    ("overspeeding_events", "Overspeeding Events", "activity", None),
    ("faults", "Faults", "activity", None),
    ("places", "Places", "activity", None),
    ("specific_conditions", "Specific Conditions", "activity", None),
    ("calibrations", "Calibrations", "activity", None),
    ("card_downloads", "Card Downloads", "activity", None),
    # Control activities exist on both driver cards (EF 0x0508) and VUs —
    # kept in the activity group so they stay visible for card files too.
    ("control_activities", "Control Activities", "activity", None),
    ("workshops", "Calibration Workshops", "activity", None),
    ("previous_vehicle", "Previous Vehicle", "activity", None),
    ("company_holders", "Company Holders", "activity", None),

    ("gnss_ad_records", "GNSS — Accumulated Driving", "g22", None),
    ("gnss_places", "GNSS — Places", "g22", None),
    ("border_crossings", "Border Crossings", "g22", None),
    ("load_unload_records", "Load / Unload", "g22", None),
    ("load_sensor_data", "Load Sensor", "g22", None),
    ("trailer_registrations", "Trailers", "g22", None),

    ("vu_identifications", "VU Identification", "vu", None),
    ("sensor_pairings", "Sensor Pairing", "vu", None),
    ("sensor_gnss_couplings", "Sensor GNSS Coupling", "vu", None),
    ("card_iw_records", "Card Insertion / Withdrawal", "vu", None),
    ("card_records", "Card Records", "vu", None),
    ("time_adjustments", "Time Adjustments", "vu", None),
    ("company_locks", "Company Locks", "vu", None),
    ("download_activities", "Downloads", "vu", None),
    ("power_interruptions", "Power Supply Interruptions", "vu", None),
    ("overspeeding_control", "Overspeeding Control", "vu", None),
    ("its_consents", "ITS Consents", "vu", None),
    ("signed_daily_records", "Signed Daily Records", "vu", None),
    ("inserted_drivers", "Inserted Drivers", "vu", None),
    ("speed_blocks", "Detailed Speed Blocks", "vu", None),
    ("vu_record_arrays", "VU Record Array (raw)", "vu", None),
]


def _row_activities(rec):
    """Expands each day into single event rows (Rest, Drive, etc.)."""
    events = rec.get("eventi", rec.get("changes", []))
    driver = rec.get("driver", "")
    daily_counter = rec.get("daily_counter", "")

    base = {
        "Date": rec.get("data", rec.get("timestamp", "?")),
        "km": rec.get("km", 0),
        "Driver": fmt_val(driver) if driver else "",
        "Day #": str(daily_counter) if daily_counter != "" else "",
    }

    if not isinstance(events, list) or not events:
            return {**base, "Time": "\u2014", "Type": "(no event)", "Slot": "", "Crew": ""}

    rows = []
    for ev in events:
        if isinstance(ev, dict):
            slot = ev.get("slot", "")
            if isinstance(slot, int):
                slot = f"Slot {slot}"
            rows.append({**base,
                "Time": ev.get("ora", ev.get("time", "?")),
                "Type": ev.get("tipo", ev.get("type", "?")),
                "Slot": fmt_val(slot) if slot else "",
                "Crew": fmt_val(ev.get("crew", ev.get("team", ""))),
            })
    return rows if rows else {**base,
        "Time": "\u2014", "Type": "(no event)", "Slot": "", "Crew": "",
    }


TRANSFORMERS = {
    "activities": _row_activities,
}


# ── Value formatting ───────────────────────────────────────────────────────

# Tachograph "data not available" sentinel (0xFFFFFF on 3 bytes).
_NOT_AVAILABLE_INTS = {0xFFFFFF, 0xFFFFFFFF}
_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?")


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
    # Card number (FullCardNumber)
    if d.get("card_number"):
        return str(d["card_number"])
    # Vehicle registration
    if "plate" in d:
        plate = (d.get("plate") or "").strip() if d.get("plate") is not None else ""
        nation = (d.get("nation") or "").strip() if d.get("nation") is not None else ""
        if not plate or set(plate) <= {"?"}:
            return "\u2014"
        return f"{nation} {plate}".strip() if "No information" not in nation else plate
    # Compact generic fallback
    items = ", ".join(f"{k}={fmt_val(val)}" for k, val in d.items())
    return items if len(items) <= 80 else items[:80] + "\u2026"


def fmt_val(v):
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
    return cols, rows


def _kv_rows(d):
    """Convert a dict to (Field, Value) rows."""
    return ["Field", "Value"], [[str(k), fmt_val(v)] for k, v in d.items()]


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
        filt.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(filt, text="\U0001f50e").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
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

        self._cols = []
        self._all_rows = []
        self._sort_state = {}

    def show(self, title, columns, rows, meta=""):
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
            width = self._col_width(c, rows)
            self.tv.column(c, width=width, minwidth=60, anchor=tk.W, stretch=False)

        self._render(self._all_rows)

    def _col_width(self, col, rows):
        idx = self._cols.index(col)
        longest = len(str(col))
        for r in rows[:200]:
            if idx < len(r):
                longest = max(longest, len(str(r[idx])))
        return min(max(longest * 8 + 24, 70), 460)

    def _render(self, rows):
        self.tv.delete(*self.tv.get_children())
        for i, r in enumerate(rows):
            tag = "even" if i % 2 == 0 else "odd"
            self.tv.insert("", tk.END, values=r, tags=(tag,))

    def _apply_filter(self):
        q = self.filter_var.get().strip().lower()
        if not q:
            self._render(self._all_rows)
            return
        filtered = [r for r in self._all_rows
                    if any(q in str(c).lower() for c in r)]
        self._render(filtered)

    def _sort_by(self, col):
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

class TachoExplorer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tacho Explorer")
        self.geometry("1280x760")
        self.minsize(900, 560)

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

        self._build_ui()
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            _log.debug("WM_DELETE_WINDOW not supported")

    # ── Layout ──────────────────────────────────────────────

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill=tk.X)
        ttk.Button(top, text="\U0001f4c2  Open DDD file", command=self._open_file).pack(
            side=tk.LEFT, padx=(0, 8))
        self.btn_export = ttk.Menubutton(top, text="\U0001f4e4  Export",
                                         state=tk.DISABLED)
        export_menu = tk.Menu(self.btn_export, tearoff=0)
        export_menu.add_command(label="Excel (.xlsx)", command=self._export_excel)
        export_menu.add_command(label="CSV (.csv)", command=self._export_csv)
        export_menu.add_command(label="JSON (.json)", command=self._export_json)
        self.btn_export["menu"] = export_menu
        self.btn_export.pack(side=tk.LEFT, padx=(0, 14))
        self.lbl_file = ttk.Label(top, text="No file loaded",
                                  font=("", 11, "bold"))
        self.lbl_file.pack(side=tk.LEFT)
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
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Right: table
        right = ttk.Frame(pw)
        pw.add(right, weight=3)
        self.table = DataTable(right)
        self.table.pack(fill=tk.BOTH, expand=True)

        self.status = ttk.Label(self, text="Ready \u2014 open a .ddd file",
                                relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # ── File open ──────────────────────────────────────────

    def _open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("DDD Files", "*.ddd *.DDD"), ("All Files", "*.*")])
        if not path:
            return
        self.status.config(text="Parsing\u2026")
        self.update_idletasks()
        try:
            data = TachoParser(path).parse()
        except Exception as e:
            self._parse_error(str(e))
            return
        if not self._destroyed:
            self._parse_done(data, path)

    def _parse_error(self, msg):
        try:
            messagebox.showerror("Parsing Error", str(msg))
        except Exception:
            pass
        self.status.config(text="Ready \u2014 open a .ddd file")

    # ── Export ────────────────────────────────────────────

    def _export_excel(self):
        if not self.current_data:
            return
        if ExportManager is None or pd is None:
            messagebox.showwarning("Export Unavailable",
                                   "Excel export requires pandas and openpyxl.\n"
                                   "pip install pandas openpyxl")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx"), ("All Files", "*.*")],
            initialfile=os.path.splitext(os.path.basename(self.current_file))[0] + "_export.xlsx")
        if not path:
            return
        try:
            self.status.config(text="Exporting to Excel\u2026")
            self.update_idletasks()
            ExportManager.export_to_excel(self.current_data, path)
            self.status.config(text=f"Exported: {os.path.basename(path)}")
            messagebox.showinfo("Export Complete", f"Excel saved to:\n{path}")
        except Exception as e:
            self.status.config(text="Export failed")
            messagebox.showerror("Export Error", str(e))

    def _export_csv(self):
        if not self.current_data:
            return
        if ExportManager is None or pd is None:
            messagebox.showwarning("Export Unavailable",
                                   "CSV export requires pandas.\n"
                                   "pip install pandas")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=os.path.splitext(os.path.basename(self.current_file))[0] + "_export.csv")
        if not path:
            return
        try:
            self.status.config(text="Exporting to CSV\u2026")
            self.update_idletasks()
            ExportManager.export_to_csv(self.current_data, path)
            self.status.config(text=f"Exported: {os.path.basename(path)}")
            messagebox.showinfo("Export Complete", f"CSV saved to:\n{path}")
        except Exception as e:
            self.status.config(text="Export failed")
            messagebox.showerror("Export Error", str(e))

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
        try:
            self.current_data = data
            self.current_file = path
            self._populate_tree(data)
            self._update_top_bar(data)
            self.btn_export.config(state=tk.NORMAL)
            meta = data.get("metadata", {})
            self.status.config(
                text=f"Loaded: {os.path.basename(path)}  |  "
                     f"{meta.get('generation', '?')}  |  "
                     f"Coverage: {meta.get('coverage_pct', 0)}%")
        except Exception:
            _log.error("GUI render failed: %s", traceback.format_exc())
            messagebox.showerror("Rendering Error",
                                  f"Failed to display file:\n{traceback.format_exc()}")
            self.status.config(text="Ready \u2014 open a .ddd file")

    def _update_top_bar(self, data):
        meta = data.get("metadata", {})
        gen = meta.get("generation", "Unknown")
        cov = meta.get("coverage_pct", 0)
        self.lbl_file.config(text=os.path.basename(self.current_file))
        self.lbl_gen.config(text=f"\u25cf {gen}",
                            foreground=GEN_COLORS.get(gen, GEN_COLORS["Unknown"]))
        cov_color = "#2e7d32" if cov >= 100 else ("#f57c00" if cov >= 80 else "#c62828")
        self.lbl_cov.config(text=f"Coverage: {cov:.0f}%", foreground=cov_color)

    # ── Tree construction ───────────────────────────────────

    def _add_section(self, parent, label, columns, rows, meta=""):
        n = len(rows)
        text = f"{label}  ({n})" if columns != ["Field", "Value"] else label
        iid = self.tree.insert(parent, tk.END, text=text)
        self._payloads[iid] = (label, columns, rows, meta)
        return iid

    def _populate_tree(self, data):
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
            "Bytes Parsed": f"{meta.get('raw_bytes_parsed', 0):,}".replace(",", " "),
            "Bytes Covered": f"{meta.get('total_bytes_covered', 0):,}".replace(",", " "),
            "Integrity": meta.get("integrity_check", "N/A"),
            "Decoder failures": meta.get("decoder_failure_count", 0),
            "Parsed at": meta.get("parsed_at", ""),
        }
        cols, rows = _kv_rows(info)
        self._add_section("", "\U0001f4c4  File Info", cols, rows)

        drv = data.get("driver", {})
        veh = data.get("vehicle", {})

        # Driver card: show holder. VU: show vehicle.
        if not is_vu and any(drv.values()):
            cols, rows = _kv_rows(drv)
            self._add_section("", "\U0001f464  Driver / Cardholder", cols, rows)

        if is_vu:
            try:
                veh_info = dict(veh)
                plate_val = veh_info.get("plate")
                vin_val = veh_info.get("vin")
                if (plate_val is None or plate_val in ("N/A", "")) and (vin_val is None or vin_val in ("N/A", "")):
                    for cal in data.get("calibrations") or []:
                        if isinstance(cal, dict):
                            vin = cal.get("vin", "")
                            if vin and vin not in ("N/A", "?????????????????"):
                                veh_info["vin"] = vin
                            plate = cal.get("plate") or (cal.get("vehicle_registration") or {}).get("plate", "")
                            if plate and plate.strip() and not all(c in '?\\x' for c in plate) and plate not in ("N/A", ""):
                                veh_info["plate"] = plate
                            nation = cal.get("registration_nation") or (cal.get("vehicle_registration") or {}).get("nation", "")
                            if nation and "No information" not in str(nation) and nation != "N/A":
                                veh_info["registration_nation"] = nation
                if any(v for v in veh_info.values() if v not in ("N/A", "", None)):
                    cols, rows = _kv_rows(veh_info)
                    self._add_section("", "\U0001f69a  Vehicle", cols, rows)
            except Exception:
                _log.debug("Vehicle section render failed: %s", traceback.format_exc())

        # ── List groups ──
        sections_by_group = {}

        # Single-record dicts → Field/Value (rendered before list loops)
        _DICT_SECTIONS = [
            ("card_issuer", "Card Issuer", "activity"),
            ("card_application", "Card Application Info", "activity"),
            ("vu_info", "VU Identification & Sensor", "vu"),
            ("vu_overview", "VU Overview", "vu"),
            ("company_info", "Company Info", "vu"),
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

        # ── Skip VU group for driver cards ──
        actual_is_vu = meta.get("is_vu", False)
        if not actual_is_vu:
            sections_by_group.pop("vu", None)

        # Activities: day hierarchy (expanded under activity group)
        activities = data.get("activities") or []
        has_activity_group = activities or "activity" in sections_by_group

        for group_key, group_label in GROUPS:
            if group_key == "security" or group_key == "raw":
                continue
            if group_key == "activity" and not has_activity_group:
                continue
            if group_key == "vu" and not actual_is_vu:
                continue
            entries = sections_by_group.get(group_key, [])
            gnode = self.tree.insert("", tk.END, text=group_label, open=True)
            if group_key == "activity" and activities:
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
            events = day.get("eventi", day.get("changes", []))
            date_str = day.get("data", day.get("timestamp", "?"))
            km = day.get("km", 0)
            driver = day.get("driver", "")
            daily_counter = day.get("daily_counter", "")

            if isinstance(events, list) and events:
                rows = []
                for ev in events:
                    if isinstance(ev, dict):
                        slot = ev.get("slot", "")
                        if isinstance(slot, int):
                            slot = f"Slot {slot}"
                        rows.append([
                            fmt_val(ev.get("ora", ev.get("time", "?"))),
                            fmt_val(ev.get("tipo", ev.get("type", "?"))),
                            fmt_val(slot) if slot else "",
                            fmt_val(ev.get("crew", ev.get("team", ""))),
                            fmt_val(km),
                        ])
                cols = ["Time", "Type", "Slot", "Crew", "km"]
            else:
                cols = ["Time", "Type"]
                rows = [[fmt_val("\u2014"), fmt_val("(no event)")]]

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
        sv = data.get("signature_verification")
        certs = data.get("certificates") or []
        cvc = data.get("vu_certificates") or []
        chip = data.get("card_chip") or {}
        icc = data.get("card_icc") or {}
        if not sv and not certs and not cvc and not chip and not icc:
            return
        gnode = self.tree.insert("", tk.END,
                                 text="\U0001f510  Security & Certificates",
                                 open=True)
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

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        payload = self._payloads.get(sel[0])
        if payload:
            label, cols, rows, meta = payload
            self.table.show(label, cols, rows, meta)
        else:
            # group node: show list of sub-sections
            children = self.tree.get_children(sel[0])
            rows = [[self.tree.item(c, "text")] for c in children]
            self.table.show(self.tree.item(sel[0], "text").strip(),
                            ["Sub-section"], rows)


def main():
    TachoExplorer().mainloop()


if __name__ == "__main__":
    main()
