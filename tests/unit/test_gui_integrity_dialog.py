"""The integrity notice must actually reach the screen, on macOS too.

The owner's report is precise: for a card file whose first two bytes were
altered, the banner at the bottom of the window DOES appear and clicking it
opens the popup — what never appears is the popup the app opens *by itself* when
the file is opened (``_check_integrity`` → ``_warn_when_idle`` → message box).
The macOS build differs from Linux in one respect that matters here: it renders
with ``update_idletasks()`` (``_PUMP_USES_EVENTS`` False), never ``update()``.

Neither the detection nor the banner is at fault, and both are exercised here
through the real path (``_open_file`` → ``after(150)`` → worker parse →
``_parse_done`` → ``_check_integrity``) in **idle** pump mode, which is the mode
that build runs. What the tests pin:

* the wait for the render is a *timer*, not an idle callback. ``update_idletasks()``
  runs the whole idle queue — ``test_a_re_arming_idle_callback_runs_again_inside_one_idle_drain``
  shows a re-arming idle callback running over and over inside one drain — so an
  idle ``_warn_when_idle`` re-enters mid-render and can be lost in the queue it
  keeps busy;
* the window is laid out and raised before the box, so a modal box cannot open
  behind it or over an unfinished window;
* the box arrives once, after the render has finished (never during it), with
  the banner already set;
* the text of a card whose signature does not verify never reads as an all-clear.

Synthetic material throughout (``tests.unit.card_crypto``, real RSA) plus the
generated mock downloads — never a corpus file.
"""
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import app.gui as gui  # noqa: E402
from app.engine import TachoParser  # noqa: E402
from core.crypto.signature import SignatureValidator  # noqa: E402
from tests.unit.card_crypto import (  # noqa: E402
    g1_cert_records,
    g1_core_payloads,
    g1_identity,
    parse_bytes,
    signed_pairs,
    stap,
    trust_store,
)
from tests.unit.test_gui_summary_default import close, new_explorer  # noqa: E402

MOCK_DIR = Path(__file__).resolve().parents[2] / "tests" / "mock_data"

#: A generic EF_ICC payload (Annex 1B §2.7). A card download opens with this
#: record, which is why the owner's two-byte edit lands on it.
EF_ICC_PAYLOAD = (b"\x00" + b"\x11" * 8 + b"\x22" * 8 + b"\x03"
                  + b"\x44" * 4 + b"\xaa\xbb" + b"\x00")


class _Boxes:
    """Record message boxes instead of showing them, with the app's state then."""

    def __init__(self, app):
        self.app = app
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, self.app._parsing, self.app._rendering))
        return record


@pytest.fixture
def idle_mode(monkeypatch):
    """The macOS render pump: ``update_idletasks()`` only, never ``update()``."""
    monkeypatch.setattr(gui, "_PUMP_USES_EVENTS", False)


@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        close(app)


def _boxes(app, monkeypatch):
    recorder = _Boxes(app)
    monkeypatch.setattr(gui, "messagebox", recorder)
    return recorder


def _wait(app, condition, timeout=60.0):
    """Turn the main loop until *condition* holds (the product's own loop)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end and not condition():
        app.update()
        time.sleep(0.01)
    assert condition()


def _settle(app, seconds=0.3):
    """Keep the loop turning a little longer, to catch a second (wrong) box."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.update()
        time.sleep(0.01)


#: One real, full-core G1 card, built once (RSA key generation is the slow part).
@pytest.fixture(scope="module")
def g1_card():
    """``(identity, payloads, card bytes)`` — a standard card download."""
    identity = g1_identity()
    payloads = g1_core_payloads()
    card = (stap(0x0002, 0x00, EF_ICC_PAYLOAD)
            + g1_cert_records(identity["card_cert"], identity["msca_cert"])
            + signed_pairs(payloads, identity["card_key"], 1))
    return identity, payloads, card


# ── the mechanism: a timer, not an idle callback ──────────────────────────

def test_the_wait_for_the_render_is_a_timer_not_an_idle_callback(explorer):
    """An idle wait is re-entered (and starved) by the render's own pumps."""
    app = explorer
    before = set(app.tk.call("after", "info"))
    app._rendering = True
    app._warn_when_idle("File Note", "message")
    pending = [aid for aid in app.tk.call("after", "info") if aid not in before]

    assert len(pending) == 1, pending
    _script, kind = app.tk.call("after", "info", pending[0])
    assert kind == "timer", (
        "an idle wait runs inside every update_idletasks() the render pumps")
    app.tk.call("after", "cancel", pending[0])


