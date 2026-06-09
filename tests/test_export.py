import os
import sys
import tempfile
import unittest
import pandas as pd
from datetime import datetime

# Assicura che il progetto sia nel path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from export_manager import ExportManager

class TestExportManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.excel_path = os.path.join(self.tmpdir, "export_test.xlsx")
        self.csv_path = os.path.join(self.tmpdir, "export_test.csv")
        
        # Mock data representing parsed tachograph output
        self.mock_data = {
            "metadata": {
                "filename": "mock_file.ddd",
                "parsed_at": "2026-06-08 19:00",
                "integrity_check": "VERIFIED (LOCAL CHAIN)"
            },
            "driver": {
                "firstname": "Mario",
                "surname": "Rossi",
                "card_number": "IT123456789"
            },
            "vehicle": {
                "plate": "AA123BB",
                "vin": "VIN1234567890"
            },
            "activities": [
                {
                    "data": "01/06/2026",
                    "km": 150,
                    "eventi": [
                        {"tipo": "GUIDA", "ora": "08:00"},
                        {"tipo": "RIPOSO", "ora": "12:00"}
                    ]
                },
                {
                    "data": "02/06/2026",
                    "km": 200,
                    "eventi": [
                        {"tipo": "GUIDA", "ora": "09:00"},
                        {"tipo": "RIPOSO", "ora": "13:00"}
                    ]
                }
            ],
            "daily_summaries": [
                {"Data": "01/06/2026", "Guida Totale": "04:00", "Lavoro Totale": "00:00", "Riposo Totale": "20:00", "Infrazioni": 0},
                {"Data": "02/06/2026", "Guida Totale": "04:00", "Lavoro Totale": "00:00", "Riposo Totale": "20:00", "Infrazioni": 1}
            ],
            "infractions": [
                {"data": "02/06/2026", "tipo": "ECCESSO_GUIDA_CONTINUA", "severita": "SI", "descrizione": "Superato il limite di guida"}
            ],
            "locations": [
                {"date": "01/06/2026 10:00", "latitude": 45.4642, "longitude": 9.1900, "description": "Milano"},
                {"date": "02/06/2026 11:00", "latitude": 41.9028, "longitude": 12.4964, "description": "Roma"}
            ]
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_export_to_excel(self):
        """Test exporting data to Excel format with multiple sheets."""
        ExportManager.export_to_excel(self.mock_data, self.excel_path)
        self.assertTrue(os.path.exists(self.excel_path))
        
        # Verify the sheets exist and are populated
        xls = pd.ExcelFile(self.excel_path)
        self.assertIn("Riepilogo", xls.sheet_names)
        self.assertIn("Attività Giornaliere", xls.sheet_names)
        self.assertIn("Infrazioni", xls.sheet_names)
        self.assertIn("Posizioni GPS", xls.sheet_names)
        
        # Test Riepilogo content
        df_summary = pd.read_excel(xls, "Riepilogo")
        self.assertEqual(df_summary.shape[0], 10)
        self.assertIn("Milano", str(pd.read_excel(xls, "Posizioni GPS").iloc[0]["description"]))
        
        # Verify KM calculations (150 + 200 = 350)
        km_row = df_summary[df_summary["Campo"] == "Distanza Totale (KM)"]
        self.assertEqual(km_row["Valore"].values[0], 350)
        
        # Verify hours calculations (4h + 4h = 8h 0m)
        hours_row = df_summary[df_summary["Campo"] == "Ore Guida Totali"]
        self.assertEqual(hours_row["Valore"].values[0], "8h 0m")

    def test_export_to_csv(self):
        """Test exporting data to CSV format."""
        ExportManager.export_to_csv(self.mock_data, self.csv_path)
        self.assertTrue(os.path.exists(self.csv_path))
        
        # Verify content of the CSV
        df_csv = pd.read_csv(self.csv_path, sep=';')
        self.assertIn("Data", df_csv.columns)
        self.assertIn("Inizio", df_csv.columns)
        self.assertIn("Tipo Attività", df_csv.columns)
        self.assertIn("Conducente", df_csv.columns)
        
        self.assertEqual(df_csv.iloc[0]["Conducente"], "Rossi Mario")
        self.assertEqual(df_csv.iloc[0]["Veicolo"], "AA123BB")

if __name__ == '__main__':
    unittest.main()
