import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import json
import os
from datetime import datetime
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from fines_calculator import FinesCalculator
from export_manager import ExportManager

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
        self.sidebar_frame.grid_rowconfigure(6, weight=1)
        
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
        self.infractions_nav_btn.grid_remove() # Hidden by default

        self.export_button = ctk.CTkButton(self.sidebar_frame, text="Esporta JSON", command=self.export_json, state="disabled", fg_color="transparent", border_width=1)
        self.export_button.grid(row=7, column=0, padx=20, pady=(20, 10))

        self.export_excel_button = ctk.CTkButton(self.sidebar_frame, text="Esporta Excel", command=self.export_excel, state="disabled", fg_color="#1E8449", hover_color="#145A32")
        self.export_excel_button.grid(row=8, column=0, padx=20, pady=10)

        self.export_csv_button = ctk.CTkButton(self.sidebar_frame, text="Esporta CSV", command=self.export_csv, state="disabled", fg_color="transparent", border_width=1)
        self.export_csv_button.grid(row=9, column=0, padx=20, pady=10)

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

        self.select_section("welcome")
        self.current_data = None

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

    def _setup_welcome_section(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sections["welcome"] = frame
        frame.grid_columnconfigure(0, weight=1)

        welcome_label = ctk.CTkLabel(frame, text="Benvenuto in DDD Analytics", font=ctk.CTkFont(size=28, weight="bold"))
        welcome_label.pack(pady=(40, 10))
        
        self.welcome_subtitle = ctk.CTkLabel(frame, text="Carica un file per iniziare l'analisi rivoluzionaria.", font=ctk.CTkFont(size=16))
        self.welcome_subtitle.pack(pady=(0, 20))

        # Legal Validation Prominent Banner
        self.legal_banner = ctk.CTkFrame(frame, height=60, corner_radius=10, fg_color="gray20")
        self.legal_banner.pack(pady=10, padx=40, fill="x")
        self.legal_banner.pack_propagate(False)
        self.legal_status_label = ctk.CTkLabel(self.legal_banner, text="In attesa di caricamento file...", font=ctk.CTkFont(size=16, weight="bold"))
        self.legal_status_label.pack(expand=True)

        # Identity Card
        self.id_card = ctk.CTkFrame(frame, width=600, height=250, corner_radius=20, border_width=2, border_color="#1F538D")
        self.id_card.pack(pady=20, padx=40, fill="x")
        self.id_card.pack_propagate(False)

        self.id_title = ctk.CTkLabel(self.id_card, text="IDENTITÀ SOGGETTO", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3B8ED0")
        self.id_title.pack(pady=(20, 10), padx=30, anchor="w")

        self.id_main_info = ctk.CTkLabel(self.id_card, text="Nessun dato caricato", font=ctk.CTkFont(size=32, weight="bold"))
        self.id_main_info.pack(pady=10, padx=30, anchor="w")

        self.id_sub_info = ctk.CTkLabel(self.id_card, text="Carica un file .ddd (Carta o Veicolo)", font=ctk.CTkFont(size=18))
        self.id_sub_info.pack(pady=5, padx=30, anchor="w")

        # Stats Grid in Welcome
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

    def _setup_explore_section(self):
        frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sections["explore"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(frame, text="Esplora Dati Grezzi (Regedit Style)", font=ctk.CTkFont(size=20, weight="bold"))
        header.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        # Treeview for Raw Tags
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
        # 1. Welcome Section Update
        # Determina il tipo di file dai metadati o dalla presenza di certi tag
        file_type_val = data['metadata'].get('type', '')
        if not file_type_val:
            # Fallback check on raw_tags
            has_card_id = any("CardIdentification" in k for k in data.get('raw_tags', {}))
            is_card = has_card_id or data['driver'].get('card_number') != 'N/A'
        else:
            is_card = file_type_val != 'VU'
        
        if is_card:
            name = f"{data['driver'].get('surname', '')} {data['driver'].get('firstname', '')}".strip() or "Conducente Ignoto"
            if name == "N/A N/A": name = "Dati Conducente non decodificati"
            self.id_main_info.configure(text=name)
            self.id_sub_info.configure(text=f"Carta N. {data['driver'].get('card_number', 'N/A')}")
            self.infractions_nav_btn.grid() # Show for Card
        else:
            self.id_main_info.configure(text=f"VEICOLO: {data['vehicle'].get('plate', 'N/A')}")
            self.id_sub_info.configure(text=f"VIN: {data['vehicle'].get('vin', 'N/A')}")
            self.infractions_nav_btn.grid_remove() # Hide for VU
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
        
        # Update Legal Status Prominently
        integrity = data['metadata'].get('integrity_check', 'Unknown')
        is_valid = str(integrity).upper() in ["OK", "VERIFIED (G1)", "TRUE", "VERIFIED"]
        
        if is_valid:
            self.legal_banner.configure(fg_color="#1B5E20") # Dark Green
            self.legal_status_label.configure(text=f"✓ FILE CERTIFICATO: Il file non ha subito manomissioni ({integrity})", text_color="white")
            self.welcome_stats["STATO INTEGRITÀ"].configure(text="CERTIFICATO", text_color="#2ECC71")
        else:
            self.legal_banner.configure(fg_color="#B71C1C") # Dark Red
            self.legal_status_label.configure(text=f"⚠ ATTENZIONE: Integrità non verificata o file non valido ({integrity})", text_color="white")
            self.welcome_stats["STATO INTEGRITÀ"].configure(text="NON VALIDO", text_color="#E74C3C")

        # 2. Explore Section (Regedit Style)
        for item in self.tag_tree.get_children(): self.tag_tree.delete(item)
        raw_tags = data.get('raw_tags', {})
        if isinstance(raw_tags, dict):
            for k, v in raw_tags.items():
                self.tag_tree.insert("", "end", values=("N/A", v.get('tag', '??'), v.get('name', k), v.get('length', 0), "Data"))
        elif isinstance(raw_tags, list):
            for tag in raw_tags:
                self.tag_tree.insert("", "end", values=(tag.get('offset', 'N/A'), tag.get('tag', '??'), tag.get('name', '??'), tag.get('length', 0), tag.get('type', 'Data')))

        # 3. Activities Section
        for item in self.act_tree.get_children(): self.act_tree.delete(item)
        for day in data.get('daily_summaries', []):
            self.act_tree.insert("", "end", values=(day['Data'], day['Guida Totale'], day['Lavoro Totale'], day['Riposo Totale'], day['Infrazioni']))

        # 4. Infractions Section
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
