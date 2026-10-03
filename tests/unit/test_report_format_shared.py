from core.utils.report_format import build_monthly_activity_report, fmt_scalar, visible_columns


def test_fmt_scalar_preserves_shared_display_conventions():
    assert fmt_scalar(None) == ""
    assert fmt_scalar(True) == "Yes"
    assert fmt_scalar(12.5) == "12.5"
    assert fmt_scalar(12345) == "12 345"
    assert fmt_scalar(0xFFFFFF) == "N/A"
    assert fmt_scalar("2026-06-01T10:30:00+00:00") == "2026-06-01 10:30"
    assert fmt_scalar("I", key="nation") == "Italy"
    assert fmt_scalar(0x21, key="trep", include_code_label=True) == "33  (TREP 21)"


def test_visible_columns_accepts_a_caller_presentation_policy():
    records = [
        {"description": "First", "value": 1, "source": "internal", "record_type": 2},
        {"purpose": "Second", "extra": 3, "_key": "dedupe"},
    ]

    assert visible_columns(
        records,
        hidden_keys={"source"},
        leading_keys=("purpose", "description"),
        trailing_keys=("record_type",),
    ) == ["purpose", "description", "value", "extra", "record_type"]
    assert visible_columns(["scalar", {"value": 1}]) == ["value"]
    assert visible_columns([{"value": 1}, "scalar"], value_column_for_non_dict=True) == ["Value"]


def test_monthly_report_sorts_by_year_then_month():
    """'MM/YYYY' labels must sort chronologically, not lexicographically."""
    activities = [
        {"date": "15/01/2024", "changes": [{"activity": "DRIVE", "time": "00:00"}]},
        {"date": "15/02/2023", "changes": [{"activity": "DRIVE", "time": "00:00"}]},
        {"date": "15/11/2023", "changes": [{"activity": "DRIVE", "time": "00:00"}]},
    ]

    headers, rows = build_monthly_activity_report(activities)

    total_rows = [r[0] for r in rows if str(r[0]).endswith("TOTAL")]
    assert total_rows == ["02/2023 TOTAL", "11/2023 TOTAL", "01/2024 TOTAL"]


def test_monthly_report_is_slot_aware_for_crew_days():
    """F-F1 / XF-F1 / XG-F1: the report engine must group by card slot.

    The old in-file engine walked ``changes`` in list order and ignored
    ``slot``, so it summed overlapping periods from both slots (an impossible
    >24h REST/Available day) and disagreed with the cover stats. The shared
    slot-aware engine sums DRIVE/WORK across slots and keeps REST/AVAILABLE at
    the max: two 8h-drive slots give 16h DRIVE and 16h REST (32h total). A crew
    day legitimately exceeds 24h (two drivers summing) — the invariant is that
    report, cover, GUI and CLI agree, not a 24h ceiling.
    """
    crew = [
        {"activity": "DRIVE", "time": "00:00", "slot": "First"},
        {"activity": "REST",  "time": "08:00", "slot": "First"},
        {"activity": "DRIVE", "time": "00:00", "slot": "Second"},
        {"activity": "REST",  "time": "08:00", "slot": "Second"},
    ]

    _, rows = build_monthly_activity_report(
        [{"date": "01/05/2025", "odometer_km": 1234, "changes": crew}])

    assert rows[0] == ["01/05/2025", "1234", "16:00", "00:00", "16:00",
                       "00:00", "00:00", "32:00"]
    assert rows[1][0] == "05/2025 TOTAL"
    assert rows[1][-1] == "32:00"


def test_monthly_report_unknown_column_is_real():
    """An unrecognised activity label must not render as a hard-zero Unknown.

    Its hours are kept in the Unknown column (and the row total) instead of
    vanishing, matching the shared engine.
    """
    day = {"date": "01/05/2025", "changes": [
        {"activity": "DRIVE", "time": "08:00"},
        {"activity": "MYSTERY", "time": "10:00"},
        {"activity": "REST", "time": "12:00"},
    ]}

    _, rows = build_monthly_activity_report([day])
    row = rows[0]
    assert row[2] == "02:00"          # Drive  = 08:00-10:00
    assert row[4] == "12:00"          # Rest   = 12:00-24:00
    assert row[6] == "\u26a0 02:00"   # Unknown = 10:00-12:00 (warning glyph)
    assert row[7] == "16:00"          # Total keeps Drive+Rest+Unknown
