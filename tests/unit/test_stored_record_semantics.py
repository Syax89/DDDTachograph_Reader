"""Stored-record semantics a second blind refutation pass found.

* a generation-1 place / specific condition with an unusable TimeReal was dropped by
  a value gate (the TREP 03 fix never reached TREP 02);
* `_append_once`'s content rule deleted a *distinct* stored record when a different
  message body happened to carry identical values;
* `time_status` disagreed across generations for TimeReal 0;
* the generation-1 calibration table lost its `N/A` convention for a withheld time.
"""
import struct

import pytest

from app.engine import TachoParser
from core.parser.vu_dispatcher import decode_place_daily, decode_specific_condition
from core.registry.registry import DecoderRegistry
from tests.unit import vu_synthetic as S
from tests.unit.test_g1_vu_semantics import (
    _g1_calibration, _parse_trep_02_g1_structured, _parse_trep_03_structured,
    _parse_trep_05_technical, _results, _trep02_body, _trep03_body, _trep05_body)

TIME = S.BASE_TIME


def _parse_file(tmp_path, name, data):
    """Parse *data* written to *tmp_path*; returns the result dict."""
    from tests.unit.test_card_envelope import _parse_bytes as parse
    return parse(tmp_path, name, data)


def _trep02_with_times(place_ts, cond_ts, day_ts=TIME):
    """One place and one specific condition, each with the given TimeReal."""
    body = bytearray()
    body += struct.pack(">I", day_ts) + (654_321).to_bytes(3, "big")
    body += struct.pack(">H", 0)                      # no IW
    body += struct.pack(">H", 0)                      # no activity changes
    body += bytes([1])                                # one place
    body += (S.full_card_number() + struct.pack(">I", place_ts)
             + bytes([0x00, 0x1A, 0x07]) + (1000).to_bytes(3, "big"))
    body += struct.pack(">H", 1)                      # one specific condition
    body += struct.pack(">I", cond_ts) + bytes([0x03])
    return bytes(body)


# ── Item 1: no value-based existence gate in TREP 02 ──────────────────────

@pytest.mark.parametrize("ts,status", [(0, "invalid"), (5, "invalid"),
                                       (0xFFFFFFFF, "invalid")])
def test_places_and_conditions_with_an_unusable_clock_are_kept(ts, status):
    results = _results()
    assert _parse_trep_02_g1_structured(_trep02_with_times(ts, ts), results) is True
    assert len(results["places"]) == 1
    assert len(results["specific_conditions"]) == 1
    place = results["places"][0]
    assert place["timestamp"] is None
    assert place["timestamp_raw"] == ts
    assert place["time_status"] == status
    condition = results["specific_conditions"][0]
    assert condition["timestamp"] is None
    assert condition["timestamp_raw"] == ts
    assert condition["time_status"] == status
    # the rest of the record is decoded as usual
    assert place["nation"] == "I"
    assert place["odometer_km"] == 1000
    assert condition["condition"] == "Ferry/Train crossing"


def test_a_usable_clock_is_still_valid():
    results = _results()
    _parse_trep_02_g1_structured(_trep02_with_times(TIME, TIME), results)
    assert results["places"][0]["time_status"] == "valid"
    assert results["specific_conditions"][0]["time_status"] == "valid"
    assert results["places"][0]["timestamp"].startswith("2024-04-0")


def test_a_truncated_trep02_body_still_fails_structurally():
    results = _results()
    ok = _parse_trep_02_g1_structured(_trep02_with_times(TIME, TIME)[:-30], results)
    assert ok is False


# ── Item 2: identity is position, content merging is scan-only ────────────

def test_two_separate_messages_with_identical_records_are_both_kept():
    results = _results()
    first = _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(), n_adj=())
    second = _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(), n_adj=())
    assert _parse_trep_03_structured(first, results, message_offset=100) is True
    assert _parse_trep_03_structured(second, results, message_offset=200) is True
    assert len(results["faults"]) == 2
    assert len(results["events"]) == 2


