"""The busy bar must keep moving while a file renders.

``_start_parse`` greys out Open/Export, shows an indeterminate
``ttk.Progressbar`` and parses on a worker thread; the poll then hands the
result to ``_parse_done``, which renders **on the main thread**. An indeterminate
progress bar animates from a Tk *timer*, and timers are delivered only while the
event loop runs — so a render that never yields freezes the bar for exactly as
long as it takes. Measured on real files under Xvfb, that was 116-349 ms of a
motionless bar under greyed-out buttons, i.e. indistinguishable from a hang.

What is pinned here, against a real ``TachoExplorer`` (skipped cleanly when no
display is available, the same pattern as ``test_gui_summary_default.py``):

* the bar is mapped for as long as the render runs and unmapped afterwards —
  the render no longer ends before the busy state does;
* Open stays disabled for the whole render (a click during it cannot start a
  second open) and is re-enabled after, with ``_finish_parse`` still running in
  ``_parse_done``'s ``finally``;
* a second ``_start_parse`` issued *mid-render* is refused: no second worker,
  no second queue entry, and the tree it would have rebuilt while the first
  render walked it is byte-for-byte the tree a solo render produces;
* the render still ends on the file overview (the ``Summary`` node), so the
  event-loop pump did not move the default view;
* the event loop really turns during the render: the longest gap between two
  loop turns, measured with a self-rescheduling Tk timer (exactly what the
  bar's own animation timer sees), stays far below a generous bound.

The last test fails without ``_pump_render``: on the synthetic payload below the
un-pumped render is a single ~0.5 s block, several times the bound.
"""
import copy
import time
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import app.gui as gui  # noqa: E402
from app.gui import TachoExplorer  # noqa: E402
from app.i18n import _  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The node a parsed file opens on (see ``test_gui_summary_default.py``).
SUMMARY_LABEL = _("Summary")

#: Where the fake parse "writes" its file. Nothing reads it: the parser below
#: never touches the disk, it just has to be a path the GUI accepts.
FAKE_PATH = str(REPO_ROOT / "synthetic_busy_bar.ddd")
OTHER_PATH = str(REPO_ROOT / "synthetic_other.ddd")

#: The longest a render may hold the event loop, in seconds.
#:
#: Two bounds, and the looser of the two applies: one pump per
#: :data:`gui._RENDER_PUMP_INTERVAL` (16.7 ms) plus the slice it interrupts was
#: measured at 19-26 ms on the real sample files, so a flat 100 ms is already
#: generous; but a loaded machine can make a single ``update()`` slow, so the
#: gap may also be as large as ``LOOP_GAP_SHARE`` of the render's *own*
#: duration. The share is what keeps the test honest on a slow box without
#: letting it pass on a fast one: a render that never yields stands still for
#: the whole render, which is always more than its own share.
LOOP_GAP_BOUND = 0.1
LOOP_GAP_SHARE = 0.4

#: Small enough to render in tens of milliseconds: used by the state tests.
MEDIUM = dict(days=60, changes=10, blocks=4, samples=2000)
#: Big enough that the un-pumped render is several times ``LOOP_GAP_BOUND``
#: (~0.5 s here), so the stall test cannot pass by accident on a fast machine.
HEAVY = dict(days=240, changes=50, blocks=30, samples=30000)


