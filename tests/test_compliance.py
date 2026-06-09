"""Tests for the ComplianceEngine covering EU 561/2006 regulations."""
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compliance_engine import ComplianceEngine, _normalize_activity


class TestNormalizeActivity(unittest.TestCase):
    def test_normalize_guida(self):
        self.assertEqual(_normalize_activity("GUIDA"), "GUIDA")
        self.assertEqual(_normalize_activity("DRIVE"), "GUIDA")
        self.assertEqual(_normalize_activity("guida"), "GUIDA")

    def test_normalize_riposo(self):
        self.assertEqual(_normalize_activity("RIPOSO"), "RIPOSO")
        self.assertEqual(_normalize_activity("REST"), "RIPOSO")
        self.assertEqual(_normalize_activity("BREAK"), "RIPOSO")
        self.assertEqual(_normalize_activity("BREAK_REST"), "RIPOSO")

    def test_normalize_lavoro(self):
        self.assertEqual(_normalize_activity("LAVORO"), "LAVORO")
        self.assertEqual(_normalize_activity("WORK"), "LAVORO")

    def test_normalize_disponibile(self):
        self.assertEqual(_normalize_activity("DISPONIBILE"), "DISPONIBILE")
        self.assertEqual(_normalize_activity("DISPONIBILITÀ"), "DISPONIBILE")
        self.assertEqual(_normalize_activity("AVAILABLE"), "DISPONIBILE")

    def test_normalize_unknown_defaults_to_lavoro(self):
        self.assertEqual(_normalize_activity("SOMETHING_ELSE"), "LAVORO")


class TestComplianceContinuousDriving(unittest.TestCase):
    def setUp(self):
        self.engine = ComplianceEngine()

    def test_driving_under_4_5h_no_infraction(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "10:00"},  # 2h driving, then rest
            ]
        }]
        result = self.engine.analyze(activities)
        driving_infractions = [i for i in result if "ECCESSO_GUIDA_CONTINUA" in i["tipo"]]
        self.assertEqual(len(driving_infractions), 0)

    def test_driving_over_4_5h_causes_infraction(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "14:00"},  # 6h driving -> 1.5h excess
            ]
        }]
        result = self.engine.analyze(activities)
        driving_infractions = [i for i in result if "ECCESSO_GUIDA_CONTINUA" in i["tipo"]]
        self.assertGreater(len(driving_infractions), 0)
        self.assertIn("severita", driving_infractions[0])

    def test_driving_excess_under_30min_is_MI(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "12:50"},  # 4h50m -> 20min excess
            ]
        }]
        result = self.engine.analyze(activities)
        driving = [i for i in result if "ECCESSO_GUIDA_CONTINUA" in i["tipo"]]
        self.assertGreater(len(driving), 0)
        self.assertEqual(driving[0]["severita"], "MI")

    def test_driving_reset_after_45min_break(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "12:00"},   # 4h driving
                {"tipo": "GUIDA", "ora": "12:45"},     # 45min rest -> reset
                {"tipo": "RIPOSO", "ora": "15:00"},     # 2h15m driving (under 4.5h after reset)
            ]
        }]
        result = self.engine.analyze(activities)
        driving = [i for i in result if "ECCESSO_GUIDA_CONTINUA" in i["tipo"]]
        self.assertEqual(len(driving), 0)


