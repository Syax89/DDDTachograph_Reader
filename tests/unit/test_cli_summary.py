"""Regression tests for app.cli.print_summary integrity reporting.

print_summary must report integrity from the canonical metadata.integrity_check
field (set by app/engine.py from validation_status) rather than from the
signature_verification dict, whose shape differs per file type (VU files have
no status/overall keys; driver-card files have an empty dict).
"""

from app.cli import print_summary


def test_summary_vu_shaped_result_uses_metadata_integrity(capsys):
    """VU-shaped signature_verification (no status/overall) must not print N/D."""
    data = {
        "signature_verification": {
            "available": True,
            "treps": ["t1", "t2"],
            "msca_to_vu": True,
        },
        "metadata": {"integrity_check": "Verified (G1 VU chain and TREP signatures)"},
    }
    print_summary(data)
    out = capsys.readouterr().out
    assert "🔐 Integrity: Verified (G1 VU chain and TREP signatures)" in out


def test_summary_driver_shaped_result_prints_integrity(capsys):
    """Driver-card-shaped empty signature_verification must still print integrity."""
    data = {
        "signature_verification": {},
        "metadata": {"integrity_check": "Verified"},
    }
    print_summary(data)
    out = capsys.readouterr().out
    assert "🔐 Integrity: Verified" in out


def test_summary_missing_metadata_integrity_defaults_to_nd(capsys):
    """Missing metadata.integrity_check must fall back to N/D."""
    data = {"metadata": {}}
    print_summary(data)
    out = capsys.readouterr().out
    assert "🔐 Integrity: N/D" in out
