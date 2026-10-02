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
"""
import contextlib
import io
import os
import struct
import tempfile

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils

from app.engine import TachoParser
from core.crypto.signature import SignatureValidator
from core.utils.report_format import (
    VERDICT_UNVERIFIED, VERDICT_VERIFIED, integrity_verdict)
from scripts.rename_ddd_files import _integrity_status

P256_OID = "2a8648ce3d030107"


def _tlv(tag, value):
    if len(value) < 128:
        length = bytes([len(value)])
    else:
        length = b"\x81" + bytes([len(value)])
    return bytes(tag) + length + value


def _cvc(private_key, signer_key, car, chr_):
    """Build a real CVC (0x7F21) certificate signed by ``signer_key``."""
    point = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public_key = _tlv(b"\x06", bytes.fromhex(P256_OID)) + _tlv(b"\x86", point)
    body = _tlv(b"\x42", car) + _tlv(b"\x5f\x20", chr_)
    body += _tlv(b"\x5f\x25", (1600000000).to_bytes(4, "big"))
    body += _tlv(b"\x5f\x24", (2000000000).to_bytes(4, "big"))
    body += _tlv(b"\x7f\x49", public_key)
    body_tlv = _tlv(b"\x7f\x4e", body)
    der = signer_key.sign(body_tlv, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return _tlv(b"\x7f\x21", body_tlv + _tlv(b"\x5f\x37", signature))


def _ef_signature(card_key, data):
    der = card_key.sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _stap(tag, dtype, data):
    return struct.pack(">HBH", tag, dtype, len(data)) + data


# A two-generation CVC identity used by every fixture (generic, no personal data).
def _new_cvc_identity(msca_signer):
    """Return a Card←MSCA←``msca_signer`` CVC identity.

    ``msca_signer`` is the ERCA key that signs the MSCA (or ``None`` for a
    self-signed attacker MSCA).
    """
    card_key = ec.generate_private_key(ec.SECP256R1())
    msca_key = ec.generate_private_key(ec.SECP256R1())
    signer = msca_key if msca_signer is None else msca_signer
    msca_cert = _cvc(msca_key, signer, b"MSSCA001", b"EUROOT01")
    card_cert = _cvc(card_key, msca_key, b"EUOCARD1", b"MSSCA001")
    return {
        "card_key": card_key,
        "msca_key": msca_key,
        "msca_cert": msca_cert,
        "card_cert": card_cert,
    }


def _build_card(identity, activity, licence, *, tamper_activity=False,
                omit_licence_signature=False, short_licence=False):
    act = bytearray(activity)
    if tamper_activity:
        act[3] ^= 0xFF
    records = [
        _stap(0x0201, 0x02, b"GENERIC DRIVER".ljust(64, b" ")),
        _stap(0x0103, 0x03, identity["card_cert"]),
        _stap(0x0104, 0x03, identity["msca_cert"]),
        _stap(0x0504, 0x02, bytes(act)),
        _stap(0x0504, 0x03, _ef_signature(identity["card_key"], activity)),
    ]
    licence_data = b"L" if short_licence else b"GENERIC-LICENCE-DATA-0123456789"
    records.append(_stap(0x0521, 0x02, licence_data))
    if not omit_licence_signature:
        records.append(_stap(0x0521, 0x03, _ef_signature(identity["card_key"], licence_data)))
    return b"".join(records)


def _parse(data, certs_dir, validator=None):
    """Parse ``data`` with an injected trust store (no global state touched).

    ``validator`` may be a ``SignatureValidator`` instance or a
    ``callable(certs_dir) -> SignatureValidator`` factory.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        parser = TachoParser(tmp.name)
        if callable(validator):
            parser.validator = validator(certs_dir)
        elif validator is not None:
            parser.validator = validator
        else:
            parser.validator = SignatureValidator(certs_dir=certs_dir)
        return parser.parse()
    finally:
        os.unlink(tmp.name)


@contextlib.contextmanager
def _trust_store(erca_cvc=None):
    with tempfile.TemporaryDirectory() as certs_dir:
        if erca_cvc is not None:
            with open(os.path.join(certs_dir, "erca_root.bin"), "wb") as handle:
                handle.write(erca_cvc)
        yield certs_dir


def _trusted_root_and_msca():
    """Real ERCA→MSCA→Card chain rooted at a synthetic-but-genuine ERCA key."""
    erca_key = ec.generate_private_key(ec.SECP256R1())
    erca_cert = _cvc(erca_key, erca_key, b"EUROOT01", b"EUROOT01")
    identity = _new_cvc_identity(erca_key)
    return erca_cert, identity