class TestComplianceSplitBreak(unittest.TestCase):
    def setUp(self):
        self.engine = ComplianceEngine()

    def test_split_break_15_plus_30_resets_driving(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "11:00"},    # 3h driving
                {"tipo": "GUIDA", "ora": "11:15"},      # 15min rest
                {"tipo": "RIPOSO", "ora": "12:45"},      # 1.5h driving
                {"tipo": "GUIDA", "ora": "13:15"},       # 30min rest -> split break complete
                {"tipo": "RIPOSO", "ora": "15:00"},      # 1.75h driving after reset
            ]
        }]
        result = self.engine.analyze(activities)
        driving = [i for i in result if "ECCESSO_GUIDA_CONTINUA" in i["tipo"]]
        self.assertEqual(len(driving), 0, f"Should be 0 infractions, got {driving}")

    def test_split_break_incomplete_causes_infraction(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "11:00"},    # 3h driving
                {"tipo": "GUIDA", "ora": "11:15"},      # 15min rest
                {"tipo": "RIPOSO", "ora": "13:15"},      # 2h driving
                {"tipo": "GUIDA", "ora": "13:35"},       # 20min rest (< 30)
                {"tipo": "RIPOSO", "ora": "15:45"},      # 2h10m driving
            ]
        }]
        result = self.engine.analyze(activities)
        driving = [i for i in result if "ECCESSO_GUIDA_CONTINUA" in i["tipo"]]
        self.assertGreater(len(driving), 0)


class TestComplianceDailyRest(unittest.TestCase):
    def setUp(self):
        self.engine = ComplianceEngine()

    def test_daily_rest_under_9h_causes_infraction(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "LAVORO", "ora": "12:00"},
                {"tipo": "RIPOSO", "ora": "16:00"},
                {"tipo": "GUIDA", "ora": "22:00"},
                {"tipo": "RIPOSO", "ora": "23:59"},
            ]
        }]
        result = self.engine.analyze(activities)
        rest = [i for i in result if "RIPOSO_GIORNALIERO" in i["tipo"]]
        self.assertGreater(len(rest), 0)

    def test_daily_rest_9h_or_more_no_infraction(self):
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "RIPOSO", "ora": "00:00"},
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "12:00"},
                {"tipo": "LAVORO", "ora": "21:30"},
                {"tipo": "RIPOSO", "ora": "23:00"},
            ]
        }]
        result = self.engine.analyze(activities)
        rest = [i for i in result if "RIPOSO_GIORNALIERO" in i["tipo"]]
        self.assertEqual(len(rest), 0)


class TestComplianceWeeklyRest(unittest.TestCase):
    def setUp(self):
        self.engine = ComplianceEngine()

    def test_weekly_rest_regular_45h_no_infraction(self):
        activities = []
        base = datetime(2025, 5, 5, 0, 0, tzinfo=timezone.utc)
        for day in range(14):
            d = base + timedelta(days=day)
            date_str = d.strftime("%d/%m/%Y")
            if d.weekday() >= 5:  # Sat+Sun
                acts = [{"tipo": "RIPOSO", "ora": "00:00"}]
            else:
                acts = [
                    {"tipo": "GUIDA", "ora": "08:00"},
                    {"tipo": "LAVORO", "ora": "12:00"},
                    {"tipo": "RIPOSO", "ora": "23:59"},
                ]
            activities.append({"data": date_str, "eventi": acts})
        result = self.engine.analyze(activities)
        weekly = [i for i in result if "MANCATA_COMPENSAZIONE" in i["tipo"]]
        self.assertEqual(len(weekly), 0, f"Weekly infractions found: {weekly}")

    def test_max_6_days_between_weekly_rests(self):
        activities = []
        base = datetime(2025, 5, 1, 0, 0, tzinfo=timezone.utc)
        for day in range(14):
            d = base + timedelta(days=day)
            date_str = d.strftime("%d/%m/%Y")
            if day == 6 or day == 13:
                acts = [{"tipo": "RIPOSO", "ora": "00:00"}]
            else:
                acts = [
                    {"tipo": "GUIDA", "ora": "08:00"},
                    {"tipo": "LAVORO", "ora": "16:00"},
                    {"tipo": "RIPOSO", "ora": "23:00"},
                ]
            activities.append({"data": date_str, "eventi": acts})
        result = self.engine.analyze(activities)
        weekly = [i for i in result if "SUPERAMENTO_6_PERIODI" in i["tipo"]]
        self.assertEqual(len(weekly), 0)


