import os
import json
import glob
from concurrent.futures import ThreadPoolExecutor
from ddd_parser import TachoParser
from compliance_engine import ComplianceEngine

class FleetAnalytics:
    def __init__(self, folder_path):
        self.folder_path = folder_path
        self.results = []
        self.compliance = ComplianceEngine()

    def process_file(self, file_path):
        try:
            filename = os.path.basename(file_path)
            parser = TachoParser(file_path)
            data = parser.parse()
            
            if not data:
                return {"filename": filename, "status": "ERROR", "error": "Parse failed"}

            # Basic Info
            driver = data.get("driver", {})
            name = f"{driver.get('firstname', '')} {driver.get('surname', '')}".strip()
            card = driver.get('card_number', 'UNKNOWN')
            
            # Metrics
            activities = data.get("activities", [])
            total_km = sum(day.get("km", 0) for day in activities)
            
            # Calculate Total Drive Time (minutes)
            total_drive_min = 0
            last_activity = "N/A"
            
            if activities:
                # Use ComplianceEngine to build a proper timeline with durations
                timeline = self.compliance._build_timeline(activities)
                
                if timeline:
                    # Sum up driving time
                    for ev in timeline:
                        if ev["tipo"] == "GUIDA":
                            total_drive_min += ev["durata"]
                    
                    # Last activity date
                    last_ev = timeline[-1]
                    last_activity = last_ev["start"].strftime("%d/%m/%Y")

            # Infractions
            infractions = self.compliance.analyze(activities)
            infraction_count = len(infractions)
            
            # Integrity
            integrity = data.get("metadata", {}).get("integrity_check", "Unknown")

            return {
                "filename": filename,
                "status": "OK",
                "driver_name": name,
                "card_number": card,
                "total_km": total_km,
                "total_drive_time_hours": round(total_drive_min / 60, 2),
                "last_activity": last_activity,
                "infractions": infraction_count,
                "integrity": integrity
            }

        except Exception as e:
            return {"filename": os.path.basename(file_path), "status": "ERROR", "error": str(e)}

    def run(self):
        files = glob.glob(os.path.join(self.folder_path, "*.ddd"))
        print(f"Analyzing {len(files)} files in {self.folder_path}...")
        
        with ThreadPoolExecutor() as executor:
            self.results = list(executor.map(self.process_file, files))
        
        return self.results

    def print_report(self):
        print(f"{'FILENAME':<25} | {'DRIVER':<20} | {'KM':<8} | {'DRIVE(H)':<8} | {'INF':<3} | {'STATUS':<15}")
        print("-" * 95)
        for r in self.results:
            if r["status"] == "OK":
                print(f"{r['filename'][:25]:<25} | {r['driver_name'][:20]:<20} | {r['total_km']:<8} | {r['total_drive_time_hours']:<8} | {r['infractions']:<3} | {r['integrity'][:15]:<15}")
            else:
                print(f"{r['filename'][:25]:<25} | {'ERROR':<20} | {'-':<8} | {'-':<8} | {'-':<3} | {r.get('error', '')}")

    def save_csv(self, filename="fleet_report.csv"):
        import csv
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Filename", "Driver", "Card", "Total KM", "Drive Time (h)", "Last Activity", "Infractions", "Status", "Integrity"])
            for r in self.results:
                if r["status"] == "OK":
                    writer.writerow([r["filename"], r["driver_name"], r["card_number"], r["total_km"], r["total_drive_time_hours"], r["last_activity"], r["infractions"], "OK", r["integrity"]])
                else:
                    writer.writerow([r["filename"], "ERROR", "", "", "", "", "", r.get("error", ""), ""])
        print(f"Report saved to {filename}")

import sys

if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    analyzer = FleetAnalytics(folder)
    analyzer.results = analyzer.run()
    analyzer.print_report()
    analyzer.save_csv()