"""EF (Elementary File) signature verification for card data integrity.

Each EF on a driver card carries two appendix copies per generation: a data
copy (dtype 0x00 for G1, 0x02 for G2) and a signature copy (dtype 0x01 for
G1, 0x03 for G2). The signature covers the entire EF data payload and is
verified with the card public key extracted from the certificate chain.

- G1: RSA PKCS#1 v1.5 with SHA-256 (128-byte signature)
- G2: ECDSA with SHA-256 (64-byte signature for P-256)

This module is called *after* the certificate chain has been validated, so the
card public key is known and trusted.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger("ddd_tacho")


# Shared epoch bounds for data size sanity checks.
_UNIX_EPOCH_2000 = 946684800
_UNIX_EPOCH_2100 = 4102444800

# Minimum lengths for known EF types (used to reject obviously-corrupt data).
# Names follow the decoder registry (core/decoder_registry.py).
_EF_MIN_LENGTHS = {
    0x0501: 10,    # DriverCardApplicationIdentification (G1 10B / G2 17B)
    0x0502: 30,    # EventsData
    0x0503: 10,    # FaultsData
    0x0504: 20,    # DriverActivityData
    0x0505: 20,    # VehiclesUsed
    0x0506: 10,    # Places
    0x0507: 10,    # CurrentUsage
    0x0508: 40,    # ControlActivityData
    0x050A: 10,    # VuCardIWRecord
    0x050E: 2,     # CardDownload (4 bytes TimeReal)
    0x0520: 10,    # Identification
    0x0521: 10,    # DrivingLicenceInfo
    0x0522: 10,    # SpecificConditions
    0x0523: 8,     # VehicleUnitsUsed (G2)
    0x0524: 10,    # GNSSPlaces (G2)
    0x0525: 10,    # GNSSAccumulatedDriving (G2.2)
    0x0526: 10,    # LoadUnloadOperations (G2.2)
    0x0527: 10,    # TrailerRegistrations (G2.2)
    0x0528: 10,    # GNSSEnhancedPlaces (G2.2)
    0x0529: 10,    # LoadSensorData (G2.2)
    0x052A: 10,    # BorderCrossings (G2.2)
}

# Schema for data+dtype pairs (one pair per generation).
_GEN_PAIRS = [
    {"data_dtype": 0x00, "sig_dtype": 0x01, "gen": "G1", "algo": "RSA"},
    {"data_dtype": 0x02, "sig_dtype": 0x03, "gen": "G2", "algo": "ECDSA"},
]

# G2-specific tags that only make sense with ECDSA verification.
# 0x0520-0x0522 (Identification, DrivingLicenceInfo, SpecificConditions)
# are G1-era EFs and must keep their G1 RSA verification.
_G2_ONLY_TAGS = {
    0x0523, 0x0524,
    0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A,
}


def pair_ef_records(ef_data: Dict[Tuple[int, int], bytes],
                    ef_signatures: Dict[Tuple[int, int], bytes]) -> List[Dict[str, Any]]:
    """Match data/signature payloads by tag + generation pair.

    Returns a list of ``{tag, gen, algo, data, signature}`` dictionaries,
    one for each (data, signature) pair found.
    """
    pairs = []
    for entry in _GEN_PAIRS:
        data_dt = entry["data_dtype"]
        sig_dt = entry["sig_dtype"]
        gen = entry["gen"]
        algo = entry["algo"]

        for (tag, dt), payload in ef_data.items():
            if dt != data_dt:
                continue
            sig_key = (tag, sig_dt)
            if sig_key not in ef_signatures:
                continue
            # G2-only tags should not be verified with G1 RSA.
            if gen == "G1" and tag in _G2_ONLY_TAGS:
                continue
            pairs.append({
                "tag": tag,
                "gen": gen,
                "algo": algo,
                "data": payload,
                "signature": ef_signatures[sig_key],
            })
    return pairs


def verify_ef_pairs(pairs: List[Dict[str, Any]],
                    card_public_key: Any,
                    signature_validator: Any,
                    generation: str,
                    key_type: Optional[str] = None,
                    card_ec_public_key: Any = None,
                    card_ec_hash: Any = None) -> Dict[str, Any]:
    """Verify every EF data/signature pair against the card public key.

    Returns a report dict with per-tag results and an overall summary.

    *key_type* discriminates between "RSA" (G1) and "EC" (G2).
    *card_ec_public_key* is the G2 ECDSA public key (from CVC).
    *card_ec_hash* is the hash algorithm associated with the CVC curve.
    """
    if card_public_key is None:
        return {"summary": "No card public key available", "ef_results": [],
                "verified": 0, "failed": 0, "total": 0}

    if not pairs:
        return {"summary": "No EF signature pairs found", "ef_results": [],
                "verified": 0, "failed": 0, "total": 0}

    results = []
    verified = 0
    failed = 0
    skipped = 0

    for pair in pairs:
        tag = pair["tag"]
        data = pair["data"]
        sig = pair["signature"]
        algo = pair["algo"]

        # Sanity-checks: reject obviously-corrupt payloads.
        min_len = _EF_MIN_LENGTHS.get(tag, 2)
        if len(data) < min_len:
            _log.debug("EF 0x%04X data too short (%d < %d), skipping", tag, len(data), min_len)
            skipped += 1
            results.append({
                "tag": f"0x{tag:04X}", "gen": pair["gen"], "algo": algo,
                "status": "skipped", "reason": f"data too short ({len(data)} < {min_len})",
                "data_size": len(data), "sig_size": len(sig),
            })
            continue

        # G2 ECDSA verification requires an EC public key.
        if algo == "ECDSA" and key_type == "RSA":
            if card_ec_public_key is None:
                skipped += 1
                results.append({
                    "tag": f"0x{tag:04X}", "gen": pair["gen"], "algo": algo,
                    "status": "skipped",
                    "reason": "G2 EC key not available (G1 chain only, no CVC key)",
                    "data_size": len(data), "sig_size": len(sig),
                })
                continue
            verify_key = card_ec_public_key
        else:
            verify_key = card_public_key

        # Verify using the appropriate algorithm.
        try:
            if algo == "RSA":
                ok = signature_validator.verify_g1_data_signature(
                    verify_key, sig, data)
            else:
                # G2 EF signatures are raw r||s (64 bytes for P-256),
                # but cryptography's verify() expects DER encoding.
                from cryptography.hazmat.primitives.asymmetric import utils as _ec_utils, ec as _ec
                from cryptography.hazmat.primitives import hashes
                sig_size = len(sig)
                r = int.from_bytes(sig[:sig_size // 2], 'big')
                s_bytes = int.from_bytes(sig[sig_size // 2:], 'big')
                sig_der = _ec_utils.encode_dss_signature(r, s_bytes)
                hash_algo = card_ec_hash() if card_ec_hash else hashes.SHA256()
                verify_key.verify(sig_der, data, _ec.ECDSA(hash_algo))
                ok = True
        except Exception as exc:
            _log.debug("EF 0x%04X verification exception: %s", tag, exc)
            ok = False

        status = "verified" if ok else "failed"
        if ok:
            verified += 1
        else:
            failed += 1

        results.append({
            "tag": f"0x{tag:04X}", "gen": pair["gen"], "algo": algo,
            "status": status, "data_size": len(data), "sig_size": len(sig),
        })

    # Build summary.
    total = verified + failed
    if total == 0 and skipped > 0:
        summary = f"No EF signatures verified ({skipped} skipped)"
    elif failed == 0 and total > 0:
        summary = f"All {total} EF signature(s) verified"
    elif verified == 0 and total > 0:
        summary = f"All {total} EF signature(s) FAILED"
    else:
        summary = f"{verified}/{total} EF signature(s) verified, {failed} FAILED"

    return {
        "summary": summary,
        "ef_results": results,
        "verified": verified,
        "failed": failed,
        "skipped": skipped,
        "total": total,
    }
