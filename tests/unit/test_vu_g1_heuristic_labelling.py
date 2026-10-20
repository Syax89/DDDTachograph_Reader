"""Gen1 heuristic synthesis must say so — at the append site, not only in metadata.

Owner's rule: *"Il decoding deve essere sempre prima come normativa e quindi Ok,
poi euristico e quindi bassa confidenza."* The deterministic (Annex 1B) walks are
authoritative and carry no per-record verdict. Everything the emergency scans
*synthesize* on top of them — a driver block scraped by regex, an activity day
found by timestamp scan, a calibration reconstructed from a VIN hit, a card
download found by pattern scan, the whole of the non-normative sensor payload —
is inferred and must be labelled ``confidence: low`` where it is appended, plus
declared in ``metadata.heuristic_fields`` with a WARNING when a route switched.

Two things are pinned here:

* every heuristic append site is labelled, including a TREP 03 body that yields
  *only* a driver (no event, no fault — the wrapper used to miss that gain);
* the deterministic paths gain **no** such marker, so a clean download never
  looks inferred.

All streams are synthetic (fictitious names, generic identifiers, non-round
timestamps); no DDD corpus sample is used.
"""
import logging
import struct

import pytest

from core.decoders.vu_g1 import (
    _parse_sensor_download,
    _parse_trep_02_g1_structured,
    _parse_trep_03_events_faults,
    _parse_trep_05_technical,
    _parse_trep_06_card_download,
)

# ── synthetic constants (deliberately non-round, not from any real file) ────
TS = 1_690_431_907
TS_END = 1_690_468_913
TS_DAY = 1_690_329_600           # a UTC midnight
TS_DAY_2 = TS_DAY + 86_400
ODO = 412_399
ODO_NEW = 429_917
VIN = "ZXCVBNMASDFGHJKL0"
CARD_NUMBER = "0000000000471126"

_HEURISTIC_EVENT = "vu_events_faults_TREP03"


# ── TREP 02: the driver block of the timestamp scan ────────────────────────

def _trep02_timestamp_scan_body():
    """A TREP 02 body only the timestamp scan can read (n_iw = 0xFFFF)."""
    body = bytearray()
    body += struct.pack(">I", TS)                 # header timestamp
    body += b"\x00\x00\x00"                       # rest of the binary header
    body += b"\xff\xff"                           # noOfIWRecords -> structured bails
    body += b"\x00"
    body += b"\x01" + b"EPSILON".ljust(35, b" ")  # surname
    body += b"\x01"
    body += b"\x01" + b"OMICRON".ljust(35, b" ")  # first names
    body += b"\x01"
    body += struct.pack(">I", TS + 1)             # daily timestamp
    body += b"\x00\x00\x01"                       # odometer at midnight
    body += b"\x01"                               # card inserted
    body += struct.pack(">H", 2)                  # noOfActivityChanges
    body += struct.pack(">HH", 60, 0)             # REST at 01:00
    body += struct.pack(">HH", 0, 0)              # (0, 0) terminator
    body += b"\x00" * 8
    return bytes(body)


def test_trep02_timestamp_scan_marks_the_recovered_driver_low_confidence():
    """A regex-recovered card holder is inferred, so it must say so."""
    from core.decoders.vu_g1 import _parse_trep_02_activities

    results = {}
    _parse_trep_02_activities(_trep02_timestamp_scan_body(), results)

    drivers = results["inserted_drivers"]
    assert drivers, "the scan recovers the driver — recovery must not regress"
    assert all(d["confidence"] == "low" for d in drivers)
    assert all(a["confidence"] == "low" for a in results["activities"])
    assert results["metadata"]["heuristic_fields"]["vu_activities_TREP02"] == [
        "activities", "inserted_drivers"]


