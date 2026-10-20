"""The confidence marker is JSON bookkeeping — it must not become a screen row.

Two dict renderers turn a mapping into key/value rows:
``core/utils/report_format.py::section_tables`` (Excel / CSV / PDF sheets) and
``app/gui.py::_kv_rows`` (the tree's key/value panel). The sensor block carries a
top-level ``confidence`` so the JSON can say the values were read from a
manufacturer extension — but that is bookkeeping, not a fact of the unit, and it
must not appear as a "Confidence | low" row.

No other dict section carries a top-level ``confidence`` today, so skipping that
one key changes nothing that already exists. The skip is deliberately **not** the
whole hidden-key set: `name` is hidden from *record* tables but VU Company Info
shows it in its key/value panel, and that must keep working (pinned below).
"""
import pytest

from app import gui
from core.utils import report_format

SENSOR = {
    "confidence": "low",
    "sensor_approval": "SENSOR1234567890",
    "approval_nation": "I",
    "approval_prefix": "0x01",
    "first_date": "2023-07-26",
    "last_date": "2023-07-27",
    "param_speed_max_kmh": 92,
    "param_speed_avg_kmh": 61,
    "param_distance_km": 120,
}


def _result(**overrides):
    data = {"sensor_info": dict(SENSOR)}
    data.update(overrides)
    return data


def _field_rows(data, label):
    """The (Field, Value) rows of one dict section, by its export label."""
    for section_label, _desc, headers, rows, _truncated in report_format.section_tables(data):
        if section_label == label:
            assert headers == ["Field", "Value"]
            return [row[0] for row in rows]
    return None


def test_export_sensor_sheet_has_no_confidence_row():
    fields = _field_rows(_result(), "Sensor Identification")

    assert fields is not None, "the sensor section disappeared"
    assert "Confidence" not in fields
    # …and every real row is still there.
    assert fields == ["Sensor Approval", "Approval Nation", "Approval Prefix",
                      "First Date", "Last Date", "Param Speed Max KMH",
                      "Param Speed Avg KMH", "Param Distance KM"]


def test_gui_sensor_panel_has_no_confidence_row():
    _headers, rows = gui._kv_rows(dict(SENSOR))

    fields = [row[0] for row in rows]
    assert "Confidence" not in fields
    assert len(rows) == len(SENSOR) - 1
    assert any(row[0] == "Sensor Approval" for row in rows)


def test_company_info_still_shows_its_name_row():
    """Control: the skip is one key, not `HIDDEN_KEYS` (which hides `name`)."""
    assert "name" in report_format.HIDDEN_KEYS       # hidden from record tables
    data = _result(company_info={"name": "GARAGE SIXTEEN"})

    assert "Name" in _field_rows(data, "VU Company Info")

    _headers, rows = gui._kv_rows({"name": "GARAGE SIXTEEN"})
    assert [row[0] for row in rows] == ["Name"]
    assert rows[0][1] == "GARAGE SIXTEEN"


def test_the_confidence_value_is_still_in_the_result():
    """It is hidden from the renderers only: consumers still read it."""
    data = _result()
    assert data["sensor_info"]["confidence"] == "low"


@pytest.mark.parametrize("key, value", [("last_date", "2023-07-27"),
                                        ("param_distance_km", 120)])
def test_other_sensor_rows_are_unaffected(key, value):
    """A single skipped key must not shift or drop its neighbours."""
    data = _result()
    data["sensor_info"][key] = value

    _headers, rows = gui._kv_rows(data["sensor_info"])
    assert dict((row[0], row[1]) for row in rows)["Param Distance KM" if
                                                   key == "param_distance_km"
                                                   else "Last Date"] == str(value)
