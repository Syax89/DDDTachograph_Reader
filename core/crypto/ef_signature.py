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
    # 0x050E (CardDownload) intentionally absent: Annex 1C §3.3 DDP_035
    # signs "the other application data EFs ... except EF Card_Download".
    # Including it here made every card download report a false "FAILED"
    # EF signature for data the norm declares unsigned (D2-010).
    0x0520: 10,    # Identification
    0x0521: 10,    # DrivingLicenceInfo
    0x0522: 10,    # SpecificConditions
    0x0523: 8,     # VehicleUnitsUsed (G2)
    0x0524: 10,    # GNSSPlaces (G2)
    0x0525: 10,    # DriverCardApplicationIdentificationV2 (G2.2)
    0x0526: 7,     # CardPlaceAuthDailyWorkPeriod (G2.2, pointer + 5B record)
    0x0527: 7,     # GNSSAuthAccumulatedDriving (G2.2, pointer + 5B record)
    0x0528: 19,    # CardBorderCrossings (G2.2, pointer + 17B record)
    0x0529: 22,    # CardLoadUnloadOperations (G2.2, pointer + 20B record)
    0x0530: 7,     # CardLoadTypeEntries (G2.2, pointer + 5B record)
    0x0540: 1,     # VuConfiguration (G2.2, opaque byte string; optional)
}

# Annex 1C §3.3 DDP_035 (reference/annex1C.txt:21556-21644) makes
# Application_Identification and Identification mandatory for EVERY card type,
# but the additional data EFs are mandatory only "when downloading a driver
# card". 0x0507 (CurrentUsage) and 0x0521 (DrivingLicenceInfo) exist on the
# card but are NOT mandatory in every download, so they are deliberately
# absent. Used to catch a signed EF being deleted outright
# (E-F3/CARD-MANDATORY-MISSING), not as an exhaustive structural check.
_UNIVERSAL_CORE_TAGS = frozenset({0x0501, 0x0520})
# Driver-only mandatory EFs for the generation-1 application.
_G1_DRIVER_TAGS = frozenset({0x0502, 0x0503, 0x0504, 0x0505, 0x0506, 0x0508, 0x0522})
# Generation-2 adds VehicleUnits_Used and GNSS_Places to the driver set.
_G2_DRIVER_TAGS = _G1_DRIVER_TAGS | {0x0523, 0x0524}
# Version-2-only generation-2 EFs (TCS_152 note: present only in version 2).
# Application_Identification_V2 (0x0525) is universal "if present"; the V2
# driver records are driver-only "if present".
_G22_V2_UNIVERSAL_TAGS = frozenset({0x0525})
_G22_V2_DRIVER_TAGS = frozenset({0x0526, 0x0527, 0x0528, 0x0529, 0x0530})
# V2-only tags whose mere presence is structured V2 evidence.
_G22_V2_TAGS = _G22_V2_UNIVERSAL_TAGS | _G22_V2_DRIVER_TAGS

# EquipmentType / typeOfTachographCardId (Annex 1C Appendix 1 §2.67).
DRIVER_CARD_TYPE = 0x01
# Recognised, non-driver card types: workshop (2), control (3), company (4).
NON_DRIVER_CARD_TYPES = frozenset({0x02, 0x03, 0x04})

# Struct-version bytes {01 01} of EF Application_Identification that mark a
# version-2 generation-2 card (TCS_152; {01 00} is version 1).
_V2_STRUCTURE_VERSION = b"\x01\x01"

# Minimum Application_Identification length for the card type to be trusted
# (G1 10 bytes / G2 17 bytes); a shorter payload leaves the identity unknown.
_APP_ID_MIN_BYTES = 10


def _paired_tag_data(pairs: List[Dict[str, Any]], tag: int, gen: str) -> Optional[bytes]:
    """Return the data payload of the single paired (*tag*, *gen*) EF, else None.

    None means the identity cannot be read unambiguously (missing, malformed,
    duplicated, or only a signature half). Callers treat that as unknown.
    """
    matches = [p for p in pairs
               if p["tag"] == tag and p.get("gen") == gen and p.get("status") == "paired"]
    if len(matches) != 1:
        return None
    data = matches[0].get("data")
    return bytes(data) if isinstance(data, (bytes, bytearray)) else None


