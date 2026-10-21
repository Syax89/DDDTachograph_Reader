"""The G1 certificate's End Of Validity is reported, not discarded.

``_validate_g1_chain`` recovers each generation-1 certificate content and then
threw it away, so the ``EOV`` (Annex 1B Appendix 11, ``content[16:20]``) never
reached the report: ``certificate_temporal_validity`` stayed ``{}`` while the G2
path shows the card/MSCA dates and status. A user had no way to see that a
card's certificate had run out.

Scope: this reports the date and the status at the download timestamp. Whether
an expired *generation-1* chain should fail closed like the G2 one is a policy
question left untouched here (see the commit note), so the verdict is unchanged.
"""
import datetime

from core.crypto.signature import SignatureValidator
from tests.unit.card_crypto import g1_identity, trust_store

_UTC = datetime.timezone.utc
_EXPIRED_EOV = int(datetime.datetime(2017, 7, 8, tzinfo=_UTC).timestamp())
_VALID_EOV = int(datetime.datetime(2033, 5, 18, tzinfo=_UTC).timestamp())


def _validator(identity):
    with trust_store(g1_erca_key=identity["erca_key"]) as certs_dir:
        return SignatureValidator(certs_dir=certs_dir)


def test_g1_certificate_end_of_validity_is_reported():
    identity = g1_identity(eov=_VALID_EOV)
    validator = _validator(identity)

    status, _key = validator.validate_tacho_chain(
        identity["card_cert"], identity["msca_cert"],
        verification_time=datetime.datetime(2026, 10, 21, tzinfo=_UTC))

    assert status is True
    temporal = validator.last_chain_temporal_validity
    assert temporal["card"]["status"] == "valid"
    assert temporal["card"]["valid_to"].startswith("2033-05-18")
    assert temporal["msca"]["valid_to"].startswith("2033-05-18")


def test_expired_g1_certificate_is_reported_as_expired():
    identity = g1_identity(eov=_EXPIRED_EOV)
    validator = _validator(identity)

    status, _key = validator.validate_tacho_chain(
        identity["card_cert"], identity["msca_cert"],
        verification_time=datetime.datetime(2026, 10, 21, tzinfo=_UTC))

    assert status is True, "the cryptographic chain is sound; only the date expired"
    temporal = validator.last_chain_temporal_validity
    assert temporal["card"]["status"] == "expired"
    assert temporal["card"]["valid_to"].startswith("2017-07-08")
    assert temporal["msca"]["status"] == "expired"


def test_g1_dates_are_unchecked_without_a_download_timestamp():
    """Same rule as G2: no timestamp means the report states the date, not a verdict."""
    identity = g1_identity(eov=_EXPIRED_EOV)
    validator = _validator(identity)

    validator.validate_tacho_chain(identity["card_cert"], identity["msca_cert"])

    assert validator.last_chain_temporal_validity["card"]["status"] == "not_checked"
    assert validator.last_chain_temporal_validity["card"]["valid_to"].startswith("2017-07-08")


def test_a_certificate_without_an_end_of_validity_reports_nothing():
    """Vehicle-unit certificates in the corpus state EOV 0xFFFFFFFF."""
    identity = g1_identity()
    validator = _validator(identity)

    assert validator._g1_certificate_temporal_status(b"\x01" * 16 + b"\xff" * 4 + b"\x00" * 8) is None
    assert validator._g1_certificate_temporal_status(None) is None
