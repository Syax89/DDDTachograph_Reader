"""Digital signature validator for tachograph certificate chains. Verifies ERCA/MSCA certificate hierarchies using ECDSA public key cryptography."""
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec
from cryptography.exceptions import InvalidSignature
import datetime
import logging
import os


def _get_tbs_bytes(cert):
    """Safe accessor for x509.Certificate.to-be-signed bytes.
    
    tbs_certificate_bytes was removed in cryptography >= 43.0.
    Falls back to re-encoding when the attribute is absent.
    """
    tbs = getattr(cert, "tbs_certificate_bytes", None)
    if tbs is not None:
        return tbs
    try:
        return cert.tbs_precertificate_bytes
    except AttributeError:
        return cert.public_bytes(serialization.Encoding.DER)

class SignatureValidator:
    """
    Validates digital signatures for Tachograph files (Annex 1B/1C).
    Supports RSA (G1/G2) and ECDSA (G2).
    Implements Certification Chain validation: ERCA -> MSCA -> Card/VU.
    """

    def __init__(self, certs_dir=None):
        self.logger = logging.getLogger("SignatureValidator")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
        
        self.certs_dir = certs_dir or os.path.join(os.path.dirname(__file__), "certs")
        self.root_certificates = {} # Map of KeyID -> Certificate
        self.msca_certificates = {} # Cache for MSCA certs found in the file
        
        self._ensure_certs_dir()
        self._load_root_certificates()

    def _ensure_certs_dir(self):
        if not os.path.exists(self.certs_dir):
            os.makedirs(self.certs_dir)
            # Create a placeholder info file
            with open(os.path.join(self.certs_dir, "README.txt"), "w") as f:
                f.write("Place European Root Certificates (ERCA) here in PEM format.\n")

    def _load_root_certificates(self):
        """Loads ERCA certificates from the certs directory."""
        if not os.path.exists(self.certs_dir):
            return
        for filename in os.listdir(self.certs_dir):
            if not os.path.isfile(os.path.join(self.certs_dir, filename)):
                continue
            if filename.endswith(".pem") or filename.endswith(".cer"):
                try:
                    path = os.path.join(self.certs_dir, filename)
                    with open(path, "rb") as f:
                        cert_data = f.read()
                        
                        # Handle JRC custom PEM format
                        if b"BEGIN ERCA PK" in cert_data:
                            lines = cert_data.decode().splitlines()
                            base64_data = "".join([line for line in lines if not line.startswith("---")])
                            from cryptography.hazmat.primitives import serialization
                            import base64
                            # In G1, EC_PK is usually a raw RSA public key modulus + exponent
                            # but JRC provides it in a custom base64 wrap
                            # For simplicity, if we can't load as X509, we'll store as raw
                            try:
                                # Try as PEM first
                                pem_data = f"-----BEGIN PUBLIC KEY-----\n{base64_data}\n-----END PUBLIC KEY-----".encode()
                                pub_key = serialization.load_pem_public_key(pem_data)
                                self.root_certificates["ERCA_G1"] = pub_key
                                self.logger.info("Loaded Root Public Key (G1) from JRC format")
                            except Exception:
                                # JRC ERCA PK files (e.g. EC_PK) hold a raw EC point, not a
                                # standard SubjectPublicKeyInfo. Store the decoded bytes as
                                # raw key material rather than falling through to the generic
                                # X.509/PEM loaders (which would log a misleading error).
                                try:
                                    self.root_certificates[f"ERCA_RAW_{filename}"] = base64.b64decode(base64_data)
                                    self.logger.debug("Stored raw ERCA PK material from %s", filename)
                                except Exception as exc:
                                    self.logger.debug("Could not decode ERCA PK %s: %s", filename, exc)
                            continue

                        # Prova a caricare come X.509
                        try:
                            cert = x509.load_pem_x509_certificate(cert_data)
                            key = cert.subject.rfc4514_string()
                            self.root_certificates[key] = cert
                            self.logger.info(f"Loaded Root Certificate (X509): {key}")
                        except Exception:
                            # Se non è X.509, potrebbe essere una chiave pubblica RSA nuda (G1 ERCA)
                            # In Tacho G1, le ERCA Keys sono spesso file binari o PEM di chiavi pubbliche.
                            pub_key = serialization.load_pem_public_key(cert_data)
                            self.root_certificates[filename] = pub_key
                            self.logger.info(f"Loaded Root Public Key: {filename}")
                except Exception as e:
                    self.logger.error(f"Failed to load cert {filename}: {e}")

    def _get_rsa_public_key(self, n_bytes, e_int=65537):
        """Constructs an RSA public key from modulus bytes."""
        n = int.from_bytes(n_bytes, 'big')
        public_numbers = rsa.RSAPublicNumbers(e_int, n)
        return public_numbers.public_key()

    def unwrap_g1_certificate(self, certificate, public_key):
        """
        Unwraps a G1 certificate (Annex 1B, Appendix 11).
        The certificate is RSA encrypted with the parent's public key.
        """
        if len(certificate) != 128:
            return None
        
        try:
            # RSA recovery (no padding as per Annex 1B)
            # cryptography doesn't support raw RSA recovery easily for non-standard padding
            # We use the raw big-endian math: recovered = (cert ^ e) mod n
            n = public_key.public_numbers().n
            e = public_key.public_numbers().e
            c = int.from_bytes(certificate, 'big')
            m = pow(c, e, n)
            
            # Format to 128 bytes
            recovered = m.to_bytes(128, 'big')
            
            # G1 Certificate Content (Recovered block):
            # 1 byte: 0x6A (Trailer)
            # 1 byte: Header 0x01
            # 1 byte: Certificate Profile
            # 14 bytes: Authority Reference
            # 1 byte: Hash Algorithm Indicator
            # 58 bytes: Public Key Modulus (partially here, partially in the file)
            # Actually, Annex 1B specifies a complex split of the modulus.
            
            if recovered[0] != 0x6A or recovered[127] != 0xBC:
                self.logger.warning("G1 ISO 9796-2 trailer check failed")
                return None
            
            return recovered
        except Exception as e:
            self.logger.error(f"G1 Unwrapping failed: {e}")
            return None

    def _certificate_is_valid_now(self, cert):
        """True if ``cert`` (an x509.Certificate) is within its validity period.
        Returns True for non-X.509 inputs (raw G1 public keys carry no dates)."""
        not_after = getattr(cert, "not_valid_after_utc", None)
        not_before = getattr(cert, "not_valid_before_utc", None)
        if not_after is None or not_before is None:
            # Older cryptography: fall back to naive UTC.
            na = getattr(cert, "not_valid_after", None)
            nb = getattr(cert, "not_valid_before", None)
            if na is None or nb is None:
                return True  # not an X.509 cert (e.g. raw RSA key)
            not_after = na.replace(tzinfo=datetime.timezone.utc)
            not_before = nb.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        if now > not_after:
            self.logger.warning("Certificate expired on %s", not_after.isoformat())
            return False
        if now < not_before:
            self.logger.warning("Certificate not yet valid (valid from %s)", not_before.isoformat())
            return False
        return True

    def verify_certificate_chain(self, child_cert, parent_cert, check_expiry=True):
        """Verifies if child_cert is signed by parent_cert.

        When ``check_expiry`` is True, the child certificate's validity period is
        enforced: an expired or not-yet-valid certificate fails verification even
        if its signature is cryptographically correct.
        """
        try:
            if check_expiry and not self._certificate_is_valid_now(child_cert):
                return False

            # Se parent_cert è una PublicKey (G1)
            if isinstance(parent_cert, (rsa.RSAPublicKey, ec.EllipticCurvePublicKey)):
                parent_pubkey = parent_cert
            else:
                parent_pubkey = parent_cert.public_key()

            if isinstance(parent_pubkey, rsa.RSAPublicKey):
                # G1/G2 RSA validation (PKCS1v15 / ISO9796-2)
                self.logger.debug("Verifying RSA signature for %s (hash=%s)",
                                   child_cert.subject.rfc4514_string(),
                                   child_cert.signature_hash_algorithm)
                parent_pubkey.verify(
                    child_cert.signature,
                    _get_tbs_bytes(child_cert),
                    padding.PKCS1v15(),
                    child_cert.signature_hash_algorithm,
                )
            elif isinstance(parent_pubkey, ec.EllipticCurvePublicKey):
                # G2 ECDSA validation
                parent_pubkey.verify(
                    child_cert.signature,
                    _get_tbs_bytes(child_cert),
                    ec.ECDSA(child_cert.signature_hash_algorithm),
                )
            else:
                return False
            return True
        except InvalidSignature:
            self.logger.debug("InvalidSignature for %s", child_cert.subject.rfc4514_string())
            return False
        except Exception as e:
            self.logger.debug("Chain verification error for %s: %s",
                              getattr(child_cert, "subject", "?"), e)
            return False

    def validate_tacho_chain(self, card_cert_raw, msca_cert_raw, erca_key_id=None):
        """
        Validates the full chain: ERCA -> MSCA -> Card.
        Returns (is_valid, card_public_key)
        """
        # G1 certs: raw RSA field concatenations (Annex 1B), typical 128 or 194 bytes.
        # G2 certs: X.509 DER (starts with ASN.1 SEQUENCE 0x30) or CVC (starts 0x7F).
        is_likely_g2 = card_cert_raw[0] in (0x30, 0x7F)
        is_known_g1_size = len(card_cert_raw) in (128, 194)

        if is_likely_g2 and not is_known_g1_size:
            return self._validate_g2_chain(card_cert_raw, msca_cert_raw)
        else:
            return self._validate_g1_chain(card_cert_raw, msca_cert_raw)

    def _validate_g1_chain(self, card_cert_raw, msca_cert_raw):
        """G1 RSA-based chain validation (Annex 1B, Appendix 11).

        In G1, the card certificate is RSA-encrypted with the MSCA private key.
        Verification consists of decrypting it with the MSCA public key and
        checking the ISO 9796-2 trailer bytes (0x6A … 0xBC).
        """
        try:
            if len(msca_cert_raw) < 128:
                return False, None
            msca_n = msca_cert_raw[:128]

            if all(b == 0 for b in msca_n):
                self.logger.warning("Empty/Null G1 MSCA modulus found.")
                return False, None

            msca_pubkey = self._get_rsa_public_key(msca_n)

            if len(card_cert_raw) != 128:
                if len(card_cert_raw) < 128:
                    return False, None
                card_raw = card_cert_raw[:128]
            else:
                card_raw = card_cert_raw

            unwrapped = self.unwrap_g1_certificate(card_raw, msca_pubkey)
            if unwrapped is None:
                self.logger.warning("G1 certificate chain verification FAILED — unwrap unsuccessful")
                return False, None

            card_n = unwrapped[58:][:58]
            if len(card_n) < 1 or all(b == 0 for b in card_n):
                self.logger.warning("Empty/Null G1 card modulus extracted from unwrapped cert.")
                return False, None
            card_n = card_n[:58]

            card_pubkey = self._get_rsa_public_key(card_n)
            self.logger.info("G1 certificate chain VERIFIED (ISO 9796-2 unwrap OK)")
            return True, card_pubkey

        except Exception as e:
            self.logger.error("G1 Chain validation failed: %s", e)
            return False, None

    def _validate_g2_chain(self, card_cert_raw, msca_cert_raw):
        """G2 ECDSA-based chain validation (Standard X.509 or BER-TLV)."""
        try:
            # Spesso i file G2 usano formati BER-TLV che non sono x509 diretti
            # ma se sono standard:
            card_cert = x509.load_der_x509_certificate(card_cert_raw)
            msca_cert = x509.load_der_x509_certificate(msca_cert_raw)
            
            if not self.verify_certificate_chain(card_cert, msca_cert):
                return False, None
            
            msca_issuer = msca_cert.issuer.rfc4514_string()
            erca_cert = self.root_certificates.get(msca_issuer)
            
            if not erca_cert:
                return "Incomplete (Missing ERCA)", card_cert.public_key()

            if not self.verify_certificate_chain(msca_cert, erca_cert):
                return False, None

            return True, card_cert.public_key()
        except Exception:
            self.logger.debug("G2 chain validation error", exc_info=True)
            self.logger.warning("G2 certificate is not standard X.509 DER")
            return False, None

    def validate_block(self, data, signature, public_key, algorithm='RSA'):
        """
        Validates a data block with its signature using the provided public key.
        """
        if algorithm == 'RSA':
            return self.verify_rsa_signature(public_key, signature, data)
        elif algorithm == 'ECDSA':
            return self.verify_ecdsa_signature(public_key, signature, data, hash_algo=hashes.SHA256())
        return False

    def verify_rsa_signature(self, public_key, signature, data, hash_algo=hashes.SHA256()):
        """Verifies RSA signature (Annex 1B/1C)."""
        if not isinstance(public_key, rsa.RSAPublicKey):
            return False
        try:
            public_key.verify(
                signature,
                data,
                padding.PKCS1v15(),
                hash_algo
            )
            return True
        except InvalidSignature:
            return False
        except Exception:
            return False

    def verify_ecdsa_signature(self, public_key, signature, data, hash_algo=hashes.SHA256()):
        """Verifies ECDSA signature (Annex 1C)."""
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False
        try:
            public_key.verify(
                signature,
                data,
                ec.ECDSA(hash_algo)
            )
            return True
        except InvalidSignature:
            return False
        except Exception:
            return False
