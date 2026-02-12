from compliance_engine import ComplianceEngine
from datetime import datetime

activities = [
    {
        "data": "10/02/2026",
        "eventi": [
            {"tipo": "RIPOSO", "ora": "00:00"},
            {"tipo": "GUIDA", "ora": "08:00"},
            {"tipo": "LAVORO", "ora": "12:00"},
            {"tipo": "RIPOSO", "ora": "13:00"},
            {"tipo": "GUIDA", "ora": "14:00"},
            {"tipo": "RIPOSO", "ora": "18:00"}
        ]
    },
    {
        "data": "11/02/2026",
        "eventi": [
            {"tipo": "GUIDA", "ora": "08:00"}, # Continued from previous day rest
            {"tipo": "GUIDA", "ora": "14:00"}, # Long drive to trigger infraction if possible
            {"tipo": "RIPOSO", "ora": "20:00"}
        ]
    }
]

engine = ComplianceEngine()
summary = engine.get_daily_summary(activities)

print("Daily Summary Output:")
for day in summary:
    print(day)

# Verify fields
expected_keys = ["Data", "Guida Totale", "Lavoro Totale", "Riposo Totale", "Infrazioni"]
for day in summary:
    for key in expected_keys:
        if key not in day:
            print(f"MISSING KEY: {key}")