def test_trep02_structured_records_gain_no_confidence_marker():
    """Rule-of-spec output is 'Ok': no per-record verdict, no heuristic note."""
    body = bytearray()
    body += struct.pack(">I", TS)                 # dateOfDay
    body += ODO.to_bytes(3, "big")                # odometerValueMidnight
    body += struct.pack(">H", 1)                  # noOfIWRecords
    iw = bytearray(129)
    iw[0:6] = b"ZETA".ljust(6, b"\x00")
    iw[36:42] = b"KAPPA".ljust(6, b"\x00")
    iw[72] = 0x01
    iw[73] = 0x1A
    iw[74:90] = CARD_NUMBER.encode()
    iw[90:94] = struct.pack(">I", TS)
    iw[94:98] = struct.pack(">I", TS)
    iw[98:101] = ODO.to_bytes(3, "big")
    iw[106:109] = ODO_NEW.to_bytes(3, "big")
    body += bytes(iw)
    body += struct.pack(">H", 1)                  # noOfActivityChanges
    body += struct.pack(">H", (5 << 2) | 3)
    body += bytes([0])                            # noOfPlaceRecords
    body += struct.pack(">H", 0)                  # noOfSpecificConditionRecords

    results = {}
    assert _parse_trep_02_g1_structured(bytes(body), results) is True

    assert "heuristic_fields" not in results.get("metadata", {})
    for record in results["card_iw_records"]:
        assert "confidence" not in record
    for record in results["activities"]:
        assert "confidence" not in record
    for record in results["inserted_drivers"]:
        assert "confidence" not in record


# ── TREP 03: the driver-only gain the wrapper used to miss ────────────────

def _trep03_driver_only_body():
    """A TREP 03 body that yields a card number and nothing else.

    No event/fault decodes (the count-prefixed walk rejects the 0xFF fault
    count and the record-boundary attempt reads a zero timestamp), and the
    byte scan finds no candidate: its only 0x01 byte is the card's codepage
    marker, whose following four bytes stay below the plausible TimeReal
    window (``0x1A493030`` = 2010-…, i.e. before 2000).
    """
    return (b"\xff\x00\x00" + b"\x00" * 30
            + b"\x01\x1a" + b"I" + CARD_NUMBER.encode()
            + b"\x00" * 8)


def test_trep03_driver_only_gain_is_declared_as_heuristic(caplog):
    """A driver with no event/fault is still a heuristic gain — and is logged."""
    with caplog.at_level(logging.WARNING):
        results = {}
        _parse_trep_03_events_faults(_trep03_driver_only_body(), results)

    assert results.get("events") is None
    assert results.get("faults") is None
    drivers = results["inserted_drivers"]
    assert [d["card_number"] for d in drivers] == ["I" + CARD_NUMBER]
    assert drivers[0]["confidence"] == "low"

    # The wrapper must notice the gain even though events/faults stayed empty.
    assert results["metadata"]["heuristic_fields"][_HEURISTIC_EVENT] == [
        "inserted_drivers"]
    warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("TREP 03" in m and "inserted_drivers" in m for m in warned), warned


def test_trep03_gain_that_includes_events_declares_both():
    """A body that also invents events declares the driver too, not just events."""
    body = (b"\xff\x00\x00" + b"\x00" * 45
            + b"\x01" + b"LANDSCAPE MOTORS" + b"  " + b"\x01" + b"DRIVER ONE X"
            + b"\x01\x1a" + b"I" + CARD_NUMBER.encode()
            + b"\x00" * 8)

    results = {}
    _parse_trep_03_events_faults(body, results)

    assert results["inserted_drivers"][0]["confidence"] == "low"
    assert all(e["confidence"] == "low" for e in results["events"])
    assert results["metadata"]["heuristic_fields"][_HEURISTIC_EVENT] == [
        "events", "inserted_drivers"]


def test_trep03_structured_records_gain_no_confidence_marker():
    """The count-prefixed walk's own records stay unlabelled."""
    fault = bytearray(82)
    fault[0] = 0x05
    fault[1] = 0x01
    struct.pack_into(">I", fault, 2, TS)
    struct.pack_into(">I", fault, 6, TS_END)
    body = (bytes([1]) + bytes(fault)
            + bytes([0])              # noOfVuEvents
            + b"\x00" * 9             # VuOverSpeedingControlData
            + bytes([0])              # noOfVuOverSpeedingEvents
            + bytes([0]))             # noOfVuTimeAdjustments

    results = {}
    _parse_trep_03_events_faults(body, results)

    assert [f["fault_type"] for f in results["faults"]] == [0x05]
    assert "confidence" not in results["faults"][0]
    assert "heuristic_fields" not in results.get("metadata", {})


