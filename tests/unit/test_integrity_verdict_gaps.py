"""Integrity-verdict gaps closed in the 2.9.x audit.

* A G2 card whose certificate is not signed by its MSCA must read as an
  invalid chain, not "Partial", and a valid VU chain elsewhere in the file must
  never overwrite it.
* A G1 chain that unwraps cleanly but whose certificate had expired when the
  download was signed must not read as verified.
* A G2 VU download signed under a VU/MSCA certificate that was expired (or not
  yet valid) at download time must not read as verified.
* Bytes after the last framed G1 VU message are covered by no TREP signature
  and must keep the download from reading as fully verified.

Bare parser and synthetic results only — no private download is needed.
"""
import datetime
import os
import tempfile

from app.engine import TachoParser
from core.crypto import vu_signature
from core.parser import g1_walker
from core.utils.report_format import (
    VERDICT_CORRUPT,
    VERDICT_PARTIAL,
    VERDICT_UNVERIFIED,
    VERDICT_VERIFIED,
    integrity_verdict,
)


def _bare_parser():
    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    tmp.write(b"\x00")
    tmp.close()
    parser = TachoParser(tmp.name)
    os.unlink(tmp.name)
    parser.results = {"metadata": {"generation": "G1"}}
    parser.card_public_key = None
    parser.card_cert_raw = None
    parser.msca_cert_raw = None
    parser.card_cert_g1 = None
    parser.msca_cert_g1 = None
    parser.validation_status = "Pending"
    return parser


def _stub_chain(parser, monkeypatch, status, pubkey=None, temporal=None):
    def fake(card, msca, verification_time=None):
        parser.validator.last_chain_temporal_validity = dict(temporal or {})
        parser.validator.last_chain_generation = "G2"
        return status, pubkey
    monkeypatch.setattr(parser.validator, "validate_tacho_chain", fake)


# --- MSCA→Card link failure ------------------------------------------------

def test_failed_msca_to_card_link_is_an_invalid_chain(monkeypatch):
    parser = _bare_parser()
    parser.card_cert_raw, parser.msca_cert_raw = b"\x7f card", b"\x7f msca"
    _stub_chain(parser, monkeypatch, "Partial — MSCA→Card FAILED")

    parser._validate_certificate_chain()

    assert parser.validation_status.startswith("Invalid Certificate Chain")
    result = {"metadata": {"is_vu": False,
                           "integrity_check": parser.validation_status}}
    assert integrity_verdict(result) == VERDICT_CORRUPT


def test_valid_vu_chain_cannot_launder_a_failed_card_link(monkeypatch):
    parser = _bare_parser()
    parser.card_cert_raw, parser.msca_cert_raw = b"\x7f card", b"\x7f msca"
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": True,
    }
    _stub_chain(parser, monkeypatch, "Partial — MSCA→Card FAILED")

    parser._validate_certificate_chain()

    assert parser.validation_status != "Verified (VU Chain)"
    assert parser.validation_status.startswith("Invalid Certificate Chain")


# --- G1 certificate expired at download time --------------------------------

def test_expired_g1_chain_is_not_verified(monkeypatch):
    parser = _bare_parser()
    parser.card_cert_g1, parser.msca_cert_g1 = b"g1 card", b"g1 msca"
    sentinel_key = object()
    _stub_chain(parser, monkeypatch, True, sentinel_key, temporal={
        "card": {"status": "expired", "valid_from": "", "valid_to": "2019-01-01"},
        "msca": {"status": "valid", "valid_from": "", "valid_to": "2030-01-01"},
    })

    parser._validate_certificate_chain()

    assert not parser.validation_status.startswith("Verified")
    assert "expired at download time" in parser.validation_status
    assert "card" in parser.validation_status
    assert parser._chain_trust == {"G1": False, "G2": False}
    # The key is kept so EF/TREP signatures are still checked and reported.
    assert parser.card_public_key is sentinel_key
    result = {"metadata": {"is_vu": False,
                           "integrity_check": parser.validation_status}}
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_valid_g1_dates_still_verify(monkeypatch):
    parser = _bare_parser()
    parser.card_cert_g1, parser.msca_cert_g1 = b"g1 card", b"g1 msca"
    _stub_chain(parser, monkeypatch, True, object(), temporal={
        "card": {"status": "valid", "valid_from": "", "valid_to": "2030-01-01"},
    })

    parser._validate_certificate_chain()

    assert parser.validation_status == "Verified"


def test_undated_download_is_not_judged(monkeypatch):
    parser = _bare_parser()
    parser.card_cert_g1, parser.msca_cert_g1 = b"g1 card", b"g1 msca"
    _stub_chain(parser, monkeypatch, True, object(), temporal={
        "card": {"status": "not_checked", "valid_from": "", "valid_to": "2019-01-01"},
    })

    parser._validate_certificate_chain()

    assert parser.validation_status == "Verified"


# --- G2 VU certificate dates -------------------------------------------------

def test_expired_vu_certificate_is_not_verified():
    parser = _bare_parser()
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": True,
        "certificate_dates_invalid": ["vu"],
    }

    parser._validate_certificate_chain()

    assert parser.validation_status != "Verified (VU Chain)"
    assert "expired at download time" in parser.validation_status
    result = {"metadata": {"is_vu": True,
                           "integrity_check": parser.validation_status},
              "signature_verification": parser.results["signature_verification"]}
    assert integrity_verdict(result) == VERDICT_UNVERIFIED


def test_verify_vu_download_flags_expired_certificates(monkeypatch):
    when = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
    fake_vu = {"effective_date": None, "expiration_date": None}
    monkeypatch.setattr(vu_signature, "iter_vu_sections", lambda data: [
        {"trep": 0x21, "marker": 0, "records": [(2, 0x0F, 4, 1, 11)]}])
    monkeypatch.setattr(vu_signature, "parse_cvc", lambda raw: fake_vu)
    monkeypatch.setattr(vu_signature, "cvc_public_key", lambda cvc: (None, None))
    monkeypatch.setattr(vu_signature, "cvc_temporal_status",
                        lambda cvc, t: {"status": "expired", "valid_from": "",
                                        "valid_to": ""})

    report = vu_signature.verify_vu_download(bytes(16), verification_time=when)

    assert report["certificate_dates_invalid"] == ["vu"]


# --- G1 VU unsigned tail -----------------------------------------------------

def _g1_vu_parser(monkeypatch, raw, messages):
    parser = _bare_parser()
    parser.is_vu = True
    parser.raw_data = raw
    parser.card_public_key = object()
    parser._chain_trust = {"G1": True, "G2": False}
    parser.validation_status = "Verified"
    monkeypatch.setattr(g1_walker, "iter_g1_vu_messages", lambda data: iter(messages))
    monkeypatch.setattr(parser.validator, "verify_g1_data_signature",
                        lambda key, sig, payload: True)
    return parser


def _signed_message(end):
    return {"pos": 0, "trep": 0x02, "body_start": 2, "body_end": end - 128,
            "sig_len": 128, "end": end}


def test_bytes_after_the_last_g1_message_are_unsigned(monkeypatch):
    raw = bytes(300) + b"\xAA" * 40
    parser = _g1_vu_parser(monkeypatch, raw, [_signed_message(300)])

    parser._verify_g1_vu_signatures()

    sv = parser.results["signature_verification"]
    assert sv["unsigned_bytes"] == 40
    assert sv["unsigned_ranges"] == [[300, 340]]
    assert parser.validation_status.startswith("Partial")
    result = {"metadata": {"is_vu": True,
                           "integrity_check": parser.validation_status},
              "signature_verification": sv}
    assert integrity_verdict(result) == VERDICT_PARTIAL


def test_download_trailer_is_not_unsigned_payload(monkeypatch):
    raw = bytes(300) + b"\x76\x00\x00\x00"
    parser = _g1_vu_parser(monkeypatch, raw, [_signed_message(300)])

    parser._verify_g1_vu_signatures()

    sv = parser.results["signature_verification"]
    assert "unsigned_bytes" not in sv
    assert parser.validation_status == "Verified (G1 VU chain and TREP signatures)"
    result = {"metadata": {"is_vu": True,
                           "integrity_check": parser.validation_status},
              "signature_verification": sv}
    assert integrity_verdict(result) == VERDICT_VERIFIED
