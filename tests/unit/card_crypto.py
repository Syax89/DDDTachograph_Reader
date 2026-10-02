"""Shared synthetic-crypto fixtures for driver-card integrity tests.

Builders here generate **real** RSA (G1 ISO 9796-2 / PKCS#1 v1.5) and ECDSA
(G2 CVC) certificate chains and EF signatures. Nothing in the shipped crypto or
parser is mocked: a test that uses these helpers exercises the actual chain
validator and signature verifier. Synthetic roots are written into a temporary
trust store and injected via ``SignatureValidator(certs_dir=...)``.

Generic identities only — no personal data, no real cards.
"""
import contextlib
import hashlib
import os
import struct
import tempfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils

P256_OID = "2a8648ce3d030107"


def tlv(tag, value):
    """Build a definite-length BER-TLV element (short or one-byte long form)."""
    if len(value) < 128:
        length = bytes([len(value)])
    else:
        length = b"\x81" + bytes([len(value)])
    return bytes(tag) + length + value


def cvc(private_key, signer_key, car, chr_):
    """Build a real CVC (0x7F21) certificate signed by ``signer_key``."""
    point = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public_key = tlv(b"\x06", bytes.fromhex(P256_OID)) + tlv(b"\x86", point)
    body = tlv(b"\x42", car) + tlv(b"\x5f\x20", chr_)
    body += tlv(b"\x5f\x25", (1600000000).to_bytes(4, "big"))
    body += tlv(b"\x5f\x24", (2000000000).to_bytes(4, "big"))
    body += tlv(b"\x7f\x49", public_key)
    body_tlv = tlv(b"\x7f\x4e", body)
    der = signer_key.sign(body_tlv, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return tlv(b"\x7f\x21", body_tlv + tlv(b"\x5f\x37", signature))


def ef_signature(card_key, data):
    """Raw r‖s ECDSA EF signature (what a G2 card stores)."""
    der = card_key.sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def stap(tag, dtype, data):
    """A tachograph STAP record: tag(2) + dtype(1) + length(2) + payload."""
    return struct.pack(">HBH", tag, dtype, len(data)) + data


def new_cvc_identity(msca_signer, *, root_chr=b"EUROOT01"):
    """Return a Card←MSCA←``msca_signer`` CVC identity.

    ``msca_signer`` is the ERCA key that signs the MSCA (``None`` for a
    self-signed attacker MSCA). Certificate references are linked the correct
    way round: the CA's ``car`` is the root's ``chr`` and the CardSign's ``car``
    is the CA's ``chr``, with distinct holder identities.
    """
    card_key = ec.generate_private_key(ec.SECP256R1())
    msca_key = ec.generate_private_key(ec.SECP256R1())
    signer = msca_key if msca_signer is None else msca_signer
    msca_chr = b"MSSCA001"
    msca_car = msca_chr if msca_signer is None else root_chr
    msca_cert = cvc(msca_key, signer, msca_car, msca_chr)
    card_cert = cvc(card_key, msca_key, msca_chr, b"EUOCARD1")
    return {
        "card_key": card_key,
        "msca_key": msca_key,
        "msca_cert": msca_cert,
        "card_cert": card_cert,
    }


def trusted_root_and_msca():
    """Real ERCA→MSCA→Card CVC chain rooted at a synthetic-but-genuine ERCA key."""
    erca_key = ec.generate_private_key(ec.SECP256R1())
    erca_cert = cvc(erca_key, erca_key, b"EUROOT01", b"EUROOT01")
    identity = new_cvc_identity(erca_key)
    return erca_cert, identity


def _rsa_g1_cert(child, signer, car, chr_):
    """A 194-byte G1 certificate: ISO 9796-2 recovered block + clear remainder."""
    pub = child.public_key().public_numbers()
    content = b"\x01" + car + b"\x00" * 7 + struct.pack(">I", 2000000000) + chr_
    content += pub.n.to_bytes(128, "big") + pub.e.to_bytes(8, "big")
    assert len(content) == 164
    block = b"\x6a" + content[:106] + hashlib.sha1(content).digest() + b"\xbc"
    private = signer.private_numbers()
    sn = pow(int.from_bytes(block, "big"), private.d, private.public_numbers.n)
    return sn.to_bytes(128, "big") + content[106:] + car


def g1_identity():
    """A real ERCA→MSCA→Card G1 RSA chain (ISO 9796-2, Annex 1B Appendix 11)."""
    erca = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    msca = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    msca_cert = _rsa_g1_cert(msca, erca, b"ROOT0001", b"MSCA0001")
    while True:
        card_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        card_cert = _rsa_g1_cert(card_key, msca, b"MSCA0001", b"CARD0001")
        # Avoid the unrelated encoding-marker G1/G2 ambiguity in the chain.
        if card_cert[0] not in (0x30, 0x7F):
            break
    return {"card_key": card_key, "card_cert": card_cert,
            "msca_cert": msca_cert, "erca_key": erca}


def write_g1_trust(certs_dir, erca_key):
    """Write the raw RSA ERCA modulus+exponent trust material (n(128)+e(8))."""
    public = erca_key.public_key().public_numbers()
    with open(os.path.join(certs_dir, "root.bin"), "wb") as handle:
        handle.write(public.n.to_bytes(128, "big") + public.e.to_bytes(8, "big"))


@contextlib.contextmanager
def trust_store(g2_erca_cert=None, g1_erca_key=None):
    """A temporary ERCA trust store holding a G2 CVC root and/or a G1 RSA root."""
    with tempfile.TemporaryDirectory() as certs_dir:
        if g2_erca_cert is not None:
            with open(os.path.join(certs_dir, "erca_root.bin"), "wb") as handle:
                handle.write(g2_erca_cert)
        if g1_erca_key is not None:
            write_g1_trust(certs_dir, g1_erca_key)
        yield certs_dir


def signed_pairs(payloads, key, gen):
    """Signed EF data+signature records for one generation (real crypto)."""
    data_dtype, sig_dtype = (0x00, 0x01) if gen == 1 else (0x02, 0x03)
    out = []
    for tag, payload in payloads.items():
        if gen == 1:
            signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA1())
        else:
            signature = ef_signature(key, payload)
        out.append(stap(tag, data_dtype, payload))
        out.append(stap(tag, sig_dtype, signature))
    return b"".join(out)


