"""A card file whose opening record was altered must still reach the customer.

The owner changed the two leading bytes of a card download (``00 02`` — the
EF_ICC record a card file starts with) and the app said nothing at all: no
banner, no dialog, "Verified". Two mechanisms exist and neither could fire:

* the only *form* note in the app (``gui._envelope_notice``) is driven by
  ``metadata["envelope"]``, i.e. a card image relayed through a TREP 06
  transfer header — this file is a plain card, so that key is absent;
* every *warning* bullet is driven by a signature or structure fact. A card's
  EF_ICC/ICC-identification record sits below the signed-EF space (tags
  < 0x0500 are metadata, ``core.crypto.ef_signature._is_certificate_or_metadata_tag``),
  so rewriting its tag leaves the bytes framed (100 % coverage, no decoder
  failure) and every signed EF intact: 9/9 verified.

``_check_integrity`` therefore took the "valid file" branch — no banner, no
dialog — for a file whose header no longer matches a standard download.

The fix publishes the FORM fact (``metadata["header_form"]``, set by
``app.engine`` from ``core.parser.origin_detector.nonstandard_header``) and
turns it into one neutral notice. The notice states the form and the signature
count only: it never calls such a file complete, valid or authentic.

Synthetic material throughout (``tests.unit.card_crypto``, real RSA), no corpus
file.
"""
import os

import pytest

pytest.importorskip("tkinter")

import app.gui as gui  # noqa: E402
from app.engine import TachoParser  # noqa: E402
from core.registry.registry import DecoderRegistry  # noqa: E402
from tests.unit.card_crypto import (  # noqa: E402
    g1_cert_records,
    g1_core_payloads,
    g1_identity,
    parse_bytes,
    signed_pairs,
    stap,
    trust_store,
)

#: A generic EF_ICC payload (Annex 1B §2.7: clock stop, extended serial number,
#: approval number, personaliser, embedder, IC identifier, one historical byte).
#: Synthetic bytes — a card download opens with this record, which is why the
#: owner's two-byte edit lands on it.
EF_ICC_PAYLOAD = (b"\x00" + b"\x11" * 8 + b"\x22" * 8 + b"\x03"
                  + b"\x44" * 4 + b"\xaa\xbb" + b"\x00")
from tests.unit.test_empty_state import close, new_explorer  # noqa: E402

#: The tag the tampered file's first record reports ("00 02" rewritten to "00 03").
TAMPERED_TAG = "0x0003"
NOTICE_PREFIX = "\u2022 File header differs"
NOTE_TEXT = "{count} note(s) \u2014 click for details"


@pytest.fixture(scope="module")
def g1_card():
    """``(identity, card bytes)`` — one real, full-core G1 card, built once.

    It opens with EF_ICC (tag 0x0002) exactly like a stored card download, so
    rewriting those two header bytes is the owner's case: the framing survives,
    the certificates and every signed EF are untouched.
    """
    identity = g1_identity()          # RSA key generation: do it once per module
    card = (stap(0x0002, 0x00, EF_ICC_PAYLOAD)
            + g1_cert_records(identity["card_cert"], identity["msca_cert"])
            + signed_pairs(g1_core_payloads(), identity["card_key"], 1))
    return identity, card


def _parse(data, certs_dir):
    return parse_bytes(data, certs_dir)[1]


def _parse_path(path, certs_dir):
    """Parse a file on disk with an injected trust store (the card's real root)."""
    from core.crypto.signature import SignatureValidator

    DecoderRegistry.reset_instance()
    parser = TachoParser(path)
    parser.validator = SignatureValidator(certs_dir=certs_dir)
    return parser.parse()


def _parse_card(g1_card, tamper=True):
    identity, card = g1_card
    blob = (b"\x00\x03" + card[2:]) if tamper else card
    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        return _parse(blob, certs_dir)


# ── the decision function ──────────────────────────────────────────────────

def test_a_standard_card_header_produces_no_notice(g1_card):
    result = _parse_card(g1_card, tamper=False)

    assert "header_form" not in result["metadata"]
    assert gui._header_notice(result) is None
    _bullets, notices = gui._integrity_bullets(result)
    assert notices == []


def test_the_two_byte_edit_leaves_the_verdict_untouched(g1_card):
    """Why the app said nothing: the two files are identical to every check."""
    clean = _parse_card(g1_card, tamper=False)
    tampered = _parse_card(g1_card, tamper=True)

    for result in (clean, tampered):
        assert result["metadata"]["integrity_check"] == "Verified"
        efv = result["ef_signature_verification"]
        assert (efv["verified"], efv["failed"], efv["total"]) == (9, 0, 9)
        assert efv["missing_core_efs"] == []
    # …so the only difference is the form fact, and it is the note channel.
    assert "header_form" in tampered["metadata"]
    assert "header_form" not in clean["metadata"]


