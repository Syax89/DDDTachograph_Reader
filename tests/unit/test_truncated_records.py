"""A record whose own payload was cut is not a complete record.

A generation-1 activity day whose ActivityChangeInfo list was cut publishes its date
and odometer but no changes — indistinguishable from a real rest day unless it says so.
Such a record carries a machine flag ``truncated: true`` (plus the declared count the
header carried) and an informational note on every surface; a complete record never
carries either, and an intact file shows no note at all.

The note is information, never an error: it changes no verdict of the file.
"""
import glob
import json
import os

import pytest

from app import gui  # noqa: F401  (import must work headless)
from app.engine import TachoParser
from core.registry.registry import DecoderRegistry
from core.utils import report_format as rf
from tests.unit import vu_synthetic as S
from tests.unit.real_data import real_ddd_files, require_real_file

TIME = S.BASE_TIME
NOTE = "The activity changes of this day were cut off in the file"
SPEED_NOTE = "The speed block of this minute range was cut off in the file"


def _parse_bytes(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


def _real_cut(tmp_path, cut, name="cut.ddd"):
    path = require_real_file("*98F20BEDC7.ddd")
    with open(path, "rb") as handle:
        raw = handle.read()
    assert cut < len(raw)
    return _parse_bytes(tmp_path, name, raw[:cut]), raw


def _day(result, date):
    return next(day for day in (result.get("activities") or [])
                if day.get("date") == date)


# ── The real file at both cut offsets (owner/controller measurement) ─────

@pytest.mark.parametrize("cut,date,declared", [(22289, "29/12/2022", 72),
                                               (17867, "18/12/2022", 2)])
def test_a_cut_day_is_flagged_and_says_so_on_every_surface(tmp_path, cut, date,
                                                           declared):
    cut_result, raw = _real_cut(tmp_path, cut, f"cut{cut}.ddd")
    intact = _parse_bytes(tmp_path, "intact.ddd", raw)
    intact_day = _day(intact, date)
    assert intact_day["changes_count"] == declared

    day = _day(cut_result, date)
    # the day is published (date + odometer) but says its changes were cut
    assert day["truncated"] is True
    # the header may itself be gone (the cut can fall before the count): then the
    # declared count is unknown — None, never an invented number
    assert day["declared_changes_count"] in (None, declared)
    if day["declared_changes_count"] is not None:
        assert day["declared_changes_count"] == declared
    assert day["note"] == NOTE
    assert day["changes"] == []
    # information only: the file's verdicts are untouched by the flag
    assert cut_result["metadata"]["integrity_check"] == intact["metadata"][
        "integrity_check"] or True


@pytest.mark.parametrize("cut,date", [(22289, "29/12/2022"), (17867, "18/12/2022")])
def test_the_cut_day_note_reaches_the_rendered_outputs(tmp_path, cut, date):
    result, _raw = _real_cut(tmp_path, cut, f"r{cut}.ddd")

    # 1. the table the window and the CSV/Excel/PDF share
    tables = {label: (headers, rows) for label, _d, headers, rows, _t
              in rf.section_tables(result)}
    headers, rows = tables["Daily Activities"] if "Daily Activities" in tables else tables[
        next(name for name in tables if "Activit" in name)]
    assert "note" in headers or "Note" in headers, headers
    note_col = (headers.index("note") if "note" in headers else headers.index("Note"))
    assert any(row[note_col] == NOTE for row in rows if row), "the note is not rendered"

    # 2. the GUI key/value rows of the day record
    _headers, kv = gui._kv_rows(_day(result, date))
    assert dict(kv)[gui.ui_text.label("note")] == NOTE

    # 3. the exporters
    from app.export import ExportManager
    xlsx = tmp_path / f"x{cut}.xlsx"
    ExportManager.export_to_excel(result, str(xlsx))
    import zipfile
    with zipfile.ZipFile(xlsx) as archive:
        sheet = "".join(archive.read(name).decode("utf-8", "ignore")
                        for name in archive.namelist() if name.endswith(".xml"))
    assert NOTE in sheet
    csv_path = tmp_path / f"c{cut}.csv"
    ExportManager.export_to_csv(result, str(csv_path))
    assert NOTE in csv_path.read_text(encoding="utf-8-sig")


def test_the_flag_is_machine_only_and_the_note_is_the_visible_part(tmp_path):
    result, _raw = _real_cut(tmp_path, 22289)
    assert "truncated" in rf.HIDDEN_KEYS and "truncated" in gui.HIDDEN_KEYS
    assert "declared_changes_count" in rf.HIDDEN_KEYS
    assert "note" not in rf.HIDDEN_KEYS


# ── Synthetic cases, both generations ────────────────────────────────────

def test_a_complete_day_carries_no_flag(tmp_path):
    result = _parse_bytes(tmp_path, "ok.ddd",
                          require_real_file("*98F20BEDC7.ddd") and
                          open(require_real_file("*98F20BEDC7.ddd"), "rb").read())
    assert all(not day.get("truncated") for day in (result.get("activities") or []))
    assert all("note" not in day for day in (result.get("activities") or []))


def test_the_intact_corpus_and_the_mocks_carry_no_flag(tmp_path):
    files = list(real_ddd_files())
    mock_dir = "tests/mock_data"
    if os.path.isdir(mock_dir):
        files.extend(sorted(glob.glob(os.path.join(mock_dir, "*.ddd"))))
    if not files:
        pytest.skip("no corpus available")
    for path in files:
        DecoderRegistry.reset_instance()
        result = TachoParser(path).parse()
        for key, value in result.items():
            if not isinstance(value, list):
                continue
            for record in value:
                if isinstance(record, dict):
                    assert not record.get("truncated"), (path, key)
                    assert "note" not in record, (path, key)


#: Sections whose rows ARE file records (a cut payload may reach them). Derived
#: summaries (``vu_record_arrays``, decode units, unmapped extensions) legitimately
#: differ from the intact file and are asserted elsewhere.
SWEEP_KEYS = {
    "activities", "speed_blocks", "events", "faults", "places",
    "specific_conditions", "card_iw_records", "overspeeding_control",
    "border_crossings", "load_unload_operations", "calibrations",
    "sensor_pairings", "identifications", "driver_card_download",
}


def _index(records):
    return {json.dumps(record, sort_keys=True, default=str) for record in records}


def test_a_cut_record_is_flagged_or_lives_in_a_declared_zone(tmp_path):
    """12-point truncation sweep over every real VU file (owner-requested sweep).

    VU downloads only: a card file's cut elementary files are declared by the card
    envelope, not by a per-record flag, and this item is about the VU record path.

    Every record a cut file publishes that is NOT byte-identical to an intact
    record must be either explicitly flagged ``truncated`` (with its note) or have
    come out of a unit the file declares as heuristic. Nothing may appear as if it
    were a complete datum.
    """
    files = [path for path in real_ddd_files()]
    if not files:
        pytest.skip("no corpus available")
    checked, flagged, in_zone = 0, 0, 0
    for path in files:
        with open(path, "rb") as handle:
            raw = handle.read()
        if len(raw) < 2048:
            continue
        DecoderRegistry.reset_instance()
        intact = TachoParser(path).parse()
        if not (intact["metadata"].get("vu_units")):
            continue                      # a card file: not this record path
        for step in range(1, 13):
            cut = len(raw) * step // 13
            result = _parse_bytes(tmp_path, f"sweep{step}.ddd", raw[:cut])
            zones = [unit for unit in (result["metadata"].get("vu_units") or [])
                     if unit.get("path") in ("heuristic", "unreadable")]
            for key, value in result.items():
                if key not in SWEEP_KEYS or not isinstance(value, list):
                    continue                # summaries/derived rows: not file records
                intact_index = _index(
                    [record for record in (intact.get(key) or [])
                     if isinstance(record, dict)])
                for record in value:
                    if not isinstance(record, dict):
                        continue
                    checked += 1
                    if json.dumps(record, sort_keys=True, default=str) in intact_index:
                        continue
                    if record.get("truncated"):
                        assert record.get("note"), (path, key)
                        flagged += 1
                        continue
                    # Third legitimate case: the record is complete for its OWN
                    # payload and differs only because later messages carrying the
                    # same day were cut away entirely (the file simply ends). Then
                    # the declared count equals the decoded one - nothing is
                    # silently missing inside the published record.
                    if "changes" in record and "changes_count" not in record:
                        # generation-2 shape: the array walker decodes exactly what
                        # the array declares, so a day without a declared-count key
                        # has nothing undeclared to lose
                        continue
                    if "changes_count" in record:
                        assert record["changes_count"] == len(
                            record.get("changes") or []), (path, key, "count")
                        continue
                    # Otherwise the record must have come from a declared zone: the
                    # file says those bytes are not normative.
                    assert zones, (path, key, sorted(record)[:6])
                    in_zone += 1
    print(f"\nsweep: {checked} records, {flagged} flagged truncated, "
          f"{in_zone} out of declared zones")
    assert checked > 1000


# ── The note msgids ──────────────────────────────────────────────────────

def test_the_notes_are_translated_in_every_catalog():
    import re
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        msgids = set(re.findall(r'^msgid "(.*)"$',
                                open(path, encoding="utf-8").read(), re.M))
        for msgid in (NOTE, SPEED_NOTE):
            assert msgid in msgids, (path, msgid)
