"""Cryptographic verification of Gen2/Gen2.2 VU downloads (Annex 1C Appendix 11).

Tachograph Gen2 certificates are **Card Verifiable Certificates** (CVC, tag
0x7F21), not X.509. Each downloaded TREP section ends with an ECDSA
SignatureRecord (recordType 0x08, r‖s) computed by the VU over that section's
data records.

This module:
  * parses the CVC MemberState (0x04) and VU (0x0F) certificates,
  * verifies the MSCA → VU chain link (VU cert signed by the MSCA key),
  * verifies every TREP data signature with the VU public key,
proving data integrity and the intermediate chain using only the data inside the
file. The ERCA root anchor (ERCA-2 EC public key) is published by the EU JRC and
is not bundled here, so the MSCA certificate itself is reported as
``root_anchored: false`` unless a matching root key is supplied.

Empirically confirmed on the real files in ``DDD/``:
  * VU cert signature verifies under the MSCA brainpoolP256r1 key (SHA-256);
  * every TREP signature verifies under the VU key — the signed region is the
    section's data records, excluding the embedded certificates in the Overview.
"""
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature

from core.logger import get_logger
from .vu_record_dispatcher import iter_vu_sections

_log = get_logger(__name__)

# Curve OID (inside 0x7F49 → 0x06) → (curve, hash). Tacho Gen2 uses these.
# See core/curve_oids.py for canonical OID strings.
_CURVES = {
    "2b2403030208010107": (ec.BrainpoolP256R1(), hashes.SHA256),  # brainpoolP256r1
    "2b2403030208010b0d": (ec.BrainpoolP384R1(), hashes.SHA384),  # brainpoolP384r1
    "2b2403030208010d0b": (ec.BrainpoolP512R1(), hashes.SHA512),  # brainpoolP512r1
    "2a8648ce3d030107": (ec.SECP256R1(), hashes.SHA256),          # NIST P-256
    "2b81040022": (ec.SECP384R1(), hashes.SHA384),                # NIST P-384
    "2b81040023": (ec.SECP521R1(), hashes.SHA512),                # NIST P-521
}

# Certificate record types carried inside the Overview section.
_CERT_RECORD_TYPES = (0x04, 0x0F)
_SIGNATURE_RECORD = 0x08


def _tlv(data):
    """Parse one BER-TLV level into {tag: value}. Handles 1–2 byte tags and
    multi-byte lengths."""
    out = {}
    i = 0
    n = len(data)
    while i < n:
        tag = data[i]
        tag_len = 2 if (tag & 0x1F) == 0x1F else 1
        if tag_len == 2:
            tag = (data[i] << 8) | data[i + 1]
        length = data[i + tag_len]
        len_len = 1
        if length & 0x80:
            nb = length & 0x7F
            if nb == 0:
                return out
            length = int.from_bytes(data[i + tag_len + 1:i + tag_len + 1 + nb], "big")
            len_len = 1 + nb
        start = i + tag_len + len_len
        out[tag] = data[start:start + length]
        i = start + length
    return out


def parse_cvc(cert_bytes):
    """Parse a CVC certificate (0x7F21). Returns a dict with car, chr, curve_oid,
    public_point, signature, body_tlv (the 0x7F4E TLV that the signature covers)."""
    outer = _tlv(cert_bytes)
    inner = outer.get(0x7F21)
    if inner is None:
        return None
    body_and_sig = _tlv(inner)
    body = body_and_sig.get(0x7F4E)
    sig = body_and_sig.get(0x5F37)
    if body is None or sig is None:
        return None
    fields = _tlv(body)
    pk = _tlv(fields.get(0x7F49, b""))
    # The signature input is the encoded body TLV (tag+len+value), i.e. the slice
    # of ``inner`` from the 0x7F4E tag up to the 0x5F37 signature tag.
    bstart = inner.find(b"\x7f\x4e")
    sstart = inner.find(b"\x5f\x37", bstart)
    body_tlv = inner[bstart:sstart] if bstart >= 0 and sstart > bstart else None
    return {
        "car": fields.get(0x42, b"").hex(),
        "chr": fields.get(0x5F20, b"").hex(),
        "curve_oid": pk.get(0x06, b"").hex(),
        "public_point": pk.get(0x86),
        "effective_date": fields.get(0x5F25, b"").hex(),
        "expiration_date": fields.get(0x5F24, b"").hex(),
        "signature": sig,
        "body_tlv": body_tlv,
    }


