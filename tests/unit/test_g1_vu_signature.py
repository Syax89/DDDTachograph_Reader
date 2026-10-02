"""Integrity tests for signed Generation 1 VU TREP sections (C1 / E-F4).

``root_anchored`` is derived from the structured per-generation chain trust
recorded by ``_validate_certificate_chain``, never from the human-readable
verdict string. A suffixed/repeated verdict must stay consistent with the real
chain, and an unanchored chain must never report anchoring just because the
status string happens to start with "Verified".
"""
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.engine import TachoParser


def _parser_for(data, key, *, chain_anchored=True, status="Verified"):
    parser = TachoParser(__file__)
    parser.raw_data = data
    parser.is_vu = True
    parser.results["metadata"]["generation"] = "G1 (Digital)"
    parser.card_public_key = key.public_key() if key is not None else None
    # Structured per-generation chain trust is established explicitly (as the
    # real chain phase does), NOT inferred from a textual Verified stamp.
    parser._chain_trust = {"G1": chain_anchored, "G2": False}
    parser.validation_status = status
    return parser


def _signed_overview(key):
    # TREP 01 has a fixed 493-byte body in the G1 structural walker.
    body = b"A" * 491 + b"\x00\x00"  # zero company-lock/control counts
    signature = key.sign(body[388:], padding.PKCS1v15(), hashes.SHA1())
    return b"\x76\x01" + body + signature


def test_g1_vu_valid_signature_keeps_verified_status():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    parser = _parser_for(_signed_overview(key), key)

    parser._verify_g1_vu_signatures()

    report = parser.results["signature_verification"]
    assert report["all_treps_valid"] is True
    assert report["root_anchored"] is True
    assert parser.validation_status == "Verified (G1 VU chain and TREP signatures)"


def test_g1_vu_tampered_payload_invalidates_integrity_status():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    data = bytearray(_signed_overview(key))
    data[400] ^= 0xFF
    parser = _parser_for(bytes(data), key)

    parser._verify_g1_vu_signatures()

    assert parser.results["signature_verification"]["all_treps_valid"] is False
    assert parser.validation_status == "Invalid G1 VU TREP Signature"


def test_g1_vu_missing_signature_is_incomplete():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    parser = _parser_for(b"\x76\x01" + b"A" * 491 + b"\x00\x00", key)

    parser._verify_g1_vu_signatures()

    report = parser.results["signature_verification"]
    assert report["missing_signatures"] == 1
    assert report["all_treps_valid"] is False
    assert parser.validation_status == "Incomplete (G1 VU TREP signatures missing)"


def test_g1_sensor_extension_without_signatures_does_not_downgrade_download():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    data = _signed_overview(key) + b"\x76\x11sensor-data\x76\x14\x00\x00"
    parser = _parser_for(data, key)

    parser._verify_g1_vu_signatures()

    report = parser.results["signature_verification"]
    assert report["all_treps_valid"] is True
    assert report["summary"] == "G1 VU TREP signatures: 1/1 valid"
    assert [entry["signature_valid"] for entry in report["treps"]] == [True, None, None]
    assert parser.validation_status == "Verified (G1 VU chain and TREP signatures)"


# ── C1: root anchoring is structured, not string-inferred ──────────────────

def test_repeated_valid_verifier_keeps_anchoring_consistent():
    """Re-running on the verifier's own suffixed verdict must stay anchored."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    parser = _parser_for(_signed_overview(key), key)

    parser._verify_g1_vu_signatures()
    first = parser.validation_status
    first_anchor = parser.results["signature_verification"]["root_anchored"]

    parser._verify_g1_vu_signatures()
    second_anchor = parser.results["signature_verification"]["root_anchored"]

    assert first == "Verified (G1 VU chain and TREP signatures)"
    assert first_anchor is True and second_anchor is True
    assert parser.validation_status == first


def test_no_messages_downgrades_and_stays_anchored():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    parser = _parser_for(b"\x76\x01", key)

    parser._verify_g1_vu_signatures()

    report = parser.results["signature_verification"]
    assert report["summary"] == "No G1 VU TREP sections found"
    assert report["root_anchored"] is True  # chain is anchored even with no TREPs
    assert parser.validation_status == "Unverified (G1 VU TREP Signatures Not Checked)"


def test_missing_key_downgrades():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    parser = _parser_for(_signed_overview(key), None)

    parser._verify_g1_vu_signatures()

    report = parser.results["signature_verification"]
    assert report["msca_to_vu"] is False
    assert report["all_treps_valid"] is False
    assert parser.validation_status == "Unverified (G1 VU TREP Signatures Not Checked)"


def test_unsigned_only_sections_do_not_stay_verified():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    parser = _parser_for(b"\x76\x11sensor\x76\x14\x00\x00", key)

    parser._verify_g1_vu_signatures()

    report = parser.results["signature_verification"]
    assert report["all_treps_valid"] is False
    assert parser.validation_status == "Unverified (G1 VU TREP Signatures Not Checked)"


def test_suffixed_input_verdict_is_downgraded_on_invalid_signature():
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    data = bytearray(_signed_overview(key))
    data[400] ^= 0xFF
    parser = _parser_for(bytes(data), key, status="Verified (already suffixed)")

    parser._verify_g1_vu_signatures()

    assert not parser.validation_status.startswith("Verified")
    assert parser.validation_status == "Invalid G1 VU TREP Signature"
    # The genuine chain is still anchored; only the TREP signature failed.
    assert parser.results["signature_verification"]["root_anchored"] is True


def test_partial_unanchored_chain_never_reports_anchored():
    """A Verified string over an unanchored chain must not report anchoring."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    parser = _parser_for(_signed_overview(key), key, chain_anchored=False)

    parser._verify_g1_vu_signatures()

    report = parser.results["signature_verification"]
    assert report["all_treps_valid"] is True
    assert report["root_anchored"] is False
