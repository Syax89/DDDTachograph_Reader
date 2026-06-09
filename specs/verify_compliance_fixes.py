"""Verification script for compliance engine fixes (B3, B4, B5, B6).

Generates synthetic activity data and asserts that the ComplianceEngine produces
the expected infractions for each scenario.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from compliance_engine import ComplianceEngine


def make_activities(events_by_day):
    """Convert {date_str: [events]} into the activity list format."""
    result = []
    for date_str, events in events_by_day.items():
        result.append({"data": date_str, "eventi": list(events)})
    return result


def find_infraction(infractions, tipo):
    """Return the first infraction with the given tipo, or None."""
    for inf in infractions:
        if inf["tipo"] == tipo:
            return inf
    return None


def count_infractions(infractions, tipo):
    return sum(1 for inf in infractions if inf["tipo"] == tipo)


def test_daily_driving_no_extension():
    """Driving <= 9h in a shift: no infraction."""
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "08:00"},
            {"tipo": "RIPOSO", "ora": "16:00"},
        ],
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    assert not find_infraction(infractions, "ECCESSO_GUIDA_GIORNALIERA"), f"Unexpected: {infractions}"
    print("PASS: test_daily_driving_no_extension")


def test_daily_driving_extension_ok():
    """First extension to 10h in a week: no infraction (allowed max 2)."""
    # 10h driving in one shift = 600 min
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "07:00"},
            {"tipo": "RIPOSO", "ora": "17:00"},
        ],
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    assert not find_infraction(infractions, "ECCESSO_ESTENSIONI_GUIDA_SETTIMANALI"), f"Unexpected: {infractions}"
    assert not find_infraction(infractions, "ECCESSO_GUIDA_GIORNALIERA"), f"Unexpected: {infractions}"
    print("PASS: test_daily_driving_extension_ok")


def test_daily_driving_third_extension_infraction():
    """Third extension to 10h in the same week: infraction MI."""
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "07:00"},
            {"tipo": "RIPOSO", "ora": "17:00"},
        ],
        "02/06/2026": [
            {"tipo": "GUIDA", "ora": "07:00"},
            {"tipo": "RIPOSO", "ora": "17:00"},
        ],
        "03/06/2026": [
            {"tipo": "GUIDA", "ora": "07:00"},
            {"tipo": "RIPOSO", "ora": "17:00"},
        ],
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    inf = find_infraction(infractions, "ECCESSO_ESTENSIONI_GUIDA_SETTIMANALI")
    assert inf is not None, f"Expected extension infraction, got: {infractions}"
    assert inf["severita"] == "MI", f"Expected MI, got: {inf['severita']}"
    print("PASS: test_daily_driving_third_extension_infraction")


def test_daily_driving_over_10h():
    """Driving > 10h in a shift: infraction MSI (> 11h / 660 min)."""
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "05:30"},
            {"tipo": "RIPOSO", "ora": "17:00"},  # 11.5h driving = 690 min > 660
        ],
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    inf = find_infraction(infractions, "ECCESSO_GUIDA_GIORNALIERA")
    assert inf is not None, f"Expected over 10h infraction, got: {infractions}"
    assert inf["severita"] == "MSI", f"Expected MSI, got: {inf['severita']}"
    print("PASS: test_daily_driving_over_10h")


def test_daily_driving_between_9h_10h_si():
    """Driving > 10h but <= 11h: infraction SI (not MSI)."""
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "16:00"},  # 10h driving = 600 min (== 600, not > 600)
        ],
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    # 600 min is exactly 10h, not > 600, so no infraction here
    # Let's test 10h1min = 601 min
    pass

    activities2 = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "16:01"},  # 10h1min = 601 min > 600, ≤ 660 => SI
        ],
    })
    engine2 = ComplianceEngine()
    infractions2 = engine2.analyze(activities2)
    inf = find_infraction(infractions2, "ECCESSO_GUIDA_GIORNALIERA")
    assert inf is not None, f"Expected over 10h infraction, got: {infractions2}"
    assert inf["severita"] == "SI", f"Expected SI, got: {inf['severita']}"
    print("PASS: test_daily_driving_between_9h_10h_si")


def test_reduced_rest_tracking():
    """> 3 reduced rests (9h-11h) between two weekly rests triggers ECCESSO_RIPOSI_RIDOTTI."""
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "GUIDA", "ora": "07:00"},
            {"tipo": "RIPOSO", "ora": "11:30"},
            {"tipo": "GUIDA", "ora": "12:15"},
            {"tipo": "LAVORO", "ora": "14:00"},
            {"tipo": "RIPOSO", "ora": "21:00"},
        ],
        "02/06/2026": [
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "11:00"},
            {"tipo": "LAVORO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "21:00"},
        ],
        "03/06/2026": [
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "11:00"},
            {"tipo": "LAVORO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "21:00"},
        ],
        "04/06/2026": [
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "11:00"},
            {"tipo": "LAVORO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "21:00"},
        ],
        "05/06/2026": [
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "11:00"},
            {"tipo": "LAVORO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "21:00"},
        ],
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    inf = find_infraction(infractions, "ECCESSO_RIPOSI_RIDOTTI")
    assert inf is not None, f"Expected reduced rest infraction, got: {infractions}"
    assert inf["severita"] == "SI", f"Expected SI, got: {inf['severita']}"
    print("PASS: test_reduced_rest_tracking")


def _make_workday(events):
    """Helper to build a standard workday with 9h reduced daily rest."""
    if events is None:
        return [
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "10:15"},
            {"tipo": "GUIDA", "ora": "11:00"},
            {"tipo": "RIPOSO", "ora": "11:30"},
            {"tipo": "LAVORO", "ora": "12:15"},
            {"tipo": "RIPOSO", "ora": "21:00"},
        ]
    return events

_wd = None  # sentinel for the default workday


def test_weekly_rest_resets_reduced_counter():
    """Weekly rest (>= 24h) resets the reduced rest counter."""
    activities = make_activities({
        # First cycle: 3 reduced rests
        "01/06/2026": _make_workday(_wd),
        "02/06/2026": _make_workday(_wd),
        "03/06/2026": _make_workday(_wd),
        # 2-day weekly rest
        "04/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "RIPOSO", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "18:00"},
            {"tipo": "RIPOSO", "ora": "23:00"},
        ],
        "05/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "RIPOSO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "23:59"},
        ],
        # Second cycle: 4 reduced rests => infraction on the 4th
        "06/06/2026": _make_workday(_wd),
        "07/06/2026": _make_workday(_wd),
        "08/06/2026": _make_workday(_wd),
        "09/06/2026": _make_workday(_wd),
        "10/06/2026": _make_workday(_wd),
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    count = count_infractions(infractions, "ECCESSO_RIPOSI_RIDOTTI")
    assert count == 1, f"Expected 1 reduced rest infraction, got {count}: {infractions}"
    print("PASS: test_weekly_rest_resets_reduced_counter")


def test_regular_rest_not_reduced():
    """Rest >= 11h (660 min) is regular, not reduced. Does not count toward reduced limit."""
    activities = make_activities({
        # Day 1: rest from 19:00 to next day 06:00 = 11h = REGULAR
        "01/06/2026": [
            {"tipo": "GUIDA", "ora": "06:00"},
            {"tipo": "RIPOSO", "ora": "10:15"},
            {"tipo": "GUIDA", "ora": "11:00"},
            {"tipo": "RIPOSO", "ora": "11:30"},
            {"tipo": "LAVORO", "ora": "12:15"},
            {"tipo": "RIPOSO", "ora": "19:00"},
        ],
        # Days 2-5: 9h reduced rests
        "02/06/2026": _make_workday(_wd),
        "03/06/2026": _make_workday(_wd),
        "04/06/2026": _make_workday(_wd),
        "05/06/2026": _make_workday(_wd),
        "06/06/2026": _make_workday(_wd),
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    # Day 1 rest is 11h (regular), days 2-5 are reduced.
    # So we have 4 reduced rests → 1 infraction on the 4th
    count = count_infractions(infractions, "ECCESSO_RIPOSI_RIDOTTI")
    assert count == 1, f"Expected 1 reduced rest infraction (1 regular + 4 reduced), got {count}: {infractions}"
    print("PASS: test_regular_rest_not_reduced")


def test_daily_rest_insufficient():
    """Rest < 9h within 24h window triggers RIPOSO_GIORNALIERO_INSUFFICIENTE."""
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "08:00"},
            {"tipo": "RIPOSO", "ora": "23:00"},  # 1h rest only
        ],
        "02/06/2026": [
            {"tipo": "GUIDA", "ora": "01:00"},
        ],
    })
    engine = ComplianceEngine()
    infractions = engine.analyze(activities)
    inf = find_infraction(infractions, "RIPOSO_GIORNALIERO_INSUFFICIENTE")
    assert inf is not None, f"Expected insufficient rest infraction, got: {infractions}"
    print("PASS: test_daily_rest_insufficient")


def test_daily_summary_format():
    """Daily summary includes expected fields."""
    activities = make_activities({
        "01/06/2026": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "08:00"},
            {"tipo": "LAVORO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "13:00"},
            {"tipo": "GUIDA", "ora": "14:00"},
            {"tipo": "RIPOSO", "ora": "18:00"},
        ],
    })
    engine = ComplianceEngine()
    summary = engine.get_daily_summary(activities)
    assert len(summary) > 0, "Empty summary"
    expected_keys = ["Data", "Guida Totale", "Lavoro Totale", "Riposo Totale", "Infrazioni"]
    for key in expected_keys:
        assert key in summary[0], f"Missing key: {key}"
    print("PASS: test_daily_summary_format")


if __name__ == "__main__":
    test_daily_driving_no_extension()
    test_daily_driving_extension_ok()
    test_daily_driving_third_extension_infraction()
    test_daily_driving_over_10h()
    test_daily_driving_between_9h_10h_si()
    test_reduced_rest_tracking()
    test_weekly_rest_resets_reduced_counter()
    test_regular_rest_not_reduced()
    test_daily_rest_insufficient()
    test_daily_summary_format()
    print("\n=== ALL TESTS PASSED ===")
