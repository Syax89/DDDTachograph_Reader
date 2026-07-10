"""EF (Elementary File) signature verification for card data integrity.

Each EF on a driver card carries two appendix copies per generation: a data
copy (dtype 0x00 for G1, 0x02 for G2) and a signature copy (dtype 0x01 for
G1, 0x03 for G2). The signature covers the entire EF data payload and is
verified with the card public key extracted from the certificate chain.

- G1: RSA PKCS#1 v1.5 with SHA-256 (128-byte signature)
- G2: ECDSA with SHA-256 (64-byte signature for P-256)

This module is called after certificate processing. A G2 CVC public key may be
used for data-integrity verification even when that certificate chain could not
be verified; the report keeps that trust limitation explicit.
"""
import logging
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

_log = logging.getLogger("ddd_tacho")


# Shared epoch bounds for data size sanity checks.

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
_GEN_PAIRS: Tuple[Tuple[int, int, str, str], ...] = (
    (0x00, 0x01, "G1", "RSA"),
    (0x02, 0x03, "G2", "ECDSA"),
)

# G2-specific tags that only make sense with ECDSA verification.
# 0x0520-0x0522 (Identification, DrivingLicenceInfo, SpecificConditions)
# are G1-era EFs and must keep their G1 RSA verification.
_G2_ONLY_TAGS = {
    0x0523, 0x0524,
    0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x052A,
}


def pair_ef_records(ef_data: List[Tuple[int, int, bytes]],
                    ef_signatures: List[Tuple[int, int, bytes]]) -> List[Dict[str, Any]]:
    """Classify EF data/signature occurrences by tag and generation.

    One data and one signature record are required for every expected pair.
    Missing or duplicate records are returned as incomplete entries rather than
    overwritten, so the integrity report cannot claim complete verification.
    """
    data_by_key: DefaultDict[Tuple[int, int], List[bytes]] = defaultdict(list)
    signatures_by_key: DefaultDict[Tuple[int, int], List[bytes]] = defaultdict(list)
    for tag, dtype, payload in ef_data:
        data_by_key[(tag, dtype)].append(payload)
    for tag, dtype, payload in ef_signatures:
        signatures_by_key[(tag, dtype)].append(payload)

    pairs = []
    for data_dt, sig_dt, gen, algo in _GEN_PAIRS:

        tags = {tag for tag, dtype in data_by_key if dtype == data_dt}
        tags.update(tag for tag, dtype in signatures_by_key if dtype == sig_dt)
        for tag in sorted(tags):
            # ICC/IC metadata and certificate blocks share the card record
            # stream but are not Annex 1B/1C signed EF payloads. Only known
            # signature-capable EFs participate in this integrity report.
            if tag not in _EF_MIN_LENGTHS:
                continue
            # G2-only tags should not be verified with G1 RSA.
            if gen == "G1" and tag in _G2_ONLY_TAGS:
                continue
            data_records = data_by_key[(tag, data_dt)]
            signature_records = signatures_by_key[(tag, sig_dt)]
            pair = {
                "tag": tag,
                "gen": gen,
                "algo": algo,
            }
            if len(data_records) != 1 or len(signature_records) != 1:
                missing = []
                duplicate = []
                if not data_records:
                    missing.append("data")
                elif len(data_records) > 1:
                    duplicate.append("data")
                if not signature_records:
                    missing.append("signature")
                elif len(signature_records) > 1:
                    duplicate.append("signature")
                problem = "missing " + ", ".join(missing) if missing else "duplicate " + ", ".join(duplicate)
                pair.update({
                    "status": "incomplete",
                    "reason": problem,
                    "data_size": sum(len(record) for record in data_records),
                    "sig_size": sum(len(record) for record in signature_records),
                })
            else:
                pair.update({
                    "status": "paired",
                    "data": data_records[0],
                    "signature": signature_records[0],
                })
            pairs.append(pair)
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
    if not pairs:
        return {"summary": "No EF signature pairs found", "ef_results": [],
                "verified": 0, "failed": 0, "total": 0}

    results = []
    verified = 0
    failed = 0
    skipped = 0
    used_cvc_key = False

    for pair in pairs:
        tag = pair["tag"]
        algo = pair["algo"]

        if pair["status"] == "incomplete":
            failed += 1
            results.append({
                "tag": f"0x{tag:04X}", "gen": pair["gen"], "algo": algo,
                "status": "incomplete", "reason": pair["reason"],
                "data_size": pair["data_size"], "sig_size": pair["sig_size"],
            })
            continue

        data = pair["data"]
        sig = pair["signature"]

        if card_public_key is None and card_ec_public_key is None:
            skipped += 1
            results.append({
                "tag": f"0x{tag:04X}", "gen": pair["gen"], "algo": algo,
                "status": "skipped", "reason": "card public key not available",
                "data_size": len(data), "sig_size": len(sig),
            })
            continue

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

        # G2 ECDSA verification can fall back to a public key extracted from a
        # raw CVC even if no RSA/G1 certificate-chain key was recovered.
        if algo == "ECDSA":
            if key_type == "EC":
                verify_key = card_public_key
            elif card_ec_public_key is not None:
                verify_key = card_ec_public_key
                used_cvc_key = True
            else:
                skipped += 1
                results.append({
                    "tag": f"0x{tag:04X}", "gen": pair["gen"], "algo": algo,
                    "status": "skipped",
                    "reason": "G2 EC key not available",
                    "data_size": len(data), "sig_size": len(sig),
                })
                continue
        else:
            if card_public_key is None:
                skipped += 1
                results.append({
                    "tag": f"0x{tag:04X}", "gen": pair["gen"], "algo": algo,
                    "status": "skipped", "reason": "G1 RSA key not available",
                    "data_size": len(data), "sig_size": len(sig),
                })
                continue
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

    key_trust = None
    if used_cvc_key:
        key_trust = (
            "CVC public key extracted for G2 EF verification; EF signature "
            "verification does not establish CVC certificate-chain trust"
        )
        summary = f"{summary}; {key_trust}"

    return {
        "summary": summary,
        "ef_results": results,
        "verified": verified,
        "failed": failed,
        "skipped": skipped,
        "total": total,
        "key_trust": key_trust,
    }