def cvc_public_key(parsed):
    """Build an EllipticCurvePublicKey from a parsed CVC certificate."""
    entry = _CURVES.get(parsed.get("curve_oid"))
    point = parsed.get("public_point")
    if entry is None or not point:
        return None, None
    curve, hash_cls = entry
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(curve, point), hash_cls
    except (ValueError, TypeError) as exc:
        _log.debug("CVC public key build failed: %s", exc)
        return None, None


def _verify_ecdsa(pub_key, hash_cls, signature_rs, message):
    """Verify a raw r‖s ECDSA signature over ``message`` (hashed with hash_cls)."""
    if pub_key is None or not signature_rs or len(signature_rs) % 2:
        return False
    half = len(signature_rs) // 2
    r = int.from_bytes(signature_rs[:half], "big")
    s = int.from_bytes(signature_rs[half:], "big")
    try:
        pub_key.verify(utils.encode_dss_signature(r, s), bytes(message), ec.ECDSA(hash_cls()))
        return True
    except InvalidSignature:
        return False
    except Exception as exc:  # malformed key/point/curve mismatch
        _log.debug("ECDSA verify error: %s", exc)
        return False


def verify_cvc_chain_link(child, parent_pub, parent_hash):
    """True if ``child`` (parsed CVC) is signed by the parent public key."""
    if child is None or child.get("body_tlv") is None:
        return False
    return _verify_ecdsa(parent_pub, parent_hash, child["signature"], child["body_tlv"])


_CURVE_NAMES = {
    "2b2403030208010107": "brainpoolP256r1",
    "2b2403030208010b0d": "brainpoolP384r1",
    "2b2403030208010d0b": "brainpoolP512r1",
    "2a8648ce3d030107": "NIST P-256",
    "2b81040022": "NIST P-384",
    "2b81040023": "NIST P-521",
}

_CERT_ROLES = {0x04: "MemberState (MSCA)", 0x0F: "Vehicle Unit (VU)"}


def _cvc_date(hex_str):
    """CVC validity dates are TimeReal (uint32, seconds since 1970-01-01 UTC).
    Returns ISO 'YYYY-MM-DD' or '' if unparseable."""
    if not hex_str:
        return ""
    try:
        import datetime
        secs = int(hex_str, 16)
        if not (0 < secs < 0xFFFFFFFF):
            return ""
        return datetime.datetime.fromtimestamp(
            secs, datetime.timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return ""


def decode_vu_certificates(raw_data):
    """Extract and decode CVC certificate fields (Appendix 11) from the VU download:
    role, CAR, CHR, curve, validity. Returns a list of dicts.
    Does not verify signatures (see verify_vu_download for that)."""
    data = bytes(raw_data)
    out = []
    seen = set()
    try:
        for sec in iter_vu_sections(data):
            for (pos, rt, rs, nr, _end) in sec["records"]:
                if rt not in _CERT_ROLES or nr == 0:
                    continue
                cert = data[pos + 5:pos + 5 + rs]
                parsed = parse_cvc(cert)
                if not parsed:
                    continue
                key = (parsed.get("car"), parsed.get("chr"))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "role": _CERT_ROLES[rt],
                    "car": parsed.get("car", ""),
                    "chr": parsed.get("chr", ""),
                    "curve": _CURVE_NAMES.get(parsed.get("curve_oid"),
                                              parsed.get("curve_oid", "")),
                    "valid_from": _cvc_date(parsed.get("effective_date")),
                    "valid_to": _cvc_date(parsed.get("expiration_date")),
                })
    except Exception as exc:
        _log.debug("CVC certificate decode failed: %s", exc)
    return out


