"""Tacho Explorer — visualizzatore DDD stile regedit.

Layout:
    ┌────────────────────────┬─────────────────────────────────────┐
    │  Albero sezioni        │  Contenuto sezione (tabella Excel)   │
    │  (stile regedit)       │  intestazioni · righe · ordinabile   │
    └────────────────────────┴─────────────────────────────────────┘

A sinistra l'albero gerarchico delle sezioni del file; a destra il contenuto
della sezione selezionata mostrato in forma tabellare (una riga per record,
una colonna per campo), con ordinamento per colonna e filtro testuale.
"""

import os
import sys
import re
import json

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ddd_parser import TachoParser


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

# Chiavi interne da non mostrare come colonne (rumore di servizio).
HIDDEN_KEYS = {"source", "raw_tail_hex", "name", "size"}
# Colonne tecniche spinte in fondo alla tabella.
TRAILING_KEYS = ["record_type", "confidence"]


# ── Definizione delle sezioni (data-driven) ─────────────────────────────────
#
# Ogni voce di lista nel dict del parser diventa una tabella. I gruppi danno
# all'albero la struttura "a cartelle" stile regedit.

GROUPS = [
    ("activity", "📊  Attività & Utilizzo"),
    ("g22", "🛰️  G2.2 — Smart V2"),
    ("vu", "🚚  Unità di Bordo (VU)"),
    ("security", "🔐  Sicurezza & Certificati"),
    ("raw", "🧩  Tag Grezzi"),
]

# data_key → (etichetta, gruppo, transformer opzionale)
LIST_SECTIONS = [
    # "activities" gestito a parte (gerarchia per giorno) — vedi _populate_activities
    ("vehicle_sessions", "Veicoli usati", "activity", None),
    ("events", "Eventi", "activity", None),
    ("faults", "Guasti", "activity", None),
    ("places", "Luoghi", "activity", None),
    ("specific_conditions", "Condizioni specifiche", "activity", None),
    ("calibrations", "Calibrazioni", "activity", None),

    ("gnss_ad_records", "GNSS — Guida accumulata", "g22", None),
    ("gnss_places", "GNSS — Luoghi", "g22", None),
    ("border_crossings", "Attraversamenti di confine", "g22", None),
    ("load_unload_records", "Carico / Scarico", "g22", None),
    ("load_sensor_data", "Sensore di carico", "g22", None),
    ("trailer_registrations", "Rimorchi", "g22", None),

    ("vu_identifications", "Identificazione VU", "vu", None),
    ("sensor_pairings", "Accoppiamento sensore", "vu", None),
    ("card_iw_records", "Inserimento / Estrazione carta", "vu", None),
    ("card_records", "Record carta", "vu", None),
    ("download_activities", "Scaricamenti", "vu", None),
    ("power_interruptions", "Interruzioni alimentazione", "vu", None),
    ("overspeeding_control", "Controllo eccesso velocità", "vu", None),
    ("its_consents", "Consensi ITS", "vu", None),
    ("vu_record_arrays", "RecordArray VU (raw)", "vu", None),
]


def _row_activities(rec):
    """Espande ogni giornata in singole righe evento (Riposo, Guida, ecc.)."""
    events = rec.get("eventi", rec.get("changes", []))
    if not isinstance(events, list) or not events:
        return {
            "Data": rec.get("data", rec.get("timestamp", "?")),
            "Ora": "—",
            "Tipo": "(nessun evento)",
            "km": rec.get("km", 0),
        }
    rows = []
    for ev in events:
        if isinstance(ev, dict):
            rows.append({
                "Data": rec.get("data", rec.get("timestamp", "?")),
                "Ora": ev.get("ora", ev.get("time", "?")),
                "Tipo": ev.get("tipo", ev.get("type", "?")),
                "km": rec.get("km", 0),
            })
    return rows if rows else {
        "Data": rec.get("data", ""),
        "Ora": "—",
        "Tipo": "(nessun evento)",
        "km": rec.get("km", 0),
    }


