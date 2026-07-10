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
