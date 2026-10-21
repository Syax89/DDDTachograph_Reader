import pytest

pytest.importorskip("tkinter")

import tkinter as tk

from app.gui import ACTIVITY_COLORS, ActivityTimelineChart


@pytest.fixture(autouse=True)
def _skip_if_no_display():
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("no display available")


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
        # Slot 1 has no 00:00 entry, so the hours before 06:00 are UNKNOWN
        # (Annex 1C §2.170, see
        # test_gui_activity_chart_matches_dashboard.py); Slot 2 starts at 00:00.
        assert blocks["Slot 1"] == [(0, 21600, "UNKNOWN"),
                                    (21600, 57600, "DRIVE"),
                                    (57600, 86400, "REST")]
        assert len(blocks["Slot 2"]) == 3

    def test_unknown_activity_is_bucketed_not_dropped(self):
        """An unrecognised label keeps its minutes as UNKNOWN (no hole in the
        day), exactly as the dashboard's totals bucket it."""
        changes = [{"activity": "XYZ", "time": "03:00", "slot": "First"}]
        blocks = ActivityTimelineChart._build_blocks(changes, is_vu=False)
        assert blocks["Cardholder"] == [(0, 10800, "UNKNOWN"),
                                        (10800, 86400, "UNKNOWN")]

    def test_unusable_time_is_dropped_not_drawn_at_a_bogus_offset(self):
        """The GUI timeline must reject out-of-range times, not draw them.

        ``ActivityTimelineChart._parse_time`` delegates to the shared
        ``core.utils.activity_stats.parse_time``; re-inlining the old unguarded
        copy would admit ``'25:00'`` and place a block at 90000 s.
        """
        dropped = ActivityTimelineChart._build_blocks(
            [{"activity": "DRIVE", "time": "25:00", "slot": "First"}], is_vu=False)
        assert dropped == {"Cardholder": []}   # no block at a fabricated offset

        mixed = ActivityTimelineChart._build_blocks([
            {"activity": "DRIVE", "time": "25:00", "slot": "First"},  # unusable -> dropped
            {"activity": "WORK",  "time": "08:00", "slot": "First"},
            {"activity": "REST",  "time": "12:00", "slot": "First"},
        ], is_vu=False)
        # Nothing is drawn at the fabricated offset; the hours before the first
        # usable entry are UNKNOWN, not silently missing (Annex 1C §2.170).
        assert mixed == {"Cardholder": [(0, 28800, "UNKNOWN"),
                                        (28800, 43200, "WORK"),
                                        (43200, 86400, "REST")]}

    @pytest.mark.parametrize("bad", ["25:00", "08:75", "24:01", "-1:00", "12:-5",
                                     "abc", "", "8:00:00", "08"])
    def test_parse_time_rejects_unusable_values(self, bad):
        """The GUI entry point must reject the same values as the shared
        engine's range guard (one implementation, not a re-inlined copy)."""
        assert ActivityTimelineChart._parse_time(bad) is None

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


class TestActivityTimelinePaintsUnknownTime:
    """The UNKNOWN minutes the segmentation produces must reach the canvas.

    ``_build_blocks`` bucketed a card-not-inserted period, an unrecognised
    activity code and a missing 00:00 status entry as UNKNOWN — the dashboard
    reports those minutes — but ``_draw`` iterated a fixed
    ``["DRIVE", "WORK", "REST", "AVAILABLE"]`` and painted nothing for them, so a
    day that is half unknown showed an empty timeline while the dashboard showed
    ``UNKNOWN``. The chart paints them in the neutral unknown colour now, on a
    row of their own (only when the day has any).
    """

    @staticmethod
    def _render(changes, is_vu=False):
        root = tk.Tk()
        root.geometry("900x600")
        chart = ActivityTimelineChart(root)
        chart.pack(fill="both", expand=True)
        chart.show("2025-01-01", is_vu=is_vu, activities=changes)
        root.update()                      # let the idle draw run
        return root, chart

    @staticmethod
    def _rectangles(chart):
        canvas = chart.canvas
        return [(canvas.itemcget(item, "fill"), canvas.coords(item))
                for item in canvas.find_all()
                if canvas.type(item) == "rectangle"]

    @staticmethod
    def _texts(chart):
        canvas = chart.canvas
        return [canvas.itemcget(item, "text") for item in canvas.find_all()
                if canvas.type(item) == "text"]

    def test_a_card_absent_period_is_drawn_in_the_unknown_colour(self):
        from app.theme import ACTIVITY_UNKNOWN

        root, chart = self._render([
            {"activity": "REST", "time": "00:00", "slot": "First",
             "card_inserted": False, "crew": False},          # 14 h UNKNOWN
            {"activity": "DRIVE", "time": "14:00", "slot": "First",
             "card_inserted": True, "crew": False},
        ])
        try:
            rows = {row[0]: row[3] for row in chart._layout["act_rows"]}
            assert rows["UNKNOWN"] == [(0, 50400)]
            assert rows["DRIVE"] == [(50400, 86400)]

            rects = self._rectangles(chart)
            unknown_rects = [coords for fill, coords in rects
                             if fill == ACTIVITY_UNKNOWN]
            # One painted band per UNKNOWN block, spanning the plot area from
            # 00:00 to 14:00 — the minutes the dashboard reports as UNKNOWN.
            assert len(unknown_rects) == 1
            x0, _y0, x1, _y1 = unknown_rects[0]
            assert x1 > x0
            drive_rects = [coords for fill, coords in rects
                           if fill == ACTIVITY_COLORS["DRIVE"]]
            assert len(drive_rects) == 1
            assert (x1 - x0) / (drive_rects[0][2] - drive_rects[0][0]) == pytest.approx(
                50400 / 36000, rel=0.02)
        finally:
            root.destroy()

    def test_the_unknown_row_is_labelled_and_totalled(self):
        root, chart = self._render([
            {"activity": "REST", "time": "00:00", "slot": "First",
             "card_inserted": False, "crew": False},
            {"activity": "DRIVE", "time": "14:00", "slot": "First",
             "card_inserted": True, "crew": False},
        ])
        try:
            from app.gui import _act_label
            texts = self._texts(chart)
            assert _act_label("UNKNOWN") in texts
            assert any("14h 00m" in text for text in texts)
        finally:
            root.destroy()

    def test_a_fully_known_day_keeps_the_four_rows(self):
        """No unknown minute → the chart looks exactly as it did before."""
        root, chart = self._render([
            {"activity": "DRIVE", "time": "00:00", "slot": "First",
             "card_inserted": True, "crew": False},
            {"activity": "REST", "time": "12:00", "slot": "First",
             "card_inserted": True, "crew": False},
        ])
        try:
            assert [row[0] for row in chart._layout["act_rows"]] == [
                "DRIVE", "WORK", "REST", "AVAILABLE"]
            from app.theme import ACTIVITY_UNKNOWN
            assert ACTIVITY_UNKNOWN not in [fill for fill, _ in self._rectangles(chart)]
        finally:
            root.destroy()
