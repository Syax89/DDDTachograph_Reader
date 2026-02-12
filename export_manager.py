import pandas as pd
import os
from datetime import datetime

class ExportManager:
    @staticmethod
    def export_to_excel(data, filepath):
        """
        Esporta i dati in un file Excel con fogli multipli.
        """
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # 1. Foglio Riepilogo
            metadata = data.get('metadata', {})
            driver = data.get('driver', {})
            vehicle = data.get('vehicle', {})
            
            summary_data = {
                'Campo': [
                    'File', 'Data Analisi', 'Integrità', 
                    'Conducente', 'N. Carta', 
                    'Veicolo', 'Targa', 'VIN',
                    'Distanza Totale (KM)', 'Ore Guida Totali'
                ],
                'Valore': [
                    metadata.get('filename', 'N/A'),
                    metadata.get('parsed_at', datetime.now().strftime("%Y-%m-%d %H:%M")),
                    metadata.get('integrity_check', 'OK'),
                    f"{driver.get('surname', '')} {driver.get('firstname', '')}".strip() or 'N/A',
                    driver.get('card_number', 'N/A'),
                    'N/A', # Placeholder for vehicle type if needed
                    vehicle.get('plate', 'N/A'),
                    vehicle.get('vin', 'N/A'),
                    ExportManager._calculate_total_km(data.get('activities', [])),
                    ExportManager._calculate_total_hours(data.get('daily_summaries', []))
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='Riepilogo', index=False)

            # 2. Foglio Attività Giornaliere
            daily_summaries = data.get('daily_summaries', [])
            if daily_summaries:
                pd.DataFrame(daily_summaries).to_excel(writer, sheet_name='Attività Giornaliere', index=False)

            # 3. Foglio Infrazioni
            infractions = data.get('infractions', [])
            if infractions:
                pd.DataFrame(infractions).to_excel(writer, sheet_name='Infrazioni', index=False)

            # 4. Foglio Posizioni GPS (se disponibili)
            gps_data = data.get('gps_positions', [])
            if gps_data:
                pd.DataFrame(gps_data).to_excel(writer, sheet_name='Posizioni GPS', index=False)
            
            # Formattazione base (opzionale, Pandas lo fa già decentemente)
            # Potremmo aggiungere formattazione openpyxl qui se necessario

    @staticmethod
    def export_to_csv(data, filepath):
        """
        Esporta i dati in un formato CSV piatto per sistemi contabili.
        """
        rows = []
        driver_name = f"{data.get('driver', {}).get('surname', '')} {data.get('driver', {}).get('firstname', '')}".strip()
        card_number = data.get('driver', {}).get('card_number', 'N/A')
        plate = data.get('vehicle', {}).get('plate', 'N/A')
        
        for day in data.get('activities', []):
            date = day.get('data', 'N/A')
            events = day.get('eventi', [])
            
            for i in range(len(events)):
                ev = events[i]
                tipo = ev.get('tipo', 'N/A')
                ora_inizio = ev.get('ora', 'N/A')
                
                # Calcola ora fine (se c'è un evento successivo)
                ora_fine = "23:59"
                durata = "N/D"
                if i < len(events) - 1:
                    ora_fine = events[i+1].get('ora', '23:59')
                    try:
                        h1, m1 = map(int, ora_inizio.split(':'))
                        h2, m2 = map(int, ora_fine.split(':'))
                        diff = (h2 * 60 + m2) - (h1 * 60 + m1)
                        durata = f"{diff} min"
                    except: pass
                
                rows.append({
                    'Data': date,
                    'Inizio': ora_inizio,
                    'Fine': ora_fine,
                    'Durata': durata,
                    'Tipo Attività': tipo,
                    'Conducente': driver_name,
                    'Carta': card_number,
                    'Veicolo': plate
                })
        
        if rows:
            pd.DataFrame(rows).to_csv(filepath, index=False, sep=';', encoding='utf-8-sig')

    @staticmethod
    def _calculate_total_km(activities):
        total = 0
        for d in activities:
            try:
                total += int(d.get('km', 0))
            except (ValueError, TypeError):
                pass
        return total

    @staticmethod
    def _calculate_total_hours(daily_summaries):
        total_min = 0
        for day in daily_summaries:
            try:
                h, m = map(int, day.get('Guida Totale', '0:0').split(':'))
                total_min += h * 60 + m
            except: pass
        return f"{total_min // 60}h {total_min % 60}m"
