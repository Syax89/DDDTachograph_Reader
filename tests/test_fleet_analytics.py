"""
Test Suite - Fase 13: Fleet Analytics
Testa FleetAnalytics e FleetPdfExporter con dati mock sintetici.
"""
import os
import sys
import csv
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Assicura che il progetto sia nel path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fleet_analytics import FleetAnalytics
from fleet_pdf_exporter import generate_fleet_pdf


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_parse_result(name="Rossi Mario", card="IT123456789", km=1500,
                       infractions=0, integrity="Verified"):
    """Restituisce un dict che simula TachoParser.parse()"""
    activities = [{"data": "12/02/2026", "km": km, "eventi": [
        {"ora": "06:00", "tipo": "GUIDA"},
        {"ora": "14:00", "tipo": "RIPOSO"},
    ]}]
    return {
        "driver": {"firstname": name.split()[1], "surname": name.split()[0],
                   "card_number": card},
        "vehicle": {"plate": "AB123CD", "vin": "VIN0001"},
        "activities": activities,
        "daily_summaries": [{"Data": "12/02/2026", "Guida Totale": "08:00",
                              "Lavoro Totale": "00:00", "Riposo Totale": "16:00",
                              "Infrazioni": infractions}],
        "infractions": [{"data": "12/02/2026", "tipo": "GUIDA_CONTINUATA",
                          "severita": "SI", "descrizione": "Test"}] * infractions,
        "metadata": {"integrity_check": integrity, "type": "Card"},
        "raw_tags": [],
    }


def _mock_timeline(activities):
    """Simula ComplianceEngine._build_timeline restituendo eventi con durata."""
    timeline = []
    for day in activities:
        for ev in day.get("eventi", []):
            h, m = map(int, ev["ora"].split(":"))
            timeline.append({
                "tipo": ev["tipo"],
                "start": __import__("datetime").datetime(2026, 2, 12, h, m),
                "durata": 480 if ev["tipo"] == "GUIDA" else 60,
            })
    return timeline


# ── Test FleetAnalytics ────────────────────────────────────────────────────────

