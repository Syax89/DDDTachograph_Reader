"""User-visible VU integrity strings must not overstate what was verified.

The card path already refuses to call a chain "Verified" without a trusted ERCA
root ("Unverified (Missing ERCA Root)"), but the vehicle-unit path used to print
and export ``Verified (VU — TREP ok, chain partial)`` for exactly the same
condition: a user with an empty ``certs/`` directory was told the file is
verified although the VU key was anchored to nothing.
"""
import os
import tempfile

from app.engine import TachoParser


def _bare_parser():
    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    tmp.write(b"\x00")
    tmp.close()
    parser = TachoParser(tmp.name)
    os.unlink(tmp.name)
    parser.results = {}
    parser.card_public_key = None
    parser.card_cert_raw = None
    parser.msca_cert_raw = None
    parser.card_cert_g1 = None
    parser.msca_cert_g1 = None
    parser.validation_status = "Pending"
    parser.validator.root_certificates.clear()
    return parser


def test_unanchored_vu_chain_is_not_reported_as_verified():
    parser = _bare_parser()
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": False,
    }

    parser._validate_certificate_chain()

    assert not parser.validation_status.startswith("Verified"), (
        "an unanchored VU chain must not print/export as Verified: "
        f"{parser.validation_status}")
    assert parser.validation_status.startswith("Unverified")
    assert "TREP" in parser.validation_status


def test_anchored_vu_chain_still_reads_verified():
    parser = _bare_parser()
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": True,
    }

    parser._validate_certificate_chain()

    assert parser.validation_status == "Verified (VU Chain)"
