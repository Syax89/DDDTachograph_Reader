"""Batch 6 — TRUST / crypto verdict regressions.

Four confirmed MEDIA families, one test class each:

* ``CRYPTO-G1-CERT-ROUTING``  — a genuine generation-1 card certificate whose
  unconstrained leading byte is the 0x30/0x7F generation-2 marker must still be
  captured and verified through the G1 chain.
* ``CRYPTO-CERT-EXPIRY``      — the certificate chain must be evaluated at the
  download/signature timestamp, not against no time at all.
* ``CRYPTO-CARD-VU-MIX``      — a presented-but-failed card chain must not be
  overwritten by valid VU signatures (worst of parts, not best).
* ``CRYPTO-EF-SKIPPED-SUMMARY``— a signed EF outside the known set must be
  reported (and counted as skipped), never dropped silently from the summary.

All chains/signatures here are real cryptography; only the identities are
synthetic and generic.
"""
import datetime
import os
import struct
import sys
import tempfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engine import TachoParser
from core.crypto.ef_signature import pair_ef_records, verify_ef_pairs
from core.crypto.signature import SignatureValidator
from core.utils.report_format import (
    VERDICT_UNVERIFIED,
    VERDICT_VERIFIED,
    integrity_verdict,
)
from tests.unit.card_crypto import (
    cvc,
    g2_cert_records,
    g2_core_payloads,
    g1_cert_records,
    g1_core_payloads,
    g1_identity_with_card_marker,
    parse_bytes,
    signed_pairs,
    stap,
    trust_store,
)


class _AlwaysValidValidator:
    def verify_g1_data_signature(self, public_key, signature, data):
        return True


# ── CRYPTO-G1-CERT-ROUTING ─────────────────────────────────────────────────

_MARKER_CACHE: dict = {}


def _g1_with_card_marker(marker):
    if marker not in _MARKER_CACHE:
        _MARKER_CACHE[marker] = g1_identity_with_card_marker(marker)
    return _MARKER_CACHE[marker]


def _assert_g1_marker_card_verifies(marker):
    ids = _g1_with_card_marker(marker)
    assert ids["card_cert"][0] == marker and len(ids["card_cert"]) == 194
    data = (g1_cert_records(ids["card_cert"], ids["msca_cert"])
            + signed_pairs(g1_core_payloads(), ids["card_key"], 1))
    with trust_store(g1_erca_key=ids["erca_key"]) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    # The legitimate G1 card certificate must be captured for the G1 chain …
    assert parser.card_cert_g1 == ids["card_cert"]
    # … and, unless its leading bytes happen to form a G2 DER length, it also
    # occupies the primary cert slot.
    assert parser.card_cert_raw in (None, ids["card_cert"])
    # … and the G1 chain must verify even though the leading byte looks G2.
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
    # The key that verified is the G1 card key, so every G1 EF pair verified
    # against the trusted G1 chain (never reported as an untrusted generation).
    efv = result["ef_signature_verification"]
    assert efv["untrusted_generations"] == []
    assert efv["failed"] == 0
    assert efv["verified"] == len(g1_core_payloads())


def test_g1_card_certificate_with_0x30_leading_byte_still_verifies():
    _assert_g1_marker_card_verifies(0x30)


def test_g1_card_certificate_with_0x7f_leading_byte_still_verifies():
    _assert_g1_marker_card_verifies(0x7F)


def test_g2_routing_failure_falls_back_to_the_g1_chain():
    """A 194-byte certificate whose leading two bytes form a real G2 marker
    (so it is tried as G2 first) but is in fact a generation-1 RSA block must
    still verify through the generation-1 chain (the G1 fallback)."""
    from unittest.mock import patch

    validator = SignatureValidator(certs_dir=tempfile.mkdtemp())
    card_cert = b"\x7f\x21" + b"x" * 192  # 194 bytes, a real-looking CVC marker
    msca_cert = b"\x7f\x21" + b"y" * 192
    with patch.object(validator, "_validate_g2_chain", return_value=(False, None)), \
            patch.object(validator, "_validate_g1_chain", return_value=(True, "g1key")):
        status, key = validator.validate_tacho_chain(card_cert, msca_cert)

    assert (status, key) == (True, "g1key")
    assert validator.last_chain_generation == "G1"