# ── TREP 05: the VIN-scan calibration ─────────────────────────────────────

def _trep05_vin_scan_body():
    """A TREP 05 body the structured walk rejects (noOfCalibrations = 0x40)."""
    body = bytearray()
    body += b"\x00" * 72                    # unreadable manufacturer + address
    body += b"\x00" * (136 - 72)
    body += bytes([0x40])                   # structure_fits -> False
    body += b"\x00" * 40
    body += VIN.encode()                    # the VIN the regex finds
    fixed = bytearray(40)
    fixed[0] = 0x0D                         # vehicleRegistrationNation
    fixed[1:15] = b"AB123CD".ljust(14)      # plate
    struct.pack_into(">H", fixed, 15, 8000)  # wVehicleCharacteristicConstant
    struct.pack_into(">H", fixed, 17, 9600)  # kConstantOfRecordingEquipment
    struct.pack_into(">H", fixed, 19, 3200)  # lTyreCircumference
    fixed[21:36] = b"295/80R22.5".ljust(15)
    fixed[36] = 80                          # authorisedSpeed
    fixed[37:40] = ODO.to_bytes(3, "big")
    body += bytes(fixed)
    body += b"\x00" * 4
    return bytes(body)


def test_trep05_vin_scan_calibration_is_low_confidence():
    """A calibration reconstructed around a VIN hit is inferred, not decoded."""
    results = {}
    _parse_trep_05_technical(_trep05_vin_scan_body(), results)

    calibrations = results["calibrations"]
    assert len(calibrations) == 1
    record = calibrations[0]
    assert record["confidence"] == "low"
    # The recovered values themselves are kept exactly as before.
    assert record["vin"] == VIN
    assert record["plate"] == "AB123CD"
    assert record["w_constant"] == 8000
    assert record["k_constant"] == 9600
    assert record["l_tyre_circumference"] == 3200
    assert record["speed_limit"] == 80
    assert record["odometer"] == ODO
    assert results["metadata"]["heuristic_fields"]["vu_technical_TREP05"] == [
        "calibrations"]


def _trep05_structured_body():
    """A TREP 05 body with one fully-formed 167-byte VuCalibrationRecord."""
    body = bytearray()
    body += b"MANUFACTURER NAME".ljust(36)
    body += b"ADDRESS LINE".ljust(36)
    body += b"PARTNUMBER123456".ljust(16)
    body += b"SERIAL12"
    body += b"SW12"
    body += struct.pack(">I", TS) + struct.pack(">I", TS)
    body += b"APPROVA8"
    body += b"SERIAL12" + b"APPROVA8" + struct.pack(">I", TS)
    assert len(body) == 136, len(body)
    body += bytes([1])                      # noOfCalibrationRecords
    rec = bytearray(167)
    rec[0] = 0x00                           # calibrationPurpose
    rec[1:37] = b"WORKSHOP NAME".ljust(36)
    rec[37:73] = b"WORKSHOP ADDRESS".ljust(36)
    rec[73] = 0x01                          # workshop card type
    rec[74] = 0x0D                          # workshop card nation
    rec[75:91] = b"W000000000047112"
    rec[91:95] = struct.pack(">I", TS)
    rec[95:112] = VIN.encode()
    rec[112] = 0x0D                         # vehicle registration nation
    rec[113] = 0x01                         # vehicle registration codePage
    rec[114:127] = b"AB123CD".ljust(13)
    struct.pack_into(">H", rec, 127, 8000)
    struct.pack_into(">H", rec, 129, 9600)
    struct.pack_into(">H", rec, 131, 3200)
    rec[133:148] = b"295/80R22.5".ljust(15)
    rec[148] = 80
    rec[149:152] = ODO.to_bytes(3, "big")
    rec[152:155] = ODO_NEW.to_bytes(3, "big")
    rec[155:159] = struct.pack(">I", TS)
    rec[159:163] = struct.pack(">I", TS_END)
    rec[163:167] = struct.pack(">I", TS_END)
    body += bytes(rec)
    return bytes(body)


