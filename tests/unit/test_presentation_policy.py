"""Presentation policy: show the regulation data, hide only the bookkeeping.

Owner rule: *if the regulation lets us read more data, show it* — a newly decoded
field is an improvement, not a regression. The earlier "screen unchanged" rule
only forbids redesign/restyling, not showing a datum the parent revision dropped.

So this file pins two things at once:

* every ``BOOKKEEPING_KEYS`` member (raw duplicates, statuses, provenance,
  completeness flags) is hidden in **both** exclusion sets and never becomes a
  column or a Field/Value row;
* every regulation datum of the show list *is* a column/row, and every new visible
  label exists in all translation catalogs.

Synthetic values only; no corpus datum.
"""
import struct

import pytest

from app import gui
from core.parser.vu_dispatcher import walk_vu_record_arrays
from core.utils import report_format
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME

#: Labels this pass introduced, each modelled on an existing catalog msgid.
NEW_LABELS = {
    "Serial": "Serial Number",
    "VU Serial": "Serial Number",
    "Month": "Date",
    "Year": "Date",
    "Sensor Pairing Time": "Sensor Pairing Date",
    "Current Date Time": "Date",
    "Entry Type Meaning": "Entry Type",
    "Old Time Full": "Old Time",
    "New Time Full": "New Time",
    "Next Calibration Full": "Next Calibration Date",
    "RCM Serial": "Serial Number",
    "Sensor GNSS Serial": "Sensor Serial",
}


def _catalogs():
    import glob
    return sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po"))


# ── Bookkeeping is hidden, in both places ───────────────────────────────────

def test_bookkeeping_keys_are_hidden_in_both_sets():
    missing = [key for key in report_format.BOOKKEEPING_KEYS
               if key not in report_format.HIDDEN_KEYS or key not in gui.HIDDEN_KEYS]
    assert missing == []


def test_bookkeeping_never_becomes_a_column_or_a_row():
    record = {key: 1 for key in report_format.BOOKKEEPING_KEYS}
    record["timestamp"] = "2024-04-05T20:34:38+00:00"
    assert report_format.visible_columns([record]) == ["timestamp"]
    assert gui._columns_for([record], None) == ["timestamp"]
    _headers, rows = gui._kv_rows({key: 1 for key in report_format.BOOKKEEPING_KEYS})
    assert rows == []
    sections = {label: (headers, rows) for label, _d, headers, rows, _t
                in report_format.section_tables({
                    "calibrations": [record],
                    "vu_info": {key: 1 for key in report_format.BOOKKEEPING_KEYS
                                if key != "timestamp"},
                    "company_info": {"name": "Synthetic"}})}
    assert sections["Calibrations"][0] == ["Timestamp"]
    # a dict section made only of bookkeeping keys yields no sheet at all
    assert "VU Information" not in sections
    # `name` is a fact of the unit and stays visible in the dict section.
    assert [row[0] for row in sections["VU Company Info"][1]] == ["Name"]


def test_nation_and_existing_columns_are_untouched():
    """Control: the pre-existing visible keys still render exactly as before."""
    record = {"timestamp": "2024-04-05T20:34:38+00:00", "nation": "I",
              "workshop": "Synthetic", "vin": "TZSYNTHVIN0000001"}
    cols = report_format.visible_columns([record])
    assert cols[0] == "timestamp"
    assert set(cols) == {"timestamp", "nation", "workshop", "vin"}


# ── The show list is visible ────────────────────────────────────────────────

def _overview_stream():
    return S.section(
        0x31,
        S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
        S.record_array(0x02, 1, [bytes([S.SLOTS_DRIVER_AND_COMPANY])]),
        S.record_array(0x03, 4, [struct.pack(">I", TIME)]),
        S.signature_record())


def _walk(stream):
    results = {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                          "registration_nation": "N/A"}}
    walk_vu_record_arrays(stream, results)
    return results


def test_gen2_overview_panel_shows_slots_and_the_vu_clock():
    results = _walk(_overview_stream())
    panel = results["vu_overview"]
    assert panel["card_slot_status"]["driver_slot"] == "occupied"
    assert panel["card_slot_status"]["codriver_slot"] == "occupied"
    assert panel["current_date_time"].startswith("2024-04-0")
    _headers, rows = gui._kv_rows(panel)
    labels = [row[0] for row in rows]
    # Same row names the generation-1 panel already uses: no new label text.
    assert any(label.startswith("Card Slot Status \u203a Driver Slot") for label in labels)
    assert "Card Slot Status \u203a Driver Slot Code" not in labels


