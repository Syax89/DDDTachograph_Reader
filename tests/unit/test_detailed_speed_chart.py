import struct
import types

import pytest

from app.gui import detailed_speed_blocks_by_day, detailed_speed_by_day
from core.decoders.vu_g1 import _parse_trep_04_speed


def test_detailed_speed_groups_samples_by_utc_day_and_keeps_gaps():
    data = {
        "speed_blocks": [{
            "begin": "2025-06-30T23:59:59+00:00",
            "_chart_speeds_kmh": [88, None, 95],
        }, {
            "timestamp": "2025-07-01T00:00:03+00:00",
            "speeds_kmh": [0xFF, 62],
        }],
    }

    assert detailed_speed_by_day(data) == {
        "2025-06-30": [(86399, 88)],
        "2025-07-01": [(1, 95), (4, 62)],
    }


def test_g1_speed_parser_retains_all_samples_for_chart_data():
    timestamp = 1751277540
    first = struct.pack(">I", timestamp) + bytes([40, 0xFF]) + bytes([41] * 58)
    second = struct.pack(">I", timestamp + 60) + bytes([42] * 60)
    results = {}

    _parse_trep_04_speed(struct.pack(">H", 2) + first + second, results)

    block = results["speed_blocks"][0]
    assert block["minutes"] == 2
    assert len(block["_chart_speeds_kmh"]) == 120
    assert block["_chart_speeds_kmh"][:3] == [40, None, 41]
    assert block["_chart_speeds_kmh"][-1] == 42


def test_detailed_speed_raw_blocks_are_available_for_each_utc_day():
    block = {
        "begin": "2025-06-30T23:59:59+00:00",
        "_chart_speeds_kmh": [88, 91],
    }

    assert detailed_speed_blocks_by_day([block]) == {
        "2025-06-30": [block],
        "2025-07-01": [block],
    }


# ── the plot as a signal: envelope + mean series and the default view ──────
#
# The plot used to draw one vertical min–max line per screen column plus a thin
# polyline through the column means; at one sample per second the lines merged
# into a solid wall. The column aggregation now feeds a filled min–max envelope
# and a mean line. Its geometry is built by two pure helpers, so what these
# tests pin down is arithmetic — columns, runs, min/max/mean, view bounds — not
# "it looks better".

from app.gui import (  # noqa: E402
    DetailedSpeedChart, SpeedBin, default_speed_view, envelope_fill_pieces,
    speed_envelope_runs)

#: A day-wide window with one screen column per 100 s, so a sample's column is
#: its second divided by 100 — arithmetic a reader can check by hand.
COLUMNS = 864
DAY_SPAN = 86400

DAY = "01/05/2025"


def test_envelope_series_keeps_min_max_and_mean_per_column():
    runs = speed_envelope_runs([(100, 50), (101, 95), (199, 90), (150, 70)],
                               0, DAY_SPAN, COLUMNS, 90)

    assert runs == [[SpeedBin(column=1, low=50, high=95, mean=76.25,
                              over_limit=True)]]


def test_envelope_series_flags_only_the_columns_above_the_limit():
    """90 km/h is a maximum, not an overspeed: only 91 flags the column red."""
    runs = speed_envelope_runs([(0, 89), (200, 90), (400, 91)],
                               0, DAY_SPAN, COLUMNS, 90)

    assert [entry.column for run in runs for entry in run] == [0, 2, 4]
    assert [entry.over_limit for run in runs for entry in run] == [False, False, True]


def test_envelope_series_breaks_at_a_gap_instead_of_interpolating():
    """Two samples 5 000 s apart stay two one-column runs: the hole is a hole.

    With 864 s per column the samples land in columns 0 and 5, so columns 1–4
    must not exist at all — nothing is invented to bridge the recording gap.
    """
    runs = speed_envelope_runs([(0, 50), (5000, 60)], 0, DAY_SPAN, 100, 90)

    assert [[entry.column for entry in run] for run in runs] == [[0], [5]]
    assert [[entry.mean for entry in run] for run in runs] == [[50.0], [60.0]]


