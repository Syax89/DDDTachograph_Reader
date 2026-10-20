"""Opt-in load trace (``DDD_TRACE_LOAD=1``) for diagnosing a slow open on a user's machine.

Off: one boolean test per call, no file is created. On: one line per stage is appended
to ``~/ddd-reader-load-trace.txt`` (``<seconds since process start>\\t<stage>\\t<details>``)
and the path is printed once to stderr. Only the file extension, size, generation and
counts are ever written: no contents, identifiers, file name or directory.
"""
import contextlib
import os
import platform
import sys
import threading
import time

ENABLED = os.environ.get("DDD_TRACE_LOAD") == "1"
FILE_NAME = "ddd-reader-load-trace.txt"

_T0 = time.monotonic()              # import time ~ process start (gui imports this first)
_NULL = contextlib.nullcontext()
_lock = threading.Lock()
_announced = False
_stage = ""                         # innermost open span, to say where a slow update() ran
_opens = 0
_pump = {"calls": 0, "real": 0, "seconds": 0.0, "longest": 0.0, "longest_stage": ""}


def event(stage, **fields):
    """Append one trace line."""
    global _announced
    if not ENABLED:
        return
    line = "%.3f\t%s\t%s\n" % (time.monotonic() - _T0, stage,
                               " ".join(f"{k}={v}" for k, v in fields.items()))
    path = os.path.join(os.path.expanduser("~"), FILE_NAME)
    with _lock:
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:               # a read-only home must not break the app
            return
        if not _announced:
            _announced = True
            print(f"DDD_TRACE_LOAD: writing {path}", file=sys.stderr)


@contextlib.contextmanager
def _timed(stage, fields):
    global _stage
    outer, _stage = _stage, stage
    started = time.monotonic()
    event(stage + ".start", **fields)
    try:
        yield
    finally:
        _stage = outer
        event(stage + ".end", seconds=round(time.monotonic() - started, 4), **fields)


def span(stage, **fields):
    """``with span("x"):`` writes ``x.start`` and ``x.end`` (with its duration)."""
    return _timed(stage, fields) if ENABLED else _NULL


def header(root, version):
    """Startup line: platform, Python, Tk, windowing system, frozen, app version."""
    if ENABLED:
        event("startup", platform=platform.platform(), python=sys.version.replace("\n", " "),
              tk=root.tk.call("info", "patchlevel"),
              windowingsystem=root.tk.call("tk", "windowingsystem"),
              frozen=bool(getattr(sys, "frozen", False)), version=version)


def opened(path):
    """A file open was requested: number it and record extension and size only."""
    global _opens
    if ENABLED:
        _opens += 1
        try:
            size = os.path.getsize(path)
        except OSError:
            size = "?"
        event("open requested", **{"open number": _opens},
              ext=os.path.splitext(path)[1].lower(), size_bytes=size)


def pump_call():
    """Count one ``_pump_render`` call (real or throttled)."""
    if ENABLED:
        _pump["calls"] += 1


def pump_update(seconds):
    """Account one real ``update()``."""
    if ENABLED:
        _pump["real"] += 1
        _pump["seconds"] += seconds
        if seconds > _pump["longest"]:
            _pump["longest"], _pump["longest_stage"] = seconds, _stage


def pump_report():
    """Emit and reset the render-pump totals."""
    if ENABLED:
        event("pump_render", calls=_pump["calls"], real=_pump["real"],
              update_seconds=round(_pump["seconds"], 4),
              longest_update=round(_pump["longest"], 4),
              longest_stage=_pump["longest_stage"])
        _pump.update(calls=0, real=0, seconds=0.0, longest=0.0, longest_stage="")