ACTIVITY = bytes(range(20))
LICENCE = b"GENERIC-LICENCE-DATA-0123456789"


# ── C1: forged / wrong-root chains are never verified ──────────────────────

def test_forged_self_signed_chain_is_not_verified():
    # Attacker controls the whole chain but it is anchored to nothing trusted.
    erca_cert, _genuine = _trusted_root_and_msca()
    attacker = _new_cvc_identity(None)  # self-signed MSCA
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    meta = result["metadata"]
    assert not meta["integrity_check"].startswith("Verified")
    assert "anchor failed" in meta["integrity_check"].lower()
    assert integrity_verdict(result) == VERDICT_UNVERIFIED
    # The EF signatures themselves are internally consistent — but that is not
    # evidence of trust and must not leak into a verified verdict.
    efv = result["ef_signature_verification"]
    assert efv["verified"] == 2 and efv["failed"] == 0


def test_no_trusted_root_does_not_verify():
    attacker = _new_cvc_identity(None)
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store() as empty_certs_dir:
        result = _parse(data, empty_certs_dir)

    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_genuine_anchored_chain_is_verified():
    erca_cert, identity = _trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
    efv = result["ef_signature_verification"]
    assert efv["failed"] == 0 and efv["skipped"] == 0 and efv["verified"] == 2


# ── C2: EF tamper / skip / absence downgrades an anchored card ─────────────

def test_tampered_ef_downgrades_anchored_card():
    erca_cert, identity = _trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE, tamper_activity=True)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    meta = result["metadata"]
    assert meta["integrity_check"] == "Unverified (EF Signature Mismatch)"
    assert integrity_verdict(result) == VERDICT_UNVERIFIED
    assert result["ef_signature_verification"]["failed"] >= 1


def test_short_ef_is_reported_skipped_not_verified():
    erca_cert, identity = _trusted_root_and_msca()
    # Tag 0x0521 (DrivingLicenceInfo) needs >= 10 bytes; a 1-byte payload makes
    # one pair unverifiable while the other still verifies.
    data = _build_card(identity, ACTIVITY, LICENCE, short_licence=True)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    efv = result["ef_signature_verification"]
    assert efv["verified"] == 1 and efv["skipped"] >= 1
    assert "skipped" in efv["summary"]
    assert result["metadata"]["integrity_check"] == "Unverified (EF Signatures Incomplete)"
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_missing_ef_signature_is_incomplete_and_downgrades():
    erca_cert, identity = _trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE, omit_licence_signature=True)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert result["ef_signature_verification"]["failed"] >= 1
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_chain_without_signed_efs_is_not_fully_verified():
    # Card carrying only certificates: a verified chain alone must not read as
    # a fully verified download.
    erca_cert, identity = _trusted_root_and_msca()
    data = b"".join([
        _stap(0x0201, 0x02, b"GENERIC DRIVER".ljust(64, b" ")),
        _stap(0x0103, 0x03, identity["card_cert"]),
        _stap(0x0104, 0x03, identity["msca_cert"]),
    ])

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert integrity_verdict(result) == VERDICT_UNVERIFIED
    assert not result["metadata"]["integrity_check"].startswith("Verified")


# ── Mixed-generation (G1 + G2) laundering ──────────────────────────────────
#
# A file can carry a genuine, anchored G1 chain *and* a G2 CVC chain. A verified
# G1 chain must never launder an attacker-signed G2 chain (or vice versa): every
# EF generation present has to be backed by its own trusted chain.
#
# Building a real ERCA→MSCA→Card RSA (ISO 9796-2) G1 chain is impractical for a
# fixture, so the G1 chain outcome is stubbed with a controlled RSA key; the G2
# CVC chain and every EF signature are still verified with real ECDSA/RSA crypto.

def _mixed_validator(g1_key, *, g1_status=True):
    """Return a validator factory that trusts a controlled G1 RSA key."""
    def factory(certs_dir):
        class _MixedValidator(SignatureValidator):
            def validate_tacho_chain(self, card_cert_raw, msca_cert_raw, *args, **kwargs):
                self.last_chain_temporal_validity = {}
                if len(card_cert_raw) == 194 and len(msca_cert_raw) == 194:
                    # Controlled G1 (194-byte) chain stub — no real ISO 9796-2.
                    return (g1_status, g1_key.public_key() if g1_status is True else None)
                return super().validate_tacho_chain(
                    card_cert_raw, msca_cert_raw, *args, **kwargs)
        return _MixedValidator(certs_dir=certs_dir)
    return factory


