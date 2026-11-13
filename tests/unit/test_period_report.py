"""Monthly period report: overlapping downloads merged, distances, outputs."""
import csv
import os
import subprocess
import sys
from pathlib import Path

from core.analysis.period_report import (
    build_period_report, format_table, merge_days, write_period_report)
from tests.integration import generate_mock_ddd as mock

ROOT = Path(__file__).resolve().parents[2]


def _ch(time, activity):
    return {"time": time, "activity": activity, "slot": "First"}


def _card_day(date, drive_h, km, cut=None):
    day = {"date": date, "day_distance_km": km,
           "changes": [_ch("00:00", "REST"), _ch("06:00", "DRIVE"),
                       _ch(f"{6 + drive_h:02d}:00", "REST")]}
    if cut:
        day["recorded_until"] = cut
    return day


def _card(days, card="X100", surname="DOE", first="JANE"):
    return {"metadata": {"is_vu": False},
            "driver": {"card_number": card, "surname": surname, "firstname": first},
            "activities": days}


def _vu(days, plate="AB123CD"):
    return {"metadata": {"is_vu": True}, "vehicle": {"plate": plate, "vin": "VIN1"},
            "activities": days}


def test_overlapping_card_downloads_count_each_day_once():
    first = _card([_card_day("30/01/2025", 4, 300), _card_day("31/01/2025", 2, 100, cut="08:00")])
    second = _card([_card_day("31/01/2025", 8, 600), _card_day("01/02/2025", 5, 400)])
    rows = build_period_report([("a.ddd", first), ("b.ddd", second)])
    assert [(r["month"], r["days_recorded"], r["drive_min"], r["distance_km"]) for r in rows] == [
        ("2025-01", 2, (4 + 8) * 60, 900),   # 31/01 taken from the complete copy
        ("2025-02", 1, 5 * 60, 400),
    ]
    assert rows[0]["entity_name"] == "DOE JANE"
    assert rows[0]["sources"] == "a.ddd, b.ddd"
    # Art. 7 (4h30 without a break), counted in the month the stretch starts:
    # 30/01 drives 4 h (fine), 31/01 8 h and 01/02 5 h (both over).
    assert rows[0]["infringements_561"] == 1
    assert rows[1]["infringements_561"] == 1


def test_a_cut_day_loses_to_a_complete_copy_whatever_the_order():
    complete = _card([_card_day("31/01/2025", 8, 600)])
    cut = _card([_card_day("31/01/2025", 2, 100, cut="08:00")])
    for order in ([("a", complete), ("b", cut)], [("b", cut), ("a", complete)]):
        days = merge_days(order)[("driver", "X100")]["days"]
        assert "recorded_until" not in next(iter(days.values()))


def test_vu_distance_is_the_odometer_increase_between_consecutive_days():
    def vu_day(date, odo):
        return {"date": date, "odometer_km": odo,
                "changes": [_ch("00:00", "REST")]}
    rows = build_period_report([("v.ddd", _vu([
        vu_day("01/03/2025", 1000), vu_day("02/03/2025", 1300),
        vu_day("05/03/2025", 2000),          # gap: not attributed to one day
        vu_day("06/03/2025", 2100)]))])
    assert rows[0]["distance_km"] == 300 + 100
    assert rows[0]["infringements_561"] == ""    # no 561 analysis for vehicles


def test_inputs_without_identity_are_left_out():
    assert build_period_report([("x", {"metadata": {}, "activities": []})]) == []
    assert "no driver card" in format_table([])[1]


def test_csv_and_xlsx_outputs(tmp_path):
    rows = build_period_report([("a.ddd", _card([_card_day("30/01/2025", 4, 300)],
                                                 surname="=CMD"))])
    path = tmp_path / "out.csv"
    write_period_report(rows, str(path))
    with open(path, encoding="utf-8-sig", newline="") as handle:
        table = list(csv.reader(handle, delimiter=";"))
    assert table[0][0] == "Type" and table[1][3] == "2025-01"
    assert table[1][2].startswith("'=")       # formula injection guarded
    xlsx = tmp_path / "out.xlsx"
    write_period_report(rows, str(xlsx))
    from openpyxl import load_workbook
    sheet = load_workbook(xlsx).active
    assert sheet["D2"].value == "2025-01" and sheet["G2"].value == 240


def test_cli_period_report_over_a_folder(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mock.generate_g2_card(str(folder / "card.ddd"))
    mock.generate_g22_vu(str(folder / "vu.ddd"))
    out = tmp_path / "months.csv"
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-m", "app.cli", str(folder),
                           "--period-report", str(out), "-q"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    with open(out, encoding="utf-8-sig", newline="") as handle:
        kinds = {row[0] for row in list(csv.reader(handle, delimiter=";"))[1:]}
    assert kinds <= {"driver", "vehicle"} and kinds


def test_cli_single_file_prints_the_table_not_json(tmp_path):
    source = tmp_path / "card.ddd"
    mock.generate_g2_card(str(source))
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    proc = subprocess.run([sys.executable, "-m", "app.cli", str(source), "--period-report"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    assert "PERIOD REPORT" in proc.stdout
    assert not proc.stdout.lstrip().startswith("{")