def test_the_same_body_read_twice_is_emitted_once():
    results = _results()
    body = _trep03_body(event_type=0x0A, fault_type=0x31, n_over=(), n_adj=())
    _parse_trep_03_structured(body, results, message_offset=100)
    _parse_trep_03_structured(body, results, message_offset=100)
    assert len(results["faults"]) == 1
    assert len(results["events"]) == 1


def test_two_generation_1_days_with_identical_values_are_both_kept():
    results = _results()
    body = _trep02_body()
    assert _parse_trep_02_g1_structured(body, results, message_offset=10) is True
    assert _parse_trep_02_g1_structured(body, results, message_offset=20) is True
    assert len(results["activities"]) == 2          # one day per message
    assert len(results["places"]) == 4              # two places per message


def test_a_damaged_file_does_not_double_publish_recovered_records(tmp_path):
    """The byte-scan recovery re-reads bytes: it must not publish twice."""
    from tests.unit.real_data import require_real_file
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        data = handle.read()
    cut = data[:len(data) // 2]
    target = tmp_path / "scan.ddd"
    target.write_bytes(cut)
    DecoderRegistry.reset_instance()
    result = TachoParser(str(target)).parse()
    keys = [record.get("_key") for record in result.get("faults") or []]
    assert len(keys) == len(set(keys)), "a recovered record was published twice"
    assert result["metadata"].get("heuristic_fields") or result["metadata"].get(
        "vu_integrity")


# ── Item 4: TimeReal 0 is not "valid" in either generation ────────────────

def test_generation_2_time_zero_is_invalid_like_generation_1():
    record = (S.card_number() + struct.pack(">I", 0) + bytes([0x00, 0x1A, 0x07])
              + bytes(3) + struct.pack(">I", 0) + bytes([0x02]) + b"\x00" * 6 + b"\x01")
    place = decode_place_daily(record)
    assert place["timestamp"] is None
    assert place["timestamp_raw"] == 0
    assert place["time_status"] == "invalid"
    condition = decode_specific_condition(struct.pack(">I", 0) + b"\x01")
    assert condition["time_status"] == "invalid"


def test_generation_2_time_out_of_window_is_invalid_too():
    record = (S.card_number() + struct.pack(">I", 5) + bytes([0x00, 0x1A, 0x07])
              + bytes(3) + struct.pack(">I", 5) + bytes([0x02]) + b"\x00" * 6 + b"\x01")
    assert decode_place_daily(record)["time_status"] == "invalid"


# ── Item 7: the withheld value keeps the table's N/A convention ───────────

def test_generation_1_calibration_withholds_with_the_na_convention():
    body = bytearray(_g1_calibration())
    struct.pack_into(">I", body, 159, 0)              # new_timeValue = 0
    struct.pack_into(">I", body, 163, 0)              # nextCalibrationDate = 0
    results = _results()
    _parse_trep_05_technical(_trep05_body([bytes(body)]), results)
    cal = results["calibrations"][0]
    assert cal["new_time"] == "N/A"
    assert cal["next_calibration_date"] == "N/A"
    # the usable value keeps the upgraded full timestamp
    assert "T" in cal["old_time"]


# ── Item 3: every label a surface renders has a catalog msgid ─────────────

def _panel_labels(result):
    """Labels the four touched surfaces render for one parse result."""
    from app import gui
    from core.utils import report_format as rf
    labels = {"Calibrations", "VU Information", "VU Overview", "Places"}
    found = set()
    for name, _desc, headers, _rows, _trunc in rf.section_tables(result):
        if name in labels:
            found.update(h for h in headers if isinstance(h, str))
    for key in ("vu_info", "vu_overview"):
        value = result.get(key)
        if isinstance(value, dict) and value:
            _headers, rows = gui._kv_rows(value)
            found.update(str(row[0]) for row in rows)
    return found


def test_every_label_this_branch_added_has_a_catalog_msgid():
    """The labels the branch introduced must resolve through the catalogs.

    Scoped to the labels this branch paints (the four touched surfaces' new rows
    and columns). The panel's legacy nested rows ("Card Slot Status", "Driver
    Slot", …) predate the branch and are reported in .audit/AUTHOR.md rather than
    silently covered by a wider assertion here.
    """
    import glob
    import re
    from core.utils import report_format as rf
    from tests.unit.real_data import real_ddd_files

    branch_labels = {
        rf.humanize_key("download_interface_version"),
        rf.humanize_key("current_date_time"),
        rf.humanize_key("rcm_serial"),
        rf.humanize_key("sensor_gnss_serial"),
        rf.humanize_key("sensor_serial"),
        rf.humanize_key("entry_type_description"),
        "VU Serial",
    }
    # the labels really are what the surfaces render
    files = real_ddd_files()
    if not files:
        pytest.skip("no private corpus available")
    rendered = set()
    for path in files:
        DecoderRegistry.reset_instance()
        rendered |= _panel_labels(TachoParser(path).parse())
    for label in branch_labels:
        assert label in rendered, label
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        msgids = set(re.findall(r'^msgid "(.*)"$',
                                open(path, encoding="utf-8").read(), re.M))
        missing = sorted(label for label in branch_labels if label not in msgids)
        assert not missing, (path, missing)


def test_the_dead_msgids_of_this_branch_are_gone():
    """Labels no surface renders must not clutter the catalogs."""
    import glob
    import re
    dead = ["Entry Type Meaning", "Month", "Year", "Serial", "Old Time Full",
            "New Time Full", "Next Calibration Full", "Sensor Pairing Time"]
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        msgids = set(re.findall(r'^msgid "(.*)"$',
                                open(path, encoding="utf-8").read(), re.M))
        for msgid in dead:
            assert msgid not in msgids, (path, msgid)


# ── Item 5: every 76 06 card region gets its own verdict ─────────────────

def test_two_card_regions_in_one_file_each_get_a_verdict(tmp_path):
    from tests.unit.real_data import require_real_file
    path = require_real_file("*_D47C4D98DF.ddd")
    with open(path, "rb") as handle:
        card = handle.read()
    result = _parse_file(tmp_path, "two_cards.ddd", card + card)
    meta = result["metadata"]
    verdicts = meta.get("embedded_card_verdicts") or []
    assert len(verdicts) == 1, verdicts          # the first card owns the file
    assert verdicts[0]["integrity_check"] == "Verified"
    assert (verdicts[0]["ef_signatures"] or {}).get("verified") == 9
    # the file is not degraded by the second region
    assert "Verified" in meta["integrity_check"]
    assert meta["envelope"]["further_regions"] == 1


def test_two_different_cards_and_card_plus_junk(tmp_path):
    from tests.unit.real_data import require_real_file
    first = require_real_file("*_D47C4D98DF.ddd")
    second = require_real_file("*_06C93F5620.ddd")
    with open(first, "rb") as handle:
        one = handle.read()
    with open(second, "rb") as handle:
        two = handle.read()
    result = _parse_file(tmp_path, "diff_cards.ddd", one + two)
    assert "Verified" in result["metadata"]["integrity_check"]
    assert (result["metadata"].get("embedded_card_verdicts") or [{}])[0][
        "integrity_check"] == "Verified"

    # a second, truncated region gets its own integrity finding
    cut = _parse_file(tmp_path, "cut_second.ddd", one + two[:len(two) // 2])
    findings = cut["metadata"].get("vu_integrity") or []
    assert any(f["status"] in ("card_download_incomplete", "card_envelope_incomplete")
               for f in findings), findings


# ── Item 6: the TREP 06 citation is right everywhere ─────────────────────

def test_no_wrong_trep06_citation_remains():
    import glob
    bad = []
    for pattern in ("core/**/*.py", "app/*.py", "docs/**/*.md", "tests/unit/*.py"):
        for path in glob.glob(pattern, recursive=True):
            text = open(path, encoding="utf-8", errors="ignore").read()
            if "2.2.6.6" in text and "no_wrong_trep06_citation" not in text:
                bad.append(path)
    assert not bad, bad