def _g1_cert(first_byte=0x01):
    # 194-byte G1 certificate placeholder; the first byte must not look like a
    # G2 encoding marker (0x30 DER / 0x7F CVC) so validate_tacho_chain picks G1.
    return bytes([first_byte]) + b"\x00" * 193


def _rsa_ef_signature(key, data):
    return key.sign(data, padding.PKCS1v15(), hashes.SHA1())


def _mixed_card(g2_identity, g1_key):
    """Genuine G1 certs + a (possibly attacker) G2 CVC chain, both with real EFs."""
    act = bytearray(ACTIVITY)
    act[3] ^= 0xFF  # attacker flips a G2 activity byte, then re-signs below
    return b"".join([
        _stap(0x0201, 0x02, b"GENERIC DRIVER".ljust(64, b" ")),
        # Genuine G1 (194-byte) certificate copies first...
        _stap(0x0103, 0x03, _g1_cert(0x01)),
        _stap(0x0104, 0x03, _g1_cert(0x02)),
        # ...then the G2 CVC chain, whose copies win the "raw" pair.
        _stap(0xC101, 0x02, g2_identity["card_cert"]),
        _stap(0xC108, 0x02, g2_identity["msca_cert"]),
        # G1 signed EF pair — real RSA SHA-1 bytes signed by the trusted G1 key.
        _stap(0x0504, 0x00, bytes(ACTIVITY)),
        _stap(0x0504, 0x01, _rsa_ef_signature(g1_key, ACTIVITY)),
        # G2 signed EF pair — re-signed by the (attacker) G2 card key.
        _stap(0x0504, 0x02, bytes(act)),
        _stap(0x0504, 0x03, _ef_signature(g2_identity["card_key"], bytes(act))),
    ])


def test_mixed_generation_forged_g2_cannot_ride_genuine_g1():
    erca_cert, _genuine = _trusted_root_and_msca()
    attacker = _new_cvc_identity(None)  # self-signed (unanchored) G2 CVC chain
    g1_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    data = _mixed_card(attacker, g1_key)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir, validator=_mixed_validator(g1_key))

    meta = result["metadata"]
    # The EF maths check out against the attacker's own key, but the G2 chain is
    # unanchored, so the download can never read as Verified.
    efv = result["ef_signature_verification"]
    assert efv["failed"] == 0 and efv["skipped"] == 0
    assert efv["untrusted_generations"] == ["G2"]
    assert not meta["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_mixed_generation_genuine_g1_and_g2_is_verified():
    erca_cert, identity = _trusted_root_and_msca()  # anchored G2 chain
    g1_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    data = _mixed_card(identity, g1_key)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir, validator=_mixed_validator(g1_key))

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


def test_failed_g1_cannot_be_rescued_by_anchored_g2():
    erca_cert, identity = _trusted_root_and_msca()  # anchored G2 chain
    g1_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    data = _mixed_card(identity, g1_key)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(
            data, certs_dir, validator=_mixed_validator(g1_key, g1_status=False))

    meta = result["metadata"]
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
    erca_cert, _genuine = _trusted_root_and_msca()
    attacker = _new_cvc_identity(None)
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert TachoExplorer._integrity_label(None, result) != "All signatures verified"
    assert _badge(result)["text"] != ""
    assert _integrity_status(result) == "UNVERIFIED"


def test_tampered_card_gui_shows_failure_and_rename_fails_closed():
    erca_cert, identity = _trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE, tamper_activity=True)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert "mismatch" in TachoExplorer._integrity_label(None, result).lower()
    badge = _badge(result)
    assert badge["text"] != "" and badge["foreground"] == "#c62828"
    assert _integrity_status(result) == "UNVERIFIED"


def test_anchored_clean_card_gui_and_rename_verified():
    erca_cert, identity = _trusted_root_and_msca()
    data = _build_card(identity, ACTIVITY, LICENCE)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    assert TachoExplorer._integrity_label(None, result) == "All signatures verified"
    assert _badge(result)["text"] == ""
    assert _integrity_status(result) == "VERIFIED"


def test_cli_summary_reports_canonical_non_verified_status():
    from app.cli import print_summary

    erca_cert, _genuine = _trusted_root_and_msca()
    attacker = _new_cvc_identity(None)
    data = _build_card(attacker, ACTIVITY, LICENCE)

    with _trust_store(erca_cert) as certs_dir:
        result = _parse(data, certs_dir)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_summary(result)
    integrity_lines = [ln for ln in buffer.getvalue().splitlines() if "Integrity" in ln]
    assert integrity_lines and "Verified" not in integrity_lines[0].split(":", 1)[1]
