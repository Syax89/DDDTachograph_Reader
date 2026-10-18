"""The detailed-speed chart's summary KPI cards and its legend.

The day's key facts used to live in one dense grey line under the plot
("N s recorded | max X km/h | avg … | above 90 km/h | moving | internal gaps")
and the red dots only explained themselves on hover. Now the numbers are KPI
cards in the dashboard's card style, the grey line keeps only what the cards
omit (recorded seconds + internal gaps) and a legend explains the red marks.

Everything here is asserted on a real Tk widget (skipped cleanly when no
display is available), like the other GUI tests of this suite.
"""
import pytest

pytest.importorskip("tkinter")

import tkinter as tk  # noqa: E402
from tkinter import font as tkfont  # noqa: E402

import app.theme as theme  # noqa: E402
from app.gui import DetailedSpeedChart  # noqa: E402

DAY = "01/05/2025"

#: 7 200 samples: 60 s at 100 km/h (over the 90 km/h default limit) inside two
#: hours of 50 km/h → max 100, avg 50.4, 1 min above the limit, 120 min moving.
SAMPLES = [(second, 100 if 3600 <= second < 3660 else 50)
           for second in range(0, 7200)]

#: A VU-recorded overspeeding event for that day.
EVENTS = [{"begin": "2025-05-01T01:00:00+00:00",
           "end": "2025-05-01T01:05:00+00:00",
           "max_speed_kmh": 131, "average_speed_kmh": 104,
           "card_driver": {"card_number": "IT12345678901234567890"}}]

#: The same day without a single second above the limit.
SLOW_SAMPLES = [(second, 50) for second in range(0, 7200)]


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        yield window
    finally:
        for after_id in window.tk.call("after", "info"):
            try:
                window.tk.call("after", "cancel", after_id)
            except tk.TclError:
                pass
        window.destroy()


def _chart(root, samples=SAMPLES, events=None, width="660x430"):
    """A chart laid out the way the dashboard lays it out (right pane only)."""
    root.geometry(width)
    chart = DetailedSpeedChart(root)
    chart.pack(fill=tk.BOTH, expand=True)
    root.update()
    chart.show(DAY, samples, overspeeding_events=events)
    root.update()
    return chart


def _value(chart, key):
    return chart.kpi[key]["value"].cget("text")


def _colour(chart, key):
    return chart.kpi[key]["value"].cget("foreground")


def _caption(chart, key):
    return chart.kpi[key]["caption"].cget("text")


# ── the cards ─────────────────────────────────────────────────────────────

def test_cards_carry_the_numbers_the_grey_line_used_to_hold(root):
    chart = _chart(root, events=EVENTS)

    assert list(chart.kpi) == ["max", "avg", "above", "moving", "events"]
    assert _caption(chart, "max") == "Max speed"
    assert _value(chart, "max") == "100 km/h"
    assert _caption(chart, "avg") == "Avg speed"
    assert _value(chart, "avg") == "50.4 km/h"
    assert _caption(chart, "above") == "Time above 90 km/h"
    assert _value(chart, "above") == "1 min"
    assert _caption(chart, "moving") == "Time moving"
    assert _value(chart, "moving") == "120 min"
    assert _caption(chart, "events") == "Overspeed events"
    assert _value(chart, "events") == "1"


def test_the_cards_are_coloured_by_what_they_mean(root):
    """Over the limit and overspeeding are red; the rest is ordinary text."""
    chart = _chart(root, events=EVENTS)

    assert _colour(chart, "above") == theme.DANGER
    assert _colour(chart, "events") == theme.DANGER
    assert _colour(chart, "moving") == theme.TEXT_PRIMARY
    # Max speed is red only when the peak really broke the limit (100 here);
    # blue belongs to the trace, not to a KPI value.
    assert _colour(chart, "max") == theme.DANGER
    assert _colour(chart, "avg") == theme.TEXT_SECONDARY


def test_zero_seconds_above_the_limit_is_not_red(root):
    chart = _chart(root, samples=SLOW_SAMPLES)

    assert _value(chart, "above") == "0 s"
    assert _colour(chart, "above") == theme.TEXT_PRIMARY
    assert "events" not in chart.kpi


def test_the_event_card_only_appears_when_the_day_has_events(root):
    without = _chart(root, events=None)
    assert "events" not in without.kpi

    chart = _chart(root, events=EVENTS)
    assert chart.kpi["events"]["value"].cget("text") == "1"

    two_events = [dict(EVENTS[0]), dict(EVENTS[0], begin="2025-05-01T03:00:00+00:00")]
    chart = _chart(root, events=two_events)
    assert chart.kpi["events"]["value"].cget("text") == "2"


