"""Batch 15 LOW / TRUST — CRYPTO-ROOT-MESSAGE (E-F6).

The VU-download summary mislabelled *every* unanchored root as
``root not anchored (ERCA-2 key absent)`` — even when a root key **was** supplied
and anchoring was merely attempted and failed. That points the operator at the
wrong cause ("key missing" vs "anchor failed"). The wording now distinguishes an
absent key from a failed anchor (mirroring ``_validate_g2_cvc_chain``'s
"no ERCA root" vs "ERCA anchor FAILED"), while a genuinely anchored chain still
reads ``root-anchored``.

Normative source: Reg. EU 2016/799 Annex 1C, Appendix 11 (download signatures) —
the ERCA-2 root anchor is separate from the MSCA→VU chain link.

A real synthetic CVC chain is used (nothing in the verifier is mocked); the
pre-fix mislabel was reproduced by ``.scratch/check_root_message.py``.
"""
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from core.crypto.vu_signature import verify_vu_download
from tests.unit.card_crypto import cvc


def _record(record_type, payload):
    return struct.pack(">BHH", record_type, len(payload), 1) + payload


def _raw_sig(private_key, message):
    der = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _download(msca_priv, vu_priv, msca_car=b"\x11" * 8):
    """A minimal VU download: Overview carrying the MSCA/VU certs, one signed
    data record, and a final SignatureRecord that covers it."""
    msca_cvc = cvc(msca_priv, msca_priv, msca_car, b"\x01" * 8)
    vu_cvc = cvc(vu_priv, msca_priv, b"\x22" * 8, b"\x02" * 8)
    data_record = _record(0x02, b"DOWNLOAD-DATA-RECORD-0123456789")
    sig_record = _record(0x08, _raw_sig(vu_priv, data_record))
    return (b"\x76\x21" + _record(0x04, msca_cvc) + _record(0x0F, vu_cvc)
            + data_record + sig_record)


def test_no_key_supplied_reports_key_absent():
    msca = ec.generate_private_key(ec.SECP256R1())
    vu = ec.generate_private_key(ec.SECP256R1())
    report = verify_vu_download(_download(msca, vu))
    assert report["root_anchored"] is False
    assert "(ERCA-2 key absent)" in report["summary"]
    assert "anchor failed" not in report["summary"]


def test_supplied_key_that_does_not_anchor_reports_anchor_failed():
    msca = ec.generate_private_key(ec.SECP256R1())
    vu = ec.generate_private_key(ec.SECP256R1())
    # A real root key that simply does not sign this MSCA.
    unrelated = ec.generate_private_key(ec.SECP256R1()).public_key()
    report = verify_vu_download(
        _download(msca, vu),
        erca_keys={"deadbeefdeadbeef": (unrelated, hashes.SHA256)},
    )
    assert report["root_anchored"] is False
    assert "(ERCA-2 anchor failed)" in report["summary"]
    # The precise point of the fix: a supplied key is never called "absent".
    assert "key absent" not in report["summary"]


def test_matching_root_key_still_reads_root_anchored():
    msca = ec.generate_private_key(ec.SECP256R1())
    vu = ec.generate_private_key(ec.SECP256R1())
    car = b"\x11" * 8
    report = verify_vu_download(
        _download(msca, vu, msca_car=car),
        erca_keys={car: (msca.public_key(), hashes.SHA256)},
    )
    assert report["root_anchored"] is True
    assert "root-anchored" in report["summary"]
    assert "not anchored" not in report["summary"]


def test_supplied_key_without_msca_does_not_claim_anchor_failed():
    # A root key is supplied but the Overview carries no MSCA (0x04) certificate
    # to anchor: the anchor was never attempted, so it cannot have "failed".
    msca = ec.generate_private_key(ec.SECP256R1())
    vu = ec.generate_private_key(ec.SECP256R1())
    vu_cvc = cvc(vu, msca, b"\x22" * 8, b"\x02" * 8)
    data_record = _record(0x02, b"DOWNLOAD-DATA-RECORD-0123456789")
    sig_record = _record(0x08, _raw_sig(vu, data_record))
    data = b"\x76\x21" + _record(0x0F, vu_cvc) + data_record + sig_record

    unrelated = ec.generate_private_key(ec.SECP256R1()).public_key()
    report = verify_vu_download(
        data, erca_keys={"deadbeefdeadbeef": (unrelated, hashes.SHA256)}
    )
    assert report["root_anchored"] is False
    assert "anchor failed" not in report["summary"]
    assert "key absent" not in report["summary"]
