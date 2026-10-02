"""Per-EF-application-generation completeness (C2 / E-F3) with real crypto.

Completeness is keyed on the EF *application* generations actually present
(dtype-00/01 G1 copies vs dtype-02/03 G2 copies), never on the user-facing
generation label. A signed mandatory EF removed outright (both data and
signature copies) must fail closed; an unobserved application must not be
demanded from the display label alone.

All chains and EF signatures are real RSA (G1 ISO 9796-2 / PKCS#1 v1.5) and
ECDSA (G2 CVC) — nothing is mocked.
"""
import pytest

from core.crypto.ef_signature import missing_core_efs
from core.utils.report_format import VERDICT_UNVERIFIED, VERDICT_VERIFIED, integrity_verdict
from tests.unit.card_crypto import (
    application_identification,
    g1_core_payloads,
    g1_cert_records,
    g1_identity,
    g2_cert_records,
    g2_core_payloads,
    non_driver_envelope,
    parse_bytes,
    signed_pairs,
    stap,
    trust_store,
    trusted_root_and_msca,
    v2_payloads,
)

# Recognised non-driver card types: workshop (2), control (3), company (4).
NON_DRIVER_TYPES = (0x02, 0x03, 0x04)
DRIVER_ONLY_G1 = (0x0502, 0x0503, 0x0504, 0x0505, 0x0506, 0x0508, 0x0522)


def _g1_card(g1_ids, payloads):
    return (g1_cert_records(g1_ids["card_cert"], g1_ids["msca_cert"])
            + signed_pairs(payloads, g1_ids["card_key"], 1))


def _g2_card(identity, payloads):
    return (g2_cert_records(identity["card_cert"], identity["msca_cert"])
            + signed_pairs(payloads, identity["card_key"], 2))


def _parse_g1(g1_ids, data):
    with trust_store(g1_erca_key=g1_ids["erca_key"]) as certs_dir:
        return parse_bytes(data, certs_dir)[1]


def _parse_g2(erca_cert, data):
    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        return parse_bytes(data, certs_dir)[1]


# ── G1 ─────────────────────────────────────────────────────────────────────

def test_g1_full_core_is_verified():
    g1_ids = g1_identity()
    result = _parse_g1(g1_ids, _g1_card(g1_ids, g1_core_payloads()))

    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
    efv = result["ef_signature_verification"]
    assert efv["missing_core_efs"] == []
    assert efv["failed"] == 0 and efv["skipped"] == 0


def test_g1_both_copies_removed_is_incomplete():
    g1_ids = g1_identity()
    payloads = g1_core_payloads()
    del payloads[0x0502]  # remove BOTH the data and the signature copy
    result = _parse_g1(g1_ids, _g1_card(g1_ids, payloads))

    assert result["ef_signature_verification"]["missing_core_efs"] == [0x0502]
    assert result["metadata"]["integrity_check"] == "Unverified (Missing EF: 0x0502)"
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_g1_optional_download_efs_are_not_required():
    """0x0507 (CurrentUsage) and 0x0521 (DrivingLicenceInfo) exist on the card
    but are not mandatory in every download, so their absence is not a defect."""
    g1_ids = g1_identity()
    result = _parse_g1(g1_ids, _g1_card(g1_ids, g1_core_payloads()))

    assert 0x0507 not in result["ef_signature_verification"]["missing_core_efs"]
    assert 0x0521 not in result["ef_signature_verification"]["missing_core_efs"]
    assert result["metadata"]["integrity_check"] == "Verified"


def test_g1_with_unknown_dtype02_does_not_disable_g1_checking():
    """An unsigned, unregistered dtype-02 record flips the *label* to G2 but
    must not disable completeness for the G1 application actually present."""
    g1_ids = g1_identity()
    payloads = g1_core_payloads()
    del payloads[0x0502]
    data = _g1_card(g1_ids, payloads) + stap(0x9001, 0x02, b"X")
    result = _parse_g1(g1_ids, data)

    assert result["metadata"]["generation"].startswith("G2")  # label flipped
    assert result["ef_signature_verification"]["missing_core_efs"] == [0x0502]
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_label_does_not_demand_an_unobserved_g2_application():
    """A G1-only download (label upgraded by an unregistered dtype-02 record)
    must not be judged incomplete for a G2 application that was never captured."""
    g1_ids = g1_identity()
    data = _g1_card(g1_ids, g1_core_payloads()) + stap(0x9001, 0x02, b"X")
    result = _parse_g1(g1_ids, data)

    assert result["metadata"]["generation"].startswith("G2")
    assert result["ef_signature_verification"]["missing_core_efs"] == []
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def test_g1_certificates_only_stays_fail_closed():
    g1_ids = g1_identity()
    data = g1_cert_records(g1_ids["card_cert"], g1_ids["msca_cert"])
    result = _parse_g1(g1_ids, data)

    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


# ── G2 ─────────────────────────────────────────────────────────────────────

def test_g2_full_core_is_verified():
    erca_cert, identity = trusted_root_and_msca()
    result = _parse_g2(erca_cert, _g2_card(identity, g2_core_payloads()))

    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
    efv = result["ef_signature_verification"]
    assert efv["missing_core_efs"] == []
    assert efv["untrusted_generations"] == []


def test_g2_both_copies_removed_is_incomplete():
    erca_cert, identity = trusted_root_and_msca()
    payloads = g2_core_payloads()
    del payloads[0x0523]  # VehicleUnits_Used: a G2-only mandatory EF
    result = _parse_g2(erca_cert, _g2_card(identity, payloads))

    assert result["ef_signature_verification"]["missing_core_efs"] == [0x0523]
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


