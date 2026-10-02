"""Regression test for XD-F4 (CARD-G22-CERT-TAGS): G2.2-native certificate
tags 0xC102 (card) / 0xC10A (CA/MSCA) must reach the same
card_cert_raw/msca_cert_raw attributes as their G1/G2 counterparts
(0xC100/0x0103 and 0xC108/0x0104), or the chain validator never sees them
and a G2.2 card's certificate chain is silently never checked.
"""
import struct
import tempfile

from app.engine import TachoParser


def _stap(tag, dtype, payload):
    return struct.pack(">HBH", tag, dtype, len(payload)) + payload


def test_g22_native_certificate_tags_feed_the_chain_validator():
    data = _stap(0xC102, 0x00, b"\x30" + b"\x00" * 193) + _stap(0xC10A, 0x00, b"\x30" + b"\x00" * 193)
    with tempfile.NamedTemporaryFile(suffix=".ddd", delete=False) as f:
        f.write(data)
        path = f.name

    parser = TachoParser(path)
    result = parser.parse()

    assert parser.card_cert_raw is not None, "0xC102 must populate card_cert_raw"
    assert parser.msca_cert_raw is not None, "0xC10A must populate msca_cert_raw"
    # A chain was actually attempted (and rejected, these are dummy bytes) --
    # not "Incomplete Certificates", which is what silently skipping the
    # chain looked like before this fix.
    assert result["metadata"]["integrity_check"] != "Incomplete Certificates"


if __name__ == "__main__":
    test_g22_native_certificate_tags_feed_the_chain_validator()
    print("OK")
