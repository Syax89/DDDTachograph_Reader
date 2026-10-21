"""Suite-wide fixtures.

The load trace keeps an in-memory ring and a stall watchdog in *every* session (that is
what makes the ``~/ddd-reader-stall-report.txt`` report work on a user's machine without
an env var). A slow test — or a debugger breakpoint — is not a user-facing stall, so the
report file is switched off for the whole suite: nothing may ever be written to the real
home directory by a test run. ``tests/unit/test_stall_report.py`` turns it back on for the
tests that check the report itself, always against a temporary ``HOME``.
"""
import pytest


@pytest.fixture(autouse=True)
def no_stall_report(monkeypatch):
    """Never let a slow test write ~/ddd-reader-stall-report.txt."""
    from core.utils import load_trace
    monkeypatch.setattr(load_trace, "STALL_REPORT", False)
