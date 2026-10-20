"""The integrity banner must not call an informational note a warning.

A card image relayed through the vehicle unit is the standard card plus the two
transfer bytes the saving tool kept (DDP_050 strips them for the storage form). The
app says so — but on a healthy file that note is *not* a warning, and the status bar
must not read "1 integrity warning(s)". So:

* real warnings only  -> the existing warning wording and the warning triangle;
* warnings + notices  -> warning wording, count = real warnings only, the dialog
  lists the warnings first and the notices after them;
* notices only        -> a neutral wording ("{count} note(s) — click for details"),
  no warning triangle, a neutral icon already used elsewhere in the app;
* nothing             -> no banner, no icon, no tab stop.

Everything is asserted through the widget's own ``cget`` values, never a screenshot.
"""
import os

import pytest

pytest.importorskip("tkinter")

from app import gui  # noqa: E402
from app.engine import TachoParser  # noqa: E402
from core.registry.registry import DecoderRegistry  # noqa: E402
from tests.integration import generate_mock_ddd as mock  # noqa: E402
from tests.unit.real_data import require_real_file  # noqa: E402
from tests.unit.test_empty_state import close, new_explorer  # noqa: E402

WARNING_TEXT = "{count} integrity warning(s) \u2014 click for details"
NOTE_TEXT = "{count} note(s) \u2014 click for details"
NOTICE_PREFIX = "\u2022 Driver-card image downloaded through the vehicle unit"


@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        gui.DayDetailWindow._open_windows.clear()
        close(app)


def _parse(tmp_path, name, data):
    path = os.path.join(str(tmp_path), name)
    with open(path, "wb") as handle:
        handle.write(data)
    DecoderRegistry.reset_instance()
    return TachoParser(path).parse(), path


def _mock_card(tmp_path, kind="g1"):
    path = os.path.join(str(tmp_path), f"mock_{kind}.ddd")
    {"g1": mock.generate_g1_card, "g2": mock.generate_g2_card}[kind](path)
    with open(path, "rb") as handle:
        return handle.read()


def _render(app, result, path):
    app._parse_done(result, path)
    app.update()


def _banner(app):
    return (app.integrity_banner.cget("text"),
            str(app.integrity_banner.cget("image")).strip("(),' "),
            str(app.integrity_banner.cget("takefocus")))


def _image_name(app, name):
    """The Tk image name the widget would show for *name* (same cache, so equal)."""
    icon = str(gui._icon(name, 16, app.integrity_banner))
    return icon.strip("(),' ")


def _as_healthy(result):
    """A result whose card signatures verified (the mock's certificates are
    placeholders, so the crypto verdict is normalised here: these tests drive the
    banner branch, not the signature layer)."""
    result["ef_signature_verification"] = {"failed": 0, "skipped": 0,
                                           "verified": 9, "total": 9}
    result["metadata"]["integrity_check"] = "Verified"
    return result


def test_healthy_wrapped_card_shows_the_note_wording_and_no_warning_icon(
        explorer, tmp_path):
    card = _mock_card(tmp_path)
    result, path = _parse(tmp_path, "healthy_wrapped.ddd", b"\x76\x06" + card)
    _as_healthy(result)
    _render(explorer, result, path)
    text, image, takefocus = _banner(explorer)
    assert text == gui._(NOTE_TEXT).format(count=1), text
    assert "warning" not in text.lower()
    assert str(explorer.integrity_banner.cget("foreground")) != str(gui.WARNING)
    # a neutral icon already used elsewhere in the app, never the warning triangle
    assert image, "the note banner must still carry the neutral icon"
    assert image != _image_name(explorer, "status-warning")
    assert image == _image_name(explorer, "file-info")
    assert takefocus


def test_wrapped_card_with_real_warnings_counts_only_them_and_lists_the_notice_after(
        explorer, tmp_path, monkeypatch):
    card = bytearray(_mock_card(tmp_path))
    card[5 + 8] ^= 0xFF                      # inside the first EF's value
    result, path = _parse(tmp_path, "tampered_wrapped.ddd", b"\x76\x06" + bytes(card))
    shown = []
    monkeypatch.setattr(explorer, "_warn_when_idle",
                        lambda title, message, kind="showwarning": shown.append(
                            (title, message)))
    _render(explorer, result, path)
    text, image, _takefocus = _banner(explorer)
    warnings, notices = gui._integrity_bullets(result)
    assert notices, "the wrapped card carries the notice"
    assert shown, "the dialog was not offered"
    dialog_bullets = [line for line in shown[0][1].split("\n")
                      if line.startswith("\u2022")]
    real = [b for b in dialog_bullets if b not in notices]
    assert real, "the tampered card is expected to raise a real warning"
    # the banner counts only the real warnings, never the note
    assert text == gui._(WARNING_TEXT).format(count=len(real)), text
    assert image == _image_name(explorer, "status-warning")
    assert shown, "the dialog was not offered"
    message = shown[0][1]
    positions = [message.index(bullet) for bullet in real + notices]
    assert positions == sorted(positions), "warnings must come before the notice"
    assert all(bullet in message for bullet in notices)


def test_healthy_plain_card_has_no_banner_at_all(explorer, tmp_path):
    card = _mock_card(tmp_path)
    result, path = _parse(tmp_path, "plain.ddd", card)
    _as_healthy(result)
    _render(explorer, result, path)
    text, image, takefocus = _banner(explorer)
    assert text == ""
    assert image == ""
    assert str(takefocus) in ("0", "False", "")