def test_the_hour_limit_in_the_caption_follows_the_authorised_speed(root):
    """The caption is not hard-wired to 90: a calibrated limit shows itself."""
    chart = DetailedSpeedChart(root)
    chart.pack(fill=tk.BOTH, expand=True)
    root.update()
    chart.show(DAY, SAMPLES, speed_limit=80)
    root.update()

    assert _caption(chart, "above") == "Time above 80 km/h"
    assert _value(chart, "above") == "1 min"


def test_the_cards_reuse_the_dashboard_card_style(root):
    """Same frame, same fonts, same caption colour as the dashboard cards."""
    chart = _chart(root, events=EVENTS)

    for key in chart.kpi:
        card = chart.kpi[key]["card"]
        caption = chart.kpi[key]["caption"]
        value = chart.kpi[key]["value"]
        assert card.cget("bg") == theme.SURFACE_RAISED
        assert card.cget("highlightbackground") == theme.CARD_BORDER
        assert int(card.cget("highlightthickness")) == 1
        caption_font = tkfont.Font(font=caption.cget("font")).actual()
        value_font = tkfont.Font(font=value.cget("font")).actual()
        assert caption_font["size"] == theme.FONT_SMALL[1]
        assert caption_font["weight"] == "normal"
        assert caption.cget("fg") == theme.TEXT_LABEL
        assert caption.cget("bg") == theme.SURFACE_RAISED
        assert value_font["size"] == theme.FONT_KPI_VALUE[1]
        assert value_font["weight"] == "bold"
        assert value.cget("bg") == theme.SURFACE_RAISED
    assert chart.kpi_frame.cget("bg") == theme.SURFACE_SUNKEN


# ── the reduced grey summary line ─────────────────────────────────────────

def test_the_summary_line_keeps_only_recorded_seconds_and_gaps(root):
    chart = _chart(root, events=EVENTS)

    summary = chart.summary_lbl.cget("text")
    assert summary == "7,200 s recorded | 0 s internal gaps"
    # What the cards show is no longer repeated under the plot.
    assert "km/h" not in summary
    assert "moving" not in summary


def test_a_day_without_samples_says_so_and_shows_no_cards_or_legend(root):
    chart = _chart(root, samples=[])

    assert chart.summary_lbl.cget("text") == "No valid speed samples"
    assert chart.kpi == {}
    assert chart._legend_labels == []
    assert chart.legend_frame.winfo_children() == []


# ── the legend of the red marks ───────────────────────────────────────────

def _glyph_items(chart):
    """``(type, fill, dash)`` of every glyph drawn in the legend."""
    items = []
    for glyph in chart._legend_glyphs:
        for item in glyph.find_all():
            items.append((glyph.type(item), glyph.itemcget(item, "fill"),
                          glyph.itemcget(item, "dash")))
    return items


def test_the_limit_line_is_always_explained(root):
    chart = _chart(root, events=None)

    assert [label.cget("text") for label in chart._legend_labels] == [
        "Speed Limit", "Speed range"]
    assert _glyph_items(chart) == [("line", theme.DANGER_STRONG, "6 4"),
                                   ("rectangle", theme.ACTIVITY_DRIVE_TINT, "")]


def test_the_event_dot_is_explained_only_when_the_day_has_events(root):
    chart = _chart(root, events=EVENTS)

    assert [label.cget("text") for label in chart._legend_labels] == [
        "Speed Limit", "Speed range", "Overspeeding event (recorded by the unit)"]
    assert _glyph_items(chart) == [
        ("line", theme.DANGER_STRONG, "6 4"),
        ("rectangle", theme.ACTIVITY_DRIVE_TINT, ""),
        ("oval", theme.DANGER_STRONG, ""),
    ]


def test_the_legend_follows_the_language_of_the_ui(root, monkeypatch):
    """The legend is UI chrome: it is translated like every other label."""
    import app.gui as gui

    monkeypatch.setattr(gui, "_", lambda text: f"<{text}>")
    chart = _chart(root, events=EVENTS)

    assert [label.cget("text") for label in chart._legend_labels] == [
        "<Speed Limit>", "<Speed range>",
        "<Overspeeding event (recorded by the unit)>"]
