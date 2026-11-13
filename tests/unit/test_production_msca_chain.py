"""Real, public MSCA certificates verify under the ERCA root shipped in certs/.

Synthetic chains test the verifier against itself; these two production
certificates (see tests/fixtures/msca/README.md) test it against what ERCA
actually signs — the CVC layout, the brainpoolP256r1 and NIST P-256 curves and
the root key in certs/. A change that breaks real-world anchoring fails here.
"""
from pathlib import Path

import pytest

from core.crypto.signature import SignatureValidator
from core.crypto.vu_signature import cvc_public_key, parse_cvc, verify_cvc_chain_link

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = sorted((ROOT / "tests" / "fixtures" / "msca").glob("*.cvc"))
ERCA_GEN2_1 = "fd45432001ffff01"


def _roots():
    keys = SignatureValidator(certs_dir=str(ROOT / "certs"))._g2_erca_keys()
    assert ERCA_GEN2_1 in keys, "the ERCA Gen2(1) root must be in certs/"
    return keys


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_production_msca_verifies_under_the_shipped_root(path):
    cert = parse_cvc(path.read_bytes())
    assert cert is not None
    assert cert["car"] == ERCA_GEN2_1
    assert cvc_public_key(cert)[0] is not None
    assert verify_cvc_chain_link(cert, *_roots()[ERCA_GEN2_1])


def test_both_curves_in_use_are_covered():
    curves = {parse_cvc(p.read_bytes())["curve_oid"] for p in FIXTURES}
    assert curves == {"2b2403030208010107", "2a8648ce3d030107"}


def test_a_tampered_production_certificate_fails():
    raw = bytearray(FIXTURES[0].read_bytes())
    raw[20] ^= 0x01          # inside the signed body
    cert = parse_cvc(bytes(raw))
    assert cert is None or not verify_cvc_chain_link(cert, *_roots()[ERCA_GEN2_1])
