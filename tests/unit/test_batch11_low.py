"""Batch 11 — SEMANTIC report/CLI/log families.

Families (6): ``CLI-ALL-PATHS`` (F-F7/XF-F7), ``REPORT-NONDICT-ROBUSTNESS``
(F-F3/XF-F9), ``REPORT-ODOMETER-MISSING`` (F-F2/XF-F5),
``REPORT-OMITS-PARSE-STATE`` (D2-009), ``REPORT-OVERNIGHT-GAP`` (XF-F2),
``REPORT-PDF-AVAILABLE-OMITTED`` (XF-F3).

Normalise source: Reg. EU 2016/799 Annex 1C (consolidated 2023-08-21). Each
assertion is independent of the production output (exact expected values), so a
regression in the fix re-breaks the specific test that pins it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from core.utils.activity_stats import compute_activity_totals
from core.utils.report_format import (
    build_monthly_activity_report,
    fmt_iso,
    summary_rows,
)

ROOT = Path(__file__).resolve().parents[2]
MOCK = ROOT / "tests" / "mock_data" / "mock_g1_card.ddd"


# ── CLI-ALL-PATHS (F-F7 / XF-F7) ───────────────────────────────────────────


@pytest.mark.skipif(not MOCK.exists(), reason="mock corpus not generated")
def test_cli_all_rejects_a_non_directory_output_path(tmp_path):
    """``--all <existing file>`` must fail cleanly, not with a raw traceback."""
    clash = tmp_path / "not_a_dir.txt"
    clash.write_text("x")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "app" / "main.py"), str(MOCK),
         "--all", str(clash), "--quiet"],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 1
    assert "not a directory" in proc.stderr
    # The old bug surfaced as an uncaught FileExistsError with a traceback.
    assert "FileExistsError" not in proc.stderr
    assert "Traceback" not in proc.stderr


@pytest.mark.skipif(not MOCK.exists(), reason="mock corpus not generated")
def test_cli_all_with_bare_json_writes_into_the_output_dir(tmp_path):
    """A bare ``--json`` under ``--all`` must not escape to the CWD (XF-F7)."""
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "app" / "main.py"), str(MOCK),
         "--all", str(out_dir), "--json", "--quiet"],
        cwd=tmp_path, capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, proc.stderr
    assert sorted(p.suffix for p in out_dir.iterdir()) == [".csv", ".json", ".pdf", ".xlsx"]
    # Nothing was written to the process working directory.
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.skipif(not MOCK.exists(), reason="mock corpus not generated")
def test_cli_auto_names_do_not_silently_overwrite(tmp_path, monkeypatch):
    """Two runs frozen to the same second must produce two files, not one (XF-F7)."""
    import app.cli as cli
    from datetime import datetime as real_datetime

    class _FrozenDatetime:
        @staticmethod
        def now():
            return real_datetime(2026, 1, 1, 12, 0, 0)

    monkeypatch.setattr(cli, "datetime", _FrozenDatetime)
    monkeypatch.chdir(tmp_path)   # even a regressed run must not pollute the repo
    out_dir = tmp_path / "out"
    for _ in range(2):
        monkeypatch.setattr(sys, "argv",
                            ["cli", str(MOCK), "--all", str(out_dir), "--json", "--quiet"])
        cli.main()
    jsons = sorted(p.name for p in out_dir.glob("*.json"))
    assert len(jsons) == 2, jsons   # second run must not clobber the first


# ── REPORT-OVERNIGHT-GAP (XF-F2) ───────────────────────────────────────────


def test_overnight_gap_is_attributed_not_dropped():
    """A day whose first change is not at 00:00 must still span 00:00→24:00.

    Annex 1C §2.170: a daily record "always includes two ActivityChangeInfo
    words giving the status of the two slots at 00:00". When the leading entry
    is absent the interval [00:00, first change) is UNKNOWN (§2.1 note 2), not
    silently discarded.
    """
    totals = compute_activity_totals([{"activity": "DRIVE", "time": "06:00"}])
    assert totals["DRIVE"] == 1080          # 06:00-24:00
    assert totals["UNKNOWN"] == 360          # 00:00-06:00 (was dropped -> 18h day)
    assert sum(totals.values()) == 24 * 60


def test_overnight_gap_synth_does_not_touch_a_full_day():
    """A day carrying its 00:00 status entry gets no synthetic UNKNOWN."""
    totals = compute_activity_totals([
        {"activity": "REST", "time": "00:00"},
        {"activity": "DRIVE", "time": "06:00"},
    ])
    assert totals == {"DRIVE": 1080, "WORK": 0, "REST": 360,
                      "AVAILABLE": 0, "UNKNOWN": 0}


def test_overnight_gap_per_slot_is_independent():
    """Only the slot missing its 00:00 entry gets the synthetic UNKNOWN."""
    totals = compute_activity_totals([
        {"activity": "DRIVE", "time": "00:00", "slot": "First"},
        {"activity": "REST", "time": "00:00", "slot": "Second"},
        {"activity": "WORK", "time": "06:00", "slot": "Second"},
    ])
    # Second: REST 00:00-06:00 (360) + WORK 06:00-24:00 (1080); First: DRIVE all day.
    assert totals["DRIVE"] == 1440
    assert totals["WORK"] == 1080
    assert totals["REST"] == 360
    assert totals["UNKNOWN"] == 0


# ── REPORT-ODOMETER-MISSING (F-F2 / XF-F5) ─────────────────────────────────


def test_monthly_report_uses_odometer_midnight_when_km_absent():
    """G1 VU days carry ``odometer_midnight``; the column must not hard-zero."""
    day = {"date": "01/05/2025", "odometer_midnight": 4321,
           "changes": [{"activity": "REST", "time": "00:00"}]}
    _, rows = build_monthly_activity_report([day])
    assert rows[0][1] == "4321"


def test_monthly_report_prefers_explicit_odometer_km():
    """When ``odometer_km`` is present it still wins over the fallback."""
    day = {"date": "01/05/2025", "odometer_km": 150, "odometer_midnight": 4321,
           "changes": [{"activity": "REST", "time": "00:00"}]}
    _, rows = build_monthly_activity_report([day])
    assert rows[0][1] == "150"


# ── REPORT-NONDICT-ROBUSTNESS (F-F3 / XF-F9) ───────────────────────────────


@pytest.mark.parametrize("value", [None, 42, 12.5, True])
def test_fmt_iso_tolerates_non_string_shapes(value):
    """``fmt_iso`` must not raise ``TypeError`` on a non-string field."""
    assert fmt_iso(value) == value
    assert fmt_iso("2026-06-01T10:30:00+00:00") == "2026-06-01 10:30"


def test_summary_rows_survives_none_and_scalar_sections():
    """A None/scalar metadata/coverage/driver/vehicle must not crash export."""
    rows = summary_rows({
        "metadata": None, "coverage": "broken",
        "driver": None, "vehicle": 7,
        "signature_verification": "x", "ef_signature_verification": None,
    })
    assert ("Source", "Driver Card") in rows
    assert ("Integrity", "N/A") in rows


def test_monthly_report_skips_non_dict_changes_without_crashing():
    """A non-dict element inside ``changes`` must not crash the export."""
    day = {"date": "01/05/2025", "changes": [
        "junk", None, 42,
        {"activity": "DRIVE", "time": "00:00"},
        {"activity": "REST", "time": "08:00"},
    ]}
    _, rows = build_monthly_activity_report([day])
    assert rows[0][2] == "08:00"   # DRIVE 00:00-08:00, junk ignored
    assert rows[0][4] == "16:00"   # REST 08:00-24:00


# ── REPORT-OMITS-PARSE-STATE (D2-009) ──────────────────────────────────────


def test_summary_discloses_partial_parse_state():
    """A partial download must be exported with its incompleteness visible."""
    data = {"metadata": {
        "integrity_check": "Verified",
        "trep_report": {
            "is_partial": True, "mandatory_ok": 3, "mandatory_total": 7,
            "completeness_pct": 42.9, "complete_walk": False,
            "mandatory_missing": [{"name": "Overview", "trep": "0x01"}],
            "decoded_suspect": [{"name": "Events", "trep": "0x15"}],
        },
        "salvage_recovered": ["events", "faults"],
        "parse_warnings": [{"phase": "ef_walk", "message": "boom"}],
        "decoder_failure_count": 2,
        "origin_note": "VU-wrapped card image detected",
    }}
    rows = dict(summary_rows(data))
    assert rows["Download completeness"] == "3/7 mandatory sections (42.9%)"
    assert rows["Missing mandatory sections"] == "Overview"
    assert rows["Corrupted sections (data discarded)"] == "Events"
    assert rows["Structural walk"] == "did not reach end of file"
    assert rows["Recovered data (low confidence)"] == "events, faults"
    assert rows["Parse warnings"] == "1 parsing phase(s) failed"
    assert rows["Decoder failures"] == 2
    assert rows["Origin"] == "VU-wrapped card image detected"


def test_summary_omits_parse_state_rows_for_a_clean_parse():
    """A complete parse must not grow any incompleteness row (inert default)."""
    rows = dict(summary_rows({"metadata": {
        "integrity_check": "Verified", "filename": "x.ddd",
    }}))
    for label in ("Download completeness", "Missing mandatory sections",
                  "Corrupted sections (data discarded)", "Structural walk",
                  "Recovered data (low confidence)", "Parse warnings",
                  "Decoder failures", "Origin"):
        assert label not in rows


# ── REPORT-PDF-AVAILABLE-OMITTED (XF-F3) ───────────────────────────────────


def test_pdf_cover_reports_available_and_unknown_and_matches_the_table(tmp_path):
    """The PDF cover stats bar must show every bucket and reconcile with the table."""
    pytest.importorskip("reportlab")
    from unittest.mock import patch

    from app.export import ExportManager
    from reportlab.platypus import Paragraph as ReportLabParagraph

    data = {
        "metadata": {"filename": "x.ddd", "generation": "G2 (Smart)", "is_vu": False},
        "activities": [{
            "date": "01/06/2026",
            "changes": [
                {"activity": "DRIVE", "time": "00:00"},
                {"activity": "AVAILABLE", "time": "06:00"},
                {"activity": "REST", "time": "10:00"},
            ],
        }],
    }

    captured = []

    def capture(text, *args, **kwargs):
        captured.append(text)
        return ReportLabParagraph(text, *args, **kwargs)

    with patch("reportlab.platypus.Paragraph", side_effect=capture):
        ExportManager.export_to_pdf(data, str(tmp_path / "cover.pdf"))

    stats = next(t for t in captured if t.startswith("Drive: "))
    assert "Drive: 6h 0m" in stats
    assert "Available: 4h 0m" in stats
    assert "Rest: 14h 0m" in stats
    assert "Unknown: 0h 0m" in stats
    assert "Total: 24h 0m" in stats

    _, rows = build_monthly_activity_report(data["activities"])
    assert rows[0][7] == "24:00"   # table total equals the cover total