# ── V2 (conditional) ───────────────────────────────────────────────────────

def test_v2_full_core_is_verified():
    erca_cert, identity = trusted_root_and_msca()
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    result = _parse_g2(erca_cert, _g2_card(identity, payloads))

    assert result["metadata"]["generation"] == "G2.2 (Smart V2)"
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
    assert result["ef_signature_verification"]["missing_core_efs"] == []


def test_v2_both_copies_removed_is_incomplete():
    erca_cert, identity = trusted_root_and_msca()
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    del payloads[0x0526]
    result = _parse_g2(erca_cert, _g2_card(identity, payloads))

    assert result["ef_signature_verification"]["missing_core_efs"] == [0x0526]
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_v2_structure_version_demands_the_v2_set():
    """A V2 Application_Identification (structure version {01 01}) alone makes
    the V2-only EFs required even before any V2 record was seen."""
    erca_cert, identity = trusted_root_and_msca()
    payloads = g2_core_payloads(v2=True)  # no 0525-0530 records
    result = _parse_g2(erca_cert, _g2_card(identity, payloads))

    assert result["ef_signature_verification"]["missing_core_efs"] == [0x0525, 0x0526, 0x0527, 0x0528, 0x0529, 0x0530]
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_v2_application_without_v2_structure_version_is_not_v2():
    """A V1 structure version and no V2 records stays a plain G2 download."""
    erca_cert, identity = trusted_root_and_msca()
    result = _parse_g2(erca_cert, _g2_card(identity, g2_core_payloads(v2=False)))

    assert result["metadata"]["generation"] == "G2 (Smart)"
    assert result["ef_signature_verification"]["missing_core_efs"] == []


# ── Unit contract + canonical verdict fail-closed ──────────────────────────

def test_missing_core_efs_returns_sorted_integer_tag_list():
    pairs = [
        {"tag": 0x0501, "gen": "G1", "status": "paired"},
        {"tag": 0x0502, "gen": "G1", "status": "paired"},
    ]
    missing = missing_core_efs(pairs)
    assert missing == sorted(missing)
    assert all(isinstance(tag, int) for tag in missing)
    assert 0x0501 not in missing and 0x0502 not in missing


def test_missing_core_efs_empty_when_no_application_generation_present():
    assert missing_core_efs([]) == []


def test_integrity_verdict_fails_closed_on_structured_missing_efs():
    result = {
        "metadata": {"integrity_check": "Verified", "is_vu": False},
        "ef_signature_verification": {
            "missing_core_efs": [0x0502],
            "untrusted_generations": [],
            "failed": 0, "skipped": 0, "verified": 8,
        },
    }
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


# ── F1: mandatory scope depends on card type, per application generation ───

@pytest.mark.parametrize("card_type", NON_DRIVER_TYPES)
def test_g1_non_driver_card_is_not_charged_driver_only_efs(card_type):
    """DDP_035 makes the driver data EFs mandatory only for driver cards. A
    workshop/control/company card download carrying just the universal minimum
    (Application_Identification + Identification) is complete."""
    g1_ids = g1_identity()
    result = _parse_g1(g1_ids, _g1_card(g1_ids, non_driver_envelope(1, card_type)))

    assert result["ef_signature_verification"]["missing_core_efs"] == []
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


@pytest.mark.parametrize("card_type", NON_DRIVER_TYPES)
def test_g2_non_driver_card_is_not_charged_driver_only_efs(card_type):
    erca_cert, identity = trusted_root_and_msca()
    result = _parse_g2(erca_cert, _g2_card(identity, non_driver_envelope(2, card_type)))

    assert result["ef_signature_verification"]["missing_core_efs"] == []
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def test_driver_card_missing_driver_only_efs_is_incomplete():
    """The same minimal envelope with type = driver (1): the driver data EFs are
    now required, so completeness fails closed."""
    g1_ids = g1_identity()
    result = _parse_g1(g1_ids, _g1_card(g1_ids, non_driver_envelope(1, 0x01)))

    missing = result["ef_signature_verification"]["missing_core_efs"]
    for tag in DRIVER_ONLY_G1:
        assert tag in missing
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_absent_application_identity_fails_closed_to_the_driver_set():
    g1_ids = g1_identity()
    payloads = {0x0520: bytes(143)}  # Identification only; 0501 absent
    result = _parse_g1(g1_ids, _g1_card(g1_ids, payloads))

    missing = result["ef_signature_verification"]["missing_core_efs"]
    assert 0x0501 in missing and 0x0502 in missing
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_duplicated_application_identity_fails_closed_to_the_driver_set():
    g1_ids = g1_identity()
    app = application_identification(1, 0x02)  # claims non-driver
    data = (_g1_card(g1_ids, {0x0520: bytes(143)})
            + signed_pairs({0x0501: app}, g1_ids["card_key"], 1)
            + signed_pairs({0x0501: app}, g1_ids["card_key"], 1))
    result = _parse_g1(g1_ids, data)

    missing = result["ef_signature_verification"]["missing_core_efs"]
    assert 0x0502 in missing  # ambiguous identity -> driver set (fail closed)
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_malformed_application_identity_fails_closed_to_the_driver_set():
    g1_ids = g1_identity()
    payloads = non_driver_envelope(1, 0x02)
    payloads[0x0501] = bytes([0x02])  # 1-byte, unreadable identity
    result = _parse_g1(g1_ids, _g1_card(g1_ids, payloads))

    missing = result["ef_signature_verification"]["missing_core_efs"]
    assert 0x0502 in missing
    assert integrity_verdict(result) == VERDICT_UNVERIFIED