def test_trep05_structured_calibration_gains_no_confidence_marker():
    """The 167-byte layout is the normative path: nothing to flag."""
    results = {}
    _parse_trep_05_technical(_trep05_structured_body(), results)

    calibrations = results["calibrations"]
    assert len(calibrations) == 1
    assert "confidence" not in calibrations[0]
    assert calibrations[0]["workshop"] == "WORKSHOP NAME"
    assert calibrations[0]["vin"] == VIN
    assert "heuristic_fields" not in results.get("metadata", {})


# ── TREP 06: the pattern-scan fallback ────────────────────────────────────

def _trep06_fallback_body():
    """A non-standard card image: the card-EF walk recovers nothing."""
    body = bytearray()
    body += b"\x01" + b"GARAGE SIXTEEN" + b"  " + b"\x01" + b"CARD HOLDER X"
    body += b"\x02\x1d" + b"I" + CARD_NUMBER.encode()
    body += struct.pack(">I", TS)
    body += b"\x00" * 12
    return bytes(body)


def test_trep06_fallback_download_and_driver_are_low_confidence():
    """Both lists the pattern scan appends to must carry the marker."""
    results = {}
    _parse_trep_06_card_download(_trep06_fallback_body(), results)

    downloads = results["card_downloads"]
    assert len(downloads) == 1
    assert downloads[0]["confidence"] == "low"
    assert downloads[0]["card_numbers"] == ["I" + CARD_NUMBER]

    drivers = results["inserted_drivers"]
    assert [d["surname"] for d in drivers] == ["GARAGE SIXTEEN"]
    assert drivers[0]["confidence"] == "low"
    assert results["metadata"]["heuristic_fields"]["vu_card_download_TREP06"] == [
        "card_downloads", "inserted_drivers"]


def test_trep06_deterministic_card_image_gains_no_confidence_marker():
    """A decodable embedded card image is the primary path: no marker at all."""
    from tests.unit.card_crypto import g1_core_payloads, stap

    body = bytearray()
    for tag, payload in g1_core_payloads().items():
        body += stap(tag, 0x00, payload)

    results = {}
    _parse_trep_06_card_download(bytes(body), results)

    # The deterministic walk recovered something, so the scan never ran.
    assert results.get("card_application")
    assert "heuristic_fields" not in results.get("metadata", {})
    for section in ("inserted_drivers", "card_downloads", "activities"):
        for record in results.get(section) or []:
            assert "confidence" not in record


# ── TREP 0x11: a manufacturer payload with no normative layout ────────────

def _sensor_body():
    """A synthetic TREP 0x11 payload: ID block + two daily speed blocks."""
    body = bytearray()
    body += bytes(range(17))                  # undocumented TOC header
    body += b"\xff" * 4                       # padding
    block = bytearray(168)
    block[0:4] = struct.pack(">I", TS)
    block[4:8] = struct.pack(">I", TS_END)
    struct.pack_into(">H", block, 10, 92)     # max speed parameter
    struct.pack_into(">H", block, 12, 61)     # average speed parameter
    struct.pack_into(">H", block, 14, 120)    # distance parameter
    block[100] = 0x01                         # approval prefix
    block[101] = 0x1A                         # approval nation
    block[102:118] = b"SENSOR1234567890"
    body += bytes(block)
    for day, event, speeds in ((TS_DAY, TS_DAY + 3600, [0, 42, 55, 61, 0]),
                               (TS_DAY_2, TS_DAY_2 + 1800, [10, 20, 30])):
        body += struct.pack(">I", day) + struct.pack(">I", event)
        body += struct.pack(">H", len(speeds)) + bytes(speeds)
        body += b"\xff" * 3
    return bytes(body)


