"""Integrity tests for signed Generation 1 VU TREP sections."""
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.engine import TachoParser


def _parser_for(data, key):
    parser = TachoParser(__file__)
    parser.raw_data = data
    parser.is_vu = True
    parser.results["metadata"]["generation"] = "G1 (Digital)"
    parser.card_public_key = key.public_key()
    parser.validation_status = "Verified"
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
