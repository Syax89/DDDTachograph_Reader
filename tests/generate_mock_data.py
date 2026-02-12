from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.x509.oid import NameOID
import datetime
import os

def generate_rsa_pair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)

def generate_ecdsa_pair():
    return ec.generate_private_key(ec.SECP256R1())

def create_cert(subject_name, issuer_key, issuer_cert=None, subject_key=None, is_ca=False, expired=False):
    if subject_key is None:
        subject_key = generate_rsa_pair().public_key()
    
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EU"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Tacho QA"),
        x509.NameAttribute(NameOID.COMMON_NAME, subject_name),
    ])
    
    issuer = issuer_cert.subject if issuer_cert else subject
    
    if expired:
        not_before = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)
        not_after = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    else:
        not_before = datetime.datetime.now(datetime.timezone.utc)
        not_after = not_before + datetime.timedelta(days=365)
        
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        subject_key
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        not_before
    ).not_valid_after(
        not_after
    )
    
    if is_ca:
        cert = cert.add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        
    cert = cert.sign(issuer_key, hashes.SHA256())
    return cert

def setup_mock_certs(base_dir):
    certs_dir = os.path.join(base_dir, "certs")
    os.makedirs(certs_dir, exist_ok=True)
    
    # 1. ERCA (Root)
    erca_key = generate_rsa_pair()
    erca_cert = create_cert("ERCA-Root", erca_key, is_ca=True)
    
    with open(os.path.join(certs_dir, "erca_root.pem"), "wb") as f:
        f.write(erca_cert.public_bytes(serialization.Encoding.PEM))
        
    # 2. MSCA (Intermediate)
    msca_key = generate_rsa_pair()
    msca_cert = create_cert("MSCA-Italy", erca_key, erca_cert, msca_key.public_key(), is_ca=True)
    
    # 3. Card Cert (End Entity)
    card_key = generate_rsa_pair()
    card_cert = create_cert("Driver-Card-123", msca_key, msca_cert, card_key.public_key())
    
    # 4. Expired Card Cert
    expired_card_cert = create_cert("Driver-Card-Expired", msca_key, msca_cert, card_key.public_key(), expired=True)

    # 5. ECDSA G2 Card Cert
    ecdsa_card_key = generate_ecdsa_pair()
    ecdsa_card_cert = create_cert("Driver-Card-G2", msca_key, msca_cert, ecdsa_card_key.public_key())

    return {
        "erca_cert": erca_cert,
        "msca_cert": msca_cert,
        "card_cert": card_cert,
        "card_key": card_key,
        "expired_card_cert": expired_card_cert,
        "ecdsa_card_cert": ecdsa_card_cert,
        "ecdsa_card_key": ecdsa_card_key
    }

if __name__ == "__main__":
    setup_mock_certs(".")
