"""A single-byte flood must cost linear time and memory, not hundreds of MB per MB.

The structural walk used to append one interval per byte (``mark_classified`` on every
unrecognised byte), so a 1 MB file of 0x76 grew the tracker to ~600 MB and the sweeps
then walked it all. Two adjacent intervals of the same label are one interval, and a
hard cap freezes the list for pathological inputs (the file is then partial with a
declared finding, never silently short of coverage).
"""

from core.parser.deterministic import CoverageTracker


def test_adjacent_ranges_of_one_label_coalesce():
    tracker = CoverageTracker(4096)
    for pos in range(1024):
        tracker.mark_unknown(pos, pos + 1, b"\x76")
    assert len(tracker.unknown_ranges) == 1
    assert len(tracker.classification_ranges) == 1
    assert tracker.classification_ranges[0][:2] == (0, 1024)
    assert tracker.classifications["Unknown"] == 1024


def test_separated_ranges_stay_separate():
    tracker = CoverageTracker(4096)
    tracker.mark_classified(0, 4, "Tag_0001")
    tracker.mark_classified(4, 8, "Tag_0002")
    tracker.mark_classified(8, 12, "Tag_0001")
    assert [c for _, _, c in tracker.classification_ranges] == [
        "Tag_0001", "Tag_0002", "Tag_0001"]


def test_the_cap_is_declared_and_makes_the_file_partial(monkeypatch, tmp_path):
    """A small injected cap: the walk stops recording and says so."""
    import core.parser.deterministic as det
    monkeypatch.setattr(det, "MAX_COVERAGE_RANGES", 3)
    # Alternating tags keep the intervals separate so the cap is reached quickly.
    body = b"".join(b"\x01\x02\x00\x00" for _ in range(20))
    path = tmp_path / "flood.ddd"
    path.write_bytes(b"\x76\x0d" + body + b"\x00" * 16)
    parser = det.DeterministicParser()
    result = parser.parse(path.read_bytes(), is_vu=False)
    codes = [f.get("code") for f in result.get("integrity_findings") or []]
    assert "COVERAGE_RANGE_CAP" in codes
    assert result.get("is_partial") is True


def test_a_recognised_file_reaches_no_cap():
    tracker = CoverageTracker(1024)
    tracker.mark_classified(0, 128, "Tag_0501")
    tracker.mark_classified(128, 256, "Tag_0501")
    assert tracker.range_cap_hit is False
    assert len(tracker.classification_ranges) == 1
