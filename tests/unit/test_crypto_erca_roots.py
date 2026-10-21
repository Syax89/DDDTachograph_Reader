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
from cryptography.hazmat.primitives.asymmetric import ec

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