def _application_card_type(pairs: List[Dict[str, Any]], gen: str) -> Optional[int]:
    """Card type of the *gen* application from its own Application_Identification.

    Derived from that generation's signed 0x0501 bytes, never the merged display
    ``card_application`` dict nor an unsigned label. Returns ``None`` when the
    identity is missing/malformed/duplicated, so the caller can fail closed.
    """
    data = _paired_tag_data(pairs, 0x0501, gen)
    if not data or len(data) < _APP_ID_MIN_BYTES:
        return None
    return data[0]


def _v2_application_present(pairs: List[Dict[str, Any]]) -> bool:
    """True when the file carries structured evidence of a V2 application.

    Either an actual V2-only EF application record is present, or the signed
    G2 Application_Identification (0x0501) declares cardStructureVersion
    {01 01}. A bare display label never counts.
    """
    for pair in pairs:
        if pair.get("gen") != "G2":
            continue
        if pair["tag"] in _G22_V2_TAGS:
            return True
    data = _paired_tag_data(pairs, 0x0501, "G2")
    return data is not None and len(data) >= 3 and data[1:3] == _V2_STRUCTURE_VERSION


def _required_tags(gen: str, card_type: Optional[int], v2_present: bool) -> set:
    """Mandatory tag set for one EF application generation present in the file.

    ``card_type`` is that generation's Application_Identification type; ``None``
    (unknown/unreadable) fails closed by requiring the driver set, so an
    unidentifiable card cannot evade the driver download checks.
    """
    required = set(_UNIVERSAL_CORE_TAGS)
    driver = card_type is None or card_type == DRIVER_CARD_TYPE
    if driver:
        required |= _G1_DRIVER_TAGS if gen == "G1" else _G2_DRIVER_TAGS
    if gen == "G2" and v2_present:
        required |= _G22_V2_UNIVERSAL_TAGS
        if driver:
            required |= _G22_V2_DRIVER_TAGS
    return required


def missing_core_efs(pairs: List[Dict[str, Any]]) -> List[int]:
    """Return mandatory EF tags missing for an EF application generation present.

    Completeness is keyed on the EF *application* generations actually observed
    (the dtype-00/01 G1 copies vs the dtype-02/03 G2 copies), never on the
    user-facing generation label, and the mandatory set depends on the card type
    encoded in that generation's own Application_Identification bytes: an
    explicit non-driver card type must not be charged driver-only EFs, while an
    unknown/unreadable identity fails closed. An unsigned, unregistered
    dtype-02 record must not disable G1 checking, and a G2 application that was
    never captured must not be demanded from the display label alone.

    ``pair_ef_records`` only reports tags it actually saw data/signature
    occurrences for -- a fully-deleted EF (both copies removed) leaves no
    trace, so completeness must be checked against a known tag set rather than
    by inspecting the pairs alone. Returns the sorted integer tag list.
    """
    present = {(pair["tag"], pair["gen"]) for pair in pairs}
    generations = {gen for _tag, gen in present}
    v2_present = _v2_application_present(pairs)
    missing: set = set()
    for gen in ("G1", "G2"):
        if gen not in generations:
            continue
        required = _required_tags(gen, _application_card_type(pairs, gen), v2_present)
        missing |= {tag for tag in required if (tag, gen) not in present}
    return sorted(missing)


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
    0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x0530, 0x0540,
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
                "verified": 0, "failed": 0, "skipped": 0, "total": 0,
                "key_trust": None}

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

    # Build summary. Skipped pairs are never counted as verified: a partial
    # check that leaves some EFs unverified must say so explicitly.
    total = verified + failed
    skipped_note = f", {skipped} skipped" if skipped else ""
    if total == 0 and skipped == 0:
        summary = "No EF signature pairs found"
    elif failed == 0 and skipped == 0:
        summary = f"All {total} EF signature(s) verified"
    elif failed == 0:
        summary = f"{verified}/{total} EF signature(s) verified{skipped_note}"
    elif verified == 0:
        summary = f"All {total} EF signature(s) FAILED{skipped_note}"
    else:
        summary = f"{verified}/{total} EF signature(s) verified, {failed} FAILED{skipped_note}"

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
