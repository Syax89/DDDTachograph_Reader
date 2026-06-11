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
            self.logger.warning(
                "ERCA certificates directory '%s' does not exist and has been created. "
                "Without ERCA root certificates all chain validations will report "
                "'Cannot Verify (Missing ERCA Root)'. Place root certificates "
                "(.pem / .cer / .bin) in this directory.", self.certs_dir)
            with open(os.path.join(self.certs_dir, "README.txt"), "w") as f:
                f.write(
                    "Place European Root Certificates (ERCA) here.\n\n"
                    "G1 (Annex 1B, RSA): EC_PK.bin / EC_PK.pem "
                    "(raw KID(8) + n(128) + e(8)).\n"
                    "G2 (Annex 1C, ECDSA): raw uncompressed EC point (.bin), "
                    "DER/PEM SubjectPublicKeyInfo, or CVC root certificate.\n\n"
                    "Published by the EU JRC: https://dtc.jrc.ec.europa.eu/\n")

    def _load_root_certificates(self):
        """Loads ERCA certificates from the certs directory."""
        if not os.path.exists(self.certs_dir):
            return
        for filename in os.listdir(self.certs_dir):
            if not os.path.isfile(os.path.join(self.certs_dir, filename)):
                continue
            if filename.endswith(".bin"):
                # Raw ERCA PK material:
                #   G1 RSA: KID(8) + n(128) + e(8) = 144, or n(128) + e(8) = 136
                #   G2 EC:  uncompressed point = 65 (256-bit), 97 (384),
                #           129 (brainpoolP512r1), 133 (NIST P-521)
                #   CVC:   0x7F21 container (variable length, ≥ 100 bytes)
                try:
                    with open(os.path.join(self.certs_dir, filename), "rb") as f:
                        raw = f.read()
                    if len(raw) in (65, 97, 129, 133, 136, 144) or (
                        len(raw) >= 100 and raw[0] == 0x7F):
                        self.root_certificates[f"ERCA_RAW_{filename}"] = raw
                        self.logger.info("Loaded raw ERCA PK material (%d bytes) from %s",
                                       len(raw), filename)
                except OSError as exc:
                    self.logger.debug("Could not read %s: %s", filename, exc)
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

                        # Handle CVC certificate in PEM wrapping
                        # ("-----BEGIN CERTIFICATE-----" with CVC base64 content).
                        if b"BEGIN CERTIFICATE" in cert_data:
                            import base64
                            lines = cert_data.decode().splitlines()
                            b64 = "".join(
                                line for line in lines
                                if not line.startswith("---"))
                            try:
                                raw = base64.b64decode(b64)
                            except Exception:
                                raw = None
                            if raw and len(raw) >= 100 and raw[0] == 0x7F:
                                self.root_certificates[f"ERCA_CVC_{filename}"] = raw
                                self.logger.info(
                                    "Loaded CVC ERCA certificate (%d bytes) from %s",
                                    len(raw), filename)
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

            # ISO 9796-2 recovered block (Annex 1B Appendix 11):
            # 0x6A || C'[0:106] || SHA1(C')(20 bytes) || 0xBC
            # (the remaining 58 bytes of C' travel in clear after the signature)

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

    def _g1_erca_key(self):
        """Return the G1 ERCA root RSA public key from the loaded root material.

        Accepts either an already-parsed RSAPublicKey, or raw JRC EC_PK bytes:
        KID(8) + n(128) + e(8) = 144 bytes, or n(128) + e(8) = 136 bytes.
        """
        for material in self.root_certificates.values():
            if isinstance(material, rsa.RSAPublicKey):
                return material
            if not isinstance(material, (bytes, bytearray)):
                continue
            if len(material) == 144:
                n = int.from_bytes(material[8:136], 'big')
                e = int.from_bytes(material[136:144], 'big')
            elif len(material) == 136:
                n = int.from_bytes(material[0:128], 'big')
                e = int.from_bytes(material[128:136], 'big')
            else:
                continue
            try:
                return rsa.RSAPublicNumbers(e, n).public_key()
            except ValueError as exc:
                self.logger.debug("Invalid raw ERCA PK material: %s", exc)
        return None

    def _g2_erca_keys(self):
        """Return a dict of CAR→(ECPublicKey, hash) for every G2 ERCA-2
        root key found in the loaded root material.

        Accepts:
          - An ``EllipticCurvePublicKey`` already parsed (e.g. from a
            DER/PEM SubjectPublicKeyInfo).
          - A CVC certificate (0x7F21) — the CAR is read from the cert.
          - Raw bytes that look like an uncompressed EC point: 65 bytes
            (brainpool/NIST 256), 97 (384), 129 (brainpoolP512r1),
            133 (NIST P-521).

        For parsed keys and raw points the real CAR (the JRC-published KID)
        is unknown, so a synthetic key is used: anchoring then relies on the
        try-all fallback in :func:`core.vu_signature_verifier.verify_vu_download`.
        """
        import hashlib

        def _hash_for(key_size):
            return {256: hashes.SHA256, 384: hashes.SHA384,
                    512: hashes.SHA512, 521: hashes.SHA512}.get(key_size, hashes.SHA256)

        # Candidate curves per uncompressed-point length (Annex 1C Part B
        # allows both brainpool and NIST curves; 65/97 bytes are ambiguous).
        point_curves = {
            65: (ec.BrainpoolP256R1(), ec.SECP256R1()),
            97: (ec.BrainpoolP384R1(), ec.SECP384R1()),
            129: (ec.BrainpoolP512R1(),),
            133: (ec.SECP521R1(),),
        }

        result = {}
        for material in self.root_certificates.values():
            if isinstance(material, ec.EllipticCurvePublicKey):
                encoded = material.public_bytes(
                    serialization.Encoding.X962,
                    serialization.PublicFormat.UncompressedPoint)
                car = hashlib.sha256(encoded).hexdigest()[:16]
                result[car] = (material, _hash_for(material.curve.key_size))
                self.logger.info("Registered G2 ERCA-2 key (synthetic CAR=%s)", car)
                continue
            if isinstance(material, (bytes, bytearray)):
                if material[0] == 0x7F and len(material) >= 100:
                    # CVC certificate — parse it to extract the public key.
                    from core.vu_signature_verifier import parse_cvc, cvc_public_key
                    try:
                        cvc = parse_cvc(bytes(material))
                        if cvc and cvc.get("public_point"):
                            pub, hash_algo = cvc_public_key(cvc)
                            car = cvc.get("car", "")
                            if pub is not None and car:
                                result[car] = (pub, hash_algo)
                                self.logger.info("Registered G2 ERCA-2 CVC key (CAR=%s, curve=%s)",
                                               car, pub.curve.name)
                    except Exception as exc:
                        self.logger.debug("CVC ERCA key parse failed: %s", exc)
                    continue
                for curve in point_curves.get(len(material), ()):
                    try:
                        pub = ec.EllipticCurvePublicKey.from_encoded_point(curve, bytes(material))
                    except (ValueError, TypeError):
                        continue  # point not on this candidate curve
                    car = hashlib.sha256(bytes(material)).hexdigest()[:16]
                    result[f"{car}:{curve.name}"] = (pub, _hash_for(curve.key_size))
                    self.logger.info("Registered G2 ERCA-2 raw key (synthetic CAR=%s, curve=%s)",
                                   car, curve.name)
        return result

    def _g1_recover_key(self, cert_raw, parent_pubkey):
        """Unwrap a 194-byte G1 certificate (Annex 1B Appendix 11) with the parent
        RSA key and rebuild the certified key.

        Layout: signature Sn(128) + remainder Cn'(58) + CAR(8).
        Recovered Sn = 0x6A || C'[0:106] || SHA1(C')(20) || 0xBC, where the full
        content C' (164 bytes) = CPI(1) CAR(8) CHA(7) EOV(4) CHR(8) n(128) e(8);
        the last 58 bytes of C' travel in clear as the remainder.

        Returns (public_key, content) on success, (None, None) on failure.
        """
        import hashlib
        if len(cert_raw) < 186:
            return None, None
        sig, remainder = cert_raw[:128], cert_raw[128:186]
        recovered = self.unwrap_g1_certificate(sig, parent_pubkey)
        if recovered is None:
            return None, None
        content = recovered[1:107] + remainder
        digest = recovered[107:127]
        if hashlib.sha1(content).digest() != digest:
            self.logger.warning("G1 ISO 9796-2 SHA-1 digest mismatch")
            return None, None
        n = int.from_bytes(content[28:156], 'big')
        e = int.from_bytes(content[156:164], 'big')
        try:
            return rsa.RSAPublicNumbers(e, n).public_key(), content
        except ValueError as exc:
            self.logger.warning("G1 certified key is invalid: %s", exc)
            return None, None

    def _validate_g1_chain(self, card_cert_raw, msca_cert_raw):
        """G1 RSA-based chain validation (Annex 1B, Appendix 11).

        Full chain: the MSCA certificate is unwrapped with the ERCA root key,
        then the card certificate with the recovered MSCA key. Each unwrap
        checks the ISO 9796-2 trailer (0x6A … 0xBC) and the SHA-1 digest of the
        certificate content. Without the ERCA root key nothing can be verified
        (the MSCA public modulus only exists inside its ERCA-signed envelope).
        """
        try:
            erca_pub = self._g1_erca_key()
            if erca_pub is None:
                self.logger.warning("G1 ERCA root key not available — chain cannot be verified")
                return "Cannot Verify (Missing ERCA Root)", None

            msca_pub, _ = self._g1_recover_key(msca_cert_raw, erca_pub)
            if msca_pub is None:
                self.logger.warning("G1 MSCA certificate unwrap FAILED under ERCA root")
                return False, None

            card_pub, _ = self._g1_recover_key(card_cert_raw, msca_pub)
            if card_pub is None:
                self.logger.warning("G1 card certificate unwrap FAILED under MSCA key")
                return False, None

            self.logger.info("G1 certificate chain VERIFIED (ERCA→MSCA→card, ISO 9796-2 + SHA-1)")
            return True, card_pub

        except Exception as e:
            self.logger.error("G1 Chain validation failed: %s", e)
            return False, None

    def _validate_g2_chain(self, card_cert_raw, msca_cert_raw):
        """G2 ECDSA-based chain validation (X.509 DER or CVC).

        When the certificates are CVC-encoded (starting with ``0x7F``), the
        MSCA→Card link is verified via :func:`core.vu_signature_verifier.verify_cvc_chain_link`.
        Without a G2 ERCA root key the ERCA→MSCA link cannot be anchored, so
        the chain is reported as *partial* rather than full.
        """
        # CVC path (0x7F21 containers — ISO 7816-8).
        if card_cert_raw[0] == 0x7F and msca_cert_raw[0] == 0x7F:
            return self._validate_g2_cvc_chain(card_cert_raw, msca_cert_raw)

        # Standard X.509 DER path.
        try:
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

    def _validate_g2_cvc_chain(self, card_cert_raw, msca_cert_raw):
        """Validate a G2 CVC certificate chain (MSCA→Card link).

        Returns ``(status, ec_public_key)``.  *status* is one of:
          ``"Partial — MSCA→Card verified (no ERCA root)"``,
          ``"Partial — MSCA→Card FAILED"``, or ``False``.
        """
        from core.vu_signature_verifier import parse_cvc, cvc_public_key, verify_cvc_chain_link

        try:
            card_cvc = parse_cvc(card_cert_raw)
            msca_cvc = parse_cvc(msca_cert_raw)
        except Exception as exc:
            self.logger.warning("G2 CVC parse failed: %s", exc)
            return False, None

        if card_cvc is None or msca_cvc is None:
            self.logger.warning("G2 CVC: missing card or MSCA certificate")
            return False, None

        msca_pub, msca_hash = cvc_public_key(msca_cvc)
        card_pub, _ = cvc_public_key(card_cvc)

        if msca_pub is None or card_pub is None:
            self.logger.warning("G2 CVC: could not extract public keys")
            return False, None

        if not verify_cvc_chain_link(card_cvc, msca_pub, msca_hash):
            self.logger.warning("G2 CVC MSCA→Card link FAILED")
            return "Partial — MSCA→Card FAILED", None

        self.logger.info("G2 CVC MSCA→Card link VERIFIED")
        return "Partial — MSCA→Card verified (no ERCA root)", card_pub

    def validate_block(self, data, signature, public_key, algorithm='RSA'):
        """
        Validates a data block with its signature using the provided public key.
        """
        if algorithm == 'RSA':
            return self.verify_rsa_signature(public_key, signature, data)
        elif algorithm == 'ECDSA':
            return self.verify_ecdsa_signature(public_key, signature, data, hash_algo=hashes.SHA256())
        return False

    def verify_rsa_signature(self, public_key, signature, data, hash_algo=None):
        """Verifies RSA signature (Annex 1B/1C). Defaults to SHA-256."""
        hash_algo = hash_algo or hashes.SHA256()
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

    def verify_g1_data_signature(self, public_key, signature, data):
        """Verify a G1 Annex 1B EF data signature (ISO 9796-2 Scheme 1, SHA-1).

        The 128-byte RSA signature is decrypted with the card's public key
        and the recovered block must contain the SHA-1 hash of *data*.
        Falls back to RSA PKCS#1 v1.5 with SHA-1 if the ISO 9796-2
        trailer is not found.
        """
        import hashlib
        if not isinstance(public_key, rsa.RSAPublicKey):
            return False
        if len(signature) != 128:
            return False

        # Try ISO 9796-2 recovery (Annex 1B Appendix 11, same as cert chain).
        try:
            n = public_key.public_numbers().n
            e = public_key.public_numbers().e
            c = int.from_bytes(signature, 'big')
            m = pow(c, e, n)
            recovered = m.to_bytes(128, 'big')

            if recovered[0] == 0x6A and recovered[127] == 0xBC:
                data_hash = hashlib.sha1(data).digest()
                # The SHA-1 hash sits before the 0xBC trailer; the exact
                # offset depends on the ISO 9796-2 padding of the message.
                for off in range(1, 108):
                    if recovered[off:off + 20] == data_hash:
                        return True
        except Exception:
            pass

        # Fallback: PKCS#1 v1.5 with SHA-1.
        try:
            public_key.verify(signature, data, padding.PKCS1v15(), hashes.SHA1())
            return True
        except Exception:
            return False

    def verify_ecdsa_signature(self, public_key, signature, data, hash_algo=None):
        """Verifies ECDSA signature (Annex 1C). Defaults to SHA-256."""
        hash_algo = hash_algo or hashes.SHA256()
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