def test_vu_information_shows_the_decoded_serials_and_pairing_time():
    info = {
        "manufacturer": "Synthetic Maker",
        "serial_number": "0A0B0C0D0711AA55",
        "vu_serial": {"serial_number": 168_000_001, "month": 11, "year": 24,
                      "manufacturer": "Synthetic Maker",
                      "month_year_status": "valid"},
        "sensor_serial": {"serial_number": 168_000_002, "month": 3, "year": 23,
                          "manufacturer": "Synthetic Maker"},
        "sensor_pairing_time": "2024-04-05T20:34:38+00:00",
    }
    _headers, rows = gui._kv_rows(info)
    labels = [row[0] for row in rows]
    assert "VU Serial \u203a Serial Number" in labels
    assert "VU Serial \u203a Month" in labels
    assert "VU Serial \u203a Manufacturer" in labels
    assert "Sensor Serial \u203a Serial Number" in labels
    assert "Sensor Pairing Time" in labels
    # the bookkeeping child of the serial dict is not a row
    assert "VU Serial \u203a Month Year Status" not in labels
    sections = {label: rows for label, _d, _h, rows, _t
                in report_format.section_tables({"vu_info": info})}
    export_labels = [row[0] for row in sections["VU Information"]]
    assert "VU Serial" in export_labels and "Sensor Serial" in export_labels
    # a nested dict is rendered readable, never as a raw {...} cell
    assert "{" not in "".join(str(row[1]) for row in sections["VU Information"])


def test_calibration_columns_show_full_times_and_all_three_serials():
    record = {
        "old_time": "2024-04-05", "new_time": "2024-04-05",
        "next_calibration_date": "2024-05-05",
        "old_time_full": "2024-04-05T20:34:38+00:00",
        "new_time_full": "2024-04-05T20:35:08+00:00",
        "next_calibration_full": "2024-05-05T00:00:00+00:00",
        "sensor_serial": {"serial_number": 168_000_001, "month": 11, "year": 24},
        "sensor_gnss_serial": {"serial_number": 168_000_002},
        "rcm_serial": {"serial_number": 168_000_003},
        "vin_status": "present",
    }
    cols = report_format.visible_columns([record])
    for key in ("old_time_full", "new_time_full", "next_calibration_full",
                "sensor_serial", "sensor_gnss_serial", "rcm_serial"):
        assert key in cols, key
    assert "vin_status" not in cols
    # the pre-existing date columns are still there, unchanged
    assert {"old_time", "new_time", "next_calibration_date"} <= set(cols)


def test_places_show_the_entry_type_meaning():
    record = {"timestamp": "2024-04-05T20:34:38+00:00", "entry_type": "START",
              "entry_type_meaning": "Begin assumed by VU", "type_code": 4}
    assert "entry_type_meaning" in report_format.visible_columns([record])


def test_records_the_parent_dropped_are_rows_now():
    """Zero-change day, unreadable-clock lock/control, activation calibration."""
    activities = [{"date": "05/04/2024", "odometer_km": 1000, "changes": [],
                   "changes_count": 0, "invalid_changes_count": 0,
                   "source": "vu_trep02"}]
    locks = [{"lock_in_time": None, "lock_out_time": None, "lock_in_raw": 0xFF000000,
              "time_status": "invalid", "company_name": "Synthetic",
              "company_card": None}]
    controls = [{"control_type": 0xE8, "control_type_label": "Printing",
                 "control_time": None, "control_time_raw": 0xFF000000,
                 "time_status": "invalid", "control_type_bits": ["Printing"]}]
    calibrations = [{"timestamp": "2024-04-05", "purpose": "Activation",
                     "purpose_code": 1, "vin": "", "vin_status": "empty",
                     "l_tyre_circumference": 0,
                     "decode_path": "normative"}]
    faults = [{"description": "Sensor fault", "fault_type": 0x35,
               "begin_time": None, "begin_time_raw": 0xFF000000,
               "time_status": "invalid"}]

    activity_cols = report_format.visible_columns(activities)
    # the day is a row (date/odometer) with its change list, and the count of
    # undecodable values is bookkeeping
    assert {"date", "odometer_km", "changes", "changes_count"} <= set(activity_cols)
    assert "invalid_changes_count" not in activity_cols
    lock_cols = report_format.visible_columns(locks)
    assert "lock_in_time" in lock_cols and "lock_in_raw" not in lock_cols
    assert "time_status" not in lock_cols
    control_cols = report_format.visible_columns(controls)
    assert "control_type_label" in control_cols
    assert "control_time" in control_cols and "control_type_bits" not in control_cols
    cal_cols = report_format.visible_columns(calibrations)
    assert "vin" in cal_cols and "l_tyre_circumference" in cal_cols
    assert "vin_status" not in cal_cols and "decode_path" not in cal_cols
    fault_cols = report_format.visible_columns(faults)
    assert "begin_time" in fault_cols and "begin_time_raw" not in fault_cols


# ── Translations ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,model", sorted(NEW_LABELS.items()))
def test_every_new_label_is_translated_in_all_catalogs(label, model):
    catalogs = _catalogs()
    assert len(catalogs) == 33, catalogs[:3]
    for path in catalogs:
        text = open(path, encoding="utf-8").read()
        assert f'msgid "{label}"' in text, f"{path}: {label}"
        # the model msgid the term was translated from is in the same catalog
        assert f'msgid "{model}"' in text, f"{path}: {model}"
