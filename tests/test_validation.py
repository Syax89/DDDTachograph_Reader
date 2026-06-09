import unittest
import os
import sys
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# Add parent dir to path to import signature_validator
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from signature_validator import SignatureValidator
from tests.generate_mock_data import setup_mock_certs

class TestSignatureValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = os.path.dirname(__file__)
        cls.project_dir = os.path.abspath(os.path.join(cls.test_dir, '..'))
        cls.mock_data = setup_mock_certs(cls.test_dir)
        cls.validator = SignatureValidator(certs_dir=os.path.join(cls.test_dir, "certs"))

    def test_erca_loading(self):
        """Test if ERCA certificates are loaded correctly."""
        self.assertGreater(len(self.validator.root_certificates), 0)
        erca_name = self.mock_data['erca_cert'].subject.rfc4514_string()
        self.assertIn(erca_name, self.validator.root_certificates)

    def test_certificate_chain_verification(self):
        """Test valid and invalid certificate chains."""
        # Valid: Card signed by MSCA
        self.assertTrue(self.validator.verify_certificate_chain(
            self.mock_data['card_cert'], self.mock_data['msca_cert']))
        
        # Valid: MSCA signed by ERCA
        self.assertTrue(self.validator.verify_certificate_chain(
            self.mock_data['msca_cert'], self.mock_data['erca_cert']))
        
        # Invalid: Card NOT signed by ERCA (skipping MSCA)
        self.assertFalse(self.validator.verify_certificate_chain(
            self.mock_data['card_cert'], self.mock_data['erca_cert']))

    def test_full_tacho_chain_validation(self):
        """Test the validate_tacho_chain method with mock DER data."""
        card_der = self.mock_data['card_cert'].public_bytes(serialization.Encoding.DER)
        msca_der = self.mock_data['msca_cert'].public_bytes(serialization.Encoding.DER)
        
        is_valid, pub_key = self.validator.validate_tacho_chain(card_der, msca_der)
        self.assertTrue(is_valid)
        self.assertIsNotNone(pub_key)

    def test_tampered_data_validation(self):
        """Test if tampering with data is detected."""
        data = b"Original Tacho Data"
        signature = self.mock_data['card_key'].sign(
            data,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        pub_key = self.mock_data['card_cert'].public_key()
        
        # Original data should be valid
        self.assertTrue(self.validator.validate_block(data, signature, pub_key))
        
        # Tampered data should be invalid
        tampered_data = b"Tampered Tacho Data"
        self.assertFalse(self.validator.validate_block(tampered_data, signature, pub_key))

    def test_missing_signature(self):
        """Test behavior when signature is missing or empty."""
        data = b"Some data"
        pub_key = self.mock_data['card_cert'].public_key()
        self.assertFalse(self.validator.validate_block(data, b"", pub_key))

    def test_g2_ecdsa_validation(self):
        """Test G2 (ECDSA) signature validation."""
        data = b"G2 Tacho Data"
        from cryptography.hazmat.primitives.asymmetric import ec
        signature = self.mock_data['ecdsa_card_key'].sign(
            data,
            ec.ECDSA(hashes.SHA256())
        )

        pub_key = self.mock_data['ecdsa_card_cert'].public_key()
        self.assertTrue(self.validator.validate_block(data, signature, pub_key, algorithm='ECDSA'))

    def test_expired_certificate(self):
        """Expired certificates must fail chain verification (expiration enforced)."""
        import datetime
        card_cert = self.mock_data['expired_card_cert']
        msca_cert = self.mock_data['msca_cert']

        # Sanity: the fixture is actually expired.
        now = datetime.datetime.now(datetime.timezone.utc)
        not_after = getattr(card_cert, "not_valid_after_utc", None) \
            or card_cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        self.assertTrue(not_after < now, "fixture should be expired")

        # With expiry enforced (default), verification must fail on dates.
        self.assertFalse(
            self.validator.verify_certificate_chain(card_cert, msca_cert),
            "Expired certificate must not pass chain verification",
        )

        # With the date check disabled, expiration alone no longer rejects it
        # (only the cryptographic signature is evaluated). Just exercise the path.
        self.validator.verify_certificate_chain(card_cert, msca_cert, check_expiry=False)

if __name__ == '__main__':
    unittest.main()