def test_a_re_arming_idle_callback_runs_again_inside_one_idle_drain(explorer):
    """Why the wait above is a timer: one drain re-runs a re-arming idle handler.

    Tk's ``update idletasks`` loops until no idle work is left, and a handler
    that schedules itself with ``after idle`` is new idle work every time. A
    ``_warn_when_idle`` that re-armed itself while ``_rendering`` was still set
    would therefore run in a tight loop inside the render's next pump.
    """
    app = explorer
    seen = []

    def rearm():
        seen.append(1)
        if len(seen) < 5:                 # capped: the point is the re-entry
            app.after_idle(rearm)

    app.after_idle(rearm)
    app.update_idletasks()

    assert len(seen) == 5, "one update_idletasks() re-ran the re-armed handler"


def test_the_window_is_laid_out_and_raised_before_the_box(explorer, monkeypatch):
    """A modal box over an unfinished or background window is a lost notice."""
    app = explorer
    order = []

    class _Boxes:
        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: order.append("box")

    monkeypatch.setattr(app, "update_idletasks", lambda: order.append("idle"))
    monkeypatch.setattr(app, "lift", lambda: order.append("lift"))
    monkeypatch.setattr(gui, "messagebox", _Boxes())

    app._warn_when_idle("File Note", "message")

    assert order == ["idle", "lift", "box"]


def test_a_widgetless_double_still_gets_its_box(monkeypatch):
    """The trace test's stand-in has no window: the box must not depend on one."""
    shown = []

    class _Boxes:
        def __getattr__(self, name):
            return lambda _title, message: shown.append((name, message))

    monkeypatch.setattr(gui, "messagebox", _Boxes())
    box_type = type("Box", (gui.TachoExplorer,),
                    {"_parsing": False, "_rendering": False, "_destroyed": False})
    box = object.__new__(box_type)

    gui.TachoExplorer._warn_when_idle(box, "File Note", "message", "showinfo")

    assert shown == [("showinfo", "message")]


def test_idle_mode_delivers_a_warning_queued_during_a_render(explorer, monkeypatch):
    """A box requested mid-render waits for the flags and then opens by itself."""
    app = explorer
    boxes = _boxes(app, monkeypatch)
    app._rendering = True
    app._warn_when_idle("File Integrity Warning", "message")
    _settle(app, 0.1)
    assert boxes.calls == [], "shown while the render was still running"

    app._rendering = False
    _wait(app, lambda: boxes.calls)

    assert len(boxes.calls) == 1
    assert boxes.calls[0][2:] == (False, False)


def test_the_box_never_opens_inside_the_pane_render(monkeypatch, tmp_path, g1_card):
    """No modal box from inside a pane's own render, in the idle pump mode.

    The deferred ``<<TreeviewSelect>>`` render is an idle callback, and the idle
    pump drains the queue it runs in: anything else parked in that queue can be
    delivered *from inside* the pane's render, with the pane half-built and Tk in
    the middle of a drain. A modal box there is exactly the kind of call that can
    be swallowed on Aqua. The box belongs after the last render, not in it.
    """
    monkeypatch.setattr(gui, "_PUMP_USES_EVENTS", False)
    identity, _payloads, card = g1_card
    tampered = bytearray(card)
    tampered[0], tampered[1] = 0x00, 0x03
    path = tmp_path / "tampered_header.ddd"
    path.write_bytes(bytes(tampered))

    order = []
    for name in ("_show_summary", "_show_table"):
        real = getattr(gui.TachoExplorer, name)

        def render(self, *args, _real=real, _name=name, **kwargs):
            order.append(_name + ".enter")
            try:
                return _real(self, *args, **kwargs)
            finally:
                order.append(_name + ".exit")

        monkeypatch.setattr(gui.TachoExplorer, name, render)

    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        def _trusted(target):
            parser = TachoParser(target)
            parser.validator = SignatureValidator(certs_dir=certs_dir)
            return parser

        monkeypatch.setattr(gui, "TachoParser", _trusted)
        app = new_explorer(monkeypatch)
        boxes = _Boxes(app)
        monkeypatch.setattr(gui, "messagebox", type("B", (), {
            "__getattr__": staticmethod(
                lambda _name: lambda *_a, **_k: order.append("box"))})())
        monkeypatch.setattr(gui.filedialog, "askopenfilename",
                            lambda **_kwargs: str(path))
        try:
            app._open_file()
            _wait(app, lambda: "box" in order)
        finally:
            close(app)
    del boxes

    assert "box" in order, order
    depth = 0
    for marker in order:
        if marker.endswith(".enter"):
            depth += 1
        elif marker.endswith(".exit"):
            depth -= 1
        elif marker == "box":
            assert depth == 0, f"the box opened inside a pane render: {order}"