def test_sensor_payload_is_labelled_low_confidence_without_a_fallback_claim(caplog):
    """No regulation defines this payload: label the values, raise no alarm.

    The uncertainty is carried by ``confidence: low`` on the data. It is *not* a
    heuristic fallback: nothing normative exists for TRTP 11..1F, so a valid
    download did not fall back from anything and must not grow a
    ``metadata.heuristic_fields`` entry or a WARNING (owner decision: a valid,
    intact file never takes — or claims — a heuristic route).
    """
    with caplog.at_level(logging.WARNING):
        results = {}
        _parse_sensor_download(_sensor_body(), results)

    info = results["sensor_info"]
    assert info["confidence"] == "low"
    assert info["sensor_approval"] == "SENSOR1234567890"
    assert info["approval_nation"] == "I"
    assert info["param_speed_max_kmh"] == 92
    assert info["param_speed_avg_kmh"] == 61
    assert info["param_distance_km"] == 120

    daily = results["sensor_daily_records"]
    assert len(daily) == 2
    assert all(record["confidence"] == "low" for record in daily)
    # The recovered values are untouched.
    assert [record["speed_samples"] for record in daily] == [5, 3]
    assert daily[0]["speed_max"] == 61
    assert daily[1]["speed_avg"] == 20.0

    # No fallback claim, and no WARNING on a valid file.
    assert "heuristic_fields" not in (results.get("metadata") or {})
    warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warned == [], [r.getMessage() for r in warned]


def test_sensor_values_match_the_pre_batch_recovery():
    """Control: dropping the declaration changed metadata only, never a value."""
    results = {}
    _parse_sensor_download(_sensor_body(), results)

    assert sorted(results["sensor_info"]) == [
        "approval_nation", "approval_prefix", "confidence", "first_date",
        "last_date", "param_distance_km", "param_speed_avg_kmh",
        "param_speed_max_kmh", "sensor_approval"]
    assert [sorted(record) for record in results["sensor_daily_records"]] == [
        ["confidence", "date", "first_event", "speed_avg", "speed_max",
         "speed_min", "speed_samples", "speed_valid_count"]] * 2


def test_sensor_payload_that_fails_the_sanity_gate_declares_nothing():
    """A false 0x76 0x11 marker must not publish garbage *or* a heuristic note."""
    body = bytearray(_sensor_body())
    # The ID block starts after the 17-byte TOC and the FF padding run.
    struct.pack_into(">H", body, 21 + 10, 30000)   # implausible max speed

    results = {}
    _parse_sensor_download(bytes(body), results)

    assert results.get("sensor_info") is None
    assert results.get("sensor_daily_records") is None
    assert "heuristic_fields" not in results.get("metadata", {})


def test_sensor_decoders_no_longer_claim_a_normative_layout():
    """The false 'Annex 1B §4.5.3.2.1 defines the sensor format' is gone.

    Annex 1B §4.5.3 is "Stored data integrity"; the §4.5.3.2.x numbering belongs
    to Annex 1C card EF layouts. The docstrings must say the payload has no
    normative layout instead of citing one.
    """
    import inspect

    doc = inspect.getdoc(_parse_sensor_download) or ""
    assert "is not normative" in doc.replace("*", "")
    assert "manufacturer extension" in doc
    assert "Annex 1B §4.5.3.2.1 defines" not in doc
    assert "defines the sensor download format" not in doc


@pytest.mark.parametrize("section", ["vu_activities_TREP02", "vu_events_faults_TREP03",
                                     "vu_technical_TREP05", "vu_card_download_TREP06"])
def test_every_declared_heuristic_section_is_also_low_confidence_at_record_level(section):
    """Metadata alone is not enough: the records must carry the marker too.

    This is the invariant behind all the site tests above — a section named in
    ``metadata.heuristic_fields`` must never hand out a record presented as a
    decoded fact.
    """
    if section == "vu_activities_TREP02":
        from core.decoders.vu_g1 import _parse_trep_02_activities
        results = {}
        _parse_trep_02_activities(_trep02_timestamp_scan_body(), results)
    elif section == "vu_events_faults_TREP03":
        results = {}
        _parse_trep_03_events_faults(_trep03_driver_only_body(), results)
    elif section == "vu_technical_TREP05":
        results = {}
        _parse_trep_05_technical(_trep05_vin_scan_body(), results)
    else:
        results = {}
        _parse_trep_06_card_download(_trep06_fallback_body(), results)

    declared = results["metadata"]["heuristic_fields"][section]
    assert declared
    for name in declared:
        value = results.get(name)
        records = value if isinstance(value, list) else [value]
        assert records
        for record in records:
            assert isinstance(record, dict) and record.get("confidence") == "low", (
                f"{section}: {name} record is declared heuristic but not labelled")
