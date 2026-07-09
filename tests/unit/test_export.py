import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.export import ExportManager


MOCK_DATA = {
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
            "date": "01/06/2026",
            "odometer_km": 150,
            "changes": [
                {"activity": "DRIVE", "time": "08:00"},
                {"activity": "REST", "time": "12:00"}
            ]
        },
        {
            "date": "02/06/2026",
            "odometer_km": 200,
            "changes": [
                {"activity": "DRIVE", "time": "09:00"},
                {"activity": "REST", "time": "13:00"}
            ]
        }
    ],
    "events": [
        {"description": "Over speeding", "begin": "2026-06-01T10:30:00+00:00",
         "end": "2026-06-01T10:35:00+00:00", "confidence": "high"},
    ],
    "faults": [
        {"description": "Sensor fault", "begin": "2026-06-02T11:00:00+00:00",
         "end": "N/A", "confidence": "medium"},
    ],
    "locations": [
        {"date": "01/06/2026 10:00", "latitude": 45.4642, "longitude": 9.1900, "description": "Milano"},
        {"date": "02/06/2026 11:00", "latitude": 41.9028, "longitude": 12.4964, "description": "Roma"}
    ],
    "border_crossings": [
        {"confidence": "high", "country_left": "I", "country_entered": "F", "odometer_km": 12345},
    ],
}


class TestExportManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.excel_path = os.path.join(self.tmpdir, "export_test.xlsx")
        self.csv_path = os.path.join(self.tmpdir, "export_test.csv")
        self.pdf_path = os.path.join(self.tmpdir, "export_test.pdf")
        self.mock_data = MOCK_DATA

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_export_to_excel(self):
        ExportManager.export_to_excel(self.mock_data, self.excel_path)
        self.assertTrue(os.path.exists(self.excel_path))

        from openpyxl import load_workbook
        wb = load_workbook(self.excel_path)
        sheets = set(wb.sheetnames)

        self.assertIn("Summary", sheets)
        self.assertIn("Daily Activities", sheets)
        self.assertIn("Events", sheets)
        self.assertIn("Faults", sheets)
        self.assertIn("GPS Locations", sheets)
        self.assertIn("Border Crossings", sheets)

        # Summary carries file, driver and vehicle info
        summary_text = "\n".join(
            str(c.value) for row in wb["Summary"].iter_rows() for c in row if c.value)
        self.assertIn("mock_file.ddd", summary_text)
        self.assertIn("Mario Rossi", summary_text)
        self.assertIn("AA123BB", summary_text)

        # Daily Activities: monthly grouped report with hours columns + monthly totals
        ws = wb["Daily Activities"]
        headers = [c.value for c in ws[1]]
        self.assertIn("Date", headers)
        self.assertIn("Drive (h)", headers)
        self.assertIn("Work (h)", headers)
        self.assertIn("Rest (h)", headers)
        self.assertIn("Available (h)", headers)
        self.assertIn("Unknown (h)", headers)
        self.assertIn("Total (h)", headers)
        rows_read = ws.max_row - 1
        self.assertGreaterEqual(rows_read, 3)  # description row + 2 days + 1 monthly total

        # Events: humanised columns, formatted timestamps, hidden keys dropped
        ws = wb["Events"]
        headers = [c.value for c in ws[1]]
        self.assertIn("Description", headers)
        self.assertNotIn("Confidence", headers)
        values = [c.value for c in ws[3]]
        self.assertIn("2026-06-01 10:30", values)
        # Row 2 is the section description
        desc = ws.cell(row=2, column=1).value
        self.assertIsNotNone(desc)

    def test_export_to_csv(self):
        ExportManager.export_to_csv(self.mock_data, self.csv_path)
        self.assertTrue(os.path.exists(self.csv_path))

        with open(self.csv_path, encoding="utf-8-sig") as handle:
            text = handle.read()

        self.assertIn("DDD TACHOGRAPH REPORT", text)
        self.assertIn("Mario Rossi", text)
        self.assertIn("=== DAILY ACTIVITIES ===", text)
        self.assertIn("=== EVENTS ===", text)
        # Section description row
        self.assertIn("Logged events", text)
        # Monthly activity report: Date, Odometer, hours columns + monthly totals
        self.assertIn("Date;Odometer km;Drive (h);Work (h);Rest (h);Available (h);Unknown (h);Total (h)", text)
        self.assertIn("01/06/2026", text)
        self.assertIn("04:00", text)
        self.assertIn("06/2026 TOTAL", text)
        # UTC note
        self.assertIn("UTC", text)
        # Formatted timestamp, not raw ISO
        self.assertIn("2026-06-01 10:30", text)
        self.assertNotIn("2026-06-01T10:30:00+00:00", text)

    def test_export_to_pdf(self):
        ExportManager.export_to_pdf(self.mock_data, self.pdf_path)
        self.assertTrue(os.path.exists(self.pdf_path))
        with open(self.pdf_path, "rb") as handle:
            head = handle.read(5)
        self.assertEqual(head, b"%PDF-")
        self.assertGreater(os.path.getsize(self.pdf_path), 1000)


if __name__ == "__main__":
    unittest.main()
