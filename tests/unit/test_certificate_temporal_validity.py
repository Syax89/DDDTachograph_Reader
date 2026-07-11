"""Temporal policy tests for X.509 and CVC certificate verification."""
import datetime
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.x509.oid import NameOID

from core.crypto.signature import SignatureValidator
from core.crypto.vu_signature import cvc_temporal_status, parse_cvc, verify_cvc_chain_link
from core.decoders.cert import parse_certificate, parse_g22_certificate_subtag
from core.registry.registry import DecoderRegistry
from core.utils.constants import CVC_EFFECTIVE_DATE_TAG, CVC_EXPIRATION_DATE_TAG


UTC = datetime.timezone.utc
START = datetime.datetime(2010, 1, 1, tzinfo=UTC)
END = datetime.datetime(2011, 1, 1, tzinfo=UTC)


def _tlv(tag, value):
    length = len(value)
    if length < 128:
        encoded_length = bytes([length])
    else:
        encoded_length = b"\x81" + bytes([length])
    return tag + encoded_length + value


def _cvc(private_key, signer, valid_from=START, valid_to=END):
    public_point = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public_key = _tlv(b"\x06", bytes.fromhex("2a8648ce3d030107"))
    public_key += _tlv(b"\x86", public_point)
    body = _tlv(b"\x42", b"issuer")
    body += _tlv(b"\x5f\x20", b"subject")
    body += _tlv(b"\x5f\x25", int(valid_from.timestamp()).to_bytes(4, "big"))
    body += _tlv(b"\x5f\x24", int(valid_to.timestamp()).to_bytes(4, "big"))
    body += _tlv(b"\x7f\x49", public_key)
    body_tlv = _tlv(b"\x7f\x4e", body)
    der_signature = signer.sign(body_tlv, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der_signature)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return _tlv(b"\x7f\x21", body_tlv + _tlv(b"\x5f\x37", signature))


def _x509_certificate(subject_key, issuer_key, subject, issuer):
    return x509.CertificateBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    ).issuer_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)])
    ).public_key(
        subject_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        START
    ).not_valid_after(
        END
    ).sign(issuer_key, hashes.SHA256())


def test_expired_x509_still_has_a_valid_historical_signature():
    parent_key = ec.generate_private_key(ec.SECP256R1())
    child_key = ec.generate_private_key(ec.SECP256R1())
    parent = _x509_certificate(parent_key, parent_key, "parent", "parent")
    child = _x509_certificate(child_key, parent_key, "child", "parent")
    with tempfile.TemporaryDirectory() as certs_dir:
        validator = SignatureValidator(certs_dir=certs_dir)

        assert validator.verify_certificate_chain(child, parent, check_expiry=False)
        status, public_key = validator.validate_tacho_chain(
            child.public_bytes(serialization.Encoding.DER),
            parent.public_bytes(serialization.Encoding.DER))
        assert status == "Incomplete (Missing ERCA)"
        assert public_key is not None
        assert validator.last_chain_temporal_validity["card"]["status"] == "not_checked"
        assert validator.certificate_temporal_status(child)["status"] == "not_checked"
        assert validator.certificate_temporal_status(
            child, START - datetime.timedelta(seconds=1))["status"] == "not_yet_valid"
        assert validator.certificate_temporal_status(
            child, END + datetime.timedelta(seconds=1))["status"] == "expired"
        assert not validator.verify_certificate_chain(
            child, parent, check_expiry=True,
            verification_time=END + datetime.timedelta(seconds=1))
        status, _ = validator.validate_tacho_chain(
            child.public_bytes(serialization.Encoding.DER),
            parent.public_bytes(serialization.Encoding.DER),
            verification_time=END + datetime.timedelta(seconds=1))
        assert status is False


def test_cvc_dates_are_deterministic_and_separate_from_chain_signature():
    msca_key = ec.generate_private_key(ec.SECP256R1())
    card_key = ec.generate_private_key(ec.SECP256R1())
    msca = parse_cvc(_cvc(msca_key, msca_key))
    card_raw = _cvc(card_key, msca_key)
    card = parse_cvc(card_raw)

    assert msca is not None
    assert card is not None
    assert verify_cvc_chain_link(card, msca_key.public_key(), hashes.SHA256)
    assert cvc_temporal_status(card)["status"] == "not_checked"
    assert cvc_temporal_status(card, START - datetime.timedelta(seconds=1))["status"] == "not_yet_valid"
    assert cvc_temporal_status(card, END + datetime.timedelta(seconds=1))["status"] == "expired"

    with tempfile.TemporaryDirectory() as certs_dir:
        validator = SignatureValidator(certs_dir=certs_dir)
        status, _ = validator.validate_tacho_chain(card_raw, _cvc(msca_key, msca_key))
        assert status == "Partial — MSCA→Card verified (no ERCA root)"
        assert validator.last_chain_temporal_validity["card"]["status"] == "not_checked"

        status, _ = validator.validate_tacho_chain(
            card_raw, _cvc(msca_key, msca_key),
            verification_time=END + datetime.timedelta(seconds=1))
        assert status is False


def test_cvc_date_tags_have_consistent_crypto_decoder_and_display_meanings():
    key = ec.generate_private_key(ec.SECP256R1())
    raw = _cvc(key, key)
    effective = int(START.timestamp()).to_bytes(4, "big")
    expiration = int(END.timestamp()).to_bytes(4, "big")

    parsed = parse_cvc(raw)
    assert parsed["effective_date"] == effective.hex()
    assert parsed["expiration_date"] == expiration.hex()
    assert cvc_temporal_status(
        parsed, START - datetime.timedelta(seconds=1))["status"] == "not_yet_valid"
    assert cvc_temporal_status(
        parsed, END + datetime.timedelta(seconds=1))["status"] == "expired"

    certificate_results = {}
    parse_certificate(raw, certificate_results)
    display = certificate_results["certificates"][0]
    assert display["valid_from"] == START.isoformat()
    assert display["valid_to"] == END.isoformat()

    subtag_results = {}
    parse_g22_certificate_subtag(effective, subtag_results, CVC_EFFECTIVE_DATE_TAG)
    parse_g22_certificate_subtag(expiration, subtag_results, CVC_EXPIRATION_DATE_TAG)
    assert subtag_results["card_icc"] == {
        "effective_date": "01/01/2010",
        "expiry_date": "01/01/2011",
    }

    names = DecoderRegistry.instance().get_tag_names()
    assert names[CVC_EFFECTIVE_DATE_TAG] == "G22_CardEffectiveDate"
    assert names[CVC_EXPIRATION_DATE_TAG] == "G22_CardExpiryDate"
