"""Suite-wide fixtures.

The load trace keeps an in-memory ring and a stall watchdog in *every* session (that is
what makes the ``~/ddd-reader-stall-report.txt`` report work on a user's machine without
an env var). A slow test — or a debugger breakpoint — is not a user-facing stall, so the
report file is switched off for the whole suite: nothing may ever be written to the real
home directory by a test run. ``tests/unit/test_stall_report.py`` turns it back on for the
tests that check the report itself, always against a temporary ``HOME``.
"""
import pytest


def pytest_configure(config):
    """Generate the synthetic mock downloads before collection, as CI does.

    About a hundred tests read ``tests/mock_data/*.ddd`` and skip at collection
    time when it is missing; CI runs ``generate_mock_ddd.py`` first, a plain
    ``pytest tests/`` did not, so the two ran different suites. The mocks are
    synthetic (no personal data), git-ignored and only written when absent.
    Set ``TACHO_NO_MOCK_GENERATION=1`` to keep the old skip behaviour.
    """
    import os
    if os.environ.get("TACHO_NO_MOCK_GENERATION") == "1":
        return
    from tests.integration.generate_mock_ddd import generate_all
    generate_all(only_missing=True, verbose=False)


@pytest.fixture(autouse=True)
def no_stall_report(monkeypatch):
    """Never let a slow test write ~/ddd-reader-stall-report.txt."""
    from core.utils import load_trace
    monkeypatch.setattr(load_trace, "STALL_REPORT", False)
