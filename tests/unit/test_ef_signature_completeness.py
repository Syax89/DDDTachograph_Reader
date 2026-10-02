"""Regression tests for EF signature record completeness."""
from unittest.mock import Mock

from core.crypto.ef_signature import pair_ef_records, verify_ef_pairs


def test_missing_ef_signature_is_reported_as_incomplete():
    pairs = pair_ef_records([(0x0502, 0x00, b"data")], [])

    report = verify_ef_pairs(pairs, None, Mock(), "G1")

    assert report["failed"] == 1
    assert report["total"] == 1
    assert report["ef_results"][0]["status"] == "incomplete"
    assert report["ef_results"][0]["reason"] == "missing signature"


def test_duplicate_ef_data_is_not_silently_overwritten():
    pairs = pair_ef_records(
        [(0x0502, 0x00, b"first"), (0x0502, 0x00, b"second")],
        [(0x0502, 0x01, b"signature")],
    )

    report = verify_ef_pairs(pairs, None, Mock(), "G1")

    assert report["failed"] == 1
    assert report["ef_results"][0]["status"] == "incomplete"
    assert report["ef_results"][0]["reason"] == "duplicate data"


def test_certificate_and_icc_records_are_not_treated_as_signed_efs():
    pairs = pair_ef_records(
        [(0x0002, 0x00, b"icc"), (0xC100, 0x00, b"certificate")],
        [],
    )

    assert pairs == []


def test_card_download_ef_is_excluded_from_signature_verification():
    """D2-010 (Batch 2): Annex 1C §3.3 DDP_035 signs "the other application
    data EFs ... except EF Card_Download" -- 0x050E must never enter the
    report, or a correctly-unsigned EF reads as a failed signature."""
    pairs = pair_ef_records(
        [(0x0502, 0x00, b"data"), (0x050E, 0x00, b"\x00\x00\x00\x00")],
        [(0x0502, 0x01, b"signature")],
    )

    tags = {p["tag"] for p in pairs}
    assert 0x050E not in tags
    assert 0x0502 in tags
