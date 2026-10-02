"""End-to-end verdict tests for forged/tampered G2 driver cards.

These tests build synthetic G2 card downloads with **real ECDSA signatures**
(no mocking of the crypto) and assert that a forged or tampered card can never
surface as verified on any user-facing surface: ``metadata.integrity_check``,
the canonical verdict, the GUI label/badge, and the rename status.

Root-cause coverage:
  * C1/E-F1 — a self-signed attacker CVC chain must not be accepted: the MSCA
    certificate has to be anchored to a trusted ERCA-2 root from the validator's
    trust store (injected here via ``certs_dir``).
  * C2/E-F2 — EF signature failures/skips and uncheckable EFs must downgrade an
    otherwise-verified card instead of leaving it identical to a clean one.

The signed control carries the **full mandatory per-download core** so a
positive verdict is never an artefact of completeness being skipped.
"""
import contextlib
import io

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from core.utils.report_format import (
    VERDICT_UNVERIFIED, VERDICT_VERIFIED, integrity_verdict)
from scripts.rename_ddd_files import _integrity_status
from tests.unit.card_crypto import (
    ef_signature as _ef_signature,
    g1_core_payloads,
    g1_identity,
    g2_core_payloads,
    new_cvc_identity,
    parse_bytes,
    signed_pairs,
    stap as _stap,
    trust_store as _trust_store,
    trusted_root_and_msca,
    write_g1_trust,
)

ACTIVITY = bytes(range(20))
LICENCE = b"GENERIC-LICENCE-DATA-0123456789"

# Mandatory G2 core (11 tags) + the optional-but-present DrivingLicenceInfo.
FULL_CORE_PAIR_COUNT = len(g2_core_payloads()) + 1


def _parse(data, certs_dir, validator=None):
    """Parse ``data`` with an injected trust store (no global state touched)."""
    _parser, result = parse_bytes(data, certs_dir, validator)
    return result


def _build_card(identity, activity, licence, *, tamper_activity=False,
                omit_licence_signature=False, short_licence=False):
    """A full-core G2 card: every mandatory EF signed by the card key.

    ``tamper_activity`` flips a byte of the on-the-wire Driver_Activity_Data
    while the signature stays over the genuine payload.
    """
    payloads = g2_core_payloads(v2=False)
    genuine_activity = payloads[0x0504]
    sent_activity = bytearray(genuine_activity)
    if tamper_activity:
        sent_activity[3] ^= 0xFF

    signed = {tag: value for tag, value in payloads.items() if tag != 0x0504}
    records = [
        _stap(0x0201, 0x02, b"GENERIC DRIVER".ljust(64, b" ")),
        _stap(0x0103, 0x03, identity["card_cert"]),
        _stap(0x0104, 0x03, identity["msca_cert"]),
        signed_pairs(signed, identity["card_key"], 2),
        _stap(0x0504, 0x02, bytes(sent_activity)),
        _stap(0x0504, 0x03, _ef_signature(identity["card_key"], genuine_activity)),
    ]
    licence_data = b"L" if short_licence else licence
    records.append(_stap(0x0521, 0x02, licence_data))
    if not omit_licence_signature:
        records.append(_stap(0x0521, 0x03, _ef_signature(identity["card_key"], licence_data)))
    return b"".join(records)


# ── C1: forged / wrong-root chains are never verified ──────────────────────

def test_forged_self_signed_chain_is_not_verified():
    # Attacker controls the whole chain but it is anchored to nothing trusted.
    erca_cert, _genuine = trusted_root_and_msca()
    attacker = new_cvc_identity(None)  # self-signed MSCA
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    meta = result["metadata"]
    assert not meta["integrity_check"].startswith("Verified")
    assert "anchor failed" in meta["integrity_check"].lower()
    assert integrity_verdict(result) == VERDICT_UNVERIFIED
    # The EF signatures themselves are internally consistent — but that is not
    # evidence of trust and must not leak into a verified verdict.
    efv = result["ef_signature_verification"]
    assert efv["verified"] == FULL_CORE_PAIR_COUNT and efv["failed"] == 0


def test_no_trusted_root_does_not_verify():
    attacker = new_cvc_identity(None)
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store() as empty_certs_dir:
        result = _parse(data, empty_certs_dir)

    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_genuine_anchored_chain_is_verified():
    erca_cert, identity = trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
    efv = result["ef_signature_verification"]
    assert efv["failed"] == 0 and efv["skipped"] == 0
    assert efv["verified"] == FULL_CORE_PAIR_COUNT


# ── C2: EF tamper / skip / absence downgrades an anchored card ─────────────

