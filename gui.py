import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk
import json
import os
from datetime import datetime
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine
from fines_calculator import FinesCalculator

# Impostazioni Tema Aurora ✨
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Aurora DDD Analytics ✨")
        self.geometry("1100x800")
        self.minsize(900, 600)

        # Configurazione Grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar ---
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="DDD ANALYTICS", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 20))

        self.open_button = ctk.CTkButton(self.sidebar_frame, text="Carica File .ddd", command=self.open_file, height=40, font=ctk.CTkFont(weight="bold"))
        self.open_button.grid(row=1, column=0, padx=20, pady=10)

        self.export_button = ctk.CTkButton(self.sidebar_frame, text="Esporta Report JSON", command=self.export_json, state="disabled", fg_color="transparent", border_width=1)
        self.export_button.grid(row=2, column=0, padx=20, pady=10)

        self.info_box = ctk.CTkTextbox(self.sidebar_frame, width=180, height=300, font=ctk.CTkFont(size=12))
        self.info_box.grid(row=3, column=0, padx=20, pady=20)
        self.info_box.insert("0.0", "DETTAGLI ANALISI:\n\nCaricare un file per visualizzare i dettagli tecnici.")

        # --- Main View ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(3, weight=1) # Tabella row

        # 1. Header Intelligente
        self.header_frame = ctk.CTkFrame(self.main_frame, height=100, corner_radius=10)
        self.header_frame.grid(row=0, column=0, padx=0, pady=(0, 20), sticky="ew")
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.header_title = ctk.CTkLabel(self.header_frame, text="In attesa di file...", font=ctk.CTkFont(size=24, weight="bold"))
        self.header_title.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")
        
        self.header_subtitle = ctk.CTkLabel(self.header_frame, text="Seleziona un file della Carta Autista o del Veicolo", font=ctk.CTkFont(size=14))
        self.header_subtitle.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="w")

        # 2. Dashboard a Mattonelle
        self.dashboard_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.dashboard_frame.grid(row=1, column=0, padx=0, pady=(0, 20), sticky="ew")
        for i in range(4):
            self.dashboard_frame.grid_columnconfigure(i, weight=1)

        self.tiles = {}
        self._create_tile(0, "Distanza Totale", "0 KM", "blue")
        self._create_tile(1, "Ore di Guida", "00:00", "blue")
        self._create_tile(2, "Infrazioni", "0", "gray")
        self._create_tile(3, "Sanzioni Stimate", "€ 0", "gray")

        # 3. Tabella Semplificata
        self.table_label = ctk.CTkLabel(self.main_frame, text="Riepilogo Giornaliero (Daily Summaries)", font=ctk.CTkFont(size=18, weight="bold"))
        self.table_label.grid(row=2, column=0, padx=0, pady=(10, 5), sticky="w")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", borderwidth=0, rowheight=30)
        style.configure("Treeview.Heading", background="#333333", foreground="white", relief="flat")
        style.map("Treeview", background=[('selected', '#1f538d')])

        columns = ("Data", "Guida", "Lavoro", "Riposo", "Infrazioni")
        self.tree = ttk.Treeview(self.main_frame, columns=columns, show='headings')
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor="center")

        self.tree.grid(row=3, column=0, padx=0, pady=(0, 0), sticky="nsew")
        
        self.current_data = None

    def _create_tile(self, col, title, value, color_type):
        colors = {
            "blue": ("#3B8ED0", "#1F538D"),
            "gray": ("#4A4A4A", "#2B2B2B"),
            "red": ("#E74C3C", "#C0392B"),
            "orange": ("#E67E22", "#D35400")
        }
        fg, border = colors.get(color_type, colors["blue"])
        
        tile = ctk.CTkFrame(self.dashboard_frame, corner_radius=10, fg_color=fg)
        tile.grid(row=0, column=col, padx=(0 if col==0 else 10, 0), sticky="nsew")
        
        label_title = ctk.CTkLabel(tile, text=title.upper(), font=ctk.CTkFont(size=11, weight="bold"))
        label_title.pack(pady=(10, 0), padx=10)
        
        label_value = ctk.CTkLabel(tile, text=value, font=ctk.CTkFont(size=22, weight="bold"))
        label_value.pack(pady=(5, 15), padx=10)
        
        self.tiles[title] = {"frame": tile, "value": label_value}

    def _update_tile(self, title, value, color_type=None):
        if title in self.tiles:
            self.tiles[title]["value"].configure(text=value)
            if color_type:
                colors = {
                    "blue": ("#3B8ED0", "#1F538D"),
                    "gray": ("#4A4A4A", "#2B2B2B"),
                    "red": ("#E74C3C", "#C0392B"),
                    "orange": ("#E67E22", "#D35400")
                }
                fg, _ = colors.get(color_type, colors["blue"])
                self.tiles[title]["frame"].configure(fg_color=fg)

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("DDD Files", "*.ddd"), ("All Files", "*.*")])
        if path:
            parser = TachoParser(path)
            data = parser.parse()
            if data:
                engine = ComplianceEngine()
                # Analyze infractions
                infractions = engine.analyze(data.get("activities", []))
                data["infractions"] = infractions
                
                # Get daily summaries
                data["daily_summaries"] = engine.get_daily_summary(data.get("activities", []))
                
                self.current_data = data
                self.update_ui(data)
                messagebox.showinfo("Completato", f"Analisi di {os.path.basename(path)} completata!")
            else:
                messagebox.showerror("Errore", "Impossibile leggere il file.")

    def update_ui(self, data):
        # 1. Header Intelligente (Glossario: Card -> Autista, VU -> Veicolo)
        file_type = "MEMORIA MASSA VEICOLO" if data['metadata'].get('type') == 'VU' else "CARTA CONDUCENTE"
        # Glossario applicato al titolo
        display_type = file_type.replace("VEICOLO", "VEICOLO (VU)").replace("CONDUCENTE", "AUTISTA (Card)")
        
        self.header_title.configure(text=display_type)
        
        info_subtitle = f"Soggetto: {data['driver']['name']} {data['driver']['surname']}" if data['driver']['name'] else f"Veicolo: {data['vehicle']['plate']}"
        self.header_subtitle.configure(text=info_subtitle)

        # 2. Dashboard a Mattonelle
        total_km = sum(d.get('km', 0) for d in data.get('activities', []))
        self._update_tile("Distanza Totale", f"{total_km} KM", "blue")
        
        # Calculate Total Driving Hours
        total_driving_min = 0
        for day in data.get('daily_summaries', []):
            h, m = map(int, day['Guida Totale'].split(':'))
            total_driving_min += h * 60 + m
        self._update_tile("Ore di Guida", f"{total_driving_min // 60}h {total_driving_min % 60}m", "blue")
        
        infractions_count = len(data.get("infractions", []))
        inf_color = "red" if infractions_count > 0 else "gray"
        self._update_tile("Infrazioni", str(infractions_count), inf_color)
        
        min_fine, max_fine = FinesCalculator.get_total_estimate(data.get("infractions", []))
        fine_text = f"€ {min_fine}" if min_fine == max_fine else f"€ {min_fine} - {max_fine}"
        self._update_tile("Sanzioni Stimate", fine_text, "orange" if min_fine > 0 else "gray")

        # 3. Sidebar Info Box (Dettagli Tecnici)
        self.info_box.delete("0.0", "end")
        info_text = f"GENERAZIONE: {data['metadata']['generation']}\n"
        info_text += f"VIN: {data['vehicle']['vin']}\n"
        info_text += f"TARGA: {data['vehicle']['plate']}\n"
        info_text += f"AUTISTA: {data['driver']['surname']} {data['driver']['name']}\n"
        info_text += f"N. CARTA: {data['driver']['card_number']}\n"
        
        infractions = data.get("infractions", [])
        if infractions:
            info_text += f"\n--- DETTAGLIO INFRAZIONI ({len(infractions)}) ---\n"
            for inf in infractions:
                info_text += f"• {inf['data']}: {inf['tipo']}\n  ({inf['severita']})\n"
        else:
            info_text += "\nAnalisi completata: nessuna infrazione rilevata ✅"
            
        self.info_box.insert("0.0", info_text)

        # 4. Tabella Semplificata (Daily Summaries)
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        for day in data.get('daily_summaries', []):
            self.tree.insert("", "end", values=(
                day['Data'], 
                day['Guida Totale'], 
                day['Lavoro Totale'], 
                day['Riposo Totale'], 
                day['Infrazioni']
            ))
        
        self.export_button.configure(state="normal")

    def export_json(self):
        if self.current_data:
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
            if path:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.current_data, f, indent=4, ensure_ascii=False)
                messagebox.showinfo("Esportazione", "File salvato correttamente!")

if __name__ == "__main__":
    app = App()
    app.mainloop()