def test_a_vu_file_keeps_the_current_behaviour(explorer, tmp_path):
    from tests.unit.test_card_envelope import _synthetic_g1_vu
    result, path = _parse(tmp_path, "vu.ddd", _synthetic_g1_vu())
    _render(explorer, result, path)
    text, _image, _takefocus = _banner(explorer)
    assert NOTICE_PREFIX not in text
    assert "note(s)" not in text


def test_real_wrapped_card_banner_is_the_note_wording(explorer, tmp_path):
    path = require_real_file("*_D47C4D98DF.ddd")
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw.startswith(b"\x76\x06"):
        pytest.skip("not a wrapped card")
    DecoderRegistry.reset_instance()
    result = TachoParser(path).parse()
    assert "Verified" in result["metadata"]["integrity_check"]
    _render(explorer, result, path)
    text, image, _takefocus = _banner(explorer)
    warnings, notices = gui._integrity_bullets(result)
    assert notices and not [b for b in warnings if b not in notices]
    assert text == gui._(NOTE_TEXT).format(count=len(notices)), text
    assert image != _image_name(explorer, "status-warning")
    assert image == _image_name(explorer, "file-info")


# ── The clarification must appear once per surface (item 2) ────────────────

def test_the_notice_never_asserts_the_card_verdict():
    """The notice states the FORM fact only.

    A wrapped card whose EF signature was tampered carries the real warning and the
    notice; asserting "the data are complete and the signatures verify" there would
    be false, so the text points to the verdict instead of claiming it.
    """
    text = gui.CARD_ENVELOPE_NOTICE.lower()
    for claim in ("complete", "verified", "valid", "intact", "all signatures"):
        assert claim not in text, claim
    assert "verdict" in text or "reported separately" in text
    assert "dp_050".replace("dp_050", "ddp_050") in text
    assert "corrupt" in text


def test_tampered_wrapped_card_notice_and_warning_coexist(tmp_path):
    """Notice + real warning, and the notice makes no positive claim."""
    raw = _mock_card(tmp_path)
    damaged = bytearray(raw)
    damaged[5 + 8] ^= 0xFF
    path = os.path.join(str(tmp_path), "wrapped_bad2.ddd")
    with open(path, "wb") as handle:
        handle.write(b"\x76\x06" + bytes(damaged))
    DecoderRegistry.reset_instance()
    result = TachoParser(path).parse()
    bullets, notices = gui._integrity_bullets(result)
    assert notices and notices[0] in bullets
    assert any("EF data signatures" in bullet for bullet in bullets)
    assert "verified normally" not in notices[0].lower()
    assert "complete" not in notices[0].lower()
    # the report row makes no claim either
    from core.utils import report_format as rf
    rows = dict(rf.summary_rows(result))
    value = rows.get("Transfer header") or ""
    assert "verified normally" not in value.lower()
    assert "complete" not in value.lower()


def test_notice_is_shown_once_per_surface(tmp_path):
    from tests.unit.real_data import real_ddd_files
    files = [p for p in real_ddd_files() if os.path.basename(p).endswith(
        "D47C4D98DF.ddd")]
    if not files:
        pytest.skip("no private corpus available")
    DecoderRegistry.reset_instance()
    result = TachoParser(files[0]).parse()
    warnings, notices = gui._integrity_bullets(result)
    assert sum(NOTICE_PREFIX in bullet for bullet in warnings) == 1
    # the File Info panel's origin note is a different, shorter sentence
    origin_note = str(result["metadata"].get("origin_note") or "")
    assert origin_note
    assert origin_note not in notices[0]
    from core.utils import report_format as rf
    rows = rf.summary_rows(result)
    header_rows = [row for row in rows if row[0] == "Transfer header"]
    assert len(header_rows) == 1
    value = header_rows[0][1]
    assert "SID 76 + TREP 06" in value and "DDP_050" in value
    # the clarification is stated once per surface: the row label is the phrase
    assert value.lower().count("transfer header") == 0

    # a plain card carries neither
    with open(files[0], "rb") as handle:
        raw = handle.read()
    plain_path = os.path.join(str(tmp_path), "plain_tmp_notice.ddd")
    with open(plain_path, "wb") as handle:
        handle.write(raw[2:])
    try:
        DecoderRegistry.reset_instance()
        plain_result = TachoParser(plain_path).parse()
    finally:
        os.unlink(plain_path)
    plain_warnings, plain_notices = gui._integrity_bullets(plain_result)
    assert not plain_notices
    assert not any(row[0] == "Transfer header" for row in rf.summary_rows(plain_result))


def test_note_and_warning_banner_msgids_are_translated_and_distinct():
    import glob
    import re
    catalogs = sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po"))
    assert len(catalogs) == 33
    for path in catalogs:
        entries = dict(re.findall(r'^msgid "(.*)"\nmsgstr "(.*)"$',
                                  open(path, encoding="utf-8").read(), re.M))
        note = entries.get(NOTE_TEXT)
        warn = entries.get(WARNING_TEXT)
        assert note and warn, path
        assert note != NOTE_TEXT and warn != WARNING_TEXT, path   # both translated
        assert note != warn, path                                  # never the same text
