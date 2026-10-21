"""macOS: the render pump must not process events; a picked file starts after ``after(150)``."""
import pytest

pytest.importorskip("tkinter")
import app.gui as gui  # noqa: E402
from tests.unit.test_gui_summary_default import close, new_explorer  # noqa: E402


class _Clock:
    t = 1000.0


def _app(monkeypatch, uses_events):
    clock = _Clock()
    monkeypatch.setattr(gui.time, "monotonic", lambda: clock.t)
    monkeypatch.setattr(gui, "_PUMP_USES_EVENTS", uses_events)
    app = object.__new__(gui.TachoExplorer)
    app._pump_due = 0.0
    app._destroyed = False
    app.calls, app.steps = [], []
    app.update = lambda: app.calls.append("update")
    app.update_idletasks = lambda: app.calls.append("idle")
    app.winfo_exists = lambda: True
    app.progress = type("P", (), {"step": lambda s, n: app.steps.append(n)})()
    return app, clock


def test_events_mode_calls_update(monkeypatch):
    app, _ = _app(monkeypatch, True)
    app._pump_render(force=True)
    assert app.calls == ["update"] and app.steps == []


def test_idle_mode_calls_only_update_idletasks_and_steps_the_bar(monkeypatch):
    app, clock = _app(monkeypatch, False)
    app._pump_render(force=True)         # first pump: no reference time yet
    clock.t += 0.048                     # 4 ticks of 12 ms
    app._pump_render(force=True)
    clock.t += 30                        # a long gap is capped
    app._pump_render(force=True)
    assert app.calls == ["idle"] * 3
    assert app.steps == [4, gui._BAR_MAX_TICKS]


def test_idle_pump_survives_a_widgetless_double(monkeypatch):
    app, _ = _app(monkeypatch, False)
    del app.progress
    app.__dict__.pop("update_idletasks")
    app._pump_render(force=True)         # AttributeError swallowed, as before


def test_env_override_and_platform_default():
    assert gui._pump_uses_events({}, "darwin") is False
    assert gui._pump_uses_events({}, "linux") is True
    assert gui._pump_uses_events({"DDD_PUMP_MODE": "events"}, "darwin") is True
    assert gui._pump_uses_events({"DDD_PUMP_MODE": "idle"}, "linux") is False
    assert gui._pump_uses_events({"DDD_PUMP_MODE": "junk"}, "darwin") is False


def test_flush_follows_the_mode(monkeypatch):
    app, _ = _app(monkeypatch, False)
    gui._flush(app)
    monkeypatch.setattr(gui, "_PUMP_USES_EVENTS", True)
    gui._flush(app)
    assert app.calls == ["idle", "update"]


def test_open_file_defers_the_parse_and_a_double_click_starts_one(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        started = []
        monkeypatch.setattr(app, "_start_parse", started.append)
        picks = []
        monkeypatch.setattr(gui.filedialog, "askopenfilename",
                            lambda **kw: picks.append(kw) or "/x/y.ddd")
        app._open_file()
        app._open_file()                 # second click on Open inside the 150 ms
        assert started == [] and len(picks) == 1
        app.update()
        assert started == []             # 150 ms not elapsed yet
        import time
        end = time.monotonic() + 5
        while not started and time.monotonic() < end:
            app.update()
            time.sleep(0.01)
        assert started == ["/x/y.ddd"] and not app._open_pending
        monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: "")
        app._open_file()                 # cancelled picker releases the guard
        assert not app._open_pending
        assert set(picks[0]) == {"filetypes"}
    finally:
        close(app)