def test_genuine_g2_marker_still_routes_to_the_g2_verifier():
    """A real G2 CVC/DER encoding (two-byte marker) is not captured as G1."""
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from tests.unit.card_crypto import der_certificate

    key = _ec.generate_private_key(_ec.SECP256R1())
    cvc_cert = cvc(key, key, b"ROOT0001", b"MSSCA001")
    assert cvc_cert[0] == 0x7F and cvc_cert[1] == 0x21
    der = der_certificate(key, key)
    assert der[0] == 0x30 and der[1] & 0x80

    for payload in (cvc_cert, der):
        data = stap(0xC100, 0x00, payload) + stap(0xC108, 0x00, payload)
        with trust_store() as certs_dir:
            parser, _result = parse_bytes(data, certs_dir)
        # A genuine generation-2 CardMA must never take the G1 card slot.
        assert parser.card_cert_raw is None
        assert parser.card_cert_g1 is None


# ── CRYPTO-CERT-EXPIRY ─────────────────────────────────────────────────────

_UTC = datetime.timezone.utc
_EXPIRED_FROM = datetime.datetime(2001, 1, 1, tzinfo=_UTC)
_EXPIRED_TO = datetime.datetime(2002, 1, 1, tzinfo=_UTC)
# A download produced long after the certificates expired.
_DOWNLOAD_2025 = int(datetime.datetime(2025, 6, 1, tzinfo=_UTC).timestamp())


def _tlv(tag, value):
    if len(value) < 128:
        return tag + bytes([len(value)]) + value
    return tag + b"\x81" + bytes([len(value)]) + value


def _cvc_dated(private_key, signer, car, chr_, valid_from, valid_to):
    point = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public_key = _tlv(b"\x06", bytes.fromhex("2a8648ce3d030107")) + _tlv(b"\x86", point)
    body = _tlv(b"\x42", car) + _tlv(b"\x5f\x20", chr_)
    body += _tlv(b"\x5f\x25", int(valid_from.timestamp()).to_bytes(4, "big"))
    body += _tlv(b"\x5f\x24", int(valid_to.timestamp()).to_bytes(4, "big"))
    body += _tlv(b"\x7f\x49", public_key)
    body_tlv = _tlv(b"\x7f\x4e", body)
    der = signer.sign(body_tlv, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return _tlv(b"\x7f\x21", body_tlv + _tlv(b"\x5f\x37", r.to_bytes(32, "big") + s.to_bytes(32, "big")))


def _expired_g2_identity():
    erca_key = ec.generate_private_key(ec.SECP256R1())
    erca_cert = cvc(erca_key, erca_key, b"EUROOT01", b"EUROOT01")  # root stays valid
    msca_key = ec.generate_private_key(ec.SECP256R1())
    card_key = ec.generate_private_key(ec.SECP256R1())
    msca_cert = _cvc_dated(msca_key, erca_key, b"EUROOT01", b"MSSCA001",
                           _EXPIRED_FROM, _EXPIRED_TO)
    card_cert = _cvc_dated(card_key, msca_key, b"MSSCA001", b"EUOCARD1",
                           _EXPIRED_FROM, _EXPIRED_TO)
    return {"card_key": card_key, "card_cert": card_cert, "msca_cert": msca_cert,
            "erca_cert": erca_cert}


def test_expired_certificate_chain_is_rejected_at_the_download_timestamp():
    ids = _expired_g2_identity()
    payloads = g2_core_payloads()
    # EF Card_Download carries the signature/download timestamp (TimeReal, 2025).
    payloads[0x050E] = struct.pack(">I", _DOWNLOAD_2025)
    data = (g2_cert_records(ids["card_cert"], ids["msca_cert"])
            + signed_pairs(payloads, ids["card_key"], 2))

    with trust_store(g2_erca_cert=ids["erca_cert"]) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser._signature_timestamp() == datetime.datetime(2025, 6, 1, tzinfo=_UTC)
    # The chain is cryptographically sound but temporally invalid: fail closed.
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) != VERDICT_VERIFIED


