"""Shared EC curve OID constants for tachograph signature verification.

All OID strings in hex (without leading 0x). Derived from:
- brainpoolP256r1 (RFC 5639, § 4.5)
- brainpoolP384r1 (RFC 5639, § 4.6)
- brainpoolP512r1 (RFC 5639, § 4.7)
- secp256r1 / NIST P-256 (RFC 5480)
- secp384r1 / NIST P-384 (RFC 5480)
- secp521r1 / NIST P-521 (RFC 5480)
"""

CURVE_OID_HEX = {
    "2b2403030208010107": "brainpoolP256r1",
    "2b2403030208010b0d": "brainpoolP384r1",
    "2b2403030208010d0b": "brainpoolP512r1",
    "2a8648ce3d030107": "secp256r1",
    "2b81040022": "secp384r1",
    "2b81040023": "secp521r1",
}