TRANSFORMERS = {
    "activities": _row_activities,
}


# ── Formattazione valori ────────────────────────────────────────────────────

# Sentinella "dato non disponibile" del tachigrafo (0xFFFFFF su 3 byte).
_NOT_AVAILABLE_INTS = {0xFFFFFF, 0xFFFFFFFF}
_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?")


def _fmt_iso(s):
    """Converte un timestamp ISO (2025-04-23T08:37:00+00:00) in 2025-04-23 08:37."""
    m = _ISO_RE.match(s)
    return f"{m.group(1)} {m.group(2)}" if m else s


def _fmt_coords(lat, lon):
    if lat is None or lon is None:
        return ""
    return f"{lat:.5f}, {lon:.5f}"


def _fmt_dict(d):
    """Riassunto leggibile delle strutture annidate note del tachigrafo."""
    # Slot carta assente
    if d.get("present") is False:
        return "—"
    # Coordinate GNSS (gnss_place → geo, oppure geo diretto)
    geo = d.get("geo") if isinstance(d.get("geo"), dict) else None
    if geo and ("latitude_deg" in geo or "longitude_deg" in geo):
        return _fmt_coords(geo.get("latitude_deg"), geo.get("longitude_deg"))
    if "latitude_deg" in d or "longitude_deg" in d:
        return _fmt_coords(d.get("latitude_deg"), d.get("longitude_deg"))
    # Numero carta (FullCardNumber)
    if d.get("card_number"):
        return str(d["card_number"])
    # Immatricolazione veicolo
    if "plate" in d:
        plate = str(d.get("plate", "")).strip()
        nation = str(d.get("nation", "")).strip()
        if not plate or set(plate) <= {"?"}:
            return "—"
        return f"{nation} {plate}".strip() if "No information" not in nation else plate
    # Fallback generico compatto
    items = ", ".join(f"{k}={fmt_val(val)}" for k, val in d.items())
    return items if len(items) <= 80 else items[:80] + "…"


def fmt_val(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sì" if v else "No"
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s if s else "0"
    if isinstance(v, int):
        if v in _NOT_AVAILABLE_INTS:
            return "N/A"
        # Separatore migliaia (spazio, non '.', per non confondersi coi decimali)
        # solo per valori grandi: i piccoli interi/coefficienti restano grezzi.
        return f"{v:,}".replace(",", " ") if abs(v) >= 10000 else str(v)
    if isinstance(v, (bytes, bytearray)):
        h = v.hex()
        return h if len(h) <= 64 else h[:64] + "…"
    if isinstance(v, dict):
        return _fmt_dict(v)
    if isinstance(v, list):
        if not v:
            return ""
        if all(not isinstance(x, (dict, list)) for x in v):
            return ", ".join(fmt_val(x) for x in v)
        return f"[{len(v)} elementi]"
    if isinstance(v, str):
        return _fmt_iso(v)
    return str(v)


def _columns_for(records, transformer):
    """Deriva l'ordine delle colonne dall'unione delle chiavi dei record."""
    if transformer:
        sample = transformer(records[0])
        if isinstance(sample, list):
            sample = sample[0]
        return list(sample.keys())
    cols = []
    for rec in records:
        if not isinstance(rec, dict):
            return ["Valore"]
        for k in rec:
            if k in HIDDEN_KEYS or k in TRAILING_KEYS or k in cols:
                continue
            cols.append(k)
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
    """Converte un dict in righe (Campo, Valore)."""
    return ["Campo", "Valore"], [[str(k), fmt_val(v)] for k, v in d.items()]


def _clean_tag_name(name):
    """Nome leggibile di un tag grezzo (toglie prefisso generazione, marca i non
    interpretati)."""
    if not name or name.startswith("BER_") or "_BER_" in name:
        return "(non interpretato)"
    for pfx in ("G22_", "G2_", "G1_", "VU_", "EF_"):
        if name.startswith(pfx):
            return name[len(pfx):]
    return name


# ── Tabella stile Excel ─────────────────────────────────────────────────────

class DataTable(ttk.Frame):
    """Treeview a sole intestazioni: griglia con colonne ordinabili e filtro."""

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
        ttk.Label(filt, text="🔎").pack(side=tk.LEFT)
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
            text=f"{len(rows)} righe · {len(columns)} colonne"
            + (f"   —   {meta}" if meta else ""))
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

        def key(row):
            v = row[idx] if idx < len(row) else ""
            try:
                num = float(str(v).replace(",", "."))
                return (0, num)
            except (ValueError, TypeError):
                return (1, str(v).lower())

        self._all_rows.sort(key=key, reverse=descending)
        self._sort_state[col] = not descending
        for c in self._cols:
            self.tv.heading(c, text=str(c) + (" ▾" if c == col and descending
                                              else " ▴" if c == col else ""))
        self._apply_filter()


