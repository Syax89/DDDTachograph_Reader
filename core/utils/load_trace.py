"""Load trace for diagnosing a slow open on a user's machine.

Always on, in memory only: the last ``RING_LINES`` lines sit in a ring buffer and a cheap
watchdog thread reports a real main-thread stall (>= 3 s) by dumping that ring once to
``~/ddd-reader-stall-report.txt`` (nothing is written in a normal session).

``DDD_TRACE_LOAD=1`` additionally writes live: one line per stage is appended
to ``~/ddd-reader-load-trace.txt`` (``<seconds since process start>\\t<stage>\\t<details>``)
and the path is printed once to stderr. Only the file extension, size, generation and
counts are ever written: no contents, identifiers, file name or directory.

A watchdog thread (started by the first line) samples the main thread's Python stack every
``INTERVAL`` seconds. When it stays the same for ``STALL_SAMPLES`` samples — that is a real
stall, not a wait the user recognizes as normal — the ring is written once to
``~/ddd-reader-stall-report.txt`` and the ``stall`` / ``stall.end`` lines go to the live file
as before. Only ``module.function:line`` of app/stdlib code, never arguments, locals or
dialog texts.

The sampler never starts in a pytest session (``WATCHDOG``): a test run builds and drops Tk
roots in a loop, and a collection on the sampler's thread then finalizes a Tk object off the
main thread, which aborts the whole process (see docs/developer/testing.md).
"""
import collections
import contextlib
import gc
import os
import platform
import sys
import threading
import time

ENABLED = os.environ.get("DDD_TRACE_LOAD") == "1"
FILE_NAME = "ddd-reader-load-trace.txt"

_T0 = time.monotonic()              # import time ~ process start (gui imports this first)
RING_LINES = 400                    # trace lines kept in memory (always; see _dump)
STALL_FILE = "ddd-reader-stall-report.txt"
STALL_REPORT = True                 # tests switch it off: a slow test is not a stall
_ring: collections.deque = collections.deque(maxlen=RING_LINES)  # written only on a stall
_header = ""                        # platform/python/Tk line(s) for the stall report
_dumped = False
_lock = threading.RLock()          # re-entrant: a GC pass can fire inside event() itself
_announced = False
_stage = ""                         # innermost open span, to say where a slow update() ran
_opens = 0
_gc = {"hooked": False, "start": 0.0, "passes": 0, "total": 0.0, "max": 0.0}
GC_MIN_SECONDS = 0.020
INTERVAL = 0.5                      # watchdog sampling period (seconds)
STALL_SAMPLES = 7                   # identical samples = 6 intervals = a stall (>= 3 s)
STACK_DEPTH = 12
FIXED_TITLES = ("File Note", "File Integrity Warning", "Rendering Error")  # app msgids
#: May ``event()`` start the sampler? Not under pytest: see the module docstring, and
#: ``DDD_STALL_WATCHDOG=0|1`` for support.
WATCHDOG = "pytest" not in sys.modules
WATCHDOG_VAR = "DDD_STALL_WATCHDOG"
_watchdog = None
_GEN = object()                     # identity of this module generation: see _watch()
_STDLIB = os.path.dirname(os.__file__)
_pump = {"calls": 0, "real": 0, "seconds": 0.0, "longest": 0.0, "longest_stage": ""}


def sampler_allowed():
    """Whether a sampler may start: ``DDD_STALL_WATCHDOG`` overrides ``WATCHDOG``.

    ``0``/``1`` force it off/on (support: reproduce a stall report from a test run or a
    script), anything else follows the module constant.
    """
    forced = os.environ.get(WATCHDOG_VAR, "")
    if forced in ("0", "1"):
        return forced == "1"
    return WATCHDOG


def event(stage, **fields):
    """Append one trace line."""
    global _announced, _watchdog
    if sampler_allowed():
        with _lock:
            if _watchdog is None:
                _watchdog = threading.Thread(target=_watch, name="load-trace-watchdog",
                                             daemon=True)
                _watchdog.start()
    line = "%.3f\t%s\t%s\n" % (time.monotonic() - _T0, stage,
                               " ".join(f"{k}={v}" for k, v in fields.items()))
    _ring.append(line)
    if not ENABLED:
        return
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


def _module(path):
    """App/stdlib module name of a source file; anything else: its bare file name."""
    path = path.replace("\\", "/")
    for root in ("/app/", "/core/"):
        if root in path:
            path = root[1:] + path.rsplit(root, 1)[1]
            break
    else:
        std = _STDLIB.replace("\\", "/") + "/"
        path = path[len(std):] if path.startswith(std) else os.path.basename(path)
    return path[:-3].replace("/", ".") if path.endswith(".py") else path


def _stack(frame):
    """Innermost-first ``(module, function, line)`` of the frame chain."""
    out = []
    while frame is not None and len(out) < STACK_DEPTH:
        out.append((_module(frame.f_code.co_filename), frame.f_code.co_name, frame.f_lineno))
        frame = frame.f_back
    return tuple(out)


def _idle(frame):
    """True for a wait that is not a stall: tkinter's ``mainloop`` (innermost frame) or the
    native file picker (``commondialog.show`` anywhere up the stack). Matched on function and
    file name, not on the module name, which a frozen build prints differently."""
    def path(f):
        return f.f_code.co_filename.replace("\\", "/")
    if frame is None:                 # between two calls: nothing is running
        return True
    if frame.f_code.co_name == "mainloop" and path(frame).endswith(
            ("tkinter/__init__.py", "tkinter/__init__.pyc")):
        return True
    while frame is not None:
        if frame.f_code.co_name == "show" and "commondialog" in path(frame):
            return True
        frame = frame.f_back
    return False