class TestFleetAnalyticsProcessFile(unittest.TestCase):
    """Testa FleetAnalytics.process_file in isolamento."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _fake_ddd(self, name="fake.ddd"):
        path = os.path.join(self.tmpdir, name)
        open(path, "wb").close()
        return path

    # ── 1. File parsato correttamente ─────────────────────────────────────────
    @patch("fleet_analytics.TachoParser")
    @patch("fleet_analytics.ComplianceEngine")
    def test_process_file_ok(self, MockCE, MockParser):
        # FleetAnalytics creato DENTRO il patch per catturare il mock di ComplianceEngine
        analyzer = FleetAnalytics(self.tmpdir)
        path = self._fake_ddd("driver1.ddd")
        mock_data = _mock_parse_result("Rossi Mario", "IT111", 2000, 0)

        MockParser.return_value.parse.return_value = mock_data
        ce_instance = MockCE.return_value
        ce_instance._build_timeline.side_effect = _mock_timeline
        ce_instance.analyze.return_value = []

        result = analyzer.process_file(path)

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["driver_name"], "Mario Rossi")
        self.assertEqual(result["total_km"], 2000)
        self.assertEqual(result["infractions"], 0)
        self.assertEqual(result["integrity"], "Verified")

    # ── 2. File con infrazioni ────────────────────────────────────────────────
    @patch("fleet_analytics.TachoParser")
    @patch("fleet_analytics.ComplianceEngine")
    def test_process_file_with_infractions(self, MockCE, MockParser):
        analyzer = FleetAnalytics(self.tmpdir)
        path = self._fake_ddd("driver2.ddd")
        mock_data = _mock_parse_result("Bianchi Luigi", "IT222", 500, 3)
        fake_infractions = mock_data["infractions"]

        MockParser.return_value.parse.return_value = mock_data
        ce_instance = MockCE.return_value
        ce_instance._build_timeline.side_effect = _mock_timeline
        ce_instance.analyze.return_value = fake_infractions

        result = analyzer.process_file(path)

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["infractions"], 3)

    # ── 3. File con parsing fallito ───────────────────────────────────────────
    @patch("fleet_analytics.TachoParser")
    @patch("fleet_analytics.ComplianceEngine")
    def test_process_file_parse_failed(self, MockCE, MockParser):
        analyzer = FleetAnalytics(self.tmpdir)
        path = self._fake_ddd("broken.ddd")
        MockParser.return_value.parse.return_value = None

        result = analyzer.process_file(path)

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("error", result)

    # ── 4. Eccezione imprevista nel parser ────────────────────────────────────
    @patch("fleet_analytics.TachoParser")
    @patch("fleet_analytics.ComplianceEngine")
    def test_process_file_exception(self, MockCE, MockParser):
        analyzer = FleetAnalytics(self.tmpdir)
        path = self._fake_ddd("exception.ddd")
        MockParser.return_value.parse.side_effect = RuntimeError("Unexpected crash")

        result = analyzer.process_file(path)

        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Unexpected crash", result["error"])

    # ── 5. Conducente senza nome ──────────────────────────────────────────────
    @patch("fleet_analytics.TachoParser")
    @patch("fleet_analytics.ComplianceEngine")
    def test_process_file_empty_driver_name(self, MockCE, MockParser):
        analyzer = FleetAnalytics(self.tmpdir)
        path = self._fake_ddd("noname.ddd")
        mock_data = _mock_parse_result("Rossi Mario", "IT999", 100)
        mock_data["driver"]["firstname"] = ""
        mock_data["driver"]["surname"] = ""

        MockParser.return_value.parse.return_value = mock_data
        ce_instance = MockCE.return_value
        ce_instance._build_timeline.side_effect = _mock_timeline
        ce_instance.analyze.return_value = []

        result = analyzer.process_file(path)

        self.assertEqual(result["status"], "OK")
        # Nome vuoto è accettabile — non deve crashare
        self.assertIn("driver_name", result)


class TestFleetAnalyticsRun(unittest.TestCase):
    """Testa FleetAnalytics.run() su una cartella con più file."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _create_fake_ddds(self, n=3):
        paths = []
        for i in range(n):
            p = os.path.join(self.tmpdir, f"driver{i}.ddd")
            open(p, "wb").close()
            paths.append(p)
        return paths

    @patch("fleet_analytics.TachoParser")
    @patch("fleet_analytics.ComplianceEngine")
    def test_run_multiple_files(self, MockCE, MockParser):
        self._create_fake_ddds(3)
        mock_data = _mock_parse_result("Verdi Carlo", "IT333", 800)
        MockParser.return_value.parse.return_value = mock_data
        ce_instance = MockCE.return_value
        ce_instance._build_timeline.side_effect = _mock_timeline
        ce_instance.analyze.return_value = []

        analyzer = FleetAnalytics(self.tmpdir)
        results = analyzer.run()

        self.assertEqual(len(results), 3)
        self.assertTrue(all(r["status"] == "OK" for r in results))

    def test_run_empty_folder(self):
        """Cartella senza .ddd — deve restituire lista vuota senza crash."""
        analyzer = FleetAnalytics(self.tmpdir)
        results = analyzer.run()
        self.assertEqual(results, [])

    @patch("fleet_analytics.TachoParser")
    def test_run_mixed_ok_error(self, MockParser):
        """Metà file OK, metà in errore."""
        self._create_fake_ddds(4)

        call_count = {"n": 0}
        def side_effect(path):
            mock = MagicMock()
            call_count["n"] += 1
            if call_count["n"] % 2 == 0:
                mock.parse.return_value = None  # errore
            else:
                mock.parse.return_value = _mock_parse_result()
            return mock

        MockParser.side_effect = side_effect

        with patch("fleet_analytics.ComplianceEngine") as MockCE:
            ce_instance = MockCE.return_value
            ce_instance._build_timeline.side_effect = _mock_timeline
            ce_instance.analyze.return_value = []

            analyzer = FleetAnalytics(self.tmpdir)
            results = analyzer.run()

        ok     = [r for r in results if r["status"] == "OK"]
        errors = [r for r in results if r["status"] == "ERROR"]
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(errors), 2)


