"""The scoped heuristic may not invent records (review findings C-4).

The scan runs on the bytes of a unit the normative decoder could not read. It
must never publish a candidate the normative handler would reject, and never a
second copy of a record already published:

* a ``0x76 <TREP>`` pair inside another message's payload is data, not a
  boundary (a phantom day of activities with no changes, found inside sensor
  data of a real download);
* a scan that starts a few bytes off re-reads a published message with garbled
  details (the same driver twice, the second time with a shifted card number).

Sources: core/parser/heuristic_zone.py; the owner rule "no record may be
published twice or invented"; commits 89cae20 / 6fc30e4 / adaad34.
"""

import tempfile
from pathlib import Path

import pytest

from app.engine import TachoParser
from core.parser.heuristic_zone import _identity, _is_empty_day, prune_candidates
from core.registry.registry import DecoderRegistry
from tests.unit.real_data import require_real_file

COUNTS = ("activities", "inserted_drivers", "events", "faults", "places",
          "card_iw_records", "calibrations", "specific_conditions")


def _parse(value):
    raw = Path(value).read_bytes() if isinstance(value, (str, Path)) else value
    path = Path(tempfile.mkdtemp()) / "probe.ddd"
    path.write_bytes(raw)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


# ── the gate itself ──────────────────────────────────────────────────────

def test_an_empty_day_added_by_a_scan_is_dropped():
    results = {"activities": []}
    results["activities"].append({"date": "01/07/2003", "changes": [],
                                 "changes_count": 0})
    assert prune_candidates({"activities": 0}, results) == ["activities:0"]
    assert results["activities"] == []


def test_a_rerun_of_a_published_driver_is_dropped():
    results = {"inserted_drivers": [
        {"surname": "AAAA", "firstname": "BBBB", "card_number": "1"},
    ]}
    results["inserted_drivers"].append({"surname": "AAAA", "firstname": "BBBB",
                                       "card_number": "2"})
    dropped = prune_candidates({"inserted_drivers": 1}, results)
    assert dropped == ["inserted_drivers:0"]
    assert len(results["inserted_drivers"]) == 1


def test_a_normative_record_is_never_touched_by_the_gate():
    published = [{"date": "01/07/2003", "changes": [1], "changes_count": 1},
                 {"date": "02/07/2003", "changes": [], "changes_count": 0}]
    results = {"activities": list(published)}
    assert prune_candidates({"activities": 2}, results) == []
    assert results["activities"] == published


def test_the_identity_of_a_record_uses_its_declared_fields():
    assert _identity({"date": "x", "changes": []}, ("date",)) == ("x",)
    assert _identity("not a record", ("date",)) == ()
    assert not _is_empty_day({"date": "x", "changes": [0x11]})
    assert not _is_empty_day({"surname": "A"})


# ── the two real downloads of the findings ───────────────────────────────

def test_a_false_marker_inside_sensor_data_adds_no_activity_day():
    """C-4a: a 76 02 pair inside a TREP 11 payload must not become a day."""
    raw = Path(require_real_file("*95537A1054.ddd")).read_bytes()
    intact = _parse(raw)
    cut = _parse(raw[:14525])
    for key in COUNTS:
        assert len(cut.get(key) or []) <= len(intact.get(key) or []), key
    assert len(cut.get("activities") or []) == len(intact.get("activities") or [])


def test_a_garbled_reread_of_a_driver_is_not_a_second_driver():
    """C-4b: the scan re-read the published message with a shifted card number."""
    raw = Path(require_real_file("*98F20BEDC7.ddd")).read_bytes()
    intact = _parse(raw)
    cut = _parse(raw[:9873])
    seen = {(d.get("surname"), d.get("firstname"), d.get("card_number"))
            for d in intact.get("inserted_drivers") or []}
    for driver in cut.get("inserted_drivers") or []:
        assert (driver.get("surname"), driver.get("firstname"),
                driver.get("card_number")) in seen, driver
    for key in COUNTS:
        assert len(cut.get(key) or []) <= len(intact.get(key) or []), key


# ── truncation sweep over the real downloads ─────────────────────────────

def _real_vu_files():
    from tests.unit.real_data import real_ddd_files
    files = []
    for name in real_ddd_files():
        path = Path(name)
        try:
            head = path.read_bytes()[:4]
        except OSError:                      # pragma: no cover - unreadable file
            continue
        # A plain VU download stream: a 76 06 file is a card image relayed by
        # the unit and goes down the card-envelope path, which has no units.
        if head[:2] not in (b"\x76\x01", b"\x76\x02", b"\x76\x03", b"\x76\x04",
                            b"\x76\x05"):
            continue
        files.append(path)
    return files


@pytest.mark.parametrize("index", range(18))
def test_every_truncation_point_tiles_and_never_invents(index):
    files = _real_vu_files()
    if not files:
        pytest.skip("no private corpus available")
    for path in files:
        raw = path.read_bytes()
        intact = _parse(raw)
        if index < 12:
            cut_at = max(2, len(raw) * (index + 1) // 13)
        else:
            cut_at = 2 + (index - 11) * 10   # inside the first 64 bytes
        cut_at = min(cut_at, len(raw) - 1)
        result = _parse(raw[:cut_at])
        units = result["metadata"].get("vu_units") or []
        spans = sorted((u["offset"], u["offset"] + u["length"]) for u in units)
        assert spans and spans[0][0] == 0, (path.name, cut_at, spans[:2])
        for (_s, end), (next_start, _e) in zip(spans, spans[1:], strict=False):
            assert end == next_start, (path.name, cut_at, end, next_start)
        assert spans[-1][1] == cut_at, (path.name, cut_at, spans[-1])
        for key in COUNTS:
            assert len(result.get(key) or []) <= len(intact.get(key) or []), (
                path.name, cut_at, key)