def synthetic_payload(days=MEDIUM["days"], changes=MEDIUM["changes"],
                      blocks=MEDIUM["blocks"], samples=MEDIUM["samples"]):
    """A parse result shaped like the real one, sized by the caller.

    Only what the render walks is filled in: ``generations`` drives
    ``_populate_tree`` (a day hierarchy through ``Daily Activities`` and a
    per-block one through ``DetailedSpeed``), and the same day list is exposed
    as ``activities`` for the parts of ``_parse_done`` that read it.
    """
    activities = []
    for index in range(days):
        month = 1 + (index // 28) % 12
        day = 1 + index % 28
        activities.append({
            "date": f"{day:02d}/{month:02d}/2025",
            "odometer_km": 1000 + index * 17,
            "changes": [
                {"activity": "DRIVE" if n % 3 else "REST",
                 "time": f"{(n * 7) % 24:02d}:{(n * 11) % 60:02d}",
                 "slot": "First" if n % 2 else ""}
                for n in range(changes)
            ],
        })
    speed = [{"timestamp": "2025-05-01T00:00:00Z",
              "_chart_speeds_kmh": [60 + (n % 40) for n in range(samples)]}
             for _ in range(blocks)]
    return {
        "metadata": {"is_vu": True, "generation": "Generation 2",
                     "file_size_bytes": 245322},
        "generations": {"Generation 2": {"Daily Activities": activities,
                                         "DetailedSpeed": speed}},
        "activities": activities,
        "driver": {},
    }


class _FakeParser:
    """Stands in for ``app.engine.TachoParser`` so no fixture file is needed.

    ``parse`` hands back a fresh deep copy every time: the render writes
    ``_day_km`` into the day dicts it is given, so one payload shared by two
    parses would make the second render differ from the first for a reason that
    has nothing to do with what is being tested.
    """

    payload = None
    calls: list = []

    def __init__(self, path):
        self.path = path

    def parse(self):
        _FakeParser.calls.append(self.path)
        return copy.deepcopy(_FakeParser.payload)


class _Dialogs:
    """Message boxes would block a headless run: record them instead."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args))


@pytest.fixture
def explorer(monkeypatch):
    """A real TachoExplorer whose parses come from :class:`_FakeParser`."""
    monkeypatch.setattr(gui, "TachoParser", _FakeParser)
    monkeypatch.setattr(_FakeParser, "calls", [])
    monkeypatch.setattr(_FakeParser, "payload", synthetic_payload())
    monkeypatch.setattr(gui, "messagebox", _Dialogs())
    try:
        app = TachoExplorer()
    except gui.tk.TclError:
        pytest.skip("no display available")
    app.geometry("1280x760")
    app.update()
    try:
        yield app
    finally:
        _close(app)


def _close(app):
    """Close a window the way the product does, cancelling every timer."""
    try:
        for after_id in app.tk.call("after", "info"):
            app.tk.call("after", "cancel", after_id)
    except gui.tk.TclError:
        pass
    try:
        app.destroy()
    except gui.tk.TclError:
        pass


def _drive(app, timeout=120.0):
    """Turn the event loop until the busy state ends (no ``mainloop``).

    One more turn afterwards settles the deferred work the render leaves
    behind: ``_parse_done`` ends by scheduling the selection of the file
    overview with ``after_idle``, so the pane and the selection are only final
    once that idle callback has run.
    """
    deadline = time.perf_counter() + timeout
    while app._parsing or app._rendering:
        if time.perf_counter() > deadline:
            pytest.fail("the render never finished")
        app.update()
        time.sleep(0.001)
    app.update()


def _observe_pumps(app, monkeypatch):
    """Record what the UI shows each time the render pumps the event loop.

    A *pump* is the only way the loop turns while a render holds the main
    thread (that is the whole point of ``_pump_render``), so observing from
    there samples the state the user would see at that instant — which is the
    only way to catch "Open is disabled *while the render runs*" before the
    ``finally`` restores it.
    """
    observations = []
    real_update = app.update

    def spy():
        if app._rendering:
            observations.append({
                "bar_mapped": bool(app.progress.winfo_ismapped()),
                "bar_manager": app.progress.winfo_manager(),
                "open_state": str(app.btn_open.cget("state")),
                "parsing": app._parsing,
            })
        real_update()

    monkeypatch.setattr(app, "update", spy)
    return observations


def _fingerprint(app):
    """Everything a render decides: the tree, the selection, the pane."""
    tree = []

    def walk(parent, depth):
        for iid in app.tree.get_children(parent):
            payload = app._payloads.get(iid)
            try:
                rows = len(payload[2]) if payload else None
            except TypeError:
                rows = None
            tree.append((depth, app.tree.item(iid, "text"),
                         app.tree.item(iid, "open"), rows))
            walk(iid, depth + 1)

    walk("", 0)
    return {
        "tree": tree,
        "selection": [app.tree.item(iid, "text") for iid in app.tree.selection()],
        "auto_select": (app.tree.item(app._auto_select_iid, "text")
                        if app.tree.exists(app._auto_select_iid) else None),
        "table": (app.table.title_lbl.cget("text"),
                  len(app.table.tv.get_children())),
        "status": app.status.cget("text"),
        "file": app.lbl_file.cget("text"),
        "open": str(app.btn_open.cget("state")),
        "export": str(app.btn_export.cget("state")),
        "bar": (app.progress.winfo_manager(), bool(app.progress.winfo_ismapped())),
        "parsing": app._parsing,
        "rendering": app._rendering,
    }


# ── the busy state ─────────────────────────────────────────────────────────

def test_the_progress_bar_is_mapped_while_the_file_renders(explorer, monkeypatch):
    """The bar has to be on screen for the whole render, not just for the parse.

    The render is where the time goes, so a bar that disappears (or is never
    laid out) before it starts is exactly the frozen-bar case: the user sees
    disabled buttons and nothing moving.
    """
    app = explorer
    observations = _observe_pumps(app, monkeypatch)

    app._start_parse(FAKE_PATH)
    _drive(app)

    assert observations, "the render never pumped the event loop"
    assert all(obs["bar_manager"] for obs in observations), \
        "the progress bar was unpacked before the render ended"
    assert any(obs["bar_mapped"] for obs in observations), \
        "the progress bar was never mapped while the render ran"
    assert not app.progress.winfo_manager(), "the bar is still packed afterwards"
    assert not app.progress.winfo_ismapped()


def test_open_stays_disabled_until_the_render_ends(explorer, monkeypatch):
    """A click during the render must not start a second open.

    ``_parsing`` is held True across the render on purpose (see ``_parse_done``):
    it is what refuses Open, a drop and the recent list while the tree is being
    rebuilt. The ``finally`` then restores the idle state — including the
    progress bar, which must be gone even though ``_finish_parse`` runs after
    the render has already handed the selection over.
    """
    app = explorer
    observations = _observe_pumps(app, monkeypatch)

    app._start_parse(FAKE_PATH)
    _drive(app)

    assert observations
    assert all(obs["open_state"] == "disabled" for obs in observations), \
        "Open was clickable while the render was still running"
    assert all(obs["parsing"] for obs in observations)
    assert str(app.btn_open.cget("state")) == "normal"
    assert str(app.btn_export.cget("state")) == "normal"
    assert not app._parsing
    assert not app._rendering


# ── re-entrancy ────────────────────────────────────────────────────────────

def test_a_second_open_issued_mid_render_is_refused(explorer, monkeypatch):
    """Pumping the loop makes a second open *possible* mid-render; it must not
    run a second render on top of the first.

    The tree of the interrupted render is compared with the tree the same
    payload produces on its own: a second render would have rebuilt it under
    the first one's feet, so the two would differ.
    """
    app = explorer
    app._start_parse(FAKE_PATH)
    _drive(app)
    solo = _fingerprint(app)

    attempted = []
    real_update = app.update

    def spy():
        if app._rendering and not attempted:
            attempted.append(app._start_parse(OTHER_PATH))
        real_update()

    monkeypatch.setattr(app, "update", spy)
    app._start_parse(FAKE_PATH)
    _drive(app)

    assert attempted, "the render never pumped the event loop"
    assert _FakeParser.calls == [FAKE_PATH, FAKE_PATH], \
        "a second parse was started while the first result was being rendered"
    assert _fingerprint(app) == solo, \
        "the refused open changed the tree the render had produced"


def test_a_parse_result_arriving_mid_render_is_dropped(explorer, monkeypatch):
    """The same refusal one layer down: ``_parse_done`` itself.

    Nothing in the UI can reach it (``_start_parse`` is refused and the poll is
    one-shot), so this pins the guard that keeps the invariant true if it ever
    is reached: the render in progress wins, the superseded result is dropped,
    and the busy state is still restored by the running render's ``finally``.
    """
    app = explorer
    second = synthetic_payload(days=3, changes=2, blocks=1, samples=10)
    injected = []
    real_update = app.update

    def spy():
        if app._rendering and not injected:
            injected.append(True)
            app._parse_done(copy.deepcopy(second), OTHER_PATH)
        real_update()

    monkeypatch.setattr(app, "update", spy)
    app._start_parse(FAKE_PATH)
    _drive(app)

    assert injected
    assert app.current_file == FAKE_PATH, "the dropped result was rendered anyway"
    assert str(app.btn_open.cget("state")) == "normal"
    assert not app._parsing
    assert not app._rendering


def test_no_exception_escapes_when_the_window_is_closed_mid_render(explorer,
                                                                  monkeypatch):
    """The pump makes "close the window while it renders" reachable.

    With the window gone there is nothing left to draw and no widget left to
    restore, so the render must stop there — ``_RenderAbandoned`` — instead of
    walking a destroyed widget tree until Tk reports a traceback out of a
    callback. That traceback is what this test looks for: tkinter funnels it
    through ``report_callback_exception``, which is patched to record instead of
    printing.
    """
    app = explorer
    escapes = []
    monkeypatch.setattr(app, "report_callback_exception",
                        lambda *exc: escapes.append(exc))
    real_update = app.update

    def spy():
        if app._rendering:
            app.update = real_update
            app._on_close()
        real_update()

    monkeypatch.setattr(app, "update", spy)
    app._start_parse(FAKE_PATH)
    deadline = time.perf_counter() + 60
    while app._parsing or app._rendering:
        if time.perf_counter() > deadline:
            pytest.fail("the render never finished")
        try:
            real_update()
        except gui.tk.TclError:
            break  # the window is gone, as the test intended
        time.sleep(0.001)

    assert not escapes, f"the closed window reported {escapes!r}"
    assert not app._rendering
    assert not app._parsing, "the busy state outlived the window"


def test_a_second_tree_rebuild_cannot_nest_inside_the_first(explorer, monkeypatch):
    """``_refresh_data_text`` rebuilds the tree too, and it pumps while doing it.

    A second toggle delivered by that pump would rebuild the tree inside the
    rebuild that owns it (and clear ``_rendering`` while the outer one still
    runs), so the guard refuses it the same way ``_start_parse`` does.
    """
    app = explorer
    app._start_parse(FAKE_PATH)
    _drive(app)

    rebuilt = []
    real_populate = app._populate_tree
    monkeypatch.setattr(app, "_populate_tree",
                        lambda data: (rebuilt.append(data), real_populate(data))[1])

    app._rendering = True
    try:
        app._refresh_data_text()
    finally:
        app._rendering = False
    assert rebuilt == [], "a tree rebuild was nested inside another one"

    app._refresh_data_text()
    assert len(rebuilt) == 1, "the rebuild no longer runs when nothing owns it"


def test_a_language_switch_during_a_translate_rebuild_is_refused(explorer,
                                                                 monkeypatch):
    """The one render that does **not** set ``_parsing`` must still refuse it.

    ``_switch_language`` refuses while a parse or an export runs because the
    restart it schedules tears the window down (``_shutdown`` + ``destroy``).
    A parse render is covered by ``_parsing``, which is held for its whole
    length — but the translate-data rebuild (:meth:`_refresh_data_text`) raises
    ``_rendering`` alone, and it pumps the event loop while it walks the tree.
    The pump delivers the language menu like any other click, so this drives the
    *real* window: parse a file, start the rebuild, and hand the switch to it
    from inside its own pump — the moment a user would have produced it.

    Without ``_rendering`` in the guard the switch is accepted mid-rebuild: the
    language is persisted and ``after_idle(_finish_restart)`` is queued on top
    of a rebuild that is still using the widgets.
    """
    app = explorer
    app._start_parse(FAKE_PATH)
    _drive(app)

    saved, restarts, delivered = [], [], []
    # A language that is *not* the one in use: ``_switch_language`` returns
    # silently for the current one, so a fixed code could make this test pass
    # without reaching the guard at all.
    other = next(code for code in gui.LANGUAGES if code != app._language)
    monkeypatch.setattr(gui, "save_language",
                        lambda code: saved.append(code) or True)
    # The restart is recorded, not run: running it is exactly what the refusal
    # prevents, and it would destroy the window the assertions below inspect.
    monkeypatch.setattr(app, "_finish_restart", lambda: restarts.append("restart"))
    real_update = app.update

    def spy():
        if app._rendering and not app._parsing and not delivered:
            delivered.append("switch")
            app._language_var.set(other)
            app._switch_language(other)
        real_update()

    monkeypatch.setattr(app, "update", spy)
    # The pump is rate-limited by wall clock (``_RENDER_PUMP_INTERVAL``), and the
    # parse above just used it: on a fast machine a rebuild that starts right
    # after it would skip every pump and the test would prove nothing. Clear the
    # gate so the first slice of the rebuild pumps, as it does for a user.
    app._pump_due = 0.0
    app._translate_data_var.set(not app._translate_data)
    app._toggle_translate_data()
    app.update()

    assert delivered, "the translate rebuild never pumped the event loop"
    assert saved == [], \
        "the language was persisted while a rebuild owned the tree"
    assert restarts == [], (
        "a restart was scheduled on top of the running rebuild: its "
        "_finish_restart would _shutdown() and destroy() the window the "
        "rebuild is still walking")
    assert app._restart_requested is False
    assert app._language_var.get() == app._language, \
        "the menu radio was not put back on the language in use"
    # ... and the window is intact: the rebuild finished, the tree is the one the
    # parse produced, the file is still the open one and the busy state is gone.
    assert not app._rendering
    assert not app._parsing
    assert app.winfo_exists()
    assert app.current_file == FAKE_PATH
    top_level = [app.tree.item(iid, "text") for iid in app.tree.get_children("")]
    assert top_level and top_level[0] == SUMMARY_LABEL, top_level
    assert app.tree.selection(), "the rebuild lost the selection it restores"
    assert str(app.btn_open.cget("state")) == "normal"


def test_a_translate_toggle_during_a_rebuild_keeps_the_tick_and_the_tree_in_step(
        explorer, monkeypatch):
    """The toggle writes the preference *before* the rebuild that applies it.

    ``_toggle_translate_data`` persists the flag, flips the process-global
    setting and only then asks ``_refresh_data_text`` to repopulate the tree —
    which refuses while a rebuild is running. A toggle delivered by the running
    rebuild's own pump would therefore leave the setting, the menu tick and the
    rows disagreeing: the preference says "translate", every cell still shows
    the file's own words, and nothing ever rebuilds them. So the toggle is
    refused as a whole and the tick goes back, like every other busy guard.
    """
    app = explorer
    app._start_parse(FAKE_PATH)
    _drive(app)
    before = app._translate_data
    applied = not before          # what the outer (accepted) toggle applies

    rebuilds = []
    real_populate = app._populate_tree
    monkeypatch.setattr(app, "_populate_tree",
                        lambda data: (rebuilds.append(data), real_populate(data))[1])
    delivered = []
    real_update = app.update

    def spy():
        if app._rendering and not app._parsing and not delivered:
            delivered.append("toggle")
            # A second click on the same checkbutton: the tick goes back, and the
            # command that follows it is what the running rebuild's pump sees.
            app._translate_data_var.set(before)
            app._toggle_translate_data()
        real_update()

    monkeypatch.setattr(app, "update", spy)
    app._pump_due = 0.0  # see the language test above: make the first pump due
    app._translate_data_var.set(applied)
    app._toggle_translate_data()
    app.update()

    assert delivered, "the translate rebuild never pumped the event loop"
    assert app._translate_data is applied, (
        "the preference was flipped back while the rebuild that applies it was "
        "refused: the setting, the tick and the rows would disagree")
    assert app._translate_data_var.get() is applied, \
        "the menu tick stayed on a preference the window never applied"
    assert len(rebuilds) == 1, \
        "the tree was rebuilt more than once for one toggle"


def test_an_export_started_mid_rebuild_is_refused(explorer, monkeypatch):
    """The export menu is reachable mid-rebuild, and its picker is modal.

    The toolbar disables Export for the whole of a parse, but the translate-data
    rebuild only owns the tree: the menu stays enabled, and the pump delivers a
    click on it while ``_rendering`` is true. ``asksaveasfilename`` is a modal
    dialog, so opening it there would hold the render — and the busy bar it
    keeps moving — for as long as the user leaves the dialog open.
    """
    app = explorer
    app._start_parse(FAKE_PATH)
    _drive(app)

    asked = []
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename",
                        lambda **kwargs: asked.append(kwargs) or "")
    delivered = []
    real_update = app.update

    def spy():
        if app._rendering and not app._parsing and not delivered:
            delivered.append("export")
            app._export_pdf()
            app._export_excel()
            app._export_csv()
            app._export_json()
        real_update()

    monkeypatch.setattr(app, "update", spy)
    app._pump_due = 0.0  # see the language test above: make the first pump due
    app._translate_data_var.set(not app._translate_data)
    app._toggle_translate_data()
    app.update()

    assert delivered, "the translate rebuild never pumped the event loop"
    assert asked == [], (
        "a save dialog was opened on top of the running rebuild — it is modal, "
        "so the render (and its busy bar) stands still until it is dismissed")
    assert not app._exporting
    assert not app._rendering


# ── the render still ends where it did ─────────────────────────────────────

def test_the_render_ends_on_the_summary_node(explorer):
    """Pumping the loop must not move the default view off the file overview."""
    app = explorer
    app._start_parse(FAKE_PATH)
    _drive(app)

    top_level = [app.tree.item(iid, "text") for iid in app.tree.get_children("")]
    assert top_level[0] == SUMMARY_LABEL
    assert app._auto_select_iid == app.tree.get_children("")[0]
    assert [app.tree.item(iid, "text") for iid in app.tree.selection()] \
        == [SUMMARY_LABEL]
    # the overview's own panel is what the pane shows, not an empty placeholder
    assert app.table.tv.get_children()


# ── the point of the whole exercise ────────────────────────────────────────

def test_the_event_loop_keeps_turning_during_the_render(explorer, monkeypatch):
    """The longest gap between event-loop turns during a render, measured.

    A self-rescheduling Tk timer fires only when the loop runs, which is exactly
    the contract the progress bar's animation timer has: the gap between two
    firings is the longest the bar can have stood still. A nested ``update()``
    from ``_pump_render`` delivers timers, so it counts as a turn — which is the
    whole fix.

    ``HEAVY`` is sized so the un-pumped render blocks for several times
    ``LOOP_GAP_BOUND``; reverted, this test fails on the bound (and on the "no
    turn at all" count) rather than on a wall-clock exact number.
    """
    app = explorer
    monkeypatch.setattr(_FakeParser, "payload", synthetic_payload(**HEAVY))

    ticks = []
    spans = []
    real_update = app.update
    real_done = app._parse_done

    def tick():
        ticks.append(time.perf_counter())
        app.after(2, tick)

    def timed_done(data, path):
        start = time.perf_counter()
        try:
            return real_done(data, path)
        finally:
            spans.append((start, time.perf_counter()))

    monkeypatch.setattr(app, "_parse_done", timed_done)
    app.after(2, tick)
    app._start_parse(FAKE_PATH)
    while app._parsing or app._rendering:
        real_update()
        time.sleep(0.001)

    assert len(spans) == 1
    started, ended = spans[0]
    inside = [t for t in ticks if started <= t <= ended]
    if not inside:
        worst = ended - started
    else:
        gaps = [second - first
                for first, second in zip(inside, inside[1:], strict=False)]
        gaps.append(inside[0] - started)
        gaps.append(ended - inside[-1])
        worst = max(gaps)

    span = ended - started
    bound = max(LOOP_GAP_BOUND, LOOP_GAP_SHARE * span)
    assert worst < bound, (
        f"the event loop stood still for {worst * 1000:.0f} ms of a "
        f"{span * 1000:.0f} ms render ({len(inside)} turns, bound "
        f"{bound * 1000:.0f} ms) — the busy bar freezes for that long")
    assert len(inside) >= 3, (
        f"the loop turned only {len(inside)} time(s) during a "
        f"{(ended - started) * 1000:.0f} ms render")