def test_expired_chain_without_a_download_timestamp_keeps_the_historical_verdict():
    """The temporal check is anchored to a real signature timestamp; with none
    the historic "not checked" behaviour (an expired cert is still evidence for
    a historic download) must stand."""
    ids = _expired_g2_identity()
    payloads = g2_core_payloads()  # no Card_Download EF, no timestamp
    data = (g2_cert_records(ids["card_cert"], ids["msca_cert"])
            + signed_pairs(payloads, ids["card_key"], 2))

    with trust_store(g2_erca_cert=ids["erca_cert"]) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser._signature_timestamp() is None
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


# ── CRYPTO-CARD-VU-MIX ─────────────────────────────────────────────────────


def _bare_parser():
    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    tmp.write(b"\x00")
    tmp.close()
    parser = TachoParser(tmp.name)
    os.unlink(tmp.name)
    parser.results = {}
    parser.card_public_key = None
    parser.card_cert_g1 = None
    parser.msca_cert_g1 = None
    parser.validation_status = "Pending"
    return parser


def test_failed_card_chain_is_not_laundered_by_valid_vu_signatures():
    parser = _bare_parser()
    # A presented card chain that does NOT verify (unparseable CVCs).
    parser.card_cert_raw = b"\x7f\x21" + b"\x00" * 30
    parser.msca_cert_raw = b"\x7f\x21" + b"\x01" * 30
    # The file also carries fully valid VU download signatures.
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": True,
    }
    parser.validator = SignatureValidator(certs_dir=tempfile.mkdtemp())

    parser._validate_certificate_chain()

    assert parser.card_public_key is None
    assert parser.validation_status == "Invalid Certificate Chain"
    assert parser.validation_status != "Verified (VU Chain)"


def test_vu_only_file_still_uses_the_vu_signature_verdict():
    """With no card chain presented at all, a valid VU download is still the
    authoritative verdict — the fix must not disable the legitimate path."""
    parser = _bare_parser()
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": True,
    }
    parser.validator = SignatureValidator(certs_dir=tempfile.mkdtemp())

    parser._validate_certificate_chain()

    assert parser.validation_status == "Verified (VU Chain)"


# ── CRYPTO-EF-SKIPPED-SUMMARY ──────────────────────────────────────────────


def test_unknown_signed_ef_is_reported_and_counted_as_skipped():
    pairs = pair_ef_records(
        [(0x0502, 0x00, b"x" * 40), (0x0999, 0x00, b"unknown-payload")],
        [(0x0502, 0x01, b"z" * 128), (0x0999, 0x01, b"unknown-signature")],
    )
    by_tag = {p["tag"]: p for p in pairs}
    assert by_tag[0x0502]["status"] == "paired"
    # The unknown-but-signed EF is present and flagged, not silently dropped.
    assert by_tag[0x0999]["status"] == "unsupported"

    report = verify_ef_pairs(pairs, object(), _AlwaysValidValidator(), "G1")
    assert report["verified"] == 1
    assert report["skipped"] == 1
    assert "skipped" in report["summary"]
    statuses = {r["tag"]: r["status"] for r in report["ef_results"]}
    assert statuses["0x0999"] == "unsupported"


def test_documented_unsigned_card_download_ef_stays_out_of_the_report():
    """EF Card_Download (0x050E) is declared unsigned by DDP_035 even though the
    card carries a signature block; it must NOT become an unverified signed EF
    (that would turn every real card download unverified)."""
    assert pair_ef_records([(0x050E, 0x00, b"\x00\x00\x00\x01")],
                           [(0x050E, 0x01, b"z" * 128)]) == []


def test_metadata_without_a_signature_half_is_not_reported():
    assert pair_ef_records([(0x0002, 0x00, b"icc")], []) == []


def test_unknown_signed_ef_downgrades_a_card_verdict():
    from tests.unit.card_crypto import trusted_root_and_msca

    erca_cert, ids = trusted_root_and_msca()
    payloads = g2_core_payloads()
    data = (g2_cert_records(ids["card_cert"], ids["msca_cert"])
            + signed_pairs(payloads, ids["card_key"], 2)
            + stap(0x0999, 0x02, b"unknown-payload")
            + stap(0x0999, 0x03, b"unknown-signature"))

    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        _parser, result = parse_bytes(data, certs_dir)

    efv = result["ef_signature_verification"]
    assert efv["skipped"] == 1
    assert result["metadata"]["integrity_check"] == "Unverified (EF Signatures Incomplete)"
    assert integrity_verdict(result) == VERDICT_UNVERIFIED
