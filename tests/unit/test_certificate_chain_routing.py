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
from core.crypto.vu_signature import parse_cvc
from core.utils.report_format import VERDICT_VERIFIED, integrity_verdict
from tests.unit.card_crypto import (
    g2_cert_records,
    g2_core_payloads,
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
