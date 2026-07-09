"""Regression tests for CVC signed bytes and G2 EF ECDSA fallback."""
from unittest.mock import Mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.engine import TachoParser
from core.crypto.vu_signature import parse_cvc


def _tlv(tag, value):
    """Build a definite-length TLV used by the small synthetic CVC fixtures."""
    if len(value) < 128:
        encoded_length = bytes([len(value)])
    else:
        encoded_length = b"\x81" + bytes([len(value)])
    return tag + encoded_length + value


def _cvc(public_point=b"\x04\x01\x02\x03"):
    public_key = _tlv(b"\x06", bytes.fromhex("2a8648ce3d030107"))
    public_key += _tlv(b"\x86", public_point)
    body = _tlv(b"\x42", b"issuer")
    body += _tlv(b"\x7f\x49", public_key)
    body += _tlv(b"\x5f\x20", b"card")
    body_tlv = _tlv(b"\x7f\x4e", body)
    signature_tlv = _tlv(b"\x5f\x37", b"\x00" * 64)
    return _tlv(b"\x7f\x21", body_tlv + signature_tlv), body_tlv


def test_parse_cvc_rejects_truncated_input_without_index_error():
    cert, _ = _cvc()

    for end in range(len(cert)):
        assert parse_cvc(cert[:end]) is None


def test_parse_cvc_uses_tlv_boundaries_when_body_contains_signature_marker():
    cert, body_tlv = _cvc(b"\x04\x99\x5f\x37\x88")

    parsed = parse_cvc(cert)

    assert parsed is not None
    assert parsed["body_tlv"] == body_tlv


def test_engine_verifies_g2_ef_with_cvc_key_without_card_public_key():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_point = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    cert, _ = _cvc(public_point)
    data = b"G2 EF payload"
    signature_der = private_key.sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature_der)
    signature_raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    parser = object.__new__(TachoParser)
    parser.card_public_key = None
    parser.card_cert_raw = cert
    parser.validator = Mock()
    parser.results = {
        "metadata": {"generation": "G2"},
        "_ef_data": [(0x0523, 0x02, data)],
        "_ef_signatures": [(0x0523, 0x03, signature_raw)],
    }

    parser._verify_ef_signatures()

    report = parser.results["ef_signature_verification"]
    assert report["verified"] == 1
    assert report["failed"] == 0
    assert report["key_trust"] == (
        "CVC public key extracted for G2 EF verification; EF signature "
        "verification does not establish CVC certificate-chain trust"
    )
