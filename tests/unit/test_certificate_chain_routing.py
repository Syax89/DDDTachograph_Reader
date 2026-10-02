"""Certificate-chain routing for G2 / G2.2 cards (C4 / XD-F4).

TCS_152 lists the normative G2 certificate FIDs: CardMA ``C100h``, CardSign
``C101h``, CA ``C108h`` and Link ``C109h`` (the same table lists V2-only EFs
0525h–0530h/0540h). The draft claimed 0xC102/0xC10A were "G2.2-native"
certificates and routed them into the chain; that premise is refuted — C102/C10A
are unsupported compatibility aliases whose provenance is unverified.

These tests use **distinct, genuine** normative CVCs with real ECDSA signatures
and signed V2 data, asserting correct role routing. Unsupported C102/C10A bytes
must not overwrite the normative C101/C108 chain inputs, for either G2 appendix
dtype (data 0x02 or signature 0x03).

**Scope of what these tests prove:** the native G2 certificate FIDs, distinct
genuine CVC public keys, a real ECDSA signature over each CVC body, and the
CA.CAR = root.CHR / CardSign.CAR = CA.CHR reference relationships. The
certificates are **shortened synthetic envelopes**, so this is NOT a complete
normative CVC / CHA / certificate-profile conformance check; C109 Link
handling and full profile/CHA validation are out of scope for this batch.
"""
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from core.crypto.vu_signature import cvc_public_key, parse_cvc, verify_cvc_chain_link
from core.registry.registry import DecoderRegistry
from core.utils.report_format import (
    VERDICT_UNVERIFIED, VERDICT_VERIFIED, integrity_verdict)
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


@pytest.mark.parametrize("dtype", [0x02, 0x03])
def test_g2_c102_c10a_dtype0203_cannot_replace_normative_certificates(dtype):
    """M4: an unsupported C102/C10A appendix carrying either G2 appendix dtype
    (data 0x02 or signature 0x03) must not overwrite the normative CardSign
    (C101) / CA (C108) inputs."""
    erca_cert, identity = trusted_root_and_msca()
    other = new_cvc_identity(None)  # genuinely signed, different identity
    data = b"".join([
        g2_cert_records(identity["card_cert"], identity["msca_cert"]),
        _signed_v2_core(identity),
        stap(0xC102, dtype, other["card_cert"]),
        stap(0xC10A, dtype, other["msca_cert"]),
    ])
    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser.card_cert_raw == identity["card_cert"]
    assert parser.msca_cert_raw == identity["msca_cert"]
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def _cardma_identity(identity):
    """A genuine CA-signed CardMA CVC (holder CARDMA01) and its private key."""
    ma_key = ec.generate_private_key(ec.SECP256R1())
    ma_cert = cvc(ma_key, identity["msca_key"], b"MSSCA001", b"CARDMA01")
    return ma_key, ma_cert


@pytest.mark.parametrize("dtype", [0x00, 0x01, 0x02, 0x03])
@pytest.mark.parametrize("position", ["before", "after"])
def test_g2_c100_cardma_never_replaces_cardsign(dtype, position):
    """F4/R4: in the generation-2 DF C100 is CardMA. A genuine CA-signed CardMA
    certificate carrying ANY appendix dtype, in either stream order, must never
    take the CardSign slot. The EF pairs are signed by the CardMA key, so a leak
    into the CardSign slot would surface as a silent `Verified`; the correct
    routing leaves an explicit failed-signature outcome instead."""
    erca_cert, identity = trusted_root_and_msca()
    ma_key, ma_cert = _cardma_identity(identity)
    ma_record = stap(0xC100, dtype, ma_cert)
    core = g2_cert_records(identity["card_cert"], identity["msca_cert"])
    certs = ma_record + core if position == "before" else core + ma_record
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    data = certs + signed_pairs(payloads, ma_key, 2)  # signed by CardMA, not CardSign

    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser.card_cert_raw == identity["card_cert"]
    assert not result["metadata"]["integrity_check"].startswith("Verified")
    assert integrity_verdict(result) != VERDICT_VERIFIED
    # Explicit failed-signature outcome, never a silent success.
    assert result["ef_signature_verification"]["failed"] >= 1
    assert result["metadata"]["integrity_check"] == "Unverified (EF Signature Mismatch)"


