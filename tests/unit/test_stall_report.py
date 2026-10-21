"""The always-on stall watchdog: a real stall writes a private report, normal use writes nothing."""
import sys
import threading
import time
import types

import pytest

from core.utils import load_trace


@pytest.fixture
def fast(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(load_trace, "STALL_REPORT", True)
    monkeypatch.setattr(load_trace, "INTERVAL", 0.05)
    monkeypatch.setattr(load_trace, "STALL_SAMPLES", 4)
    monkeypatch.setattr(load_trace, "_dumped", False)
    monkeypatch.setattr(load_trace, "_ring", type(load_trace._ring)(maxlen=400))
    return tmp_path / load_trace.STALL_FILE


def _watch_main_thread_for(seconds):
    """Run the watchdog loop while *this* (main) thread executes ``sleep``-like work."""
    threading.Thread(target=load_trace._watch, daemon=True).start()
    time.sleep(seconds)


def test_normal_session_creates_no_file(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(load_trace, "STALL_SAMPLES", 10_000)
    load_trace.event("open requested", ext=".ddd")
    load_trace.pump_report()
    time.sleep(0.3)
    assert not fast.exists() and list(tmp_path.iterdir()) == []


def test_real_stall_dumps_the_ring_once_and_privately(fast, tmp_path, capsys):
    secret_dir = tmp_path / "secretdir"
    load_trace.event("open requested", ext=".ddd", size_bytes=7)
    load_trace.header(types.SimpleNamespace(tk=types.SimpleNamespace(
        call=lambda *a: "8.6.13" if a[0] == "info" else "aqua")), "9.9")
    with load_trace.dialog("info", "SECRET DIALOG TITLE"):
        pass
    # pytest means no sampler (see test_no_sampler_starts_in_a_pytest_session_unless_asked):
    # this test asks for one, exactly as the app's first event() would start it
    threading.Thread(target=load_trace._watch, daemon=True).start()
    load_trace.event("again")
    time.sleep(0.5)                      # the real stack sits in time.sleep: a stall
    assert fast.exists()
    text = fast.read_text(encoding="utf-8")
    assert "\tstall\t" in text and "open requested" in text and "tk=8.6.13" in text
    assert "platform=" in text and "python=" in text
    assert oct(fast.stat().st_mode & 0o777) == "0o600"
    assert str(secret_dir) not in text and str(tmp_path) not in text
    assert "SECRET DIALOG TITLE" not in text and "title=other" in text
    assert str(fast) in capsys.readouterr().err
    first = text
    time.sleep(0.5)
    assert fast.read_text(encoding="utf-8") == first      # once


def _frame(name, filename):
    """A real frame whose code has this function and file name."""
    code = compile("def %s():\n    return sys._getframe()\n" % name, filename, "exec")
    ns = {"sys": sys}
    exec(code, ns)                       # noqa: S102 - test fixture
    return ns[name]()


def test_idle_mainloop_and_picker_stacks_are_not_stalls():
    assert load_trace._idle(_frame("mainloop", "/opt/frozen/tkinter/__init__.py"))
    assert load_trace._idle(_frame("mainloop", "C:\\py\\Lib\\tkinter\\__init__.pyc"))
    assert load_trace._idle(_frame("show", "/usr/lib/python3/tkinter/commondialog.py"))
    assert not load_trace._idle(_frame("update", "/usr/lib/python3/tkinter/__init__.py"))
    assert not load_trace._idle(_frame("mainloop", "/app/other.py"))
    assert not load_trace._idle(_frame("show", "/app/gui.py"))


def test_no_sampler_starts_in_a_pytest_session_unless_asked(monkeypatch):
    """A test run is not a user session: no sampler thread may appear behind a test's back.

    Reproduced here (round 2): with the sampler running, a full ``xvfb-run`` suite aborted
    with ``Fatal Python error: Aborted``, faulthandler showing the sampler thread
    *garbage-collecting* while tests built and dropped Tk roots — a Tk object finalized off
    the main thread calls Tcl from the wrong thread and aborts the process. Nothing the GUI
    can do about that from here, so the sampler simply does not run under pytest.
    """
    monkeypatch.setenv("not-a-real-var", "1")
    monkeypatch.delenv(load_trace.WATCHDOG_VAR, raising=False)
    monkeypatch.setattr(load_trace, "WATCHDOG", False)     # what the module computes here
    monkeypatch.setattr(load_trace, "_watchdog", None)
    before = [t for t in threading.enumerate() if t.name == "load-trace-watchdog"]
    load_trace.event("x")
    assert [t for t in threading.enumerate() if t.name == "load-trace-watchdog"] == before
    assert load_trace._watchdog is None
    assert any("\tx\t" in line for line in load_trace._ring)   # the ring still records


def test_the_module_decides_by_pytest_not_by_os_environ(monkeypatch):
    assert "pytest" in sys.modules
    monkeypatch.setattr(load_trace, "WATCHDOG", "pytest" not in sys.modules)
    monkeypatch.delenv(load_trace.WATCHDOG_VAR, raising=False)
    assert load_trace.sampler_allowed() is False
    monkeypatch.setenv(load_trace.WATCHDOG_VAR, "1")        # support: force it on
    assert load_trace.sampler_allowed() is True
    monkeypatch.setenv(load_trace.WATCHDOG_VAR, "0")
    assert load_trace.sampler_allowed() is False
    monkeypatch.setenv(load_trace.WATCHDOG_VAR, "junk")
    assert load_trace.sampler_allowed() is False
    monkeypatch.setattr(load_trace, "WATCHDOG", True)
    assert load_trace.sampler_allowed() is True