# ── the whole path, in the macOS pump mode ────────────────────────────────

def test_idle_pump_mode_shows_the_note_after_the_render(
        idle_mode, monkeypatch, tmp_path, g1_card):
    """The owner's case: two leading bytes altered, every signature still valid.

    Runs the real entry point (``_open_file`` → the picker's ``after(150)`` →
    worker parse → ``_parse_done`` → ``_check_integrity``) with the macOS idle
    pump. The note must open by itself, once, over a finished window.
    """
    identity, _payloads, card = g1_card
    tampered = bytearray(card)
    tampered[0], tampered[1] = 0x00, 0x03
    path = tmp_path / "tampered_header.ddd"
    path.write_bytes(bytes(tampered))

    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        def _trusted(target):
            parser = TachoParser(target)
            parser.validator = SignatureValidator(certs_dir=certs_dir)
            return parser

        monkeypatch.setattr(gui, "TachoParser", _trusted)
        app = new_explorer(monkeypatch)
        boxes = _boxes(app, monkeypatch)
        monkeypatch.setattr(gui.filedialog, "askopenfilename",
                            lambda **_kwargs: str(path))
        try:
            app._open_file()
            _wait(app, lambda: boxes.calls)

            assert len(boxes.calls) == 1, boxes.calls
            kind, args, parsing, rendering = boxes.calls[0]
            assert (parsing, rendering) == (False, False), (
                "the box was opened while the file was still being opened")
            assert (kind, args[0]) == ("showinfo", gui._("File Note"))
            assert "0x0003" in args[1]
            # the note states the counts, never an all-clear
            assert "0 of 9 signature(s) could not be verified" in args[1]
            assert "note(s)" in app.integrity_banner.cget("text")
            _settle(app)
            assert len(boxes.calls) == 1, "the notice must arrive once"
        finally:
            close(app)


def test_a_failing_signature_still_raises_the_warning_dialog(idle_mode, monkeypatch):
    """The mock card's signatures do not verify: that must reach the screen."""
    if not (MOCK_DIR / "mock_g2_card.ddd").is_file():
        pytest.skip("mocks not generated")
    app = new_explorer(monkeypatch)
    boxes = _boxes(app, monkeypatch)
    try:
        app._start_parse(str(MOCK_DIR / "mock_g2_card.ddd"))
        _wait(app, lambda: boxes.calls)

        assert len(boxes.calls) == 1, boxes.calls
        kind, args, parsing, rendering = boxes.calls[0]
        assert (parsing, rendering) == (False, False)
        assert (kind, args[0]) == ("showwarning", gui._("File Integrity Warning"))
        assert "warning(s)" in app.integrity_banner.cget("text")
    finally:
        close(app)


# ── the words: never an all-clear for a file with a broken signature ──────

def test_a_broken_signature_is_never_reported_as_verified(
        g1_card, tmp_path, monkeypatch):
    """The verdict is Unverified, so the text may not read as an all-clear.

    The card is a complete, valid G1 download with exactly one byte changed
    inside a signed EF body: every EF is present, the framing is intact, and one
    signature cannot verify. The banner must be the *warning* banner and the
    message must carry the count of unverified signatures — never a sentence
    stating that the signatures verified, and never a claim of completeness.
    """
    identity, payloads, card = g1_card
    broken = bytearray(card)
    record = stap(0x0504, 0x00, payloads[0x0504])
    start = broken.find(record)
    assert start > 0
    broken[start + len(record) - 1] ^= 0xFF          # keep every length intact
    path = os.path.join(str(tmp_path), "broken_signature.ddd")
    with open(path, "wb") as handle:
        handle.write(bytes(broken))

    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        _parser, data = parse_bytes(bytes(broken), certs_dir)

    assert data["metadata"]["integrity_check"].startswith("Unverified"), \
        data["metadata"]["integrity_check"]
    assert data["ef_signature_verification"]["failed"] == 1

    app = new_explorer(monkeypatch)
    boxes = _boxes(app, monkeypatch)
    try:
        app._parse_done(data, path)
        _wait(app, lambda: boxes.calls)

        kind, args, _parsing, _rendering = boxes.calls[0]
        message = args[1]
        assert kind == "showwarning"
        assert "warning(s)" in app.integrity_banner.cget("text")
        assert "8/9 EF signature(s) verified" in message
        assert "1 NOT validated" in message
        # no all-clear wording anywhere, and no completeness claim
        assert "all 9" not in message.lower()
        assert "complete" not in message.lower().replace("incomplete", "")
        assert "100" not in message
    finally:
        close(app)
