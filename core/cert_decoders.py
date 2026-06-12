"""Certificate and public-key decoders: G1 RSA certificates, G2/G2.2 CVC profiles, signatures and authentication sub-tags."""

import struct

from core.logger import get_logger
from core.decode_primitives import decode_date, decode_string, get_nation

_log = get_logger(__name__)

def parse_g22_auth_subtag(val, results, tag):
    """Parse G2.2 authentication sub-tags inside security container.

    Tags handled:
      0x960F - GNSS authentication data (raw bytes retained for crypto)
      0x6399 - Load/unload authentication data (raw bytes retained for crypto)

    Attempts structure detection: header (first 4 bytes) + payload (rest).
    """
    try:
        total_len = len(val)
        header_end = min(4, total_len)
        header_bytes = val[:header_end]
        payload_bytes = val[header_end:]

        _log.debug("Auth subtag 0x%04X: total=%d header=%d payload=%d",
                   tag, total_len, header_end, len(payload_bytes))

        entry = {
            "tag": f"0x{tag:04X}",
            "length": total_len,
            "raw_hex": val.hex(),
            "header_hex": header_bytes.hex(),
            "payload_hex": payload_bytes.hex(),
            "header_length": header_end,
            "payload_length": len(payload_bytes),
        }

        dest_key = "gnss_auth" if tag == 0x960F else "load_unload_auth"
        results.setdefault(dest_key, []).append(entry)
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Auth subtag parse failed for tag 0x%04X: %s", tag, exc)

def parse_g22_certificate_subtag(val, results, tag):
    """Parse G22 certificate sub-tags (5Fxx) found inside security container."""
    try:
        if tag == 0x5F20:  # G22_CardHolderName
            results.setdefault("card_icc", {})["holder_name"] = decode_string(val)
        elif tag == 0x5F24:  # G22_CardEffectiveDate
            results.setdefault("card_icc", {})["effective_date"] = decode_date(val)
        elif tag == 0x5F25:  # G22_CardExpiryDate
            results.setdefault("card_icc", {})["expiry_date"] = decode_date(val)
        elif tag == 0x5F29:  # G22_CardIssuingMemberState
            if len(val) >= 1:
                results.setdefault("card_icc", {})["issuing_nation"] = get_nation(val[0])
        elif tag == 0x5F4C:  # G22_CardExtendedSerialNumber
            results.setdefault("card_icc", {})["extended_serial"] = val.hex().upper()
    except (struct.error, IndexError, ValueError, KeyError) as exc:
        _log.debug("Certificate subtag parse failed: %s", exc)

def parse_g1_certificate(val, results):
    """Parse G1 certificate (tags 0xC100, 0xC108, 0x0103, 0x0104) — 194 bytes.

    Structure (Annex 1B §2.29-2.30 / Annex 1C §2.30-2.31, C# config):
      Signature                 128  HexValue
      PublicKeyRemainder         58  HexValue (RSA pubkey remainder)
      Nation                      1  Country
      NationCode                  3  SimpleString (numeric)
      SerialNumber                1  UInt8
      AdditionalInfo              2  UInt16
      CaIdentifier                1  UInt8
    Total: 194 bytes
    """
    if len(val) < 194:
        return
    try:
        sig = val[0:128]
        pk_remainder = val[128:186]
        nation = get_nation(val[186])
        nation_code = val[187:190].decode('latin-1', errors='replace').strip()
        serial = val[190]
        add_info = struct.unpack(">H", val[191:193])[0]
        ca_id = val[193]

        results.setdefault("certificates", []).append({
            "signature_hex": sig.hex().upper(),
            "signature_length": 128,
            "public_key_remainder_hex": pk_remainder.hex().upper(),
            "public_key_remainder_length": 58,
            "nation": nation,
            "nation_code": nation_code,
            "serial_number": serial,
            "additional_info": f"0x{add_info:04X}",
            "ca_identifier": f"0x{ca_id:02X}",
            "total_size": 194,
        })
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("G1 certificate parse failed: %s", exc)

def parse_certificate_signature(val, results):
    """Parse ECDSA certificate signature (tag 0x5F37) — Annex 1C §2.31.

    Structure: 64-byte ECDSA signature = r(32 bytes) || s(32 bytes).
    """
    try:
        sig_info = {"signature_raw": val.hex().upper()}
        if len(val) >= 64:
            r_int = int.from_bytes(val[0:32], 'big')
            s_int = int.from_bytes(val[32:64], 'big')
            sig_info.update({
                "r_hex": val[0:32].hex().upper(),
                "s_hex": val[32:64].hex().upper(),
                "r_int": str(r_int),
                "s_int": str(s_int),
            })
        results.setdefault("card_icc", {})["certificate_signature"] = sig_info
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Certificate signature parse failed: %s", exc)

EC_CURVE_OIDS = {
    "2b2403030208010107": "brainpoolP256r1",
    "2a8648ce3d030107": "secp256r1 (NIST P-256)",
}