def parse_bytes(data, certs_dir=None, validator=None):
    """Parse ``data`` as a file with an injected trust store."""
    from app.engine import TachoParser
    from core.crypto.signature import SignatureValidator

    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        parser = TachoParser(tmp.name)
        if validator is not None:
            parser.validator = validator
        else:
            parser.validator = SignatureValidator(certs_dir=certs_dir)
        return parser, parser.parse()
    finally:
        os.unlink(tmp.name)


# ── Minimal-but-conforming EF payloads for the mandatory download sets ───────

def _gnss_place_auth(ts):
    coord = lambda v: int(v).to_bytes(3, "big", signed=True)
    return struct.pack(">I", ts) + bytes([7]) + coord(45041) + coord(9125) + bytes([1])


_TS = 1700000000


def application_identification(gen, card_type=0x01, v2=False):
    """A signed Application_Identification payload with an explicit card type.

    ``gen`` is 1 or 2. The first byte is ``typeOfTachographCardId`` (1 = driver,
    2 = workshop, 3 = control, 4 = company).
    """
    if gen == 1:
        return bytes([card_type]) + b"\x01\x00" + bytes(7)  # 10 bytes
    version = b"\x01\x01" if v2 else b"\x01\x00"
    return bytes([card_type]) + version + bytes(14)  # 17 bytes


def non_driver_envelope(gen, card_type):
    """The DDP_035 universal minimum for a non-driver card: 0501 + 0520."""
    return {
        0x0501: application_identification(gen, card_type),
        0x0520: bytes(143),  # Identification
    }


def g1_core_payloads(card_type=0x01):
    """The nine mandatory G1 driver-card EFs (DDP_035), each ≥ its min length."""
    return {
        0x0501: application_identification(1, card_type),
        0x0502: bytes(48),   # Events_Data
        0x0503: bytes(24),   # Faults_Data
        0x0504: bytes(range(20)),  # Driver_Activity_Data
        0x0505: bytes(31),   # Vehicles_Used
        0x0506: bytes(10),   # Places
        0x0508: bytes(46),   # Control_Activity_Data
        0x0520: bytes(143),  # Identification
        0x0522: bytes(10),   # Specific_Conditions
    }


def g2_core_payloads(card_type=0x01, v2=False):
    """The G2 mandatory set: the G1 core plus VehicleUnits_Used / GNSS_Places."""
    payloads = dict(g1_core_payloads(card_type))
    payloads[0x0501] = application_identification(2, card_type, v2=v2)
    payloads[0x0523] = bytes(12)  # VehicleUnits_Used
    payloads[0x0524] = bytes(20)  # GNSS_Places
    return payloads


def v2_payloads():
    """The V2-only generation-2 EFs (0525-0530)."""
    return {
        0x0525: struct.pack(">HHHHH", 8, 1, 1, 1, 0),  # Application_Identification_V2
        0x0526: b"\x00\x00" + struct.pack(">IB", _TS, 1),
        0x0527: b"\x00\x00" + struct.pack(">IB", _TS, 1),
        0x0528: b"\x00\x00" + bytes([0x1A, 0x0D]) + _gnss_place_auth(_TS) + (100).to_bytes(3, "big"),
        0x0529: b"\x00\x00" + struct.pack(">IB", _TS, 1) + _gnss_place_auth(_TS) + (100).to_bytes(3, "big"),
        0x0530: b"\x00\x00" + struct.pack(">IB", _TS, 1),
    }


def g1_cert_records(card_cert, msca_cert):
    return stap(0xC100, 0x00, card_cert) + stap(0xC108, 0x00, msca_cert)


def g2_cert_records(card_cert, msca_cert):
    return stap(0xC101, 0x02, card_cert) + stap(0xC108, 0x02, msca_cert)
