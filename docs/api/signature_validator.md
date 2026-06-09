# SignatureValidator

Digital signature validator for tachograph certificate chains. Verifies ERCA/MSCA certificate hierarchies using ECDSA and RSA public key cryptography.

**File:** `signature_validator.py`

---

## Class: `SignatureValidator`

```python
class SignatureValidator:
    """Validates digital signatures for Tachograph files (Annex 1B/1C).
    Supports RSA (G1/G2) and ECDSA (G2).
    Implements Certification Chain validation: ERCA -> MSCA -> Card/VU."""
```

### Constructor

```python
def __init__(self, certs_dir: str = None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `certs_dir` | `str` or `None` | `None` | Directory containing ERCA root certificates in PEM format. Defaults to `certs/` relative to `signature_validator.py`. |

**Initialization steps:**
1. Sets up logging with `"SignatureValidator"` logger
2. Creates `certs/` directory if it doesn't exist (with README placeholder)
3. Loads all ERCA root certificates from `.pem` and `.cer` files in `certs_dir`
4. Supports JRC custom PEM format (`BEGIN ERCA PK`) by trying public key loading

**Internal state:**
- `root_certificates` — Dict mapping `subject → X.509 cert` or `filename → PublicKey`
- `msca_certificates` — Cache for MSCA certs found in parsed files

---

### Method: `validate_tacho_chain(card_cert_raw, msca_cert_raw, erca_key_id=None)`

```python
def validate_tacho_chain(self, card_cert_raw: bytes, msca_cert_raw: bytes, erca_key_id=None) -> tuple
```

Validates the full certificate chain: ERCA → MSCA → Card. Called automatically by `TachoParser.parse()`.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `card_cert_raw` | `bytes` | Raw card certificate bytes (from tag 0xC100/0x0103/0xC101) |
| `msca_cert_raw` | `bytes` | Raw MSCA certificate bytes (from tag 0xC108/0x0104/C109) |
| `erca_key_id` | any | Optional ERCA key identifier (currently unused) |

**Returns:** `(is_valid, card_public_key)`

| `is_valid` | Meaning |
|-----------|---------|
| `True` | Full chain verified: ERCA → MSCA → Card |
| `"Verified (G1)"` | G1 chain validated via RSA modulus recovery |
| `"Verified (Local Chain)"` | MSCA → Card verified, ERCA not found locally |
| `"Incomplete (Missing ERCA)"` | MSCA → Card OK, no ERCA root cert available |
| `"G2 (Unknown Format)"` | Certificate format not recognized |
| `"Invalid (Null Data)"` | Modulus data is all zeros |
| `False` | Chain validation failed or error occurred |

**Generation routing:**
- If `card_cert_raw` is 194 bytes → G1 chain (`_validate_g1_chain`)
- Otherwise → G2 chain (`_validate_g2_chain`)

---

### ERCA / MSCA Certificate Hierarchy

```
ERCA (European Root CA)
  │
  └─ MSCA (Member State CA)
       │
       ├─ Card Certificate (driver card)
       └─ VU Certificate (vehicle unit)
