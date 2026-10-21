"""A calibration whose TimeReal is outside the calendar says so.

``VuCalibrationRecord`` (Annex 1B §2.118) keeps a stored record even when its
clock is unusable: the value is withheld and the reason travels in
``field_status``. The status was unreachable — the field it tested had already
been replaced by the "N/A" display sentinel — so a calibration with e.g.
``oldTimeValue = 0`` silently looked like a record the decoder had no opinion on.

Every value below is synthetic.
"""
import struct

from core.decoders.vu_g1 import _parse_trep_05_technical
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME
STATUS = "TimeReal outside the calendar"


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"},
            "activities": [], "events": [], "faults": [], "inserted_drivers": [],
            "card_iw_records": [], "places": [], "specific_conditions": [],
            "overspeeding_events": [], "overspeeding_control": [],
            "time_adjustments": [], "calibrations": [], "workshops": [],
            "calibration_vins": set(), "vu_info": {}, "vu_overview": {},
            "company_locks": [], "control_activities": [], "company_info": {},
            "speed_blocks": []}


def _calibration(old_time=TIME):
    """One 167-byte VuCalibrationRecord with a synthetic VIN and constants."""
    rec = bytearray(167)
    rec[0] = 0x01                                            # purpose
    rec[1:37] = S.coded_string("SYNTH WORKSHOP", code_page=1, length=36)
    rec[37:73] = S.coded_string("SYNTH STREET 3", code_page=1, length=36)
    rec[74] = 0x1A
    rec[75:91] = b"T00000000000001\x00"[:16]
    rec[91:95] = b"\x00" * 4
    rec[95:112] = S.VIN.encode("ascii").ljust(17, b"\x00")
    rec[112] = 0x1A
    rec[113] = 0x01
    rec[114:127] = S.PLATE.encode("ascii").ljust(13, b"\x00")
    rec[127:129] = struct.pack(">H", 2_150)                  # w
    rec[129:131] = struct.pack(">H", 39_000)                 # k
    rec[131:133] = struct.pack(">H", 2_600)                  # l
    rec[133:148] = S.coded_string("SYNTH TYRE", code_page=1, length=15)
    rec[148] = 90
    rec[149:152] = (120_000).to_bytes(3, "big")
    rec[152:155] = (120_010).to_bytes(3, "big")
    rec[155:159] = struct.pack(">I", old_time)
    rec[159:163] = struct.pack(">I", old_time)
    rec[163:167] = struct.pack(">I", old_time)
    return bytes(rec)


def _body(*records):
    """A TREP 05 body: VuIdentification(116) + SensorPaired(20) + records."""
    identification = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
                      + S.coded_string("SYNTH VU ADDRESS", code_page=1, length=36)
                      + b"\x00" * 44)
    assert len(identification) == 116
    return (identification + b"\x00" * 20 + bytes([len(records)])
            + b"".join(records))


def test_an_out_of_calendar_calibration_clock_is_reported():
    results = _results()
    _parse_trep_05_technical(_body(_calibration(old_time=0)), results)
    record = results["calibrations"][0]
    assert record["old_time_iso"] is None
    assert record["old_time"] == "N/A"          # the table's missing-value word
    assert record["field_status"]["old_time"] == STATUS


def test_a_usable_calibration_clock_carries_no_status():
    results = _results()
    _parse_trep_05_technical(_body(_calibration(old_time=TIME)), results)
    record = results["calibrations"][0]
    assert record["old_time"] == record["old_time_iso"] != "N/A"
    assert "old_time" not in record["field_status"]


def test_every_out_of_calendar_clock_of_the_record_is_reported():
    """The record holds THREE TimeReals; each one gets the same reason.

    ``VuCalibrationRecord`` (Annex 1B §2.118) carries oldTimeValue,
    newTimeValue and nextCalibrationTime. Only ``old_time`` gained a status, so
    an unusable ``newTimeValue``/``nextCalibrationTime`` read as an empty cell
    with no explanation.
    """
    results = _results()
    record_body = bytearray(_calibration(old_time=TIME))
    record_body[159:163] = struct.pack(">I", 0)          # newTimeValue
    record_body[163:167] = struct.pack(">I", 0)          # nextCalibrationTime
    _parse_trep_05_technical(_body(bytes(record_body)), results)
    record = results["calibrations"][0]
    assert record["new_time_iso"] is None
    assert record["next_calibration_iso"] is None
    assert record["new_time"] == record["next_calibration_date"] == "N/A"
    assert record["field_status"]["new_time"] == STATUS
    assert record["field_status"]["next_calibration_date"] == STATUS
    # A usable sibling keeps no status at all.
    assert "old_time" not in record["field_status"]


def test_a_usable_record_reports_no_clock_status_for_any_sibling():
    results = _results()
    _parse_trep_05_technical(_body(_calibration(old_time=TIME)), results)
    assert results["calibrations"][0]["field_status"].get("new_time") is None
    assert results["calibrations"][0]["field_status"].get(
        "next_calibration_date") is None