def test_tampered_ef_downgrades_anchored_card():
    erca_cert, identity = trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE, tamper_activity=True)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    meta = result["metadata"]
    assert meta["integrity_check"] == "Unverified (EF Signature Mismatch)"
    assert integrity_verdict(result) == VERDICT_UNVERIFIED
    assert result["ef_signature_verification"]["failed"] >= 1


def test_short_ef_is_reported_skipped_not_verified():
    erca_cert, identity = trusted_root_and_msca()
    # Tag 0x0521 (DrivingLicenceInfo) needs >= 10 bytes; a 1-byte payload makes
    # one pair unverifiable while the rest of the core still verifies.
    data = _build_card(identity, ACTIVITY, LICENCE, short_licence=True)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    efv = result["ef_signature_verification"]
    assert efv["verified"] == FULL_CORE_PAIR_COUNT - 1 and efv["skipped"] >= 1
    assert "skipped" in efv["summary"]
    assert result["metadata"]["integrity_check"] == "Unverified (EF Signatures Incomplete)"
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_missing_ef_signature_is_incomplete_and_downgrades():
    erca_cert, identity = trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE, omit_licence_signature=True)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert result["ef_signature_verification"]["failed"] >= 1
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_chain_without_signed_efs_is_not_fully_verified():
    # Card carrying only certificates: a verified chain alone must not read as
    # a fully verified download.
    erca_cert, identity = trusted_root_and_msca()
    data = b"".join([
        _stap(0x0201, 0x02, b"GENERIC DRIVER".ljust(64, b" ")),
        _stap(0x0103, 0x03, identity["card_cert"]),
        _stap(0x0104, 0x03, identity["msca_cert"]),
    ])

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert integrity_verdict(result) == VERDICT_UNVERIFIED
    assert not result["metadata"]["integrity_check"].startswith("Verified")


# ── Mixed-generation (G1 + G2) laundering ──────────────────────────────────
#
# A file can carry a genuine, anchored G1 chain *and* a G2 CVC chain. A verified
# G1 chain must never launder an attacker-signed G2 chain (or vice versa): every
# EF generation present has to be backed by its own trusted chain. Both chains
# and every EF signature are verified with real RSA/ECDSA crypto here.

def _mixed_card(g2_identity, g1_ids, *, drop_g2=()):
    """Genuine G1 (194-byte ISO 9796-2) certs + a G2 CVC chain, full cores."""
    g2_payloads = g2_core_payloads()
    for tag in drop_g2:
        g2_payloads.pop(tag, None)
    g1_cert = g1_ids["card_cert"]
    g1_msca = g1_ids["msca_cert"]
    return b"".join([
        _stap(0x0201, 0x02, b"GENERIC DRIVER".ljust(64, b" ")),
        # Genuine G1 (194-byte) certificate copies first...
        _stap(0x0103, 0x00, g1_cert),
        _stap(0x0104, 0x00, g1_msca),
        # ...then the G2 CVC chain, whose copies win the "raw" pair.
        _stap(0xC101, 0x02, g2_identity["card_cert"]),
        _stap(0xC108, 0x02, g2_identity["msca_cert"]),
        signed_pairs(g1_core_payloads(), g1_ids["card_key"], 1),
        signed_pairs(g2_payloads, g2_identity["card_key"], 2),
    ])


