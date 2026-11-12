"""Detailed-speed chart of the GUI (the per-day speed envelope and its KPI cards).

Moved out of ``app/gui.py`` unchanged; ``app.gui`` re-exports every name, so
``app.gui.DetailedSpeedChart`` and the helpers keep working for callers and
tests. It depends only on the theme, the translation function and Tk.
"""

import tkinter as tk
from app.i18n import _
from app.theme import (
    ACCENT,
    ACTIVITY_DRIVE_TINT,
    BORDER,
    CARD_BORDER,
    CHART_GRID_MAJOR,
    CHART_GRID_MINOR,
    DANGER,
    DANGER_BAND,
    DANGER_STRONG,
    FONT_KPI_VALUE,
    FONT_SMALL,
    FONT_TITLE,
    GAP_BAND,
    SURFACE,
    SURFACE_RAISED,
    SURFACE_SUNKEN,
    TEXT_LABEL,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TOOLTIP_BG,
    TOOLTIP_BORDER,
    TOOLTIP_FG,
    WHITE,
)
from bisect import bisect_left
from datetime import datetime
from tkinter import font as tkfont, ttk
from typing import NamedTuple


SPEED_LIMIT_KMH = 90


def _fmt_seconds_duration(seconds):
    """Render a whole-second count as a duration without truncating a
    non-zero value to "0 min" (GUI-SPEED-ROUNDING, G-F5).  Values under a
    minute are shown in seconds; longer ones keep minutes and drop the
    residual seconds only when they are exactly zero."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} min {rest} s" if rest else f"{minutes} min"


#: Card geometry, shared by the dashboard cards and the speed chart's row so
#: the two panels are built from the same numbers (see :func:`_kpi_card`).
_KPI_CARD_PADX = 14


_KPI_CARD_PADY = 10


_KPI_CARD_BORDER = 1


_KPI_GRID_PAD = 5


#: Slack added to every measured row item: Tk's own requested width can differ
#: from the font measurement by a pixel or two, and a row must never be packed
#: so tightly that the grid has to squeeze it.
_KPI_WIDTH_SLACK = 4


#: Width of the small legend glyphs (the dot and the dashed line sample).
_LEGEND_GLYPH_WIDTH = 18


def _flow_rows(widths, available):
    """Pack ``widths`` into as few rows as ``available`` pixels allow.

    Returns a list of rows, each a list of indexes into ``widths``. Used by the
    speed chart's KPI cards and legend so a narrow window (or a long
    translation) adds a *row* instead of clipping a label.
    """
    rows = []
    current = []
    used = 0
    for index, width in enumerate(widths):
        if current and used + width > available:
            rows.append(current)
            current, used = [], 0
        current.append(index)
        used += width
    if current:
        rows.append(current)
    return rows


def _kpi_card(parent, caption, value, colour):
    """Build one dashboard-style KPI card: raised frame, caption, bold value.

    Shared by the daily-activities dashboard grid and the detailed-speed
    summary row, so both panels are built — and look — exactly the same. The
    caller positions the returned frame and owns the returned labels.
    """
    card = tk.Frame(parent, bg=SURFACE_RAISED,
                    highlightbackground=CARD_BORDER,
                    highlightthickness=_KPI_CARD_BORDER,
                    padx=_KPI_CARD_PADX, pady=_KPI_CARD_PADY)
    caption_lbl = tk.Label(card, text=caption, font=FONT_SMALL, fg=TEXT_LABEL,
                           bg=SURFACE_RAISED, anchor=tk.W)
    caption_lbl.pack(anchor=tk.W)
    value_lbl = tk.Label(card, text=value, font=FONT_KPI_VALUE, fg=colour,
                         bg=SURFACE_RAISED, anchor=tk.W)
    value_lbl.pack(anchor=tk.W)
    return card, caption_lbl, value_lbl


# ── Detailed-speed series (pure geometry, no Tk) ───────────────────────
#: Seconds in a UTC day, and the narrowest window the speed plot opens on
#: (15 minutes): one isolated sample still gets a readable neighbourhood.
SPEED_DAY_SECONDS = 86400


SPEED_MIN_VIEW_SECONDS = 900


#: Shortest hole in the recording the plot marks with a band (two minutes):
#: at the zoom the plot opens on, a shorter hole is a few pixels wide and the
#: bands became vertical slivers that read as noise.
SPEED_GAP_SECONDS = 120


class SpeedBin(NamedTuple):
    """One screen column of the detailed-speed trace.

    ``column`` is the pixel column inside the plot (0 at its left edge),
    ``low``/``high`` the slowest and fastest sample that landed in it, ``mean``
    their arithmetic mean and ``over_limit`` whether any of them is above the
    speed limit — i.e. whether the column is drawn in the red DANGER colour.
    """

    column: int
    low: int
    high: int
    mean: float
    over_limit: bool


def speed_envelope_runs(samples, view_start, span, columns, speed_limit):
    """Aggregate ``samples`` into screen columns, split into contiguous runs.

    One pass over the (time-sorted) ``(second, speed)`` samples of the visible
    window, exactly like the per-pixel bins the chart always used: a sample
    belongs to column ``int((second - view_start) * columns / span)``. A column
    no sample lands in stays *absent*, so a hole in the recording remains a
    hole — nothing is interpolated across it.

    The columns are then cut into runs of adjacent columns (``column`` =
    previous + 1): a run is one piece of the signal that can be stroked as a
    single polyline and filled without bridging a gap. (Filling may need
    :func:`envelope_fill_pieces` to cut a run further, because a steep jump
    makes a single polygon self-intersect.)

    Args:
        samples: ``[(second_of_day, speed_kmh), ...]``, ordered by second.
        view_start: First second of the view window.
        span: Width of the view window in seconds.
        columns: Width of the plot area in pixels.
        speed_limit: Speed above which a column is flagged as over the limit.

    Returns:
        ``[[SpeedBin, ...], ...]`` — one list per contiguous run.
    """
    if span <= 0 or columns <= 0:
        return []
    totals = {}
    for second, speed in samples:
        column = int((second - view_start) * columns / span)
        if not 0 <= column < columns:
            continue
        total, count, low, high = totals.get(column, (0, 0, speed, speed))
        totals[column] = (total + speed, count + 1, min(low, speed), max(high, speed))
    runs = []
    previous = None
    for column in sorted(totals):
        total, count, low, high = totals[column]
        entry = SpeedBin(column=column, low=low, high=high,
                         mean=total / count, over_limit=high > speed_limit)
        if previous is None or column != previous + 1:
            runs.append([])
        runs[-1].append(entry)
        previous = column
    return runs


def envelope_fill_pieces(run):
    """Split a run into the pieces that can each be filled as one polygon.

    The envelope is drawn as a polygon that walks the upper edge left→right
    and the lower edge right→left. That polygon is only *simple* while two
    neighbouring columns' min–max bands overlap: when the signal jumps further
    than the band is tall (a column at 60–65 km/h followed by one at 0–5), the
    two edges cross and Tk's even-odd fill silently cancels the area — the
    envelope vanished exactly where the trace is steep. Cutting the run where
    the bands stop overlapping keeps every piece a simple polygon; the pieces
    touch at the shared column, so the fill still looks continuous.

    Args:
        run: One contiguous run of :class:`SpeedBin`, ordered by column.

    Returns:
        ``[[SpeedBin, ...], ...]`` — one list per fillable piece.
    """
    pieces = []
    for entry in run:
        if pieces and min(pieces[-1][-1].high, entry.high) >= max(pieces[-1][-1].low,
                                                                  entry.low):
            pieces[-1].append(entry)
        else:
            pieces.append([entry])
    return pieces


def default_speed_view(sample_seconds):
    """Return the UTC view window ``(start, end)`` that frames the samples.

    A day is not a full 24 h of driving: opening on 00:00–24:00 spent most of
    the plot on empty hours, so the trace was squeezed into a band a few
    minutes wide. The chart therefore opens on the span the samples actually
    cover, padded by 5 % on each side (the same ratio expressed as a
    ``×1.10`` window width), clamped to ``[0, 86400)`` and never narrower than
    :data:`SPEED_MIN_VIEW_SECONDS`.

    A day recorded across (almost) the whole 24 h still gets the full day,
    because the 10 % padding alone exceeds it; a day with no samples at all
    keeps the full day too. The zoom buttons keep working from here and can
    still reach the full day.

    Args:
        sample_seconds: The day's sample times, in seconds from UTC midnight.

    Returns:
        ``(start, end)`` as floats, ``0 <= start < end <= 86400``.
    """
    day = float(SPEED_DAY_SECONDS)
    if not sample_seconds:
        return 0.0, day
    first, last = float(min(sample_seconds)), float(max(sample_seconds))
    span = min(day, max(float(SPEED_MIN_VIEW_SECONDS), (last - first) * 1.10))
    start = max(0.0, min((first + last) / 2 - span / 2, day - span))
    return start, start + span


class DetailedSpeedChart(ttk.Frame):
    """Canvas chart for one UTC day of per-second speed samples."""

    def __init__(self, parent):
        super().__init__(parent)
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=8, pady=(8, 2))
        self.title_lbl = ttk.Label(header, font=FONT_TITLE)
        self.title_lbl.pack(side=tk.LEFT)
        self.zoom_in_btn = ttk.Button(header, text="+", width=3, command=self._zoom_in)
        self.zoom_in_btn.pack(side=tk.RIGHT)
        self.zoom_out_btn = ttk.Button(header, text="-", width=3, command=self._zoom_out)
        self.zoom_out_btn.pack(side=tk.RIGHT, padx=(0, 4))
        # The day's key facts as KPI cards (the dashboard's card style) instead
        # of one dense grey line; the grey line keeps only what they omit.
        self.kpi = {}
        self._kpi_specs = []
        self._kpi_rows = None
        self._measure_fonts = {}
        self._legend_items = []
        self._legend_rows = None
        self._legend_labels = []
        self._legend_glyphs = []
        self.kpi_frame = tk.Frame(self, bg=SURFACE_SUNKEN)
        self.kpi_frame.pack(fill=tk.X, padx=8, pady=(2, 0))
        self.kpi_frame.bind("<Configure>", self._layout_kpis)
        # What the red marks of the plot mean. Widgets (not canvas items) so a
        # long translation wraps instead of running off the plot.
        self.legend_frame = tk.Frame(self, bg=SURFACE)
        self.legend_frame.pack(fill=tk.X, padx=8, pady=(2, 0))
        self.legend_frame.bind("<Configure>", self._layout_legend)
        self.canvas = tk.Canvas(self, background=WHITE, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 2))
        self.canvas.bind("<Configure>", lambda _event: self._schedule_draw())
        self.canvas.bind("<Motion>", self._show_hover)
        self.canvas.bind("<Leave>", lambda _event: self.canvas.delete("speed_hover"))
        self.canvas.bind("<ButtonPress-1>", self._start_selection)
        self.canvas.bind("<B1-Motion>", self._extend_selection)
        self.canvas.bind("<ButtonRelease-1>", self._finish_selection)
        self.summary_lbl = ttk.Label(self, foreground=TEXT_MUTED, anchor=tk.W)
        self.summary_lbl.pack(fill=tk.X, padx=8, pady=(2, 8))
        self._day = ""
        self._samples = []
        self._sample_seconds = []
        self._plot = None
        self._view_start = 0
        self._view_end = 86400
        self._selection_start = None
        self._selection_moved = False
        self._y_scale = None
        self._draw_after_id = None
        self._overspeeding_events = []
        self._oes_dots = []
        #: The bins the last draw painted (``[(SpeedBin, ...), ...]``).
        self._series = []
        self._speed_limit = SPEED_LIMIT_KMH

    def show(self, day, samples, overspeeding_events=None, speed_limit=None):
        self._day = day
        self._speed_limit = speed_limit or SPEED_LIMIT_KMH
        self._samples = samples
        self._sample_seconds = [second for second, _speed in samples]
        # Open on the data, not on the empty hours of the day: zoom -/+ and
        # drag-to-zoom work from this window, and zooming out still reaches
        # the whole day.
        self._view_start, self._view_end = default_speed_view(self._sample_seconds)
        self._selection_start = None
        self._selection_moved = False
        self._overspeeding_events = overspeeding_events or []
        speeds = [speed for _second, speed in samples]
        recorded = len(speeds)
        moving = sum(speed > 0 for speed in speeds)
        above_limit = sum(speed > self._speed_limit for speed in speeds)
        # Only a real hole counts: the seconds between two ordinary samples are
        # the sampling interval, not missing data. Summing them reported "193
        # min internal gaps" for a day with one ten-minute hole, and the number
        # disagreed with the bands the plot draws.
        internal_gaps = sum(second - previous - 1
                            for (previous, _prev), (second, _cur)
                            in zip(samples, samples[1:], strict=False)
                            if second - previous > SPEED_GAP_SECONDS)
        self.title_lbl.config(text=_("Detailed Speed - {day} (UTC)").format(day=day))
        self._render_kpis(max(speeds) if speeds else None,
                          sum(speeds) / recorded if recorded else 0.0,
                          above_limit, moving)
        # A gap shorter than a minute is invisible at any zoom the plot opens
        # on; only a real hole in the recording earns a band and a legend item.
        self._has_gap = any(second - previous > SPEED_GAP_SECONDS
                            for (previous, _prev), (second, _cur)
                            in zip(samples, samples[1:], strict=False))
        self._render_legend(bool(speeds))
        self.summary_lbl.config(text=(
            _("{recorded:,} s recorded | {gaps} internal gaps").format(
                recorded=recorded,
                gaps=_fmt_seconds_duration(internal_gaps))
            if speeds else _("No valid speed samples")))
        self._schedule_draw()

    def _render_kpis(self, max_speed, avg_speed, above_limit, moving):
        """Rebuild the summary cards above the plot in the dashboard style.

        They carry what the old grey line packed into one dense string: peak
        and average speed, the time spent above the limit, the time actually
        moving and — only when the day has any — the number of overspeeding
        events the unit recorded. ``max_speed is None`` means the day has no
        samples at all: then there is nothing to summarise.
        """
        self._clear(self.kpi_frame)
        self.kpi = {}
        self._kpi_specs = []
        self._kpi_rows = None
        if max_speed is None:
            return
        self._kpi_specs = [
            # Blue is the trace's colour: a KPI painted the same blue reads as
            # part of the series. Red only when the peak really broke the
            # limit, neutral otherwise.
            ("max", _("Max speed"), f"{max_speed:.0f} km/h",
             DANGER if max_speed > self._speed_limit else TEXT_PRIMARY),
            ("avg", _("Avg speed"), f"{avg_speed:.1f} km/h", TEXT_SECONDARY),
            ("above", _("Time above {limit} km/h").format(limit=self._speed_limit),
             _fmt_seconds_duration(above_limit),
             DANGER if above_limit else TEXT_PRIMARY),
            ("moving", _("Time moving"), _fmt_seconds_duration(moving),
             TEXT_PRIMARY),
        ]
        if self._overspeeding_events:
            self._kpi_specs.append(("events", _("Overspeed events"),
                                    str(len(self._overspeeding_events)), DANGER))
        self._layout_kpis()

    def _layout_kpis(self, _event=None):
        """Place the cards in as many rows as the available width needs.

        One row of five at the default window; more rows once the right pane is
        as narrow as the minimum window allows (≈430 px at 900x560) or once a
        translation is wide. Each row is its own frame, so a wide card only
        ever widens its own row — it can never squeeze its neighbour's caption
        — and every card keeps its natural width, so no text is clipped.
        """
        specs = self._kpi_specs
        if not specs:
            return
        widths = [
            max(self._text_width(caption, FONT_SMALL),
                self._text_width(value, FONT_KPI_VALUE))
            + 2 * _KPI_CARD_PADX + 2 * _KPI_CARD_BORDER + 2 * _KPI_GRID_PAD
            + _KPI_WIDTH_SLACK
            for _key, caption, value, _colour in specs]
        rows = _flow_rows(widths, self._row_width(self.kpi_frame, _event))
        if rows == self._kpi_rows:
            return
        self._kpi_rows = rows
        self._clear(self.kpi_frame)
        self.kpi = {}
        # A full row stretches its cards evenly; a short last row keeps the
        # cards at their natural width, left aligned, instead of blowing the
        # lone card up across the whole pane. Uniform columns are not an
        # option: equal widths clip a long translation in a narrow window.
        for indexes in rows:
            row_frame = tk.Frame(self.kpi_frame, bg=SURFACE_SUNKEN)
            row_frame.pack(fill=tk.X)
            stretch = "nsew" if len(indexes) == max(map(len, rows)) else "nw"
            for column, index in enumerate(indexes):
                key, caption, value, colour = specs[index]
                card, caption_lbl, value_lbl = _kpi_card(row_frame, caption,
                                                         value, colour)
                card.grid(row=0, column=column, padx=_KPI_GRID_PAD,
                          pady=_KPI_GRID_PAD, sticky=stretch)
                row_frame.columnconfigure(column, weight=1)
                self.kpi[key] = {"card": card, "caption": caption_lbl,
                                 "value": value_lbl}

    def _render_legend(self, has_samples):
        """Explain the red marks of the plot: the limit line and the events.

        Drawn only when there is something to explain — a day without samples
        shows no legend at all, and the event item appears only for a day that
        really has overspeeding events in the file.
        """
        self._clear(self.legend_frame)
        self._legend_items = []
        self._legend_rows = None
        self._legend_labels = []
        self._legend_glyphs = []
        if not has_samples:
            return
        self._legend_items = [("line", _("Speed Limit")),
                              ("range", _("Speed range"))]
        if self._overspeeding_events:
            self._legend_items.append(
                ("dot", _("Overspeeding event (recorded by the unit)")))
        if getattr(self, "_has_gap", False):
            self._legend_items.append(("band", _("No samples recorded")))
        self._layout_legend()

    def _layout_legend(self, _event=None):
        """Lay the legend out like the cards: a long one wraps to a new line."""
        items = self._legend_items
        if not items:
            return
        widths = [_LEGEND_GLYPH_WIDTH + 4 + self._text_width(text, FONT_SMALL)
                  + 12 + _KPI_WIDTH_SLACK for _kind, text in items]
        rows = _flow_rows(widths, self._row_width(self.legend_frame, _event))
        if rows == self._legend_rows:
            return
        self._legend_rows = rows
        self._clear(self.legend_frame)
        self._legend_labels = []
        self._legend_glyphs = []
        for indexes in rows:
            row_frame = tk.Frame(self.legend_frame, bg=SURFACE)
            row_frame.pack(fill=tk.X)
            for column, index in enumerate(indexes):
                kind, text = items[index]
                glyph = tk.Canvas(row_frame, width=_LEGEND_GLYPH_WIDTH, height=10,
                                  bg=SURFACE, highlightthickness=0, borderwidth=0)
                if kind == "dot":
                    glyph.create_oval(6, 2, 12, 8, fill=DANGER_STRONG, outline=WHITE)
                elif kind == "band":
                    glyph.create_rectangle(1, 1, _LEGEND_GLYPH_WIDTH - 1, 9,
                                           fill=GAP_BAND, outline=BORDER)
                elif kind == "range":
                    glyph.create_rectangle(1, 1, _LEGEND_GLYPH_WIDTH - 1, 9,
                                           fill=ACTIVITY_DRIVE_TINT, outline="")
                else:
                    # Same dash and width as the rule on the plot, so the
                    # swatch is the line rather than a lookalike.
                    glyph.create_line(1, 5, _LEGEND_GLYPH_WIDTH - 1, 5,
                                      fill=DANGER_STRONG, dash=(6, 4), width=2)
                glyph.grid(row=0, column=column * 2, sticky="w", padx=(0, 4))
                label = tk.Label(row_frame, text=text, font=FONT_SMALL,
                                 fg=TEXT_MUTED, bg=SURFACE, anchor=tk.W,
                                 justify=tk.LEFT)
                label.grid(row=0, column=column * 2 + 1, sticky="w", padx=(0, 12))
                self._legend_glyphs.append(glyph)
                self._legend_labels.append(label)
            # Only the last column takes the leftover width, so the items stay
            # grouped on the left instead of being spread across the pane.
            row_frame.columnconfigure(len(indexes) * 2 - 1, weight=1)

    def _row_width(self, frame, event=None):
        """Usable width of a row container.

        A ``<Configure>`` handler must use the event's width: ``winfo_width()``
        can still report the size the frame is leaving, and a row packed for a
        wider pane is then squeezed (and its captions clipped) by the narrower
        one.
        """
        width = getattr(event, "width", None) or frame.winfo_width()
        return width if width > 1 else max(1, self.winfo_width() - 16)

    def _text_width(self, text, spec):
        """Natural pixel width of ``text`` in the font ``spec``."""
        font = self._measure_fonts.get(spec)
        if font is None:
            font = self._measure_fonts[spec] = tkfont.Font(font=spec)
        return font.measure(text)

    @staticmethod
    def _clear(frame):
        for child in frame.winfo_children():
            child.destroy()

    def _zoom_in(self):
        self._set_zoom((self._view_start + self._view_end) / 2, (self._view_end - self._view_start) / 2)

    def _zoom_out(self):
        self._set_zoom((self._view_start + self._view_end) / 2, (self._view_end - self._view_start) * 2)

    def _set_zoom(self, center, span):
        """Set a bounded UTC view window; 60 seconds is the closest zoom."""
        span = min(86400, max(60, span))
        start = max(0, min(center - span / 2, 86400 - span))
        self._view_start, self._view_end = start, start + span
        self._schedule_draw()

    def _schedule_draw(self):
        if self._draw_after_id is not None:
            self.after_cancel(self._draw_after_id)
        self._draw_after_id = self.after_idle(self._draw)

    def _draw(self):
        self._draw_after_id = None
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 120 or height < 100:
            return
        # The 90 km/h label needs enough dedicated y-axis space on all scales.
        left, right, top, bottom = 76, 18, 28, height - 34
        plot_width, plot_height = width - left - right, bottom - top
        first = bisect_left(self._sample_seconds, self._view_start)
        last = bisect_left(self._sample_seconds, self._view_end)
        visible_samples = self._samples[first:last]
        speeds = [speed for _second, speed in visible_samples]
        max_speed = max(speeds, default=self._speed_limit)
        # G-F4: a recorded overspeeding event can exceed every sampled speed of
        # the visible window. Include the visible events' max speed in the
        # ceiling, otherwise the marker is drawn above the plot (off-canvas,
        # invisible and unhoverable).
        event_max = 0.0
        for evt in self._overspeeding_events:
            begin = evt.get("begin", "")
            try:
                evt_dt = datetime.fromisoformat(str(begin).replace("Z", "+00:00"))
            except (ValueError, AttributeError, TypeError):
                continue
            evt_sec = evt_dt.hour * 3600 + evt_dt.minute * 60 + evt_dt.second
            if evt_sec < self._view_start or evt_sec > self._view_end:
                continue
            try:
                event_max = max(event_max, float(evt.get("max_speed_kmh")))
            except (TypeError, ValueError):
                continue
        top_speed = max(max_speed, event_max)
        ceiling = max(100, (int(top_speed) + 19) // 20 * 20)

        def y_for(speed):
            return bottom - speed * plot_height / ceiling

        self._plot = (left, right, top, bottom, plot_width, self._view_start, self._view_end)
        self._y_scale = (bottom, ceiling, plot_height)

        # Axes and gridlines. The light horizontal gridlines go behind
        # everything; the 0 / ceiling lines and every axis label below the
        # trace; the dashed red limit line is drawn on top of it (see below),
        # because the envelope fill would otherwise bury it where the profile
        # runs at the limit.
        grid_step = self._grid_step(ceiling, plot_height)
        for value in range(grid_step, ceiling, grid_step):
            if value == self._speed_limit:
                continue  # the limit keeps its own, stronger label below
            y = y_for(value)
            canvas.create_line(left, y, width - right, y, fill=CHART_GRID_MINOR)
            canvas.create_text(left - 7, y, text=str(value), anchor=tk.E,
                               fill=TEXT_MUTED)

        for value in (0, self._speed_limit, ceiling):
            y = y_for(value)
            color = DANGER_STRONG if value == self._speed_limit else CHART_GRID_MAJOR
            if value != self._speed_limit:
                canvas.create_line(left, y, width - right, y, fill=color)
            label = f"{value} km/h" if value == self._speed_limit else str(value)
            canvas.create_text(left - 7, y, text=label, anchor=tk.E, fill=color)

        span = self._view_end - self._view_start
        tick_step = self._tick_step(span, plot_width)
        first_tick = int(self._view_start // tick_step) * tick_step
        for second in range(first_tick, int(self._view_end) + tick_step, tick_step):
            if second < self._view_start or second > self._view_end:
                continue
            x = left + plot_width * (second - self._view_start) / span
            canvas.create_line(x, top, x, bottom, fill=CHART_GRID_MINOR)
            canvas.create_text(x, bottom + 16, text=self._time_label(second, span), anchor=tk.N,
                               fill=TEXT_MUTED)
        canvas.create_text(left, 10, text=_("Speed (km/h)"), anchor=tk.W, fill=TEXT_MUTED)

        # Aggregate to screen pixels, then paint the result as a signal: the
        # min–max envelope as a filled area and the column mean as a line. A
        # column no sample lands in stays blank, so chart resolution never
        # invents a continuous speed trace across a gap — and a gap also breaks
        # the fill into a new run instead of being bridged by the polygon.
        self._draw_gaps(visible_samples, left, y_for, plot_width, span, top, bottom)
        runs = speed_envelope_runs(visible_samples, self._view_start, span,
                                   plot_width, self._speed_limit)
        self._series = runs
        self._draw_envelope_fills(runs, left, y_for)

        # Overspeed zone shading (stipple)
        overspeed_runs = []
        run_start = None
        for second, speed in visible_samples:
            if speed > self._speed_limit:
                if run_start is None:
                    run_start = second
            else:
                if run_start is not None:
                    overspeed_runs.append((run_start, second))
                    run_start = None
        if run_start is not None:
            overspeed_runs.append((run_start, visible_samples[-1][0]))
        for rs_start, rs_end in overspeed_runs:
            x0 = left + (rs_start - self._view_start) * plot_width / span
            x1 = left + (rs_end - self._view_start) * plot_width / span
            if x1 - x0 < 1:
                continue
            canvas.create_rectangle(x0, top, x1, bottom,
                                    fill=DANGER_BAND, outline="", stipple="gray25",
                                    tags="speed_overspeed")

        # The mean line and the over-limit part of the envelope go on top of
        # the stippled band: under it, the band's 25 % veil turned the red area
        # into a pink checkerboard and cut the line into dashes.
        self._draw_envelope_marks(runs, left, y_for)

        # Dashed red limit line on top of the trace (and of its red overlay),
        # so "the profile crossed the limit" is always readable.
        limit_y = y_for(self._speed_limit)
        canvas.create_line(left, limit_y, width - right, limit_y,
                           fill=DANGER_STRONG, dash=(6, 4), width=2,
                           tags="speed_limit_line")

        # Overspeeding event markers (red dots from file data)
        self._oes_dots = []
        for evt in self._overspeeding_events:
            ts = evt.get("begin", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                sec_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second
            except (ValueError, AttributeError):
                continue
            if sec_of_day < self._view_start or sec_of_day > self._view_end:
                continue
            x = left + (sec_of_day - self._view_start) * plot_width / span
            try:
                evt_speed = float(evt.get("max_speed_kmh"))
            except (TypeError, ValueError):
                evt_speed = self._speed_limit
            y_center = y_for(evt_speed)
            r = 4
            canvas.create_oval(x - r, y_center - r, x + r, y_center + r,
                               fill=DANGER_STRONG, outline=WHITE, width=1,
                               tags="speed_oes")
            self._oes_dots.append((x, y_center, evt))

    def _draw_envelope_fills(self, runs, left, y_for):
        """Fill the min–max envelope of every contiguous run.

        Each run is filled piece by piece (see :func:`envelope_fill_pieces`)
        in the light :data:`ACTIVITY_DRIVE_TINT` with no outline. A gap in the
        samples produced a new run, so the fill is never drawn across it.

        Args:
            runs: The :func:`speed_envelope_runs` result for this view.
            left: Canvas x of the plot's left edge (column 0).
            y_for: Callable mapping a speed in km/h to a canvas y.
        """
        for run in runs:
            for piece in envelope_fill_pieces(run):
                # The envelope of a *column* is the whole one-pixel column, not
                # a point: each column contributes its band from x to x+1, so
                # the fill reads as an area instead of a ribbon that hides
                # under the mean line where the profile is steep.
                xs = [left + entry.column for entry in piece]
                outline = []
                for x, entry in zip(xs, piece, strict=False):
                    y = y_for(entry.high)
                    outline.extend((x, y, x + 1, y))
                for x, entry in zip(reversed(xs), reversed(piece), strict=False):
                    y = y_for(entry.low)
                    outline.extend((x + 1, y, x, y))
                self.canvas.create_polygon(*outline, fill=ACTIVITY_DRIVE_TINT,
                                           outline="", tags="speed_envelope")

    def _draw_gaps(self, samples, left, y_for, plot_width, span, top, bottom):
        """Shade the stretches the unit recorded nothing in.

        Zero speed and missing data look identical on a speed plot until one
        of them is shaded: a vehicle standing still draws a flat line on the
        baseline, a hole draws nothing at all. Only holes of at least
        :data:`SPEED_GAP_SECONDS` get a band, so per-second sampling jitter
        never speckles the plot.
        """
        for (previous, _prev), (second, _cur) in zip(samples, samples[1:], strict=False):
            if second - previous <= SPEED_GAP_SECONDS:
                continue
            x0 = left + (previous - self._view_start) * plot_width / span
            x1 = left + (second - self._view_start) * plot_width / span
            if x1 - x0 < 2:
                continue
            self.canvas.create_rectangle(x0, top, x1, bottom, fill=GAP_BAND,
                                         outline="", tags="speed_gap")

    def _draw_envelope_marks(self, runs, left, y_for):
        """Draw what has to stay readable on top of the fill and the band.

        Per run: the part of the envelope above the speed limit as a solid
        :data:`DANGER` overlay clipped at the limit line, then the column means
        as a 2 px line — :data:`DANGER` where the mean itself is over the
        limit, :data:`ACCENT` otherwise. A column that merely *contains* a peak
        stays blue: colouring it red painted red streaks down to 50 km/h on a
        steep minute, which read as "50 km/h is over the limit". The red
        sliver above the line is what says the profile crossed it. One colour
        change is one canvas item: a full day fills every column, and one
        segment per column would be thousands of items.

        Args:
            runs: The :func:`speed_envelope_runs` result for this view.
            left: Canvas x of the plot's left edge (column 0).
            y_for: Callable mapping a speed in km/h to a canvas y.
        """
        canvas = self.canvas
        limit_y = y_for(self._speed_limit)
        for run in runs:
            xs = [left + entry.column for entry in run]
            ys_mean = [y_for(entry.mean) for entry in run]
            if len(run) == 1:
                # One isolated column: zoomed in far enough that samples are
                # pixels apart, the mean dot is what keeps the sample visible.
                colour = DANGER if run[0].mean > self._speed_limit else ACCENT
                canvas.create_line(xs[0], y_for(run[0].low), xs[0],
                                   y_for(run[0].high), fill=colour, width=2,
                                   tags="speed_sample")
                canvas.create_oval(xs[0] - 2, ys_mean[0] - 2, xs[0] + 2,
                                   ys_mean[0] + 2, fill=colour, outline="",
                                   tags="speed_mean")
                continue
            if any(entry.over_limit for entry in run):
                # Only the sliver above the limit: the upper edge clipped to
                # the limit line, so a column that dips below the limit adds no
                # red at all, and nothing under the limit turns red.
                over = []
                for x, entry in zip(xs, run, strict=False):
                    over.extend((x, y_for(max(entry.high, self._speed_limit))))
                over.extend((xs[-1], limit_y, xs[0], limit_y))
                canvas.create_polygon(*over, fill=DANGER, outline="",
                                      tags="speed_over_limit")
            # The mean line is red only where it is above the limit, and a
            # segment that crosses the line is split at the crossing: colouring
            # the whole segment red painted a red diagonal down to 50 km/h
            # after every overspeed spike.
            segments = []  # [(colour, [x1, y1, x2, y2, ...]), ...]
            for index in range(len(run) - 1):
                x1, y1 = xs[index], ys_mean[index]
                x2, y2 = xs[index + 1], ys_mean[index + 1]
                m1, m2 = run[index].mean, run[index + 1].mean
                if (m1 > self._speed_limit) == (m2 > self._speed_limit):
                    colour = DANGER if m1 > self._speed_limit else ACCENT
                    current = segments[-1] if segments and segments[-1][0] == colour else None
                    if current is None:
                        segments.append([colour, [x1, y1, x2, y2]])
                    else:
                        current[1].extend((x2, y2))
                    continue
                # One endpoint above the line: cut the segment where it is.
                ratio = ((self._speed_limit - m1) / (m2 - m1))
                cross_x = x1 + (x2 - x1) * ratio
                above_first = m1 > self._speed_limit
                first_colour = DANGER if above_first else ACCENT
                second_colour = ACCENT if above_first else DANGER
                segments.append([first_colour, [x1, y1, cross_x, limit_y]])
                segments.append([second_colour, [cross_x, limit_y, x2, y2]])
            for colour, coords in segments:
                if len(coords) < 4:
                    continue
                canvas.create_line(*coords, fill=colour, width=2,
                                   tags="speed_mean")

    @staticmethod
    def _grid_step(ceiling, plot_height):
        """Horizontal gridline step in km/h for a plot ``plot_height`` tall.

        20 km/h is the readable default; 25 (then 50) is used when the plot is
        too short to carry that many lines — roughly 30 px between two
        gridlines. The ceiling is always a multiple of 20 and at least 100, so
        a normal window gets 20 and a squeezed one gets 25 or 50.
        """
        budget = max(3, plot_height // 30)
        for step in (20, 25, 50):
            if ceiling / step <= budget:
                return step
        return 50

    @staticmethod
    def _tick_step(span, plot_width=None):
        """Seconds between two time labels.

        Picked from the span, then doubled while the labels would sit closer
        than ~70 px: at the minimum window an hourly grid put twelve labels in
        six hundred pixels and read as a smear.
        """
        step = DetailedSpeedChart._tick_step_for_span(span)
        if plot_width:
            while plot_width * step / span < 70 and step < 86400:
                step *= 2
        return step

    @staticmethod
    def _tick_step_for_span(span):
        if span >= 43200:
            return 10800
        if span >= 14400:
            return 3600
        if span >= 7200:
            return 1800
        if span >= 3600:
            return 900
        if span >= 1800:
            return 300
        if span >= 600:
            return 60
        return 30

    @staticmethod
    def _time_label(second, span):
        hours, remainder = divmod(int(second), 3600)
        minutes, seconds = divmod(remainder, 60)
        return (f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                if span < 600 else f"{hours:02d}:{minutes:02d}")

    def _show_hover(self, event):
        """Show the closest recorded sample under the cursor in UTC."""
        if not self._plot or not self._samples:
            return
        left, _right, top, bottom, plot_width, view_start, view_end = self._plot
        if not left <= event.x <= left + plot_width or not top <= event.y <= bottom:
            self.canvas.delete("speed_hover")
            return

        # Check overspeeding event dots first
        for ox, oy, evt in self._oes_dots:
            if abs(event.x - ox) <= 8 and abs(event.y - oy) <= 8:
                b = evt.get("begin", "")[:16]
                e = evt.get("end", "")[:16]
                mx = evt.get("max_speed_kmh", "?")
                av = evt.get("average_speed_kmh", "?")
                cd = evt.get("card_driver", {})
                drv = ""
                if isinstance(cd, dict):
                    drv = (cd.get("card_number") or "").strip()
                text = _("Overspeeding: {start} \u2192 {end} | max {max_speed} | "
                         "avg {avg_speed}").format(start=b, end=e, max_speed=mx, avg_speed=av)
                if drv:
                    text += f" | {drv}"
                self.canvas.delete("speed_hover")
                label_x = min(event.x + 12, self.canvas.winfo_width() - 290)
                label_y = max(event.y - 24, 4)
                text_id = self.canvas.create_text(label_x, label_y, text=text,
                                                  anchor=tk.NW, fill=TOOLTIP_FG,
                                                  tags="speed_hover")
                x1, yb1, x2, yb2 = self.canvas.bbox(text_id)
                bg = self.canvas.create_rectangle(x1 - 5, yb1 - 3, x2 + 5, yb2 + 3,
                                                  fill=TOOLTIP_BG, outline=TOOLTIP_BORDER,
                                                  tags="speed_hover")
                self.canvas.tag_lower(bg, text_id)
                return

        span = view_end - view_start
        target_second = round(view_start + (event.x - left) * span / plot_width)
        index = bisect_left(self._sample_seconds, target_second)
        candidates = self._samples[max(0, index - 1):index + 1]
        if not candidates:
            return
        second, speed = min(candidates, key=lambda sample: abs(sample[0] - target_second))
        # At day scale, one screen pixel represents several seconds. Do not
        # pretend a distant sample belongs to a long unrecorded gap.
        if abs(second - target_second) > max(2, round(span / plot_width) * 2):
            self.canvas.delete("speed_hover")
            return
        hours, remainder = divmod(second, 3600)
        minutes, seconds = divmod(remainder, 60)
        text = f"{hours:02d}:{minutes:02d}:{seconds:02d} UTC  |  {speed} km/h"
        self.canvas.delete("speed_hover")
        if self._y_scale:
            dot_y, dot_ceiling, dot_h = self._y_scale
            dot_x = left + (second - view_start) * plot_width / (view_end - view_start)
            dot_py = dot_y - speed * dot_h / dot_ceiling
            r = 4
            self.canvas.create_oval(dot_x - r, dot_py - r, dot_x + r, dot_py + r,
                                    fill=DANGER if speed > self._speed_limit else ACCENT,
                                    outline=WHITE, width=1, tags="speed_hover")
        label_x = min(event.x + 12, self.canvas.winfo_width() - 190)
        label_y = max(event.y - 24, 4)
        text_id = self.canvas.create_text(label_x, label_y, text=text, anchor=tk.NW,
                                          fill=TOOLTIP_FG, tags="speed_hover")
        x1, y1, x2, y2 = self.canvas.bbox(text_id)
        background = self.canvas.create_rectangle(x1 - 5, y1 - 3, x2 + 5, y2 + 3,
                                                  fill=TOOLTIP_BG, outline=TOOLTIP_BORDER,
                                                  tags="speed_hover")
        self.canvas.tag_lower(background, text_id)

    def _start_selection(self, event):
        if not self._plot:
            return
        left, _right, top, bottom, _width, _start, _end = self._plot
        if left <= event.x <= self.canvas.winfo_width() - 18 and top <= event.y <= bottom:
            self._selection_start = event.x
            self._selection_moved = False
            self.canvas.delete("speed_hover")

    def _extend_selection(self, event):
        if self._selection_start is None or not self._plot:
            return
        left, _right, top, bottom, plot_width, _start, _end = self._plot
        current = min(max(event.x, left), left + plot_width)
        if abs(current - self._selection_start) > 3:
            self._selection_moved = True
        self.canvas.delete("speed_hover")
        self.canvas.delete("speed_selection")
        self.canvas.create_rectangle(self._selection_start, top, current, bottom,
                                     outline=ACCENT, dash=(4, 3), width=2,
                                     tags="speed_selection")

    def _finish_selection(self, event):
        if self._selection_start is None or not self._plot:
            return
        left, _right, _top, _bottom, plot_width, view_start, view_end = self._plot
        current = min(max(event.x, left), left + plot_width)
        start_x, self._selection_start = self._selection_start, None
        moved = self._selection_moved
        self._selection_moved = False
        self.canvas.delete("speed_selection")
        # Click without drag: re-center the view on the clicked time.
        if not moved:
            span = view_end - view_start
            target = view_start + (start_x - left) * span / plot_width
            self._set_zoom(target, span)
            return
        # Drag: zoom to the selected region.
        if abs(current - start_x) < 5:
            return
        span = view_end - view_start
        start = view_start + (min(start_x, current) - left) * span / plot_width
        end = view_start + (max(start_x, current) - left) * span / plot_width
        self._set_zoom((start + end) / 2, end - start)
