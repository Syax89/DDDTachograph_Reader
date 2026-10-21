"""A generation-2 certificate must not be dropped by a generation-1 size gate.

C108h is the CA certificate FID in both generations. In the generation-1 DF it
is the flat 194-byte ISO 9796-2 RSA block (Annex 1B §2.30); in the
generation-2 DF the same FID carries a CVC (``0x7F21`` BER-TLV) or DER X.509
certificate, whose length depends on the key profile and is *not* 194 bytes.

``TagDecoder`` registrations for the certificate FIDs used to pin
``record_size=194``, so ``_validate_decoder_payload`` rejected every genuine
generation-2 CA certificate with ``decoder_record_size_violation`` and the
certificate never reached ``parse_certificate`` — a real certificate silently
missing from the report. The decoder itself already self-validates (it
auto-detects CVC/DER vs the 194-byte RSA form and ignores anything else), so
the length gate is redundant *and* wrong.
"""
import pytest

from core.parser.deterministic import DeterministicParser
from cryptography.hazmat.primitives.asymmetric import ec

from tests.unit.card_crypto import (
    cvc_pad,
    g2_cert_records,
    stap,
    trusted_root_and_msca,
)


def _formats(result):
    return [c.get("format") for c in result.get("certificates", [])]


@pytest.fixture(scope="module")
def g2_identity():
    _erca_cert, identity = trusted_root_and_msca()
    # A 206-byte CVC reproduces a real generation-2 CA certificate (the samples
    # carry a 205-byte one): longer than the 194-byte generation-1 RSA block, so
    # a record_size=194 gate rejects it.
    identity["msca_cert"] = cvc_pad(
        ec.generate_private_key(ec.SECP256R1()), identity["msca_key"],
        b"MSSCA001", b"EUOMSCA1", pad=16)
    assert len(identity["msca_cert"]) > 194
    return identity


def test_generation_2_ca_certificate_on_c108_is_decoded(g2_identity):
    """A CVC longer than 194 bytes on 0xC108 is a valid CA certificate."""
    data = g2_cert_records(g2_identity["card_cert"], g2_identity["msca_cert"])

    result = DeterministicParser().parse(data, is_vu=False)

    assert not result["metadata"].get("decoder_validation_warnings")
    assert _formats(result) == ["CVC", "CVC"]


def test_generation_2_certificate_alias_fids_are_decoded(g2_identity):
    """The same gate was on the 0103h/0104h certificate alias FIDs."""
    data = (stap(0x0103, 0x02, g2_identity["card_cert"])
            + stap(0x0104, 0x02, g2_identity["msca_cert"]))

    result = DeterministicParser().parse(data, is_vu=False)

    assert not result["metadata"].get("decoder_validation_warnings")
    assert _formats(result) == ["CVC", "CVC"]


def test_generation_1_rsa_certificate_is_still_decoded(g2_identity):
    """The 194-byte generation-1 RSA form keeps working on the same FID."""
    rsa_cert = bytes(range(194))
    data = stap(0xC108, 0x00, rsa_cert)

    result = DeterministicParser().parse(data, is_vu=False)

    assert _formats(result) == ["G1_RSA"]
    assert result["certificates"][0]["total_size"] == 194


def test_a_payload_that_is_neither_form_is_not_a_certificate(g2_identity):
    """Dropping the gate must not turn arbitrary bytes into certificates."""
    data = stap(0xC108, 0x02, b"\xAA" * 205)

    result = DeterministicParser().parse(data, is_vu=False)

    assert _formats(result) == []


def test_a_194_byte_cvc_on_c108_is_a_cvc_not_an_rsa_certificate(g2_identity):
    """The decoder, not the length, decides the form (cvc_pad is exactly 194)."""
    signer = g2_identity["msca_key"]
    padded = cvc_pad(ec.generate_private_key(ec.SECP256R1()), signer,
                     b"MSSCA001", b"EUOCARD1")
    assert len(padded) == 194
    data = stap(0xC108, 0x02, padded)

    result = DeterministicParser().parse(data, is_vu=False)

    assert _formats(result) == ["CVC"]

