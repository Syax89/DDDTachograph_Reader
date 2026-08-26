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