# ── Applicazione principale ─────────────────────────────────────────────────

class TachoExplorer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tacho Explorer")
        self.geometry("1280x760")
        self.minsize(900, 560)

        try:
            self.call("tk", "scaling", 1.0)
        except Exception:
            pass

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview.Heading", background=HEADER_BG,
                        font=("", 10, "bold"))
        style.configure("Treeview", rowheight=24)

        self.current_data = None
        self.current_file = None
        self._payloads = {}  # iid -> (title, columns, rows, meta)

        self._build_ui()

    # ── Layout ──────────────────────────────────────────────

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill=tk.X)
        ttk.Button(top, text="📂  Apri file DDD…", command=self._open_file).pack(
            side=tk.LEFT, padx=(0, 14))
        self.lbl_file = ttk.Label(top, text="Nessun file caricato",
                                  font=("", 11, "bold"))
        self.lbl_file.pack(side=tk.LEFT)
        self.lbl_gen = ttk.Label(top, text="")
        self.lbl_gen.pack(side=tk.RIGHT, padx=8)
        self.lbl_cov = ttk.Label(top, text="")
        self.lbl_cov.pack(side=tk.RIGHT, padx=8)

        pw = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Sinistra: albero
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

        # Destra: tabella
        right = ttk.Frame(pw)
        pw.add(right, weight=3)
        self.table = DataTable(right)
        self.table.pack(fill=tk.BOTH, expand=True)

        self.status = ttk.Label(self, text="Pronto — apri un file .ddd",
                                relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # ── Apertura file ───────────────────────────────────────

    def _open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("File DDD", "*.ddd *.DDD"), ("Tutti i file", "*.*")])
        if not path:
            return
        self.status.config(text="Parsing in corso…")
        self.update()
        import threading
        def _parse():
            try:
                data = TachoParser(path).parse()
            except Exception as e:
                self.after(0, lambda: self._parse_error(str(e)))
                return
            self.after(0, lambda: self._parse_done(data, path))
        threading.Thread(target=_parse, daemon=True).start()

    def _parse_error(self, msg):
        messagebox.showerror("Errore di parsing", msg)
        self.status.config(text="Pronto — apri un file .ddd")

    def _parse_done(self, data, path):
        self.current_data = data
        self.current_file = path
        self._populate_tree(data)
        self._update_top_bar(data)
        meta = data.get("metadata", {})
        self.status.config(
            text=f"Caricato: {os.path.basename(path)}  |  "
                 f"{meta.get('generation', '?')}  |  "
                 f"Copertura: {meta.get('coverage_pct', 0)}%")

    def _update_top_bar(self, data):
        meta = data.get("metadata", {})
        gen = meta.get("generation", "Unknown")
        cov = meta.get("coverage_pct", 0)
        self.lbl_file.config(text=os.path.basename(self.current_file))
        self.lbl_gen.config(text=f"● {gen}",
                            foreground=GEN_COLORS.get(gen, GEN_COLORS["Unknown"]))
        cov_color = "#2e7d32" if cov >= 100 else ("#f57c00" if cov >= 80 else "#c62828")
        self.lbl_cov.config(text=f"Copertura: {cov:.0f}%", foreground=cov_color)

    # ── Costruzione albero ──────────────────────────────────

    def _add_section(self, parent, label, columns, rows, meta=""):
        n = len(rows)
        text = f"{label}  ({n})" if columns != ["Campo", "Valore"] else label
        iid = self.tree.insert(parent, tk.END, text=text)
        self._payloads[iid] = (label, columns, rows, meta)
        return iid

    def _populate_tree(self, data):
        self.tree.delete(*self.tree.get_children())
        self._payloads.clear()
        meta = data.get("metadata", {})

        # ── File Info (chiave/valore) ──
        info = {
            "Nome file": os.path.basename(self.current_file),
            "Dimensione": f"{meta.get('file_size_bytes', 0):,} byte".replace(",", " "),
            "Origine": meta.get("source", "Carta conducente"),
            "Generazione": meta.get("generation", "?"),
            "Copertura": f"{meta.get('coverage_pct', 0)}%",
            "Integrità": meta.get("integrity_check", "N/A"),
            "Fallimenti decoder": meta.get("decoder_failure_count", 0),
            "Parsed at": meta.get("parsed_at", ""),
        }
        cols, rows = _kv_rows(info)
        self._add_section("", "📄  Info File", cols, rows)

        drv = data.get("driver", {})
        if any(drv.values()):
            cols, rows = _kv_rows(drv)
            self._add_section("", "👤  Conducente / Titolare", cols, rows)

        veh = data.get("vehicle", {})
        if any(veh.values()):
            cols, rows = _kv_rows(veh)
            self._add_section("", "🚚  Veicolo", cols, rows)

        # ── Gruppi di liste ──
        sections_by_group = {}
        for key, label, group, tname in LIST_SECTIONS:
            records = data.get(key) or []
            if not records:
                continue
            transformer = TRANSFORMERS.get(tname) if tname else None
            cols, rows = _rows_for(records, transformer)
            sections_by_group.setdefault(group, []).append((label, cols, rows))

        # Attività: gerarchia per giorno (espansa sotto il gruppo activity)
        activities = data.get("activities") or []
        has_activity_group = activities or "activity" in sections_by_group

        for group_key, group_label in GROUPS:
            if group_key == "security" or group_key == "raw":
                continue
            if group_key == "activity" and not has_activity_group:
                continue
            entries = sections_by_group.get(group_key, [])
            gnode = self.tree.insert("", tk.END, text=group_label, open=True)
            if group_key == "activity" and activities:
                self._populate_activities(gnode, activities)
            for label, cols, rows in entries:
                self._add_section(gnode, label, cols, rows)

        # ── Sicurezza ──
        self._populate_security(data)

        # ── Tag grezzi ──
        # Nei file VU il walk BER-TLV è un artefatto: cammina dentro record,
        # certificati e firme già decodificati (copertura 100%) inventando tag
        # da byte crittografici. Mostriamo i tag grezzi solo per le carte, dove
        # sono i veri identificatori EF/strutturali.
        raw = data.get("raw_tags", {})
        is_vu = bool(data.get("vu_record_arrays"))
        if raw and not is_vu:
            self._populate_raw_tags(raw)

        # ── Generazioni rilevate ──
        gens = data.get("generations", {})
        if gens:
            flat = {g: ", ".join(v.keys()) if isinstance(v, dict) else str(v)
                    for g, v in gens.items()}
            cols, rows = _kv_rows(flat)
            self._add_section("", "📦  Generazioni rilevate", cols, rows)

    def _populate_activities(self, parent, activities):
        """Crea sotto-nodi per ogni giorno, ciascuno con i propri eventi."""
        for day in activities:
            if not isinstance(day, dict):
                continue
            events = day.get("eventi", day.get("changes", []))
            date_str = day.get("data", day.get("timestamp", "?"))
            km = day.get("km", 0)

            if isinstance(events, list) and events:
                rows = []
                for ev in events:
                    if isinstance(ev, dict):
                        rows.append([
                            fmt_val(ev.get("ora", ev.get("time", "?"))),
                            fmt_val(ev.get("tipo", ev.get("type", "?"))),
                            fmt_val(km),
                        ])
                cols = ["Ora", "Tipo", "km"]
            else:
                cols = ["Ora", "Tipo"]
                rows = [[fmt_val("—"), fmt_val("(nessun evento)")]]

            self._add_section(parent, date_str, cols, rows)

    def _populate_security(self, data):
        sv = data.get("signature_verification")
        certs = data.get("certificates") or []
        cvc = data.get("vu_certificates") or []
        if not sv and not certs and not cvc:
            return
        gnode = self.tree.insert("", tk.END, text="🔐  Sicurezza & Certificati",
                                 open=True)
        if cvc:
            cols, rows = _rows_for(cvc, None)
            self._add_section(gnode, "Certificati CVC (decodificati)", cols, rows,
                              meta="Appendice 11 · CAR=autorità emittente, "
                                   "CHR=titolare, validità da TimeReal")
        if sv:
            summary = {
                "Disponibile": sv.get("available"),
                "Catena MSCA→VU": sv.get("msca_to_vu"),
                "Ancorata a root ERCA": sv.get("root_anchored"),
                "Tutte le firme TREP valide": sv.get("all_treps_valid"),
                "Riepilogo": sv.get("summary", ""),
            }
            cols, rows = _kv_rows(summary)
            self._add_section(gnode, "Verifica firme", cols, rows)
            treps = sv.get("treps") or []
            if treps:
                cols, rows = _rows_for(treps, None)
                self._add_section(gnode, "Firme per sezione (TREP)", cols, rows)
        if certs:
            cols, rows = _rows_for(certs, None)
            self._add_section(gnode, "Certificati", cols, rows)

    def _populate_raw_tags(self, raw):
        """Tabella di sintesi dei tag attraversati dal navigator BER-TLV ma non
        mappati a una struttura decodificata. Aggregati per tag (un record per
        tag), così non si elencano migliaia di occorrenze ripetute."""
        agg = {}
        for occs in raw.values():
            for o in occs if isinstance(occs, list) else [occs]:
                if not isinstance(o, dict):
                    continue
                tid = o.get("tag_id", "")
                a = agg.get(tid)
                if a is None:
                    a = {"tid": tid, "name": _clean_tag_name(o.get("tag_name", "")),
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

        cols = ["Tag", "Nome", "Occorrenze", "Byte tot.", "1° offset",
                "Gen", "Hex (1ª occ.)"]
        rows = []
        for a in sorted(agg.values(), key=lambda r: r["tid"]):
            h = a["hex"]
            rows.append([
                a["tid"], a["name"], fmt_val(a["count"]), fmt_val(a["bytes"]),
                a["offset"], a["gen"],
                h[:48] + "…" if len(h) > 48 else h,
            ])
        self._add_section(
            "", "🧩  Tag Grezzi", cols, rows,
            meta="tag attraversati dal parser BER-TLV ma non decodificati · "
                 "\"(non interpretato)\" = nessuna struttura nota associata")

    # ── Selezione → tabella ─────────────────────────────────

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        payload = self._payloads.get(sel[0])
        if payload:
            label, cols, rows, meta = payload
            self.table.show(label, cols, rows, meta)
        else:
            # nodo gruppo: mostra elenco delle sotto-sezioni
            children = self.tree.get_children(sel[0])
            rows = [[self.tree.item(c, "text")] for c in children]
            self.table.show(self.tree.item(sel[0], "text").strip(),
                            ["Sotto-sezione"], rows)


def main():
    TachoExplorer().mainloop()


if __name__ == "__main__":
    main()
