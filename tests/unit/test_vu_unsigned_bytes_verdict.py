"""Bytes no signature covers must not ride along under a "verified" verdict.

``verify_vu_download`` already computes ``unsigned_bytes``/``unsigned_ranges``
"so a report never asserts a fully signed download while unsigned bytes ride
along", but nothing consumed them: appending junk to a fully signed download
kept both the printed status and ``integrity_verdict`` at verified.

These tests use a bare parser and a synthetic result dict — no private download.
"""
import os
import tempfile

from app.engine import TachoParser
from core.crypto import vu_signature
from core.utils.report_format import (
    VERDICT_PARTIAL,
    VERDICT_VERIFIED,
    integrity_verdict,
)


def _bare_parser():
    tmp = tempfile.NamedTemporaryFile(suffix=".ddd", delete=False)
    tmp.write(b"\x00")
    tmp.close()
    parser = TachoParser(tmp.name)
    os.unlink(tmp.name)
    parser.results = {}
    parser.card_public_key = None
    parser.card_cert_raw = None
    parser.msca_cert_raw = None
    parser.card_cert_g1 = None
    parser.msca_cert_g1 = None
    parser.validation_status = "Pending"
    parser.validator.root_certificates.clear()
    return parser


def _vu_result(**signature_verification):
    return {
        "metadata": {"is_vu": True, "integrity_check": "Verified (VU Chain)"},
        "signature_verification": signature_verification,
    }


def test_appended_bytes_do_not_report_a_verified_download():
    parser = _bare_parser()
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": True,
        "unsigned_bytes": 78, "unsigned_ranges": [[107589, 107667]],
    }

    parser._validate_certificate_chain()

    assert parser.validation_status != "Verified (VU Chain)"
    assert "unsigned" in parser.validation_status.lower()


def test_appended_bytes_fail_the_canonical_verdict():
    verdict = integrity_verdict(_vu_result(
        msca_to_vu=True, all_treps_valid=True, root_anchored=True,
        unsigned_bytes=78))

    assert verdict == VERDICT_PARTIAL


def test_a_fully_signed_download_still_verifies():
    """The fix must not downgrade the clean case."""
    parser = _bare_parser()
    parser.results["signature_verification"] = {
        "msca_to_vu": True, "all_treps_valid": True, "root_anchored": True,
    }
    parser._validate_certificate_chain()
    assert parser.validation_status == "Verified (VU Chain)"

    verdict = integrity_verdict(_vu_result(
        msca_to_vu=True, all_treps_valid=True, root_anchored=True))
    assert verdict == VERDICT_VERIFIED


def test_trailing_junk_is_counted_as_unsigned(monkeypatch):
    """End-to-end at the verifier level: appended bytes produce a count."""
    section = {
        "marker": 0,
        "trep": 0x21,
        "records": [
            (2, 0x04, 1, 1, 8),
            (8, 0x0F, 1, 1, 14),
            (14, 0x01, 1, 1, 20),
            (20, 0x08, 64, 1, 89),
        ],
    }
    data = bytearray(89)
    data[7] = 0x04
    data[13] = 0x0F
    monkeypatch.setattr(vu_signature, "iter_vu_sections", lambda _data: iter([section]))
    monkeypatch.setattr(vu_signature, "parse_cvc", lambda _raw: {"car": "ca"})
    monkeypatch.setattr(vu_signature, "cvc_public_key",
                        lambda _cvc: (object(), object()))
    monkeypatch.setattr(vu_signature, "cvc_temporal_status", lambda *_args: {})
    monkeypatch.setattr(vu_signature, "verify_cvc_chain_link", lambda *_args: True)
    monkeypatch.setattr(vu_signature, "_verify_ecdsa", lambda *_args: True)

    clean = vu_signature.verify_vu_download(bytes(data))
    dirty = vu_signature.verify_vu_download(bytes(data) + b"\x41" * 20)

    assert clean["all_treps_valid"] is True
    assert "unsigned_bytes" not in clean
    assert dirty["all_treps_valid"] is True
    assert dirty["unsigned_bytes"] == 20
    assert dirty["unsigned_ranges"] == [[89, 109]]
