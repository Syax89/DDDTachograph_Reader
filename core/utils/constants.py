UNIX_EPOCH_2000 = 946684800
UNIX_EPOCH_2100 = 4102444800
MAX_TLV_LENGTH = 0x100000
MAX_BER_TAG_OCTETS = 4
STAP_HEADER_SIZE = 5
MAX_RECURSION_DEPTH = 12
RECORD_ARRAY_MAX_RECORDS = 20000
RECORD_ARRAY_MAX_SIZE = 4096
# Global cap on records decoded from one VU RecordArray stream. The per-array
# cap above does not bound the stream, so a small densely-packed file could
# otherwise amplify into hundreds of MB of per-record dicts.
VU_MAX_TOTAL_RECORDS = 500000
MAX_ODO_DISTANCE_KM = 1000000

# CVC validity fields: 0x5F25 is effective/not-before; 0x5F24 is
# expiration/not-after. These semantics apply to both crypto and display paths.
CVC_EFFECTIVE_DATE_TAG = 0x5F25
CVC_EXPIRATION_DATE_TAG = 0x5F24


def looks_like_g2_certificate(payload) -> bool:
    """True when *payload* carries a generation-2 certificate encoding.

    Generation-2 certificates are either CVC (tag ``0x7F21`` — two bytes
    ``7F 21``) or DER X.509 (``30`` followed by a long-form length byte with
    the high bit set). A generation-1 certificate is an ISO 9796-2 RSA block
    whose leading byte is the first byte of an unconstrained RSA signature, so
    ``0x30``/``0x7F`` alone does not make it a generation-2 encoding. The
    second byte is what disambiguates the two generations, both when the
    parser captures a ``C100``/CardSign certificate and when the chain
    validator routes it.
    """
    if not payload or len(payload) < 2:
        return False
    if payload[0] == 0x7F and payload[1] == 0x21:
        return True
    return payload[0] == 0x30 and bool(payload[1] & 0x80)

# EC curve OID (hex string) → human-readable name.
EC_CURVE_OIDS = {
    "2b2403030208010107": "brainpoolP256r1",
    "2b2403030208010b0d": "brainpoolP384r1",
    "2b2403030208010d0b": "brainpoolP512r1",
    "2a8648ce3d030107": "NIST P-256",
    "2b81040022": "NIST P-384",
    "2b81040023": "NIST P-521",
}