def test_envelope_series_splits_only_on_non_adjacent_columns():
    """Adjacent columns stay one run; one empty column between them starts a new one."""
    runs = speed_envelope_runs([(0, 10), (100, 20), (300, 30)],
                               0, DAY_SPAN, COLUMNS, 90)

    assert [[entry.column for entry in run] for run in runs] == [[0, 1], [3]]


def test_envelope_series_drops_samples_outside_the_window():
    """The view window is authoritative: 50 s per column, columns 0–4 only."""
    runs = speed_envelope_runs([(200, 55), (300, 60), (470, 70), (500, 80)],
                               250, 250, 5, 90)

    assert [[entry.column for entry in run] for run in runs] == [[1], [4]]
    assert [[entry.mean for entry in run] for run in runs] == [[60.0], [70.0]]


def test_fill_pieces_split_where_neighbouring_bands_stop_overlapping():
    """A polygon whose two edges cross is not filled at all by Tk's even-odd rule."""
    jump = [SpeedBin(column=0, low=60, high=65, mean=62.0, over_limit=False),
            SpeedBin(column=1, low=0, high=5, mean=2.0, over_limit=False)]
    assert [[entry.column for entry in piece] for piece in envelope_fill_pieces(jump)] \
        == [[0], [1]]

    smooth = [SpeedBin(column=0, low=60, high=65, mean=62.0, over_limit=False),
              SpeedBin(column=1, low=62, high=68, mean=65.0, over_limit=False)]
    assert [[entry.column for entry in piece] for piece in envelope_fill_pieces(smooth)] \
        == [[0, 1]]


def test_default_view_frames_the_recorded_span_with_five_percent_padding():
    """A 07:00–17:00 day gets 30 min of air on each side, not 24 h of nothing."""
    start, end = default_speed_view([25200, 61200])

    assert (start, end) == (23400.0, 63000.0)
    assert 25200 - start == pytest.approx(0.05 * (61200 - 25200))
    assert end - 61200 == pytest.approx(0.05 * (61200 - 25200))


def test_default_view_keeps_the_whole_day_when_the_samples_cover_it():
    start, end = default_speed_view(range(0, 86400))

    assert (start, end) == (0.0, 86400.0)


def test_default_view_gives_one_lone_sample_a_fifteen_minute_window():
    start, end = default_speed_view([50000])

    assert (start, end) == (49550.0, 50450.0)
    assert end - start == 900


def test_default_view_is_clamped_to_the_day_and_never_narrower_than_15_minutes():
    assert default_speed_view([100, 200]) == (0.0, 900.0)      # pinned at 00:00
    assert default_speed_view([86200, 86300]) == (85500.0, 86400.0)  # at 24:00
    assert default_speed_view([]) == (0.0, 86400.0)


@pytest.mark.parametrize("ceiling,height,step", [
    (100, 555, 20),   # a normal plot: a gridline every 20 km/h
    (260, 555, 20),
    (100, 120, 25),   # too short for five lines: 25 km/h instead
    (100, 60, 50),    # only three lines fit at all
])
def test_grid_step_stays_readable_for_the_plot_height(ceiling, height, step):
    assert DetailedSpeedChart._grid_step(ceiling, height) == step


# ── the same geometry, as drawn on a canvas ───────────────────────────────

@pytest.fixture
def root():
    """A real Tk root, or a clean skip when there is no display."""
    tkinter = pytest.importorskip("tkinter")
    try:
        window = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display available")
    try:
        yield window
    finally:
        for after_id in window.tk.call("after", "info"):
            try:
                window.tk.call("after", "cancel", after_id)
            except tkinter.TclError:
                pass
        window.destroy()


def _dense_day(gap=True, speed=lambda second: 60 + second % 6):
    """2 h of 1 Hz samples, optionally with a 10-minute hole at 07:00.

    The default profile ripples over 6 km/h, so every column's min–max band
    overlaps its neighbour's: the envelope fills as one piece per run.
    """
    samples = []
    for second in range(6 * 3600, 8 * 3600):
        if gap and 7 * 3600 <= second < 7 * 3600 + 600:
            continue
        samples.append((second, speed(second)))
    return samples


