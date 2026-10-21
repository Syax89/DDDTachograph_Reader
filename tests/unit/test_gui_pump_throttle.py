"""``_pump_render`` throttles itself by the cost of its own ``update()``."""

import pytest

pytest.importorskip("tkinter")
import app.gui as gui  # noqa: E402


class _Clock:
    t = 1000.0


def _app(monkeypatch, cost):
    clock = _Clock()
    monkeypatch.setattr(gui.time, "monotonic", lambda: clock.t)
    app = object.__new__(gui.TachoExplorer)
    app._pump_due = 0.0
    app._destroyed = False
    app.pumps = []

    def update():
        app.pumps.append(clock.t)
        clock.t += cost

    app.update = update
    app.winfo_exists = lambda: True
    return app, clock


def test_slow_pump_is_throttled(monkeypatch):
    app, clock = _app(monkeypatch, 0.08)
    for _ in range(810):
        app._pump_render()
        clock.t += 0.004  # the render work between two calls
    assert len(app.pumps) <= 81


def test_fast_pump_keeps_the_frame_rate(monkeypatch):
    app, clock = _app(monkeypatch, 0.0)
    for _ in range(600):
        app._pump_render()
        clock.t += 0.001
    gaps = [b - a for a, b in zip(app.pumps, app.pumps[1:], strict=False)]
    assert min(gaps) >= gui._RENDER_PUMP_INTERVAL
    assert max(gaps) < gui._RENDER_PUMP_INTERVAL + 0.002


def test_force_always_pumps(monkeypatch):
    app, _ = _app(monkeypatch, 0.08)
    app._pump_render()
    app._pump_render(force=True)
    app._pump_render(force=True)
    assert len(app.pumps) == 3


def test_gap_is_capped(monkeypatch):
    app, clock = _app(monkeypatch, 5.0)
    app._pump_render()
    assert app._pump_due - clock.t == pytest.approx(gui._RENDER_PUMP_MAX_GAP)
