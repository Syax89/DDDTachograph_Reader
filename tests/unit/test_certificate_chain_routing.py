"""Certificate-chain routing for G2 / G2.2 cards (C4 / XD-F4).

TCS_152 lists the normative G2 certificate FIDs: CardMA ``C100h``, CardSign
``C101h``, CA ``C108h`` and Link ``C109h`` (the same table lists V2-only EFs
0525h–0530h/0540h). The draft claimed 0xC102/0xC10A were "G2.2-native"
certificates and routed them into the chain; that premise is refuted — C102/C10A
are unsupported compatibility aliases whose provenance is unverified.

These tests use **distinct, genuine** normative CVCs with real ECDSA signatures
and signed V2 data, asserting correct role routing. Unsupported C102/C10A bytes
must not overwrite the normative C101/C108 chain inputs.
"""
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from core.crypto.vu_signature import cvc_public_key, parse_cvc, verify_cvc_chain_link
from core.utils.report_format import VERDICT_VERIFIED, integrity_verdict
from tests.unit.card_crypto import (
    cvc,
    g1_cert_records,
    g1_core_payloads,
    g1_identity,
    g2_cert_records,
    g2_core_payloads,
    new_cvc_identity,
    parse_bytes,
    signed_pairs,
    stap,
    trust_store,
    trusted_root_and_msca,
    v2_payloads,
)


def _signed_v2_card(identity):
    """Normative C101/C108 certificate chain + a full signed V2 core."""
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    return (g2_cert_records(identity["card_cert"], identity["msca_cert"])
            + signed_pairs(payloads, identity["card_key"], 2))


def test_normative_card_and_ca_certificates_route_to_the_right_roles():
    erca_cert, identity = trusted_root_and_msca()
    assert identity["card_cert"] != identity["msca_cert"]

    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        parser, result = parse_bytes(_signed_v2_card(identity), certs_dir)

    assert parser.card_cert_raw == identity["card_cert"]
    assert parser.msca_cert_raw == identity["msca_cert"]
    # The two CVCs really carry distinct identities (not identical dummy bytes).
    assert parse_cvc(parser.card_cert_raw)["car"] != parse_cvc(parser.msca_cert_raw)["car"]
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def test_swapped_card_and_ca_certificates_do_not_verify():
    """Roles are real: feeding the CA certificate as the card's fails the chain."""
    erca_cert, identity = trusted_root_and_msca()
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    swapped = (g2_cert_records(identity["msca_cert"], identity["card_cert"])
               + signed_pairs(payloads, identity["card_key"], 2))

    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        _parser, result = parse_bytes(swapped, certs_dir)

    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) != VERDICT_VERIFIED


def test_unsupported_c102_c10a_do_not_replace_normative_certificate_inputs():
    erca_cert, identity = trusted_root_and_msca()
    # Non-normative, unsupported bytes appended after the genuine chain.
    aliases = (stap(0xC102, 0x00, b"\x30" + bytes(193))
               + stap(0xC10A, 0x00, b"\x30" + bytes(193)))

    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        parser, result = parse_bytes(_signed_v2_card(identity) + aliases, certs_dir)

    # The normative C101/C108 inputs survive: the aliases must not overwrite them.
    assert parser.card_cert_raw == identity["card_cert"]
    assert parser.msca_cert_raw == identity["msca_cert"]
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def test_certificate_only_g2_card_does_not_verify():
    erca_cert, identity = trusted_root_and_msca()
    data = g2_cert_records(identity["card_cert"], identity["msca_cert"])

    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        _parser, result = parse_bytes(data, certs_dir)

    assert integrity_verdict(result) != VERDICT_VERIFIED


# ── Fixture identity: CAR/CHR relationships and signatures ────────────────

def test_fixture_certificate_references_and_signatures_are_consistent():
    """The shared fixture must link references the correct way round and each
    CVC must carry a real ECDSA signature over its body (labels alone are not a
    profile check)."""
    erca_cert, identity = trusted_root_and_msca()
    root = parse_cvc(erca_cert)
    ca = parse_cvc(identity["msca_cert"])
    sign = parse_cvc(identity["card_cert"])

    assert ca["car"] == root["chr"]
    assert sign["car"] == ca["chr"]
    assert len({root["chr"], ca["chr"], sign["chr"]}) == 3

    root_pub, root_hash = cvc_public_key(root)
    ca_pub, ca_hash = cvc_public_key(ca)
    assert verify_cvc_chain_link(ca, root_pub, root_hash)
    assert verify_cvc_chain_link(sign, ca_pub, ca_hash)


# ── M4 / F4: signing-role routing ─────────────────────────────────────────

def _signed_v2_core(identity):
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    return signed_pairs(payloads, identity["card_key"], 2)


def test_g2_c102_c10a_dtype02_cannot_replace_normative_certificates():
    """M4: an unsupported C102/C10A appendix carrying the G2 dtype (02/03) must
    not overwrite the normative CardSign (C101) / CA (C108) inputs."""
    erca_cert, identity = trusted_root_and_msca()
    other = new_cvc_identity(None)  # genuinely signed, different identity
    data = b"".join([
        g2_cert_records(identity["card_cert"], identity["msca_cert"]),
        _signed_v2_core(identity),
        stap(0xC102, 0x02, other["card_cert"]),
        stap(0xC10A, 0x02, other["msca_cert"]),
    ])
    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser.card_cert_raw == identity["card_cert"]
    assert parser.msca_cert_raw == identity["msca_cert"]
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def _cardma_certificate(identity):
    """A genuine CardMA (Member Authority) CVC: holder CARDMA01, issued by the CA."""
    ma_key = ec.generate_private_key(ec.SECP256R1())
    return cvc(ma_key, identity["msca_key"], b"MSSCA001", b"CARDMA01")


@pytest.mark.parametrize("position", ["before", "after"])
def test_g2_c100_cardma_never_replaces_cardsign(position):
    """F4: in the generation-2 DF, C100 is CardMA — a different role that must
    never be used as the CardSign key, in either stream order."""
    erca_cert, identity = trusted_root_and_msca()
    ma_record = stap(0xC100, 0x02, _cardma_certificate(identity))
    core = g2_cert_records(identity["card_cert"], identity["msca_cert"])
    certs = ma_record + core if position == "before" else core + ma_record
    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        parser, result = parse_bytes(certs + _signed_v2_core(identity), certs_dir)

    assert parser.card_cert_raw == identity["card_cert"]
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def test_g1_c100_card_certificate_capture_is_legitimate():
    """The generation-1 DF legitimately uses C100 as the card certificate."""
    g1_ids = g1_identity()
    data = (g1_cert_records(g1_ids["card_cert"], g1_ids["msca_cert"])
            + signed_pairs(g1_core_payloads(), g1_ids["card_key"], 1))
    with trust_store(g1_erca_key=g1_ids["erca_key"]) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser.card_cert_raw == g1_ids["card_cert"]
    assert parser.msca_cert_raw == g1_ids["msca_cert"]
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED
