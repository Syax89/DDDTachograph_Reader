"""One console line per crypto log event, and ``--quiet`` stays quiet.

``SignatureValidator`` used to install a private ``StreamHandler`` on its own
logger (level INFO). Every record was then written twice — once by that handler,
once by whatever handler the application configured on the root logger — and the
CLI's ``-q``/default WARNING verbosity could not silence the crypto lines at all,
because the private handler was pinned at INFO.

The validator writes through ``logging`` only: verbosity and destination belong
to the application that embeds it.
"""
import logging
import tempfile

import pytest

from core.crypto.signature import SignatureValidator
from tests.unit.card_crypto import g1_identity, write_g1_trust


@pytest.fixture
def root_store():
    """A trust store holding one readable root, so loading logs one event."""
    identity = g1_identity()
    with tempfile.TemporaryDirectory() as certs_dir:
        write_g1_trust(certs_dir, identity["erca_key"])
        yield certs_dir


@pytest.fixture(autouse=True)
def restore_logging():
    """Root and crypto logger are process-global: put both back after a test."""
    root = logging.getLogger()
    crypto = logging.getLogger("SignatureValidator")
    handlers, level = list(root.handlers), root.level
    crypto_handlers, crypto_level = list(crypto.handlers), crypto.level
    try:
        yield
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        crypto.handlers[:] = crypto_handlers
        crypto.setLevel(crypto_level)


def test_validator_installs_no_handler_of_its_own(root_store):
    validator = SignatureValidator(certs_dir=root_store)

    assert validator.logger.handlers == [], (
        "the validator must not own console output: the embedding application "
        "configures logging")


def test_each_crypto_event_is_written_once(root_store, capsys):
    logging.basicConfig(level=logging.INFO, force=True)

    SignatureValidator(certs_dir=root_store)

    lines = [line for line in capsys.readouterr().err.splitlines()
             if "ERCA" in line or "root" in line.lower()]
    assert len(lines) == 1, f"crypto log line written twice: {lines}"


def test_warning_verbosity_silences_crypto_informational_lines(root_store, capsys):
    """The CLI default (WARNING) and ``-q`` must not see INFO crypto lines."""
    logging.basicConfig(level=logging.WARNING, force=True)

    validator = SignatureValidator(certs_dir=root_store)
    # A warning is still reported at this verbosity: only INFO is filtered.
    validator.validate_tacho_chain(None, None)

    captured = capsys.readouterr().err
    assert "Loaded raw ERCA PK material" not in captured
    assert "missing a card or MSCA certificate" in captured
