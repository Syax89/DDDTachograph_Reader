import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import json
import os
import threading
from datetime import datetime
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from fines_calculator import FinesCalculator
from export_manager import ExportManager
from fleet_analytics import FleetAnalytics
from fleet_pdf_exporter import generate_fleet_pdf

# Impostazioni Tema Aurora ✨
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Aurora DDD Analytics ✨ - Lead UX Edition")
        self.geometry("1200x850")
        self.minsize(1000, 700)

        # Configurazione Grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar Navigation ---
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(7, weight=1)
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="DDD ANALYTICS", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 20))

        self.open_button = ctk.CTkButton(self.sidebar_frame, text="Carica File .ddd", command=self.open_file, height=40, font=ctk.CTkFont(weight="bold"))
        self.open_button.grid(row=1, column=0, padx=20, pady=(10, 20))

        # Tab Buttons
        self.nav_buttons = {}
        self._create_nav_button(2, "BENVENUTO", "welcome")
        self._create_nav_button(3, "ESPLORA DATI", "explore")
        self._create_nav_button(4, "ATTIVITÀ", "activities")
        self.infractions_nav_btn = self._create_nav_button(5, "INFRAZIONI", "infractions")
        self.infractions_nav_btn.grid_remove()  # Hidden by default
        self._create_nav_button(6, "🚛 FLOTTA", "fleet")

        self.export_button = ctk.CTkButton(self.sidebar_frame, text="Esporta JSON", command=self.export_json, state="disabled", fg_color="transparent", border_width=1)
        self.export_button.grid(row=8, column=0, padx=20, pady=(20, 10))

        self.export_excel_button = ctk.CTkButton(self.sidebar_frame, text="Esporta Excel", command=self.export_excel, state="disabled", fg_color="#1E8449", hover_color="#145A32")
        self.export_excel_button.grid(row=9, column=0, padx=20, pady=10)

        self.export_csv_button = ctk.CTkButton(self.sidebar_frame, text="Esporta CSV", command=self.export_csv, state="disabled", fg_color="transparent", border_width=1)
        self.export_csv_button.grid(row=10, column=0, padx=20, pady=10)

        # --- Main Content Area ---
        self.container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.container.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.container.grid_columnconfigure(0, weight=1)
        self.container.grid_rowconfigure(0, weight=1)

        self.sections = {}
        self._setup_welcome_section()
        self._setup_explore_section()
        self._setup_activities_section()
        self._setup_infractions_section()
        self._setup_fleet_section()

        self.select_section("welcome")
        self.current_data = None
        self.fleet_results = []

    def _create_nav_button(self, row, text, section_id):
        btn = ctk.CTkButton(self.sidebar_frame, text=text, corner_radius=0, height=40, border_spacing=10,
                            fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                            anchor="w", command=lambda: self.select_section(section_id))
        btn.grid(row=row, column=0, sticky="ew")
        self.nav_buttons[section_id] = btn
        return btn

    def select_section(self, section_id):
        for sid, btn in self.nav_buttons.items():
            if sid == section_id:
                btn.configure(fg_color=("gray75", "gray25"))
                self.sections[sid].grid(row=0, column=0, sticky="nsew")
            else:
                btn.configure(fg_color="transparent")
                self.sections[sid].grid_forget()

    # ─────────────────────────────────────────────
    # WELCOME SECTION
    # ─────────────────────────────────────────────
    def _setup_welcome_section(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sections["welcome"] = frame
        frame.grid_columnconfigure(0, weight=1)

        welcome_label = ctk.CTkLabel(frame, text="Benvenuto in DDD Analytics", font=ctk.CTkFont(size=28, weight="bold"))
        welcome_label.pack(pady=(40, 10))
        
        self.welcome_subtitle = ctk.CTkLabel(frame, text="Carica un file per iniziare l'analisi rivoluzionaria.", font=ctk.CTkFont(size=16))
        self.welcome_subtitle.pack(pady=(0, 20))

        self.legal_banner = ctk.CTkFrame(frame, height=60, corner_radius=10, fg_color="gray20")
        self.legal_banner.pack(pady=10, padx=40, fill="x")
        self.legal_banner.pack_propagate(False)
        self.legal_status_label = ctk.CTkLabel(self.legal_banner, text="In attesa di caricamento file...", font=ctk.CTkFont(size=16, weight="bold"))
        self.legal_status_label.pack(expand=True)

        self.id_card = ctk.CTkFrame(frame, width=600, height=250, corner_radius=20, border_width=2, border_color="#1F538D")
        self.id_card.pack(pady=20, padx=40, fill="x")
        self.id_card.pack_propagate(False)

        self.id_title = ctk.CTkLabel(self.id_card, text="IDENTITÀ SOGGETTO", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3B8ED0")
        self.id_title.pack(pady=(20, 10), padx=30, anchor="w")

        self.id_main_info = ctk.CTkLabel(self.id_card, text="Nessun dato caricato", font=ctk.CTkFont(size=32, weight="bold"))
        self.id_main_info.pack(pady=10, padx=30, anchor="w")

        self.id_sub_info = ctk.CTkLabel(self.id_card, text="Carica un file .ddd (Carta o Veicolo)", font=ctk.CTkFont(size=18))
        self.id_sub_info.pack(pady=5, padx=30, anchor="w")

        self.stats_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.stats_frame.pack(pady=40, padx=40, fill="x")
        for i in range(3): self.stats_frame.grid_columnconfigure(i, weight=1)

        self.welcome_stats = {}
        self._create_welcome_stat(0, "DISTANZA TOTALE", "0 KM")
        self._create_welcome_stat(1, "ORE GUIDA", "00:00")
        self._create_welcome_stat(2, "STATO INTEGRITÀ", "---")

    def _create_welcome_stat(self, col, title, value):
        f = ctk.CTkFrame(self.stats_frame, corner_radius=15)
        f.grid(row=0, column=col, padx=10, sticky="nsew")
        t = ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color="gray")
        t.pack(pady=(15, 0))
        v = ctk.CTkLabel(f, text=value, font=ctk.CTkFont(size=24, weight="bold"))
        v.pack(pady=(5, 15))
        self.welcome_stats[title] = v

    # ─────────────────────────────────────────────
    # EXPLORE SECTION
    # ─────────────────────────────────────────────
    def _setup_explore_section(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sections["explore"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(frame, text="Esplora Dati Grezzi (Regedit Style)", font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        style = ttk.Style()
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", rowheight=30)
        
        self.tree_frame = ctk.CTkFrame(frame)
        self.tree_frame.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.tree_frame.grid_rowconfigure(0, weight=1)

        cols = ("Offset", "Tag", "Descrizione", "Lunghezza", "Tipo")
        self.tag_tree = ttk.Treeview(self.tree_frame, columns=cols, show='headings')
        for col in cols:
            self.tag_tree.heading(col, text=col)
            self.tag_tree.column(col, width=100)
        self.tag_tree.column("Descrizione", width=300)
        self.tag_tree.grid(row=0, column=0, sticky="nsew")
        
        sb = ctk.CTkScrollbar(self.tree_frame, orientation="vertical", command=self.tag_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tag_tree.configure(yscrollcommand=sb.set)

    # ─────────────────────────────────────────────
    # ACTIVITIES SECTION
    # ─────────────────────────────────────────────
    def _setup_activities_section(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sections["activities"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(frame, text="Analisi Attività Giornaliere", font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        cols = ("Data", "Guida", "Lavoro", "Pausa/Riposo", "Infrazioni")
        self.act_tree = ttk.Treeview(frame, columns=cols, show='headings')
        for col in cols:
            self.act_tree.heading(col, text=col)
            self.act_tree.column(col, width=120, anchor="center")
        self.act_tree.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")

    # ─────────────────────────────────────────────
    # INFRACTIONS SECTION
    # ─────────────────────────────────────────────
    def _setup_infractions_section(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sections["infractions"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        header = ctk.CTkLabel(frame, text="Rilevamento Infrazioni", font=ctk.CTkFont(size=20, weight="bold"), text_color="#E74C3C")
        header.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        self.fine_box = ctk.CTkFrame(frame, fg_color="#3E2723", corner_radius=10)
        self.fine_box.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")
        self.fine_label = ctk.CTkLabel(self.fine_box, text="Sanzioni Stimate: € 0", font=ctk.CTkFont(size=18, weight="bold"))
        self.fine_label.pack(pady=15)

        cols = ("Data", "Tipo Infrazione", "Severità", "Descrizione")
        self.inf_tree = ttk.Treeview(frame, columns=cols, show='headings')
        for col in cols:
            self.inf_tree.heading(col, text=col)
        self.inf_tree.column("Descrizione", width=400)
        self.inf_tree.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")

    # ─────────────────────────────────────────────
    # FLEET SECTION (FASE 13)
    # ─────────────────────────────────────────────
    def _setup_fleet_section(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sections["fleet"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(3, weight=1)

        # Header
        header = ctk.CTkLabel(frame, text="🚛 Analisi Flotta Multi-Conducente", font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")

        sub = ctk.CTkLabel(frame, text="Analizza tutti i file .ddd in una cartella in un colpo solo.", font=ctk.CTkFont(size=13), text_color="gray")
        sub.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="w")

        # Toolbar
        toolbar = ctk.CTkFrame(frame, fg_color="transparent")
        toolbar.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        toolbar.grid_columnconfigure(4, weight=1)

        self.fleet_folder_btn = ctk.CTkButton(toolbar, text="📂 Seleziona Cartella", command=self.fleet_select_folder, height=36, font=ctk.CTkFont(weight="bold"))
        self.fleet_folder_btn.grid(row=0, column=0, padx=(0, 10))

        self.fleet_analyze_btn = ctk.CTkButton(toolbar, text="▶ Analizza", command=self.fleet_run_analysis, height=36, state="disabled", fg_color="#1E8449", hover_color="#145A32")
        self.fleet_analyze_btn.grid(row=0, column=1, padx=(0, 10))

        self.fleet_export_btn = ctk.CTkButton(toolbar, text="⬇ Esporta CSV", command=self.fleet_export_csv, height=36, state="disabled", fg_color="transparent", border_width=1)
        self.fleet_export_btn.grid(row=0, column=2, padx=(0, 10))

        self.fleet_pdf_btn = ctk.CTkButton(toolbar, text="📄 Esporta PDF", command=self.fleet_export_pdf, height=36, state="disabled", fg_color="#1F538D", hover_color="#144070")
        self.fleet_pdf_btn.grid(row=0, column=3, padx=(0, 10))

        self.fleet_status_label = ctk.CTkLabel(toolbar, text="Nessuna cartella selezionata", text_color="gray", anchor="w")
        self.fleet_status_label.grid(row=0, column=4, padx=10, sticky="ew")

        # Stats bar (visibile dopo analisi)
        self.fleet_stats_frame = ctk.CTkFrame(frame, corner_radius=10, fg_color="gray17")
        self.fleet_stats_frame.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.fleet_stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.fleet_stat_labels = {}
        stats_defs = [
            ("CONDUCENTI", "fleet_drivers"),
            ("KM TOTALI", "fleet_km"),
            ("ORE GUIDA TOTALI", "fleet_hours"),
            ("INFRAZIONI TOTALI", "fleet_infractions"),
        ]
        for i, (title, key) in enumerate(stats_defs):
            sf = ctk.CTkFrame(self.fleet_stats_frame, fg_color="transparent")
            sf.grid(row=0, column=i, padx=10, pady=10, sticky="ew")
            ctk.CTkLabel(sf, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color="gray").pack()
            lbl = ctk.CTkLabel(sf, text="—", font=ctk.CTkFont(size=20, weight="bold"))
            lbl.pack()
            self.fleet_stat_labels[key] = lbl

        # Progress bar (visibile durante elaborazione)
        self.fleet_progress = ctk.CTkProgressBar(frame, mode="indeterminate")
        self.fleet_progress.grid(row=4, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.fleet_progress.grid_remove()

        # Treeview risultati
        tree_frame = ctk.CTkFrame(frame)
        tree_frame.grid(row=5, column=0, padx=20, pady=(0, 20), sticky="nsew")
        frame.grid_rowconfigure(5, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        cols = ("Conducente", "Carta", "KM Totali", "Ore Guida", "Ultima Attività", "Infrazioni", "Integrità", "File")
        self.fleet_tree = ttk.Treeview(tree_frame, columns=cols, show='headings')

        col_widths = {"Conducente": 160, "Carta": 130, "KM Totali": 80, "Ore Guida": 80,
                      "Ultima Attività": 110, "Infrazioni": 80, "Integrità": 120, "File": 200}
        for col in cols:
            self.fleet_tree.heading(col, text=col)
            self.fleet_tree.column(col, width=col_widths.get(col, 100), anchor="center")
        self.fleet_tree.column("Conducente", anchor="w")
        self.fleet_tree.column("File", anchor="w")

        # Tag colori per stato
        self.fleet_tree.tag_configure("ok", foreground="#2ECC71")
        self.fleet_tree.tag_configure("error", foreground="#E74C3C")
        self.fleet_tree.tag_configure("warn", foreground="#F39C12")

        self.fleet_tree.grid(row=0, column=0, sticky="nsew")

        sb_v = ctk.CTkScrollbar(tree_frame, orientation="vertical", command=self.fleet_tree.yview)
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h = ctk.CTkScrollbar(tree_frame, orientation="horizontal", command=self.fleet_tree.xview)
        sb_h.grid(row=1, column=0, sticky="ew")
        self.fleet_tree.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

        self.fleet_folder_path = None

    def fleet_select_folder(self):
        folder = filedialog.askdirectory(title="Seleziona cartella con file .ddd")
        if folder:
            self.fleet_folder_path = folder
            import glob
            count = len(glob.glob(os.path.join(folder, "*.ddd")))
            self.fleet_status_label.configure(text=f"📁 {os.path.basename(folder)} — {count} file .ddd trovati", text_color="white")
            self.fleet_analyze_btn.configure(state="normal" if count > 0 else "disabled")
            if count == 0:
                messagebox.showwarning("Nessun file", "Nessun file .ddd trovato nella cartella selezionata.")

    def fleet_run_analysis(self):
        if not self.fleet_folder_path:
            return
        # Disabilita bottoni durante analisi
        self.fleet_analyze_btn.configure(state="disabled", text="⏳ Analisi...")
        self.fleet_export_btn.configure(state="disabled")
        self.fleet_progress.grid()
        self.fleet_progress.start()

        # Avvia in thread separato per non bloccare la GUI
        thread = threading.Thread(target=self._fleet_analysis_worker, daemon=True)
        thread.start()

    def _fleet_analysis_worker(self):
        try:
            analyzer = FleetAnalytics(self.fleet_folder_path)
            results = analyzer.run()
            # Aggiorna la GUI nel thread principale
            self.after(0, self._fleet_update_ui, results)
        except Exception as e:
            self.after(0, self._fleet_on_error, str(e))

    def _fleet_update_ui(self, results):
        self.fleet_results = results
        self.fleet_progress.stop()
        self.fleet_progress.grid_remove()
        self.fleet_analyze_btn.configure(state="normal", text="▶ Analizza")

        # Svuota treeview
        for item in self.fleet_tree.get_children():
            self.fleet_tree.delete(item)

        total_km = 0
        total_hours = 0.0
        total_infractions = 0
        ok_count = 0

        for r in results:
            if r["status"] == "OK":
                ok_count += 1
                total_km += r.get("total_km", 0)
                total_hours += r.get("total_drive_time_hours", 0)
                total_infractions += r.get("infractions", 0)

                inf_count = r.get("infractions", 0)
                tag = "warn" if inf_count > 0 else "ok"

                self.fleet_tree.insert("", "end", tags=(tag,), values=(
                    r.get("driver_name", "N/A"),
                    r.get("card_number", "N/A"),
                    f"{r.get('total_km', 0)} km",
                    f"{r.get('total_drive_time_hours', 0):.1f} h",
                    r.get("last_activity", "N/A"),
                    inf_count if inf_count > 0 else "✓ 0",
                    r.get("integrity", "N/A"),
                    r.get("filename", "N/A"),
                ))
            else:
                self.fleet_tree.insert("", "end", tags=("error",), values=(
                    "⚠ ERRORE", "—", "—", "—", "—", "—", "—",
                    r.get("filename", "N/A"),
                ))

        # Aggiorna stats
        self.fleet_stat_labels["fleet_drivers"].configure(text=str(ok_count))
        self.fleet_stat_labels["fleet_km"].configure(text=f"{total_km:,} km")
        self.fleet_stat_labels["fleet_hours"].configure(text=f"{total_hours:.1f} h")
        inf_color = "#E74C3C" if total_infractions > 0 else "#2ECC71"
        self.fleet_stat_labels["fleet_infractions"].configure(text=str(total_infractions), text_color=inf_color)

        self.fleet_export_btn.configure(state="normal")
        self.fleet_pdf_btn.configure(state="normal")
        self.fleet_status_label.configure(text=f"✅ Analisi completata: {ok_count}/{len(results)} file elaborati con successo.", text_color="#2ECC71")

    def _fleet_on_error(self, error_msg):
        self.fleet_progress.stop()
        self.fleet_progress.grid_remove()
        self.fleet_analyze_btn.configure(state="normal", text="▶ Analizza")
        self.fleet_status_label.configure(text=f"❌ Errore: {error_msg}", text_color="#E74C3C")
        messagebox.showerror("Errore Analisi Flotta", f"Errore durante l'analisi:\n{error_msg}")

    def fleet_export_pdf(self):
        if not self.fleet_results:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            initialfile="fleet_report.pdf"
        )
        if path:
            try:
                folder_name = os.path.basename(self.fleet_folder_path) if self.fleet_folder_path else ""
                generate_fleet_pdf(self.fleet_results, path, folder_name)
                messagebox.showinfo("Esportazione PDF Flotta", f"Report PDF flotta salvato in:\n{path}")
            except Exception as e:
                messagebox.showerror("Errore Esportazione PDF", f"Errore: {e}")

    def fleet_export_csv(self):
        if not self.fleet_results:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile="fleet_report.csv"
        )
        if path:
            try:
                import csv
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["File", "Conducente", "Carta", "KM Totali", "Ore Guida", "Ultima Attività", "Infrazioni", "Integrità", "Stato"])
                    for r in self.fleet_results:
                        if r["status"] == "OK":
                            writer.writerow([
                                r.get("filename", ""), r.get("driver_name", ""), r.get("card_number", ""),
                                r.get("total_km", 0), r.get("total_drive_time_hours", 0),
                                r.get("last_activity", ""), r.get("infractions", 0),
                                r.get("integrity", ""), "OK"
                            ])
                        else:
                            writer.writerow([r.get("filename", ""), "ERRORE", "", "", "", "", "", "", r.get("error", "")])
                messagebox.showinfo("Esportazione CSV Flotta", f"Report flotta salvato in:\n{path}")
            except Exception as e:
                messagebox.showerror("Errore Esportazione", f"Errore: {e}")

    # ─────────────────────────────────────────────
    # FILE LOADING & UPDATE UI
    # ─────────────────────────────────────────────
    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("DDD Files", "*.ddd"), ("All Files", "*.*")])
        if path:
            parser = TachoParser(path)
            data = parser.parse()
            if data:
                engine = ComplianceEngine()
                data["infractions"] = engine.analyze(data.get("activities", []))
                data["daily_summaries"] = engine.get_daily_summary(data.get("activities", []))
                self.current_data = data
                self.update_ui(data)
                messagebox.showinfo("Successo", f"Interfaccia aggiornata con i dati di {os.path.basename(path)}")
            else:
                messagebox.showerror("Errore", "Impossibile leggere il file.")

    def update_ui(self, data):
        file_type_val = data['metadata'].get('type', '')
        if not file_type_val:
            has_card_id = any("CardIdentification" in k for k in data.get('raw_tags', {}))
            is_card = has_card_id or data['driver'].get('card_number') != 'N/A'
        else:
            is_card = file_type_val != 'VU'
        
        if is_card:
            name = f"{data['driver'].get('surname', '')} {data['driver'].get('firstname', '')}".strip() or "Conducente Ignoto"
            if name == "N/A N/A": name = "Dati Conducente non decodificati"
            self.id_main_info.configure(text=name)
            self.id_sub_info.configure(text=f"Carta N. {data['driver'].get('card_number', 'N/A')}")
            self.infractions_nav_btn.grid()
        else:
            self.id_main_info.configure(text=f"VEICOLO: {data['vehicle'].get('plate', 'N/A')}")
            self.id_sub_info.configure(text=f"VIN: {data['vehicle'].get('vin', 'N/A')}")
            self.infractions_nav_btn.grid_remove()
            if self.nav_buttons["infractions"].cget("fg_color") != "transparent":
                self.select_section("welcome")

        total_km = sum(d.get('km', 0) for d in data.get('activities', []))
        self.welcome_stats["DISTANZA TOTALE"].configure(text=f"{total_km} KM")
        
        total_min = 0
        for day in data.get('daily_summaries', []):
            try:
                h, m = map(int, day['Guida Totale'].split(':'))
                total_min += h * 60 + m
            except: pass
        self.welcome_stats["ORE GUIDA"].configure(text=f"{total_min // 60}h {total_min % 60}m")
        
        integrity = data['metadata'].get('integrity_check', 'Unknown')
        integrity_upper = str(integrity).upper()

        # Tre stati: VERIFICATO / NON VERIFICABILE (cert mancanti) / MANOMESSO
        VERIFIED_STATES    = {"OK", "VERIFIED (G1)", "TRUE", "VERIFIED", "VERIFIED (LOCAL CHAIN)"}
        UNVERIFIABLE_STATES = {"INCOMPLETE CERTIFICATES", "INCOMPLETE_CERTIFICATES",
                               "NO CERTIFICATES", "UNKNOWN"}
        is_verified     = integrity_upper in VERIFIED_STATES
        is_unverifiable = integrity_upper in UNVERIFIABLE_STATES

        if is_verified:
            self.legal_banner.configure(fg_color="#1B5E20")
            self.legal_status_label.configure(
                text=f"✓ FILE CERTIFICATO — Firma digitale valida. Il file non ha subito manomissioni. ({integrity})",
                text_color="white")
            self.welcome_stats["STATO INTEGRITÀ"].configure(text="CERTIFICATO", text_color="#2ECC71")
        elif is_unverifiable:
            self.legal_banner.configure(fg_color="#4A3800")
            self.legal_status_label.configure(
                text=f"⚠ Firma non verificabile — Certificati ERCA non presenti nel sistema. I dati estratti sono comunque leggibili. ({integrity})",
                text_color="#F0C040")
            self.welcome_stats["STATO INTEGRITÀ"].configure(text="NON VERIF.", text_color="#F0C040")
        else:
            self.legal_banner.configure(fg_color="#B71C1C")
            self.legal_status_label.configure(
                text=f"✗ FIRMA NON VALIDA — Il file potrebbe essere stato manomesso. ({integrity})",
                text_color="white")
            self.welcome_stats["STATO INTEGRITÀ"].configure(text="NON VALIDO", text_color="#E74C3C")

        # Treeview risultati
        for item in self.tag_tree.get_children(): self.tag_tree.delete(item)
        raw_tags = data.get('raw_tags', {})
        
        # Mappa per tenere traccia dei nodi creati (per gerarchia)
        node_map = {}

        # Ordiniamo le chiavi per profondità e poi per offset per una visualizzazione coerente
        all_items = []
        for path, occurrences in raw_tags.items():
            for occ in occurrences:
                all_items.append((path, occ))
        
        # Sort by offset (hex string to int)
        all_items.sort(key=lambda x: int(x[1]['offset'], 16))

        for path, occ in all_items:
            # Dividiamo il path per trovare il genitore
            parts = path.split(" > ")
            current_path = ""
            parent_node = ""
            
            for i, part in enumerate(parts):
                current_path = f"{current_path} > {part}" if current_path else part
                if current_path not in node_map:
                    if i == len(parts) - 1:
                        # È la foglia (il tag corrente)
                        node_id = self.tag_tree.insert(parent_node, "end", text=part, values=(
                            occ.get('offset', 'N/A'),
                            occ.get('tag_id', '??'),
                            occ.get('tag_name', '??'),
                            occ.get('length', 0),
                            occ.get('data_type', 'Data')
                        ), open=True)
                        node_map[current_path] = node_id
                    else:
                        # È un nodo intermedio (container)
                        node_id = self.tag_tree.insert(parent_node, "end", text=part, values=(
                            "---", "---", part, "---", "Container"
                        ), open=True)
                        node_map[current_path] = node_id
                
                parent_node = node_map[current_path]

        for item in self.act_tree.get_children(): self.act_tree.delete(item)
        for day in data.get('daily_summaries', []):
            self.act_tree.insert("", "end", values=(day['Data'], day['Guida Totale'], day['Lavoro Totale'], day['Riposo Totale'], day['Infrazioni']))

        for item in self.inf_tree.get_children(): self.inf_tree.delete(item)
        infractions = data.get("infractions", [])
        for inf in infractions:
            self.inf_tree.insert("", "end", values=(inf['data'], inf['tipo'], inf['severita'], inf.get('descrizione', 'Sforamento tempi')))
        
        min_f, max_f = FinesCalculator.get_total_estimate(infractions)
        fine_text = f"Sanzioni Stimate: € {min_f}" if min_f == max_f else f"Sanzioni Stimate: € {min_f} - {max_f}"
        self.fine_label.configure(text=fine_text)
        
        self.export_button.configure(state="normal")
        self.export_excel_button.configure(state="normal")
        self.export_csv_button.configure(state="normal")
        self.select_section("welcome")

    # ─────────────────────────────────────────────
    # EXPORT (singolo file)
    # ─────────────────────────────────────────────
    def export_json(self):
        if self.current_data:
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
            if path:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.current_data, f, indent=4, ensure_ascii=False)
                messagebox.showinfo("Esportazione", "File salvato correttamente!")

    def export_excel(self):
        if self.current_data:
            path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel Files", "*.xlsx")])
            if path:
                try:
                    ExportManager.export_to_excel(self.current_data, path)
                    messagebox.showinfo("Esportazione Excel", f"File Excel salvato con successo in:\n{path}")
                except Exception as e:
                    messagebox.showerror("Errore Esportazione", f"Errore durante il salvataggio: {e}")

    def export_csv(self):
        if self.current_data:
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
            if path:
                try:
                    ExportManager.export_to_csv(self.current_data, path)
                    messagebox.showinfo("Esportazione CSV", f"File CSV salvato con successo in:\n{path}")
                except Exception as e:
                    messagebox.showerror("Errore Esportazione", f"Errore durante il salvataggio: {e}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