def _drawn(root, samples, speed_limit=None):
    # A fixed window: the plot's width and height set the column width and the
    # gridline step, so letting them follow the display scale made the exact
    # counts below depend on the machine.
    root.geometry("1100x760")
    chart = DetailedSpeedChart(root)
    chart.pack(fill="both", expand=True)
    root.update()
    chart.show(DAY, samples, speed_limit=speed_limit)
    root.update_idletasks()
    chart._draw()
    return chart


def _y_for(chart, speed):
    """The chart's own speed→y mapping, read back from the drawn scale."""
    bottom, ceiling, plot_height = chart._y_scale
    return bottom - speed * plot_height / ceiling


def test_the_plot_opens_on_the_samples_not_on_the_whole_day(root):
    samples = _dense_day()

    chart = _drawn(root, samples)

    assert (chart._view_start, chart._view_end) == default_speed_view(
        [second for second, _speed in samples])


def test_zooming_out_from_the_default_view_still_reaches_the_whole_day(root):
    chart = _drawn(root, _dense_day())

    for _ in range(8):
        chart._zoom_out()

    assert (chart._view_start, chart._view_end) == (0, 86400)


def test_one_filled_envelope_per_run_and_a_hole_between_them(root):
    """A 10-minute gap splits the fill instead of being bridged by it."""
    chart = _drawn(root, _dense_day())
    canvas = chart.canvas
    left, _right, top, bottom, plot_width, _start, _end = chart._plot

    envelopes = canvas.find_withtag("speed_envelope")
    assert len(envelopes) == len(chart._series) == 2
    spans = []
    for item in envelopes:
        coords = [float(value) for value in canvas.coords(item)]
        xs, ys = coords[0::2], coords[1::2]
        assert min(xs) >= left and max(xs) <= left + plot_width
        assert min(ys) >= top and max(ys) <= bottom
        spans.append((min(xs), max(xs)))

    # The two fills are the two runs, and the hole between them is wide: the
    # gap is 600 s of a 7 920 s window.
    assert spans[0][1] < spans[1][0]
    assert spans[1][0] - spans[0][1] > 0.5 * 600 / (chart._view_end - chart._view_start) * plot_width


def test_a_steep_jump_is_filled_as_two_polygons(root):
    """Bands that do not overlap must not share one polygon (Tk cancels it).

    A step from 10 km/h to 100 km/h jumps further than a column is tall, so a
    run must be cut into simple polygons that touch. Whether the step lands on
    a column edge (two pieces) or inside one column (whose band then overlaps
    both neighbours, so one piece is correct) depends on the plot's width, i.e.
    on the display scale and font: the test therefore moves the step across
    successive offsets until one cuts, checks the piece count against the bins actually drawn,
    and requires that at least one offset really produced a cut.
    """
    cut_seen = False
    for offset in range(120):          # a column is far fewer than 120 s wide
        step = 7 * 3600 + offset
        samples = _dense_day(gap=False,
                             speed=lambda second, step=step: 10 if second < step else 100)

        chart = _drawn(root, samples)

        run = chart._series[0]
        pieces = envelope_fill_pieces(run)
        assert len(chart._series) == 1                  # no hole: one run
        cuts = sum(1 for a, b in zip(run, run[1:], strict=False)
                   if min(a.high, b.high) < max(a.low, b.low))
        assert len(pieces) == cuts + 1
        for left, right in zip(pieces, pieces[1:], strict=False):
            assert left[-1].column + 1 == right[0].column   # touching at the jump
        assert len(chart.canvas.find_withtag("speed_envelope")) == len(pieces)
        cut_seen = cut_seen or len(pieces) > 1
        chart.destroy()
        if cut_seen and offset >= 3:
            break
    assert cut_seen, "no offset put the step on a column edge: the cut is untested"


