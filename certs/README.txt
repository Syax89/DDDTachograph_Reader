Place European Root Certificates (ERCA) here.

G1 (Annex 1B, RSA 1024-bit):
  - EC_PK.bin: raw KID(8) + n(128) + e(8) = 144 bytes
  - EC_PK.pem: custom "BEGIN ERCA PK" base64 encoding of the same key

G2 (Annex 1C, brainpoolP256r1 ECDSA):
  - Place a raw uncompressed EC point (65 bytes: 0x04 || x || y)
    as e.g. ERCA2_PK.bin
  - Or a DER-encoded SubjectPublicKeyInfo as .pem/.der

The ERCA-2 public key is published by the EU JRC Digital Tachograph team
at https://dtc.jrc.ec.europa.eu/