def parse_public_key_info(val, results):
    """Parse public key info (tag 0x7F49) — EC curve OID + public key point."""
    try:
        info = {"algorithm": "ECDSA"}
        hex_val = val.hex()
        for oid_hex, curve_name in EC_CURVE_OIDS.items():
            idx = hex_val.find(oid_hex)
            if idx >= 0:
                info["curve"] = curve_name
                key_start = idx // 2 + len(oid_hex) // 2
                rest = val[key_start:]
                if rest[:1] == b'\x86' and len(rest) >= 2:
                    inner_len = rest[1]
                    if inner_len & 0x80:
                        num_len = inner_len & 0x7f
                        if len(rest) >= 2 + num_len:
                            inner_len = int.from_bytes(rest[2:2+num_len], 'big')
                            rest = rest[2+num_len:]
                        else:
                            rest = b''
                    else:
                        rest = rest[2:]
                    if len(rest) >= inner_len:
                        key_data = rest[:inner_len]
                        if key_data[:1] == b'\x04' and len(key_data) >= 65:
                            x = key_data[1:33].hex().upper()
                            y = key_data[33:65].hex().upper()
                            info["public_key_x"] = x
                            info["public_key_y"] = y
                        else:
                            info["public_key_hex"] = key_data.hex().upper()
                elif rest[:1] == b'\x04' and len(rest) >= 65:
                    info["public_key_x"] = rest[1:33].hex().upper()
                    info["public_key_y"] = rest[33:65].hex().upper()
                break
        results.setdefault("card_icc", {})["public_key"] = info
    except (struct.error, IndexError, ValueError, KeyError) as exc:
        _log.debug("Public key info parse failed: %s", exc)

def parse_g22_certificate_profile(val, results):
    """Parse G22 CertificateProfileIdentifier (tag 0x42/0x4208) — certificate metadata.

    Attempts to detect BER-TLV structure within security container data,
    identify OID/algorithm sections, and extract nested tags.
    Falls back to Latin-1 text decode + raw hex.
    """
    from core.ber_tlv import read_ber_tlv_header

    try:
        profile = {"raw_hex": val.hex().upper()}

        nested_tags = []
        parsed_bytes = 0
        pos = 0
        while pos + 2 <= len(val):
            if val[pos] in (0x00, 0xFF):
                pos += 1
                continue

            tag, length, hdr_size = read_ber_tlv_header(val, pos)
            if tag is None or length == 0 or pos + hdr_size + length > len(val):
                pos += 1
                continue

            tag_data = val[pos + hdr_size:pos + hdr_size + length]
            tag_desc = f"0x{tag:04X}"
            if tag == 0x06:
                tag_desc = "OID"
            elif tag in (0x30, 0x31):
                tag_desc = "SEQUENCE"
            elif tag == 0x04:
                tag_desc = "OCTET_STRING"
            elif tag == 0x03:
                tag_desc = "BIT_STRING"
            elif tag == 0x02:
                tag_desc = "INTEGER"
            elif tag == 0xA0:
                tag_desc = "CONTEXT_0"
            elif tag == 0xA1:
                tag_desc = "CONTEXT_1"
            nested_tags.append({
                "tag": f"0x{tag:04X}",
                "tag_desc": tag_desc,
                "length": length,
                "offset": pos,
                "data_hex": tag_data[:64].hex().upper() + ("..." if len(tag_data) > 64 else ""),
            })
            parsed_bytes += hdr_size + length
            pos += hdr_size + length

        if nested_tags:
            profile["nested_tags"] = nested_tags
            _log.debug("Certificate profile: detected %d nested BER-TLV tags", len(nested_tags))

        # Identify OID sections from hex data
        known_oids = {
            "2a8648ce3d030107": "secp256r1 (NIST P-256)",
            "2b2403030208010107": "brainpoolP256r1",
            "2a8648ce3d040303": "ECDSA with SHA-384",
            "2a8648ce3d040302": "ECDSA with SHA-256",
        }
        hex_val = val.hex()
        found_oids = []
        for oid_hex, oid_name in known_oids.items():
            if oid_hex in hex_val:
                found_oids.append({"oid": oid_hex, "name": oid_name})
        if found_oids:
            profile["identified_oids"] = found_oids
            _log.debug("Certificate profile: identified %d known OIDs", len(found_oids))

        # Latin-1 text decode
        if len(val) >= 3:
            try:
                text = val.decode('latin-1', errors='ignore')
                ascii_part = ''.join(c for c in text if 32 <= ord(c) < 127).strip()
                if ascii_part:
                    profile["text"] = ascii_part
            except (UnicodeDecodeError, ValueError):
                pass

        # Report unknown byte percentage
        if nested_tags:
            unknown_bytes = len(val) - parsed_bytes
            if unknown_bytes > 0:
                profile["unknown_bytes"] = unknown_bytes

        results.setdefault("card_icc", {})["certificate_profile"] = profile
    except (struct.error, IndexError, ValueError) as exc:
        _log.debug("Certificate profile parse failed: %s", exc)
