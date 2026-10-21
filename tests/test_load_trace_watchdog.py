"""Stall watchdog and dialog timing of the load trace (no private files).

The *live file* is opt-in (``DDD_TRACE_LOAD=1``); the in-memory ring and the watchdog
thread that reports a real stall are always on, so they run with the env var off too.
"""
import importlib
import threading
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def trace(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def load(enabled):
        monkeypatch.setenv("DDD_TRACE_LOAD", "1" if enabled else "0")
        from core.utils import load_trace
        lt = importlib.reload(load_trace)
        lt.STALL_REPORT = False          # a slow test is not a user-facing stall
        lt.WATCHDOG = True               # pytest means no sampler; these tests ask for one
        return lt
    yield load, tmp_path
    monkeypatch.setenv("DDD_TRACE_LOAD", "0")
    from core.utils import load_trace
    importlib.reload(load_trace)


def test_off_keeps_the_watchdog_and_the_ring_but_writes_no_file(trace):
    load, home = trace
    lt = load(False)
    lt.event("x")
    with lt.dialog("showinfo", "File Note"):
        pass
    # always on in the app: the stall report needs the ring and the sampler without an env
    # var (the test asks for the sampler because pytest itself never starts one)
    assert any(t.name == "load-trace-watchdog" for t in threading.enumerate())
    assert any("\tx\t" in line for line in lt._ring)
    assert not list(home.iterdir())               # no live trace, and no stall happened


def _blocked_for_the_test_stall():
    time.sleep(2.6)


def test_stall_line_and_end(trace):
    load, home = trace
    lt = load(True)
    lt.INTERVAL, lt.STALL_SAMPLES = 0.05, 4
    lt.event("start")
    _blocked_for_the_test_stall()
    time.sleep(0.12)
    text = (home / lt.FILE_NAME).read_text()
    stall = [x for x in text.splitlines() if "\tstall\t" in x]
    assert len(stall) == 1 and "_blocked_for_the_test_stall" in stall[0]
    assert "seconds>=" in stall[0]
    assert "\tstall.end\t" in text
    assert str(home) not in text


def test_warn_when_idle_lines(trace, monkeypatch):
    load, home = trace
    lt = load(True)
    from app import gui
    shown = []
    monkeypatch.setattr(gui, "messagebox", SimpleNamespace(
        showinfo=lambda t, m: shown.append(m), showwarning=lambda t, m: None))
    box = SimpleNamespace(_parsing=False, _rendering=False)
    secret = "SECRET-MESSAGE-TEXT mock_file.ddd"
    gui.TachoExplorer._warn_when_idle(box, "File Note", secret, "showinfo")
    gui.TachoExplorer._warn_when_idle(box, "Some Secret Title", secret, "showwarning")
    text = (home / lt.FILE_NAME).read_text()
    assert shown == [secret]
    assert text.count("warn_when_idle.enter") == 2 and text.count("warn_when_idle.returned") == 2
    assert "kind=showinfo title=File Note" in text and "title=other" in text
    for leak in (str(home), "SECRET", "mock_file", "Some Secret"):
        assert leak not in text


def test_open_source_of_each_entry_point(trace, monkeypatch):
    load, home = trace
    lt = load(True)
    from app import gui
    monkeypatch.setattr(gui, "filedialog", SimpleNamespace(askopenfilename=lambda **k: "/x/secret.ddd"))
    monkeypatch.setattr(gui, "dropped_paths", lambda part, split=None: [part])
    started = []
    status = SimpleNamespace(config=lambda **k: None)
    box = SimpleNamespace(_parsing=False, _rendering=False, _open_pending=False, status=status,
                          tk=SimpleNamespace(splitlist=lambda x: x),
                          after=lambda ms, fn: fn(),      # run the deferred start now
                          _start_parse=lambda path: (started.append(box._open_source), lt.opened(path, box._open_source)))
    gui.TachoExplorer._open_file(box)
    gui.TachoExplorer._open_recent(box, "/x/secret.ddd")
    gui.TachoExplorer._on_drop(box, "/x/secret.ddd")
    assert started == ["picker", "recent", "drop"]
    box._initial_file = "/x/secret.ddd"
    gui.TachoExplorer._open_initial_file(box)
    assert started[-1] == "cli"
    # the real _start_parse records the source its caller set
    real = SimpleNamespace(_parsing=False, _rendering=False, _open_source="cli")
    with pytest.raises(AttributeError):    # stops right after the trace line (no buttons)
        gui.TachoExplorer._start_parse(real, str(home / "m.ddd"))
    box._parsing = True
    gui.TachoExplorer._open_recent(box, "/x/secret.ddd")
    text = (home / lt.FILE_NAME).read_text()
    for src in ("picker", "recent", "drop", "cli"):
        assert "source=" + src in text
    assert "picker.opened" in text and "chosen=yes" in text
    assert "recent.click\trefused=no" in text and "recent.click\trefused=yes" in text
    assert "secret" not in text and str(home) not in text