def _dump(stall):
    """Write the ring buffer, the platform header and the stall line (once, mode 0600)."""
    global _dumped
    if _dumped or not STALL_REPORT:
        return
    _dumped = True
    path = os.path.join(os.path.expanduser("~"), STALL_FILE)
    events = _ring.copy()             # C-level copy of the deque: no other thread can interleave
    if events and events[-1] == stall:
        events.pop()                  # already the headline: do not print it twice
    text = "".join(("# ddd-reader stall report (no file names, paths or contents)\n",
                    "# platform=%s\n# python=%s\n# frozen=%s\n" % (
                        platform.platform(), sys.version.replace("\n", " "),
                        bool(getattr(sys, "frozen", False))),
                    _header, stall, "# last events, oldest first:\n", *events))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, 0o600)
    except OSError:                   # a read-only home must not break the app
        return
    print(f"ddd-reader: stall report written to {path}", file=sys.stderr)


def _watch(token=None):
    """Sample the main thread every ``INTERVAL`` seconds until this sampler is retired.

    A sampler belongs to the module generation (``_GEN``) that started it: a reload — which
    only happens in tests — replaces that object, and the samplers of the old generation
    stop at their next tick instead of sampling (and reporting) alongside the new one.
    """
    token = _GEN if token is None else token
    main = threading.main_thread().ident
    last, count, since, reported = None, 0, 0.0, False
    while True:
        time.sleep(INTERVAL)
        if token is not _GEN:         # a newer generation owns the report now
            return
        try:
            frame = sys._current_frames().get(main)
        except Exception:             # noqa: BLE001 - sampling may never hurt the app
            continue
        stack = _stack(frame)
        idle = _idle(frame)
        if stack == last and not idle:
            count += 1
            if count == STALL_SAMPLES:
                reported = True
                fields = {"seconds>": "%g" % ((count - 1) * INTERVAL),
                          "stack": " <- ".join("%s.%s:%d" % f for f in stack)}
                event("stall", **fields)
                _dump(_ring[-1])
            continue
        if reported:
            event("stall.end", seconds=round(time.monotonic() - since, 2))
        last, count, since, reported = stack, 1, time.monotonic(), False


@contextlib.contextmanager
def dialog(kind, title):
    """Time one modal message box call; the title is written only if it is a fixed msgid."""
    fields = {"kind": kind, "title": title if title in FIXED_TITLES else "other"}
    started = time.monotonic()
    event("warn_when_idle.enter", **fields)
    try:
        yield
    finally:
        event("warn_when_idle.returned", blocked_seconds=round(time.monotonic() - started, 3),
              **fields)


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
    return _timed(stage, fields)


def header(root, version):
    """Startup line: platform, Python, Tk, windowing system, frozen, app version."""
    global _header
    tk, ws = root.tk.call("info", "patchlevel"), root.tk.call("tk", "windowingsystem")
    _header = f"# tk={tk} windowingsystem={ws} version={version}\n"
    event("startup", platform=platform.platform(), python=sys.version.replace("\n", " "),
          tk=tk, windowingsystem=ws, frozen=bool(getattr(sys, "frozen", False)), version=version)
    _gc_state()


def opened(path, source="?"):
    """A file open was requested: number it and record extension and size only."""
    global _opens
    _opens += 1
    try:
        size = os.path.getsize(path)
    except OSError:
        size = "?"
    event("open requested", **{"open number": _opens},
          ext=os.path.splitext(path)[1].lower(), size_bytes=size, source=source)
    _gc_state()


def picker(choose):
    """Run ``choose()`` (the file picker) and trace how long it was open and if a file was chosen."""
    started = time.monotonic()
    event("picker.opened")
    path = choose()
    event("picker.closed", seconds=round(time.monotonic() - started, 3),
          chosen="yes" if path else "no")
    return path


def _gc_callback(phase, info):
    if phase == "start":
        _gc["start"] = time.monotonic()
        return
    seconds = time.monotonic() - _gc["start"]
    _gc["passes"] += 1
    _gc["total"] += seconds
    _gc["max"] = max(_gc["max"], seconds)
    if seconds > GC_MIN_SECONDS:
        event("gc_pass", generation=info.get("generation"), seconds=round(seconds, 4),
              collected=info.get("collected"), during=_stage or "idle")


def _gc_state():
    if ENABLED:
        if not _gc["hooked"]:
            _gc["hooked"] = True
            gc.callbacks.append(_gc_callback)
        event("gc_state", enabled=gc.isenabled(), frozen=gc.get_freeze_count())


def pump_call():
    """Count one ``_pump_render`` call (real or throttled)."""
    _pump["calls"] += 1


def pump_update(seconds):
    """Account one real ``update()``."""
    _pump["real"] += 1
    _pump["seconds"] += seconds
    if seconds > _pump["longest"]:
        _pump["longest"], _pump["longest_stage"] = seconds, _stage


def pump_report():
    """Emit and reset the render-pump totals."""
    event("pump_render", calls=_pump["calls"], real=_pump["real"],
          update_seconds=round(_pump["seconds"], 4),
          longest_update=round(_pump["longest"], 4),
          longest_stage=_pump["longest_stage"])
    _pump.update(calls=0, real=0, seconds=0.0, longest=0.0, longest_stage="")


def idle_report():
    """Idle line extras: GC totals since the last report, and the GC state."""
    event("gc_summary", passes=_gc["passes"], total_seconds=round(_gc["total"], 4),
          max_seconds=round(_gc["max"], 4))
    _gc.update(passes=0, total=0.0, max=0.0)
    _gc_state()