def test_envelope_fill_pieces_cuts_only_where_the_bands_stop_overlapping():
    """The rule itself, with no chart and no display scale involved."""
    def bin_(column, low, high):
        return SpeedBin(column=column, low=low, high=high,
                        mean=(low + high) / 2, over_limit=False)

    flat = [bin_(0, 10, 12), bin_(1, 11, 13), bin_(2, 12, 14)]
    assert [len(p) for p in envelope_fill_pieces(flat)] == [3]
    jump = [bin_(0, 10, 10), bin_(1, 10, 10), bin_(2, 100, 100), bin_(3, 99, 100)]
    pieces = envelope_fill_pieces(jump)
    assert [len(p) for p in pieces] == [2, 2]
    assert pieces[0][-1].column + 1 == pieces[1][0].column
    straddling = [bin_(0, 10, 10), bin_(1, 10, 100), bin_(2, 100, 100)]
    assert [len(p) for p in envelope_fill_pieces(straddling)] == [3]


def test_the_envelope_spans_the_column_min_and_max(root):
    chart = _drawn(root, _dense_day())
    canvas = chart.canvas
    first_run = chart._series[0]

    coords = [float(value) for value in canvas.coords(
        canvas.find_withtag("speed_envelope")[0])]
    ys = coords[1::2]

    assert min(ys) == pytest.approx(_y_for(chart, max(entry.high for entry in first_run)))
    assert max(ys) == pytest.approx(_y_for(chart, min(entry.low for entry in first_run)))


def test_the_mean_is_a_two_pixel_line_inside_the_envelope(root):
    chart = _drawn(root, _dense_day())
    canvas = chart.canvas
    left, _right, _top, _bottom, plot_width, _start, _end = chart._plot
    low = min(entry.low for run in chart._series for entry in run)
    high = max(entry.high for run in chart._series for entry in run)

    lines = canvas.find_withtag("speed_mean")
    assert lines
    for item in lines:
        assert canvas.type(item) == "line"
        assert float(canvas.itemcget(item, "width")) == 2
        assert canvas.itemcget(item, "fill") == "#1565c0"  # ACCENT: not over the limit
        xs = [float(value) for value in canvas.coords(item)][0::2]
        ys = [float(value) for value in canvas.coords(item)][1::2]
        assert left <= min(xs) and max(xs) <= left + plot_width
        # Every mean is a recorded speed, so it lies inside its run's band.
        assert min(ys) >= _y_for(chart, high) - 1
        assert max(ys) <= _y_for(chart, low) + 1


def test_the_parts_above_the_limit_stay_red(root):
    """Half the day runs at 100 km/h: only that half's fill and line are red."""
    samples = _dense_day(speed=lambda second: 50 if second < 7 * 3600 else 100)

    chart = _drawn(root, samples, speed_limit=90)
    canvas = chart.canvas

    over = canvas.find_withtag("speed_over_limit")
    assert len(over) == 1
    ys = [float(value) for value in canvas.coords(over[0])][1::2]
    assert max(ys) <= _y_for(chart, 90) + 1        # never below the limit line
    assert min(ys) == pytest.approx(_y_for(chart, 100))
    # ...and the mean line follows the same split: one blue and one red item.
    fills = {canvas.itemcget(item, "fill") for item in canvas.find_withtag("speed_mean")}
    assert fills == {"#1565c0", "#c62828"}          # ACCENT / DANGER


def test_a_day_under_the_limit_has_no_red_overlay(root):
    chart = _drawn(root, _dense_day(), speed_limit=90)

    assert not chart.canvas.find_withtag("speed_over_limit")
    fills = {chart.canvas.itemcget(item, "fill")
             for item in chart.canvas.find_withtag("speed_mean")}
    assert fills == {"#1565c0"}


def test_the_limit_line_is_drawn_above_the_trace(root):
    """The envelope fill would otherwise bury the dashed red limit line."""
    chart = _drawn(root, _dense_day(), speed_limit=90)
    canvas = chart.canvas
    items = canvas.find_all()

    limit_lines = list(canvas.find_withtag("speed_limit_line"))
    assert all(canvas.type(item) == "line" for item in limit_lines)
    assert canvas.itemcget(limit_lines[0], "fill") == "#d32f2f"
    assert canvas.itemcget(limit_lines[0], "dash")
    assert len(limit_lines) == 1
    trace = canvas.find_withtag("speed_envelope")
    assert items.index(limit_lines[0]) > max(items.index(item) for item in trace)