```

- **G1** (Annex 1B, Appendix 11): RSA-based certificates (128-byte modulus + exponent). Uses RSA raw recovery (no padding): `m = c^e mod n`
- **G2** (Annex 1C): ECDSA-based certificates in X.509 DER format (or BER-TLV containers)

---

### Supported Algorithms

| Algorithm | Generation | Key Type | Signature Format |
|-----------|-----------|----------|------------------|
| RSA | G1 | `rsa.RSAPublicKey` (128-byte modulus, e=65537) | PKCS1v15 |
| ECDSA | G2, G2.2 | `ec.EllipticCurvePublicKey` | ECDSA with SHA-256 |

---

### Method: `verify_certificate_chain(child_cert, parent_cert)`

```python
def verify_certificate_chain(self, child_cert, parent_cert) -> bool
```

Verifies that `child_cert` is signed by `parent_cert`.

**Parameters:**
- `child_cert` — `x509.Certificate` (DER-loaded X.509)
- `parent_cert` — `x509.Certificate` or `RSAPublicKey` or `EllipticCurvePublicKey`

**Returns:** `True` if signature is valid, `False` otherwise.

**Logic:**
- If parent is `RSAPublicKey`: Uses PKCS1v15 padding with child's signature hash algorithm
- If parent is `EllipticCurvePublicKey`: Uses ECDSA with child's signature hash algorithm

---

### Method: `validate_block(data, signature, public_key, algorithm='RSA')`

```python
def validate_block(self, data: bytes, signature: bytes, public_key, algorithm: str = 'RSA') -> bool
```

Validates a data block against its signature using the provided public key.

**Parameters:**
- `data` — Data to verify
- `signature` — Signature bytes
- `public_key` — `RSAPublicKey` or `EllipticCurvePublicKey`
- `algorithm` — `"RSA"` or `"ECDSA"`

---

### Additional Methods

| Method | Description |
|--------|-------------|
| `verify_rsa_signature(public_key, signature, data, hash_algo)` | RSA PKCS1v15 verification |
| `verify_ecdsa_signature(public_key, signature, data, hash_algo)` | ECDSA verification |
| `unwrap_g1_certificate(certificate, public_key)` | G1 RSA certificate unwrapping (ISO 9796-2) |
| `_validate_g1_chain(card_cert_raw, msca_cert_raw)` | Internal G1 chain validation |
| `_validate_g2_chain(card_cert_raw, msca_cert_raw)` | Internal G2 X.509 chain validation |
| `_get_rsa_public_key(n_bytes, e_int=65537)` | Constructs RSA public key from modulus bytes |
| `_load_root_certificates()` | Loads ERCA certs from filesystem |
| `_ensure_certs_dir()` | Creates certs directory with README |

---

## Usage Example

```python
from signature_validator import SignatureValidator

# Create validator with default certs directory
validator = SignatureValidator()

# Or specify a custom directory
validator = SignatureValidator(certs_dir="/path/to/erca_certs")

# Validate chain with raw certificate bytes from parsing
# (normally done automatically by TachoParser)
card_cert = bytes.fromhex("...")  # From tag 0xC100
msca_cert = bytes.fromhex("...")  # From tag 0xC108

is_valid, pubkey = validator.validate_tacho_chain(card_cert, msca_cert)
print(f"Chain valid: {is_valid}")
if pubkey:
    print(f"Card public key: {pubkey}")
```

### Integration with TachoParser (automatic)

```python
# From ddd_parser.py:187-194
from ddd_parser import TachoParser

parser = TachoParser("file.ddd")
data = parser.parse()

# Validation happens automatically during parse()
# Status available via:
print(parser.validation_status)          # "Verified", "Verified (Local Chain)", etc.
print(data["metadata"]["integrity_check"])  # Same value as validation_status
print(parser.card_public_key)           # Public key if validated
```

## See Also

- [TachoParser](tacho_parser.md) — Integrates SignatureValidator automatically
- [DecoderRegistry](decoder_registry.md) — Certificate tag definitions

## Common Tasks

### Check validation status of a parsed file

```python
parser = TachoParser("file.ddd")
data = parser.parse()
status = data["metadata"]["integrity_check"]
if status == "Verified":
    print("File integrity confirmed")
elif "Incomplete" in str(status):
    print("Partial validation — ERCA certs may be missing")
else:
    print(f"Warning: {status}")
```

### Set up ERCA certificates

```python
# Place ERCA certificates in the certs/ directory
# The validator will auto-load them on instantiation

# Supported formats:
# - PEM X.509 certificates (.pem, .cer)
# - JRC custom PEM format (BEGIN ERCA PK)
# - Raw RSA public key PEM
```

### Manual data block verification

```python
from cryptography.hazmat.primitives.asymmetric import rsa

validator = SignatureValidator()
# ... obtain public_key, data, signature from parsed file ...
is_valid = validator.validate_block(data, signature, public_key, algorithm='RSA')
```