def test_mixed_generation_forged_g2_cannot_ride_genuine_g1():
    erca_cert, _genuine = trusted_root_and_msca()
    attacker = new_cvc_identity(None)  # self-signed (unanchored) G2 CVC chain
    g1_ids = g1_identity()
    data = _mixed_card(attacker, g1_ids)

    with _trust_store(g2_erca_cert=erca_cert, g1_erca_key=g1_ids["erca_key"]) as certs_dir:
        result = _parse(data, certs_dir)

    meta = result["metadata"]
    # The EF maths check out against the attacker's own key, but the G2 chain is
    # unanchored, so the download can never read as Verified.
    efv = result["ef_signature_verification"]
    assert efv["failed"] == 0 and efv["skipped"] == 0
    assert efv["untrusted_generations"] == ["G2"]
    assert not meta["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_mixed_generation_genuine_g1_and_g2_is_verified():
    erca_cert, identity = trusted_root_and_msca()  # anchored G2 chain
    g1_ids = g1_identity()                        # anchored G1 chain
    data = _mixed_card(identity, g1_ids)

    with _trust_store(g2_erca_cert=erca_cert, g1_erca_key=g1_ids["erca_key"]) as certs_dir:
        result = _parse(data, certs_dir)

    efv = result["ef_signature_verification"]
    assert efv["untrusted_generations"] == []
    assert efv["failed"] == 0 and efv["skipped"] == 0
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
    # The G2 chain still supplies its card+MSCA temporal status even though a
    # second (G1) chain is evaluated afterwards (no reset to {}).
    temporal = result["certificate_temporal_validity"]
    assert temporal["card"]["status"] == "not_checked"
    assert temporal["msca"]["status"] == "not_checked"


def test_deleting_a_g2_copy_while_the_g1_copy_remains_is_incomplete():
    """Per-generation completeness: a G1 copy must not stand in for a deleted
    G2 copy of the same tag."""
    erca_cert, identity = trusted_root_and_msca()
    g1_ids = g1_identity()
    data = _mixed_card(identity, g1_ids, drop_g2=(0x0502,))

    with _trust_store(g2_erca_cert=erca_cert, g1_erca_key=g1_ids["erca_key"]) as certs_dir:
        result = _parse(data, certs_dir)

    efv = result["ef_signature_verification"]
    assert efv["missing_core_efs"] == [0x0502]
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_failed_g1_cannot_be_rescued_by_anchored_g2():
    erca_cert, identity = trusted_root_and_msca()  # anchored G2 chain
    g1_ids = g1_identity()
    data = _mixed_card(identity, g1_ids)
    decoy = rsa.generate_private_key(public_exponent=65537, key_size=1024)

    # A trust store with the genuine G2 root but a decoy G1 root: the G1 chain
    # cannot be recovered, while the G2 chain stays anchored.
    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        write_g1_trust(certs_dir, decoy)
        result = _parse(data, certs_dir)

    meta = result["metadata"]
    assert result["ef_signature_verification"]["untrusted_generations"] == ["G1"]
    assert not meta["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


# ── verify_ef_pairs summary transparency ───────────────────────────────────

def test_ef_summary_never_hides_skipped_pairs():
    from core.crypto.ef_signature import verify_ef_pairs

    class _AlwaysValidValidator:
        def verify_g1_data_signature(self, *_args):
            return True

    pairs = [
        {"tag": 0x0502, "gen": "G1", "algo": "RSA", "status": "paired",
         "data": b"D" * 40, "signature": b"S" * 64},
        {"tag": 0x0503, "gen": "G1", "algo": "RSA", "status": "incomplete",
         "reason": "missing signature", "data_size": 10, "sig_size": 0},
    ]
    report = verify_ef_pairs(pairs, object(), _AlwaysValidValidator(), "G1")

    assert report["verified"] == 1 and report["failed"] == 1
    assert "All 1 EF signature(s) verified" != report["summary"]


# ── GUI + rename surfaces ──────────────────────────────────────────────────

pytest.importorskip("tkinter")
from unittest.mock import Mock  # noqa: E402

from app.gui import TachoExplorer  # noqa: E402


def _badge(data):
    app = object.__new__(TachoExplorer)
    app.lbl_status = Mock()
    app.current_file = "card.ddd"
    app.title = Mock()
    app._update_status_badge(data)
    return app.lbl_status.config.call_args.kwargs


def test_forged_card_gui_and_rename_fail_closed():
    erca_cert, _genuine = trusted_root_and_msca()
    attacker = new_cvc_identity(None)
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert TachoExplorer._integrity_label(None, result) != "All signatures verified"
    assert _badge(result)["text"] != ""
    assert _integrity_status(result) == "UNVERIFIED"


def test_tampered_card_gui_shows_failure_and_rename_fails_closed():
    erca_cert, identity = trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE, tamper_activity=True)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert "mismatch" in TachoExplorer._integrity_label(None, result).lower()
    badge = _badge(result)
    assert badge["text"] != "" and badge["foreground"] == "#c62828"
    assert _integrity_status(result) == "UNVERIFIED"


def test_anchored_clean_card_gui_and_rename_verified():
    erca_cert, identity = trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert TachoExplorer._integrity_label(None, result) == "All signatures verified"
    assert _badge(result)["text"] == ""
    assert _integrity_status(result) == "VERIFIED"


def test_cli_summary_reports_canonical_non_verified_status():
    from app.cli import print_summary

    erca_cert, _genuine = trusted_root_and_msca()
    attacker = new_cvc_identity(None)
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store(g2_erca_cert=erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_summary(result)
    integrity_lines = [ln for ln in buffer.getvalue().splitlines() if "Integrity" in ln]
    assert integrity_lines and "Verified" not in integrity_lines[0].split(":", 1)[1]
