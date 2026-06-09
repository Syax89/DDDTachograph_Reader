import os
import sys
import tempfile
import unittest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from export_manager import ExportManager


class TestExportManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.excel_path = os.path.join(self.tmpdir, "export_test.xlsx")
        self.csv_path = os.path.join(self.tmpdir, "export_test.csv")

        self.mock_data = {
            "metadata": {
                "filename": "mock_file.ddd",
                "parsed_at": "2026-06-08 19:00",
                "integrity_check": "VERIFIED (LOCAL CHAIN)",
                "generation": "G2 (Smart)",
                "file_size_bytes": 12345,
                "coverage_pct": 100.0,
                "is_vu": False,
                "decoder_failure_count": 0,
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
                        {"tipo": "DRIVE", "ora": "08:00"},
                        {"tipo": "REST", "ora": "12:00"}
                    ]
                },
                {
                    "data": "02/06/2026",
                    "km": 200,
                    "eventi": [
                        {"tipo": "DRIVE", "ora": "09:00"},
                        {"tipo": "REST", "ora": "13:00"}
                    ]
                }
            ],
            "events": [
                {"descrizione": "Over speeding", "begin": "2026-06-01T10:30:00+00:00", "end": "2026-06-01T10:35:00+00:00", "confidence": "high"},
            ],
            "faults": [
                {"descrizione": "Sensor fault", "begin": "2026-06-02T11:00:00+00:00", "end": "N/A", "confidence": "medium"},
            ],
            "locations": [
                {"date": "01/06/2026 10:00", "latitude": 45.4642, "longitude": 9.1900, "description": "Milano"},
                {"date": "02/06/2026 11:00", "latitude": 41.9028, "longitude": 12.4964, "description": "Roma"}
            ],
            "border_crossings": [
                {"confidence": "high", "country_left": "I", "country_entered": "F", "odometer_km": 12345},
            ],
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_export_to_excel(self):
        ExportManager.export_to_excel(self.mock_data, self.excel_path)
        self.assertTrue(os.path.exists(self.excel_path))

        xls = pd.ExcelFile(self.excel_path)
        sheet_names = set(xls.sheet_names)

        self.assertIn("Summary", sheet_names)
        self.assertIn("Driver", sheet_names)
        self.assertIn("Vehicle", sheet_names)
        self.assertIn("Daily Activities", sheet_names)
        self.assertIn("Events", sheet_names)
        self.assertIn("Faults", sheet_names)
        self.assertIn("GPS Locations", sheet_names)
        self.assertIn("Border Crossings", sheet_names)

        df_summary = pd.read_excel(xls, "Summary")
        self.assertEqual(df_summary.shape[0], 8)

        df_activities = pd.read_excel(xls, "Daily Activities")
        self.assertEqual(len(df_activities), 4)
        self.assertIn("Date", df_activities.columns)
        self.assertIn("Activity Type", df_activities.columns)

    def test_export_to_csv(self):
        ExportManager.export_to_csv(self.mock_data, self.csv_path)
        self.assertTrue(os.path.exists(self.csv_path))

        df_csv = pd.read_csv(self.csv_path, sep=";")
        self.assertIn("Date", df_csv.columns)
        self.assertIn("Time", df_csv.columns)
        self.assertIn("Activity Type", df_csv.columns)
        self.assertIn("Driver", df_csv.columns)
        self.assertIn("Card Number", df_csv.columns)
        self.assertIn("Vehicle Plate", df_csv.columns)

        self.assertEqual(df_csv.iloc[0]["Driver"], "Rossi Mario")
        self.assertEqual(df_csv.iloc[0]["Vehicle Plate"], "AA123BB")


if __name__ == "__main__":
    unittest.main()
