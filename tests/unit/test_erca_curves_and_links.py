"""ERCA-2 roots on the larger brainpool curves, and ERCA link certificates.

Found by running the JRC interoperability test PKI ("Samples v1.4") through the
verifier: every certificate under the test ERCA (2) and ERCA (3) failed, 42 of
115. Two independent defects:

* The brainpoolP384r1 / brainpoolP512r1 OIDs were mis-encoded
  (``…08 01 0b 0d`` / ``…08 01 0d 0b`` instead of ``…08 01 01 0b`` /
  ``…08 01 01 0d``), so no 384/512-bit CVC key could be built or verified.
* A link certificate (old root → new root) was registered under its CAR (the
  *old* root's reference) although it carries the *new* root's key, and it was
  trusted without checking that the old root signed it.

The certificates here are generated with real ECDSA keys; nothing is mocked.
"""
import os
import tempfile

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from core.crypto.signature import SignatureValidator
from core.crypto.vu_signature import cvc_public_key, parse_cvc, verify_cvc_chain_link
from core.decoders.cert import _CVC_CURVE_NAMES
from core.utils.constants import EC_CURVE_OIDS

# OID DER bodies as the cryptography library encodes them (SubjectPublicKeyInfo).
CURVES = {
    "bp256": (ec.BrainpoolP256R1(), hashes.SHA256, "2b2403030208010107", 32),
    "bp384": (ec.BrainpoolP384R1(), hashes.SHA384, "2b240303020801010b", 48),
    "bp512": (ec.BrainpoolP512R1(), hashes.SHA512, "2b240303020801010d", 64),
}


def tlv(tag, value):
    """BER-TLV with short, one- or two-byte long-form length (512-bit certs
    exceed 255 bytes)."""
    n = len(value)
    if n < 0x80:
        length = bytes([n])
    elif n < 0x100:
        length = b"\x81" + bytes([n])
    else:
        length = b"\x82" + n.to_bytes(2, "big")
    return bytes(tag) + length + value


def _key(curve):
    return ec.generate_private_key(CURVES[curve][0])


def _cvc(subject_key, subject_curve, signer_key, signer_curve, car, chr_):
    """A CVC whose key is on ``subject_curve``, signed with the signer's hash."""
    oid = CURVES[subject_curve][2]
    point = subject_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    body = tlv(b"\x42", car) + tlv(b"\x5f\x20", chr_)
    body += tlv(b"\x5f\x25", (1600000000).to_bytes(4, "big"))
    body += tlv(b"\x5f\x24", (2000000000).to_bytes(4, "big"))
    body += tlv(b"\x7f\x49", tlv(b"\x06", bytes.fromhex(oid)) + tlv(b"\x86", point))
    body_tlv = tlv(b"\x7f\x4e", body)
    _, hash_cls, _, size = CURVES[signer_curve]
    r, s = utils.decode_dss_signature(signer_key.sign(body_tlv, ec.ECDSA(hash_cls())))
    return tlv(b"\x7f\x21", body_tlv + tlv(b"\x5f\x37",
                                            r.to_bytes(size, "big") + s.to_bytes(size, "big")))


def test_oid_bodies_match_the_cryptography_library_encoding():
    for curve, (obj, _hash, oid, _size) in CURVES.items():
        spki = ec.generate_private_key(obj).public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        assert bytes.fromhex(oid) in spki, curve
        assert oid in EC_CURVE_OIDS, curve
        assert oid in _CVC_CURVE_NAMES, curve


@pytest.mark.parametrize("curve", sorted(CURVES))
def test_self_signed_root_verifies_on_every_brainpool_curve(curve):
    key = _key(curve)
    cert = parse_cvc(_cvc(key, curve, key, curve, b"EUROOT01", b"EUROOT01"))
    pub, hash_cls = cvc_public_key(cert)
    assert pub is not None and pub.curve.name == CURVES[curve][0].name
    assert verify_cvc_chain_link(cert, pub, hash_cls)


def _validator(*certs):
    tmp = tempfile.TemporaryDirectory()
    for index, raw in enumerate(certs):
        with open(os.path.join(tmp.name, f"erca_{index}.bin"), "wb") as handle:
            handle.write(raw)
    return tmp, SignatureValidator(certs_dir=tmp.name)


def _pki():
    k1, k2, k3 = _key("bp256"), _key("bp384"), _key("bp512")
    root1 = _cvc(k1, "bp256", k1, "bp256", b"EUROOT01", b"EUROOT01")
    link12 = _cvc(k2, "bp384", k1, "bp256", b"EUROOT01", b"EUROOT02")
    link23 = _cvc(k3, "bp512", k2, "bp384", b"EUROOT02", b"EUROOT03")
    return (k1, k2, k3), root1, link12, link23


def _card_chain_under(root_key, root_curve, root_chr):
    msca_key, card_key = _key("bp384"), _key("bp256")
    msca = _cvc(msca_key, "bp384", root_key, root_curve, root_chr, b"MSCA0001")
    card = _cvc(card_key, "bp256", msca_key, "bp384", b"MSCA0001", b"CARD0001")
    return card, msca


def test_link_certificates_register_the_new_root_under_its_chr():
    (_k1, _k2, _k3), root1, link12, link23 = _pki()
    # Deliberately out of order: the 2→3 link is seen before the 1→2 link.
    tmp, validator = _validator(link23, root1, link12)
    with tmp:
        keys = validator._g2_erca_keys()
    assert set(keys) == {b"EUROOT01".hex(), b"EUROOT02".hex(), b"EUROOT03".hex()}
    assert keys[b"EUROOT02".hex()][0].curve.name == "brainpoolP384r1"
    assert keys[b"EUROOT03".hex()][0].curve.name == "brainpoolP512r1"
    # The old root keeps its own key: the link did not overwrite it.
    assert keys[b"EUROOT01".hex()][0].curve.name == "brainpoolP256r1"


@pytest.mark.parametrize("level", [2, 3])
def test_msca_under_a_linked_root_is_anchored(level):
    keys, root1, link12, link23 = _pki()
    root_key = keys[level - 1]
    root_curve = ("bp384", "bp512")[level - 2]
    card, msca = _card_chain_under(root_key, root_curve, f"EUROOT0{level}".encode())
    tmp, validator = _validator(root1, link12, link23)
    with tmp:
        status, pub = validator._validate_g2_cvc_chain(card, msca)
    assert status is True
    assert pub is not None


def test_a_link_not_signed_by_a_trusted_root_is_ignored():
    k1 = _key("bp256")
    root1 = _cvc(k1, "bp256", k1, "bp256", b"EUROOT01", b"EUROOT01")
    attacker, new_key = _key("bp256"), _key("bp384")
    forged_link = _cvc(new_key, "bp384", attacker, "bp256", b"EUROOT01", b"EUROOT02")
    tmp, validator = _validator(root1, forged_link)
    with tmp:
        keys = validator._g2_erca_keys()
        assert b"EUROOT02".hex() not in keys
        card, msca = _card_chain_under(new_key, "bp384", b"EUROOT02")
        status, _pub = validator._validate_g2_cvc_chain(card, msca)
    assert status is not True


def test_a_link_without_its_issuer_is_ignored():
    (_k1, k2, _k3), _root1, link12, _link23 = _pki()
    tmp, validator = _validator(link12)
    with tmp:
        keys = validator._g2_erca_keys()
        assert keys == {}
        card, msca = _card_chain_under(k2, "bp384", b"EUROOT02")
        status, _pub = validator._validate_g2_cvc_chain(card, msca)
    assert status is not True