def test_unsupported_c102_c10a_aliases_are_marked_non_native():
    """Pin the registry marking that labels the unsupported C102/C10A
    compatibility aliases as non-native, so the marking cannot be silently
    removed: they must not claim a normative Annex 1C identity."""
    registry = DecoderRegistry.instance()
    for tag, legacy_name in ((0xC102, "G22_CardCertificate_Legacy"),
                             (0xC10A, "G22_CA_Certificate_Legacy")):
        dec = registry.get_decoder(tag, generation="G2.2", is_vu=False)
        assert dec is not None
        assert dec.name == legacy_name
        assert "Unverified" in dec.annex_ref and "not Annex" in dec.annex_ref


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


# ── R5: C100 CardMA must never be the EF signing key, even with no C101 ────

@pytest.mark.parametrize("dtype", [0x00, 0x01, 0x02, 0x03])
def test_c100_cardma_without_c101_never_supplies_the_ef_signing_key(dtype):
    """R5: with a normative CA present but NO CardSign record, a genuine
    CA-signed CardMA ``C100`` must not stand in as the EF-signing key even when
    the EF pairs are signed by the CardMA key (which would otherwise verify)."""
    erca_cert, identity = trusted_root_and_msca()
    ma_key, ma_cert = _cardma_identity(identity)
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    data = (stap(0xC100, dtype, ma_cert)
            + stap(0xC108, 0x02, identity["msca_cert"])
            + signed_pairs(payloads, ma_key, 2))  # signed by CardMA

    with trust_store(g2_erca_cert=erca_cert) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser.card_cert_raw is None  # CardMA never takes the CardSign slot
    meta = result["metadata"]["integrity_check"]
    assert not meta.startswith("Verified")
    assert meta in ("Incomplete Certificates", "Invalid Certificate Chain")
    assert integrity_verdict(result) == VERDICT_UNVERIFIED
    efv = result["ef_signature_verification"]
    assert efv.get("verified", 0) == 0        # nothing verified with the CardMA key
    assert efv.get("failed", 0) >= 1 or efv.get("skipped", 0) >= 1


@pytest.mark.parametrize("position", ["before", "after"])
def test_g1_form_c100_never_clobbers_a_captured_cardsign(position):
    """A legitimate generation-1 (194-byte, non-CVC) C100 arriving after the
    generation-2 CardSign must not clobber the CardSign / EF-signing slot; the
    same file reaches Verified in either stream order."""
    erca_cert, identity = trusted_root_and_msca()
    g1_ids = g1_identity()
    g1_record = stap(0xC100, 0x00, g1_ids["card_cert"])  # 194-byte G1 form
    core = (stap(0xC101, 0x02, identity["card_cert"])
            + stap(0xC108, 0x02, identity["msca_cert"]))
    certs = g1_record + core if position == "before" else core + g1_record
    payloads = g2_core_payloads(v2=True)
    payloads.update(v2_payloads())
    data = certs + signed_pairs(payloads, identity["card_key"], 2)  # CardSign-signed

    with trust_store(g2_erca_cert=erca_cert, g1_erca_key=g1_ids["erca_key"]) as certs_dir:
        parser, result = parse_bytes(data, certs_dir)

    assert parser.card_cert_raw == identity["card_cert"]
    assert result["metadata"]["integrity_check"] == "Verified"
    assert integrity_verdict(result) == VERDICT_VERIFIED


def test_g1_card_certificate_gate_accepts_only_the_194_byte_form():
    """M3: the `card_cert_g1` generation-1 RSA chain input is fed from the exact
    194-byte card certificate form; a differently-sized G1-form payload must not
    feed it (the constant is real generated output, not free to drift)."""
    erca_cert, identity = trusted_root_and_msca()
    g1_ids = g1_identity()
    g1_cert = g1_ids["card_cert"]
    assert len(g1_cert) == 194
    assert g1_cert[0] not in (0x30, 0x7F)  # the generation-1 payload form

    def _parse_with(card_payload):
        data = (stap(0xC100, 0x00, card_payload)
                + stap(0xC108, 0x00, g1_ids["msca_cert"])
                + signed_pairs(g1_core_payloads(), g1_ids["card_key"], 1))
        with trust_store(g1_erca_key=g1_ids["erca_key"]) as certs_dir:
            return parse_bytes(data, certs_dir)[0]

    exact = _parse_with(g1_cert)
    assert exact.card_cert_g1 == g1_cert
    assert exact.card_cert_raw == g1_cert

    shortened = _parse_with(g1_cert[:193])
    assert shortened.card_cert_g1 is None
