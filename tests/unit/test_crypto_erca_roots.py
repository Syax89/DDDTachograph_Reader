"""ERCA trust-store loading regressions.

``certs/README.txt`` tells a user to drop the EU ERCA material into ``certs/``,
including a DER/PEM ``SubjectPublicKeyInfo``. Those files used to be dropped on
the floor: a function-local re-import of ``serialization`` made the name local
for the whole loader, so the generic PEM/DER branch raised ``UnboundLocalError``
which the loader swallowed as "Failed to load cert". The root store stayed
empty and every chain that needed an anchor reported "missing ERCA root".

The keys here are synthetic (generated per test); no real certificate material
is used.
"""
import logging
import os
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from core.crypto.signature import SignatureValidator
from tests.unit.card_crypto import new_cvc_identity


def _write(directory, name, payload):
    with open(os.path.join(directory, name), "wb") as handle:
        handle.write(payload)


def test_pem_public_key_root_is_loaded():
    """A PEM ``SubjectPublicKeyInfo`` in the trust store must become a root."""
    erca_key = ec.generate_private_key(ec.SECP256R1())
    pem = erca_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    with tempfile.TemporaryDirectory() as certs_dir:
        _write(certs_dir, "ERCA2_PK.pem", pem)
        validator = SignatureValidator(certs_dir=certs_dir)

    assert validator.root_certificates, "the PEM root key was dropped"
    assert validator._g2_erca_keys(), "the loaded PEM root is not usable as a G2 anchor"


def test_pem_public_key_root_anchors_a_real_chain(caplog):
    """A PEM root in the store must actually anchor an ERCA→MSCA→Card chain."""
    erca_key = ec.generate_private_key(ec.SECP256R1())
    identity = new_cvc_identity(erca_key)
    pem = erca_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    with tempfile.TemporaryDirectory() as certs_dir:
        _write(certs_dir, "ERCA2_PK.pem", pem)
        validator = SignatureValidator(certs_dir=certs_dir)

    with caplog.at_level(logging.ERROR, logger="SignatureValidator"):
        status, public_key = validator.validate_tacho_chain(
            identity["card_cert"], identity["msca_cert"])

    assert status is True, "a genuine chain was not anchored to the loaded PEM root"
    assert public_key is not None
    assert not [r for r in caplog.records if "Failed to load cert" in r.getMessage()]


# ── Every G1 ERCA key in the store is tried, not just the first ────────────

def test_g1_chain_uses_every_erca_root_in_the_store():
    """A decoy root ahead of the genuine one must not fail a genuine chain.

    The loader keeps the root material in ``os.listdir`` order, which is not
    sorted, and the G1 chain used to consume only the first RSA key it found.
    Two published ERCA keys in ``certs/`` (or a stale key left behind beside
    the current one) therefore reported a genuine chain as invalid.
    """
    from tests.unit.card_crypto import g1_identity

    identity = g1_identity()
    decoy = rsa.generate_private_key(public_exponent=65537, key_size=1024).public_key()
    real = identity["erca_key"].public_key()

    validator = SignatureValidator(certs_dir=tempfile.mkdtemp())
    validator.root_certificates = {"decoy": decoy, "real": real}
    status, public_key = validator.validate_tacho_chain(
        identity["card_cert"], identity["msca_cert"])

    assert status is True, "the genuine ERCA root was never tried"
    assert public_key is not None


def test_g1_chain_reports_a_bad_root_as_invalid():
    """Trying every root must not turn a wrong root into a verified chain."""
    from tests.unit.card_crypto import g1_identity

    identity = g1_identity()
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=1024).public_key()

    validator = SignatureValidator(certs_dir=tempfile.mkdtemp())
    validator.root_certificates = {"wrong": wrong}
    status, public_key = validator.validate_tacho_chain(
        identity["card_cert"], identity["msca_cert"])

    assert status is False
    assert public_key is None


# ── DER material, as documented in certs/README.txt ────────────────────────

def test_der_public_key_root_is_loaded():
    """``certs/README.txt`` documents ``.pem/.der``; ``.der`` was ignored."""
    erca_key = ec.generate_private_key(ec.SECP256R1())
    der = erca_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    with tempfile.TemporaryDirectory() as certs_dir:
        _write(certs_dir, "ERCA2_PK.der", der)
        validator = SignatureValidator(certs_dir=certs_dir)

    assert validator.root_certificates, "the DER root key was dropped"
    assert validator._g2_erca_keys(), "the loaded DER root is not usable as a G2 anchor"


def test_der_certificate_root_is_loaded():
    """A DER X.509 CA certificate is documented as accepted too."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic ERCA")])
    now = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(1).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=365))
            .sign(key, hashes.SHA256()))
    with tempfile.TemporaryDirectory() as certs_dir:
        _write(certs_dir, "erca.der", cert.public_bytes(serialization.Encoding.DER))
        validator = SignatureValidator(certs_dir=certs_dir)

    assert "CN=Synthetic ERCA" in validator.root_certificates