def test_a_tampered_header_gets_the_notice(g1_card):
    """The popup/notice decision returns a notice for *this* file."""
    result = _parse_card(g1_card)

    assert result["metadata"]["header_form"]["first_record"] == TAMPERED_TAG
    notice = gui._header_notice(result)

    assert notice is not None
    assert notice.startswith(NOTICE_PREFIX), notice
    assert TAMPERED_TAG in notice
    assert "0 of 9 signature(s) could not be verified" in notice
    # and it is the note channel, never the warning channel
    _bullets, notices = gui._integrity_bullets(result)
    assert notices == [notice]


def test_the_notice_states_the_real_signature_count(g1_card):
    """A file that also fails signatures must say so, not fall back to silence."""
    result = _parse_card(g1_card)
    result["ef_signature_verification"]["failed"] = 2
    result["ef_signature_verification"]["skipped"] = 1

    notice = gui._header_notice(result)

    assert "3 of 9 signature(s) could not be verified" in notice
    assert gui._("No EF signatures verified") not in notice


def test_the_notice_says_nothing_about_the_file_being_whole():
    """The wording is a form fact plus a count — never a clean bill of health."""
    text = gui.CARD_HEADER_NOTICE.lower()
    for claim in ("complete", "authentic", "valid", "intact", "repaired"):
        assert claim not in text, claim
    assert "0x0002" in text and "0x0101" in text, "the standard form is named"


def test_a_card_without_ef_pairs_gets_the_neutral_fallback(g1_card):
    """No ``ef_signature_verification`` at all: still no invented count."""
    result = _parse_card(g1_card)
    result.pop("ef_signature_verification", None)

    notice = gui._header_notice(result)

    assert gui._("No EF signatures verified") in notice


def test_a_vu_download_gets_no_header_notice():
    from tests.unit.test_card_envelope import _synthetic_g1_vu

    with trust_store() as certs_dir:
        result = _parse(_synthetic_g1_vu(), certs_dir)

    assert result["metadata"]["is_vu"] is True
    assert gui._header_notice(result) is None


def test_a_g2_card_header_is_standard(g1_card, tmp_path):
    """G2/G2.2 cards open with 01 01, not 00 02: the rule is not G1-only."""
    from tests.integration import generate_mock_ddd as mock

    path = os.path.join(str(tmp_path), "mock_g2_card.ddd")
    mock.generate_g2_card(path)
    DecoderRegistry.reset_instance()
    result = TachoParser(path).parse()

    assert "header_form" not in result["metadata"]
    assert gui._header_notice(result) is None


# ── the surface the owner reported: banner + dialog ────────────────────────

@pytest.fixture
def explorer(monkeypatch):
    app = new_explorer(monkeypatch)
    try:
        yield app
    finally:
        gui.DayDetailWindow._open_windows.clear()
        close(app)


def _render(app, result, path):
    app._parse_done(result, path)
    app.update()


def test_the_tampered_header_shows_the_note_banner_and_dialog(
        explorer, monkeypatch, g1_card, tmp_path):
    """No warning colour, no warning words: one neutral note, as for envelopes."""
    identity, card = g1_card
    path = os.path.join(str(tmp_path), "tampered_header.ddd")
    with open(path, "wb") as handle:
        handle.write(b"\x00\x03" + card[2:])
    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        result = _parse_path(path, certs_dir)
    assert result["metadata"]["integrity_check"] == "Verified"

    shown = []
    monkeypatch.setattr(explorer, "_warn_when_idle",
                        lambda title, message, kind="showwarning": shown.append(
                            (kind, title, message)))
    _render(explorer, result, path)

    text, image, takefocus = (explorer.integrity_banner.cget("text"),
                              str(explorer.integrity_banner.cget("image")).strip("(),' "),
                              str(explorer.integrity_banner.cget("takefocus")))
    assert text == gui._(NOTE_TEXT).format(count=1), text
    assert "warning" not in text.lower()
    assert str(explorer.integrity_banner.cget("foreground")) != str(gui.WARNING)
    assert image != str(gui._icon("status-warning", 16, explorer.integrity_banner)
                        ).strip("(),' ")
    assert takefocus

    assert len(shown) == 1, shown
    kind, title, message = shown[0]
    assert kind == "showinfo"
    assert title == gui._("File Note")
    assert gui._header_notice(result) in message


def test_a_clean_card_still_opens_with_no_banner(explorer, g1_card, tmp_path):
    identity, card = g1_card
    path = os.path.join(str(tmp_path), "clean_header.ddd")
    with open(path, "wb") as handle:
        handle.write(card)
    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        result = _parse_path(path, certs_dir)

    _render(explorer, result, path)

    assert explorer.integrity_banner.cget("text") == ""