def verify_vu_download(raw_data, erca_keys=None):
    """Verify the cryptographic integrity of a Gen2/Gen2.2 VU download.

    Returns a report dict:
      {
        "available": bool,
        "msca_to_vu": bool,          # VU cert signed by MSCA
        "root_anchored": bool,       # MSCA cert verified against an ERCA root key
        "treps": [{"trep", "section", "signature_valid"}],
        "all_treps_valid": bool,
        "summary": str,
      }
    """
    data = bytes(raw_data)
    report = {"available": False, "msca_to_vu": False, "root_anchored": False,
              "treps": [], "all_treps_valid": False, "summary": ""}
    try:
        sections = list(iter_vu_sections(data))
        if not sections:
            report["summary"] = "No VU sections found"
            return report

        # Collect the MSCA (0x04) and VU (0x0F) certificates from the Overview.
        msca_raw = vu_raw = None
        for sec in sections:
            for (pos, rt, rs, nr, _end) in sec["records"]:
                if rt == 0x04 and nr > 0 and msca_raw is None:
                    msca_raw = data[pos + 5:pos + 5 + rs]
                elif rt == 0x0F and nr > 0 and vu_raw is None:
                    vu_raw = data[pos + 5:pos + 5 + rs]
        if not vu_raw:
            report["summary"] = "VU certificate (0x0F) not found"
            return report

        report["available"] = True
        vu = parse_cvc(vu_raw)
        if vu is None:
            report["summary"] = "VU certificate (0x0F) parsing failed"
            return report
        vu_pub, vu_hash = cvc_public_key(vu)

        # MSCA → VU chain link.
        if msca_raw:
            msca = parse_cvc(msca_raw)
            if msca is not None:
                msca_pub, msca_hash = cvc_public_key(msca)
                report["msca_to_vu"] = verify_cvc_chain_link(vu, msca_pub, msca_hash)
                # Optional root anchor: verify the MSCA cert against a supplied
                # ERCA key. Prefer the key matching the MSCA's CAR, but fall
                # back to trying every registered root (raw points carry a
                # synthetic CAR that can never match the real KID).
                if erca_keys:
                    matched = erca_keys.get(msca.get("car"))
                    candidates = [matched] if matched else list(erca_keys.values())
                    for erca_pub, erca_hash in candidates:
                        if verify_cvc_chain_link(msca, erca_pub, erca_hash):
                            report["root_anchored"] = True
                            break

        # Per-TREP data signatures, verified with the VU public key.
        all_valid = True
        for sec in sections:
            recs = sec["records"]
            sig_recs = [r for r in recs if r[1] == _SIGNATURE_RECORD]
            if not sig_recs:
                continue
            sig_pos, _, sig_size, _, _ = sig_recs[0]
            # Signature size follows the curve: 64 (P-256), 96 (P-384), 128 (P-512).
            sig = data[sig_pos + 5:sig_pos + 5 + sig_size]
            # Signed region: data records up to the signature, excluding the
            # leading embedded certificates (the Overview carries the MSCA/VU
            # certs, which self-authenticate and are not part of the signed data).
            start = sec["marker"] + 2
            for (pos, rt, _rs, _nr, end) in recs:
                if rt in _CERT_RECORD_TYPES and pos == start:
                    start = end  # advance past a leading certificate record
                else:
                    break
            if start == sig_pos:
                continue
            valid = _verify_ecdsa(vu_pub, vu_hash, sig, data[start:sig_pos])
            all_valid = all_valid and valid
            report["treps"].append({
                "trep": f"0x{sec['trep']:02X}",
                "signature_valid": valid,
            })

        report["all_treps_valid"] = bool(report["treps"]) and all_valid
        anchor = "root-anchored" if report["root_anchored"] else "root not anchored (ERCA-2 key absent)"
        report["summary"] = (
            f"MSCA→VU: {'OK' if report['msca_to_vu'] else 'FAIL'}; "
            f"TREP signatures: {sum(t['signature_valid'] for t in report['treps'])}/"
            f"{len(report['treps'])} valid; {anchor}"
        )
        return report
    except Exception as exc:  # never break parsing on a crypto issue
        _log.debug("VU signature verification failed: %s", exc)
        report["summary"] = f"verification error: {exc}"
        return report