class TestFleetAnalyticsSaveCsv(unittest.TestCase):
    """Testa la funzione save_csv."""

    def test_save_csv_creates_file(self):
        tmpdir = tempfile.mkdtemp()
        csv_path = os.path.join(tmpdir, "fleet.csv")

        results = [
            {"filename": "a.ddd", "status": "OK", "driver_name": "Rossi Mario",
             "card_number": "IT001", "total_km": 1000, "total_drive_time_hours": 8.5,
             "last_activity": "10/02/2026", "infractions": 0, "integrity": "Verified"},
            {"filename": "b.ddd", "status": "ERROR", "error": "Parse failed"},
        ]

        analyzer = FleetAnalytics(tmpdir)
        analyzer.results = results
        analyzer.save_csv(csv_path)

        self.assertTrue(os.path.exists(csv_path))
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        # Header + 2 righe
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][0], "a.ddd")
        self.assertEqual(rows[2][0], "b.ddd")


# ── Test FleetPdfExporter ──────────────────────────────────────────────────────

class TestFleetPdfExporter(unittest.TestCase):
    """Testa generate_fleet_pdf con dati mock."""

    def _sample_results(self, n_ok=3, n_err=1, n_inf=1):
        results = []
        for i in range(n_ok):
            results.append({
                "filename": f"driver{i}.ddd",
                "status": "OK",
                "driver_name": f"Conducente {i}",
                "card_number": f"IT{i:06d}",
                "total_km": 1000 * (i + 1),
                "total_drive_time_hours": 8.0 * (i + 1),
                "last_activity": "12/02/2026",
                "infractions": n_inf if i == 0 else 0,
                "integrity": "Verified",
            })
        for j in range(n_err):
            results.append({
                "filename": f"broken{j}.ddd",
                "status": "ERROR",
                "error": "Parse failed",
            })
        return results

    def test_generates_pdf_file(self):
        """Il PDF viene creato e ha dimensione > 0."""
        tmpdir = tempfile.mkdtemp()
        out_path = os.path.join(tmpdir, "fleet.pdf")

        results = self._sample_results()
        generate_fleet_pdf(results, out_path, folder_name="TestFlotta")

        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 1024)  # almeno 1 KB

    def test_pdf_starts_with_pdf_header(self):
        """Il file è un PDF valido (magic bytes)."""
        tmpdir = tempfile.mkdtemp()
        out_path = os.path.join(tmpdir, "fleet.pdf")

        generate_fleet_pdf(self._sample_results(), out_path)

        with open(out_path, "rb") as f:
            header = f.read(4)
        self.assertEqual(header, b"%PDF")

    def test_empty_results_no_crash(self):
        """Lista risultati vuota — non deve crashare."""
        tmpdir = tempfile.mkdtemp()
        out_path = os.path.join(tmpdir, "empty_fleet.pdf")
        generate_fleet_pdf([], out_path, folder_name="Vuota")
        self.assertTrue(os.path.exists(out_path))

    def test_all_errors_no_crash(self):
        """Solo risultati in errore — non deve crashare."""
        tmpdir = tempfile.mkdtemp()
        out_path = os.path.join(tmpdir, "all_err.pdf")
        results = [{"filename": "x.ddd", "status": "ERROR", "error": "crash"}]
        generate_fleet_pdf(results, out_path)
        self.assertTrue(os.path.exists(out_path))

    def test_returns_output_path(self):
        """La funzione deve restituire il path di output."""
        tmpdir = tempfile.mkdtemp()
        out_path = os.path.join(tmpdir, "ret.pdf")
        returned = generate_fleet_pdf(self._sample_results(), out_path)
        self.assertEqual(returned, out_path)

    def test_infractions_section_triggered(self):
        """Nessun crash quando ci sono conducenti con infrazioni."""
        tmpdir = tempfile.mkdtemp()
        out_path = os.path.join(tmpdir, "inf.pdf")
        results = self._sample_results(n_ok=4, n_inf=2)
        generate_fleet_pdf(results, out_path)
        self.assertGreater(os.path.getsize(out_path), 1024)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