class TestComplianceBiweeklyDriving(unittest.TestCase):
    def setUp(self):
        self.engine = ComplianceEngine()

    def test_biweekly_driving_under_90h_no_infraction(self):
        activities = []
        base = datetime(2025, 5, 1, 0, 0, tzinfo=timezone.utc)
        for day in range(14):
            d = base + timedelta(days=day)
            date_str = d.strftime("%d/%m/%Y")
            if d.weekday() == 6:
                acts = [{"tipo": "RIPOSO", "ora": "00:00"}]
            else:
                acts = [
                    {"tipo": "GUIDA", "ora": "08:00"},
                    {"tipo": "LAVORO", "ora": "14:00"},
                    {"tipo": "RIPOSO", "ora": "23:59"},
                ]
            activities.append({"data": date_str, "eventi": acts})
        result = self.engine.analyze(activities)
        bisettimanale = [i for i in result if "ECCESSO_GUIDA_BISETTIMANALE" in i["tipo"]]
        self.assertEqual(len(bisettimanale), 0)

    def test_biweekly_driving_over_90h_detected(self):
        activities = []
        base = datetime(2025, 5, 5, 0, 0, tzinfo=timezone.utc)
        for day in range(14):
            d = base + timedelta(days=day)
            date_str = d.strftime("%d/%m/%Y")
            if d.weekday() == 6:  # Sunday rest
                acts = [{"tipo": "RIPOSO", "ora": "00:00"}]
            elif d.weekday() == 5:  # Saturday: drive only
                acts = [
                    {"tipo": "GUIDA", "ora": "00:00"},
                    {"tipo": "RIPOSO", "ora": "10:00"},
                ]
            else:
                acts = [
                    {"tipo": "GUIDA", "ora": "00:00"},
                    {"tipo": "RIPOSO", "ora": "10:00"},
                ]
            activities.append({"data": date_str, "eventi": acts})
        result = self.engine.analyze(activities)
        bisettimanale = [i for i in result if "ECCESSO_GUIDA_BISETTIMANALE" in i["tipo"]]
        self.assertGreater(len(bisettimanale), 0)


class TestComplianceWeeklyDrivingLimit(unittest.TestCase):
    def setUp(self):
        self.engine = ComplianceEngine()

    def test_weekly_driving_over_56h_causes_infraction(self):
        activities = []
        base = datetime(2025, 5, 5, 0, 0, tzinfo=timezone.utc)
        for day in range(7):
            d = base + timedelta(days=day)
            date_str = d.strftime("%d/%m/%Y")
            if d.weekday() == 6:
                acts = [{"tipo": "RIPOSO", "ora": "00:00"}]
            else:
                acts = [
                    {"tipo": "GUIDA", "ora": "00:00"},
                    {"tipo": "RIPOSO", "ora": "11:00"},
                ]
            activities.append({"data": date_str, "eventi": acts})
        result = self.engine.analyze(activities)
        settimanale = [i for i in result if "ECCESSO_GUIDA_SETTIMANALE" in i["tipo"]]
        self.assertGreater(len(settimanale), 0)


class TestComplianceNoActivities(unittest.TestCase):
    def test_empty_activities_returns_empty(self):
        engine = ComplianceEngine()
        result = engine.analyze([])
        self.assertEqual(result, [])


class TestComplianceGetReport(unittest.TestCase):
    def test_report_matches_infractions(self):
        engine = ComplianceEngine()
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "14:00"},
            ]
        }]
        engine.analyze(activities)
        report = engine.get_report()
        self.assertEqual(len(report), len(engine.infractions))


class TestDailySummary(unittest.TestCase):
    def test_daily_summary_returns_data(self):
        engine = ComplianceEngine()
        activities = [{
            "data": "01/05/2025",
            "eventi": [
                {"tipo": "GUIDA", "ora": "08:00"},
                {"tipo": "RIPOSO", "ora": "10:00"},
            ]
        }]
        summary = engine.get_daily_summary(activities)
        self.assertGreater(len(summary), 0)
        self.assertIn("Guida Totale", summary[0])
        self.assertIn("Lavoro Totale", summary[0])
        self.assertIn("Riposo Totale", summary[0])
        self.assertIn("Infrazioni", summary[0])


if __name__ == "__main__":
    unittest.main()