def test_horizontal_gridlines_are_labelled_and_sit_behind_the_trace(root):
    chart = _drawn(root, _dense_day())
    canvas = chart.canvas
    items = canvas.find_all()
    labels = {canvas.itemcget(item, "text"): canvas.itemcget(item, "fill")
              for item in items if canvas.type(item) == "text"}

    assert labels["20"] == "#536273" and labels["40"] == "#536273"   # TEXT_MUTED
    assert labels["0"] == "#d9e1ea" and labels["100"] == "#d9e1ea"   # CHART_GRID_MAJOR
    assert labels["90 km/h"] == "#d32f2f"                            # DANGER_STRONG
    horizontal = [item for item in items
                  if canvas.type(item) == "line"
                  and canvas.itemcget(item, "fill") == "#edf1f5"
                  and canvas.coords(item)[1] == canvas.coords(item)[3]]
    # 20 / 40 / 60 / 80 km/h: the ceiling is 100, so four interior gridlines.
    assert len(horizontal) == 4
    assert max(items.index(item) for item in horizontal) < min(
        items.index(item) for item in canvas.find_withtag("speed_envelope"))


def test_hover_still_reports_the_sample_under_the_cursor(root):
    chart = _drawn(root, _dense_day())
    left, _right, _top, _bottom, plot_width, view_start, view_end = chart._plot
    second, speed = 6 * 3600 + 100, 60 + (6 * 3600 + 100) % 6
    x = left + (second - view_start) * plot_width / (view_end - view_start)

    chart._show_hover(types.SimpleNamespace(x=x, y=chart._plot[2] + 20))

    texts = [chart.canvas.itemcget(item, "text")
             for item in chart.canvas.find_withtag("speed_hover")
             if chart.canvas.type(item) == "text"]
    assert texts == [f"06:01:40 UTC  |  {speed} km/h"]


def test_the_mean_line_is_red_only_where_it_is_above_the_limit(root):
    """A segment crossing the limit is cut at the crossing, not painted whole.

    Colouring the whole segment red after an overspeed spike drew a red
    diagonal down to 50 km/h, which read as "50 km/h is over the limit".
    """
    # 40 min at 60 km/h, one minute at 100 km/h in the middle: the spike's
    # mean line climbs from below the limit and falls back below it.
    samples = [(second, 100 if 6 * 3600 + 1800 <= second < 6 * 3600 + 1860
                else 60) for second in range(6 * 3600, 7 * 3600)]
    chart = _drawn(root, samples, speed_limit=90)
    canvas = chart.canvas
    limit_y = None
    for item in canvas.find_withtag("speed_limit_line"):
        limit_y = canvas.coords(item)[1]
    assert limit_y is not None

    red_segments = [canvas.coords(item) for item in canvas.find_withtag("speed_mean")
                    if canvas.itemcget(item, "fill") == "#c62828"]
    assert red_segments, "the over-limit stretch must still be marked red"
    for coords in red_segments:
        for y in coords[1::2]:
            assert y <= limit_y + 1, (
                f"a red mean segment reaches below the limit line: y={y} > {limit_y}")


def test_internal_gaps_count_holes_not_the_sampling_interval(root):
    """Seconds between ordinary samples are the sampling rate, not a gap."""
    # 1 Hz for ten minutes, then a real 10-minute hole, then 1 Hz again.
    samples = ([(second, 50) for second in range(6 * 3600, 6 * 3600 + 600)]
               + [(second, 50) for second in range(6 * 3600 + 1200,
                                                6 * 3600 + 1800)])
    chart = DetailedSpeedChart(root)
    chart.pack(fill="both", expand=True)
    root.update()
    chart.show(DAY, samples)
    root.update_idletasks()

    assert chart.summary_lbl.cget("text") == "1,200 s recorded | 10 min internal gaps"
