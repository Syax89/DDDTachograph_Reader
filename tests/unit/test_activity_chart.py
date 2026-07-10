import pytest

pytest.importorskip("tkinter")

from app.gui import ActivityTimelineChart


class TestActivityTimelineChart:
    """Unit tests for ActivityTimelineChart block building and rendering."""

    def test_single_slot_continuous_blocks(self):
        changes = [
            {"activity": "DRIVE", "time": "00:00", "slot": "First", "crew": False},
            {"activity": "WORK", "time": "04:30", "slot": "First", "crew": False},
            {"activity": "REST", "time": "05:45", "slot": "First", "crew": False},
        ]
        blocks = ActivityTimelineChart._build_blocks(changes, is_vu=False)
        assert list(blocks.keys()) == ["Cardholder"]
        card_blocks = blocks["Cardholder"]
        assert len(card_blocks) == 3
        assert card_blocks[0] == (0, 16200, "DRIVE")           # 00:00 → 4h30m
        assert card_blocks[1] == (16200, 20700, "WORK")         # 04:30 → 5h45m
        assert card_blocks[2] == (20700, 86400, "REST")         # 05:45 → 24:00

    def test_driver_card_hides_slot_label(self):
        changes = [{"activity": "DRIVE", "time": "08:00", "slot": "First"}]
        blocks = ActivityTimelineChart._build_blocks(changes, is_vu=False)
        assert "Cardholder" in blocks
        assert "Slot 1" not in blocks
        assert "Slot 2" not in blocks

    def test_vu_shows_two_separate_slots(self):
        changes = [
            {"activity": "DRIVE", "time": "06:00", "slot": "First"},
            {"activity": "REST",  "time": "16:00", "slot": "First"},
            {"activity": "REST",  "time": "00:00", "slot": "Second"},
            {"activity": "DRIVE", "time": "10:00", "slot": "Second"},
            {"activity": "REST",  "time": "14:00", "slot": "Second"},
        ]
        blocks = ActivityTimelineChart._build_blocks(changes, is_vu=True)
        assert set(blocks.keys()) == {"Slot 1", "Slot 2"}
        assert len(blocks["Slot 1"]) == 2
        assert len(blocks["Slot 2"]) == 3

    def test_unknown_activity_is_skipped(self):
        changes = [{"activity": "XYZ", "time": "03:00", "slot": "First"}]
        blocks = ActivityTimelineChart._build_blocks(changes, is_vu=False)
        assert blocks["Cardholder"] == []

    def test_parse_time_handles_midnight_and_invalid(self):
        assert ActivityTimelineChart._parse_time("00:00") == 0
        assert ActivityTimelineChart._parse_time("23:59") == 86340
        assert ActivityTimelineChart._parse_time("24:00") == 86400
        assert ActivityTimelineChart._parse_time("abc") is None
        assert ActivityTimelineChart._parse_time("") is None

    def test_show_does_not_crash_with_empty_changes(self):
        chart = ActivityTimelineChart(None)
        chart.show("2025-01-01", is_vu=False, activities=[])
        assert chart._slots == {}
