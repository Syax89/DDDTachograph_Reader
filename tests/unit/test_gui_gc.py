"""The GC is paused while a file is parsed and drawn, frozen and restored after (never left off)."""
import gc
import time
from pathlib import Path

import pytest

import app.gui as gui
from core.utils import load_trace
from tests.unit.test_gui_summary_default import close, new_explorer

MOCK = Path(__file__).resolve().parents[2] / "tests" / "mock_data" / "mock_g2_card.ddd"


@pytest.fixture(autouse=True)
def gc_state():
    was = gc.isenabled()
    yield
    gc.unfreeze()
    gc.enable() if was else gc.disable()


def double():
    """A TachoExplorer without a window: only the GC logic runs."""
    obj = object.__new__(gui.TachoExplorer)
    obj.progress = type("P", (), {"stop": lambda s: None, "pack_forget": lambda s: None})()
    obj.btn_open = obj.btn_export = type("B", (), {"config": lambda s, **k: None})()
    obj.current_data = None
    obj.title = lambda *_: None
    return obj


def test_finish_restores_freezes_and_is_idempotent():
    obj = double()
    obj._gc_was_enabled = gui._gc_pause()
    assert not gc.isenabled()
    obj._finish_parse()
    assert gc.isenabled() and gc.get_freeze_count() > 0
    obj._finish_parse()
    assert gc.isenabled()


def test_a_collector_the_caller_disabled_stays_disabled():
    gc.disable()
    obj = double()
    obj._gc_was_enabled = gui._gc_pause()
    obj._finish_parse()
    assert not gc.isenabled()


def test_shutdown_path_resumes():
    obj = double()
    obj._gc_was_enabled = gui._gc_pause()
    obj._resume_gc()
    assert gc.isenabled()


def _wait(app, cond):
    end = time.monotonic() + 60
    while time.monotonic() < end and not cond():
        app.update()
        time.sleep(0.01)
    assert cond()


def test_real_parse_twice_and_error(monkeypatch):
    if not MOCK.is_file():
        pytest.skip("mocks not generated")
    app = new_explorer(monkeypatch)
    try:
        for _ in range(2):
            app._start_parse(str(MOCK))
            assert not gc.isenabled()
            _wait(app, lambda: not app._parsing and not app._rendering)
            assert gc.isenabled() and gc.get_freeze_count() > 0
        app._start_parse(str(MOCK))
        assert not gc.isenabled()
        app._parse_error("boom")
        assert gc.isenabled()
    finally:
        close(app)


def test_exception_in_render_restores(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        monkeypatch.setattr(app, "_populate_tree", lambda d: 1 / 0)
        monkeypatch.setattr(app, "_warn_when_idle", lambda *a, **k: None)
        monkeypatch.setattr(gui, "add_recent_file", lambda p: None)
        app._parsing = True
        app._gc_was_enabled = gui._gc_pause()
        app._parse_done({"raw_tags": {"x": 1}}, "/x.ddd")
        assert gc.isenabled() and not app._parsing
    finally:
        close(app)


def test_slow_gc_pass_is_traced_and_nothing_hooked_when_off(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setitem(load_trace._gc, "hooked", False)
    monkeypatch.setattr(load_trace, "ENABLED", False)
    before = list(gc.callbacks)
    load_trace.opened("a.ddd")
    assert gc.callbacks == before and list(tmp_path.iterdir()) == []
    monkeypatch.setattr(load_trace, "ENABLED", True)
    monkeypatch.setattr(load_trace, "GC_MIN_SECONDS", -1.0)
    monkeypatch.setattr(load_trace, "_announced", False)
    try:
        load_trace.opened("a.ddd")
        load_trace.opened("a.ddd")                     # still ONE callback
        assert gc.callbacks.count(load_trace._gc_callback) == 1
        gc.collect()
        load_trace.idle_report()
    finally:
        gc.callbacks.remove(load_trace._gc_callback)
    text = (tmp_path / load_trace.FILE_NAME).read_text()
    assert "gc_state\tenabled=True" in text
    for key in ("gc_pass\tgeneration=2 seconds=", "collected=", "during=idle",
                "gc_summary\tpasses=", "total_seconds=", "max_seconds=", "frozen="):
        assert key in text, key
