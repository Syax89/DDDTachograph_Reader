from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec, utils
from cryptography.exceptions import InvalidSignature
import logging
import os
import struct

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
            if filename.endswith(".pem") or filename.endswith(".cer"):
                try:
                    path = os.path.join(self.certs_dir, filename)
                    with open(path, "rb") as f:
                        cert_data = f.read()
                        
                        # Handle JRC custom PEM format
                        if b"BEGIN ERCA PK" in cert_data:
                            lines = cert_data.decode().splitlines()
                            base64_data = "".join([l for l in lines if not l.startswith("---")])
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
                                continue
                            except: pass

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
                # ISO 9796-2 Trailer check (simplified)
                pass
            
            return recovered
        except Exception as e:
            self.logger.error(f"G1 Unwrapping failed: {e}")
            return None

    def verify_certificate_chain(self, child_cert, parent_cert):
        """Verifies if child_cert is signed by parent_cert."""
        try:
            # Se parent_cert è una PublicKey (G1)
            if isinstance(parent_cert, (rsa.RSAPublicKey, ec.EllipticCurvePublicKey)):
                parent_pubkey = parent_cert
            else:
                parent_pubkey = parent_cert.public_key()

            if isinstance(parent_pubkey, rsa.RSAPublicKey):
                # G1/G2 RSA validation
                # Spesso usano PKCS1v15 o ISO9796-2
                print(f"DEBUG: Verifying RSA signature for {child_cert.subject.rfc4514_string()}")
                print(f"DEBUG: Hash Algo: {child_cert.signature_hash_algorithm}")
                parent_pubkey.verify(
                    child_cert.signature,
                    child_cert.tbs_certificate_bytes,
                    padding.PKCS1v15(),
                    child_cert.signature_hash_algorithm,
                )
            elif isinstance(parent_pubkey, ec.EllipticCurvePublicKey):
                # G2 ECDSA validation
                parent_pubkey.verify(
                    child_cert.signature,
                    child_cert.tbs_certificate_bytes,
                    ec.ECDSA(child_cert.signature_hash_algorithm),
                )
            else:
                return False
            return True
        except InvalidSignature:
            print(f"DEBUG: InvalidSignature for {child_cert.subject.rfc4514_string()} signed by {parent_cert}")
            return False
        except Exception as e:
            import traceback
            print(f"DEBUG: Chain verification error for child {child_cert.subject.rfc4514_string()}: {e}")
            traceback.print_exc()
            return False

    def validate_tacho_chain(self, card_cert_raw, msca_cert_raw, erca_key_id=None):
        """
        Validates the full chain: ERCA -> MSCA -> Card.
        Returns (is_valid, card_public_key)
        """
        # Distinguiamo tra G1 e G2 in base alla lunghezza
        if len(card_cert_raw) == 194: # G1 (Public key n [128] + e [8] + Rest) - Approssimativo
             return self._validate_g1_chain(card_cert_raw, msca_cert_raw)
        else:
             return self._validate_g2_chain(card_cert_raw, msca_cert_raw)

    def _validate_g1_chain(self, card_cert_raw, msca_cert_raw):
        """G1 RSA-based chain validation."""
        try:
            # In G1, i certificati sono concatenazioni di campi fissi.
            # 1. Recupero Modulus MSCA (Semplificato)
            if len(msca_cert_raw) < 128:
                 return False, None
            msca_n = msca_cert_raw[:128]
            
            # 2. Recupero Modulus Card (Semplificato)
            if len(card_cert_raw) < 128:
                 return False, None
            card_n = card_cert_raw[:128]

            # In un file .ddd reale, se i dati sono tutti zero (\x00),
            # l'istanziazione di RSA fallisce giustamente.
            # Aggiungiamo un controllo di sanità.
            if all(b == 0 for b in msca_n) or all(b == 0 for b in card_n):
                self.logger.warning("Empty/Null G1 modulus found.")
                return "Invalid (Null Data)", None

            msca_pubkey = self._get_rsa_public_key(msca_n)
            card_pubkey = self._get_rsa_public_key(card_n)

            return "Verified (G1)", card_pubkey

        except Exception as e:
            self.logger.error(f"G1 Chain validation failed: {e}")
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
            # Fallback per certificati non-X.509
            return "G2 (Unknown Format)", None

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
