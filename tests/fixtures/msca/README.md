# Production MSCA certificates (public)

Two Member State CA certificates for the Smart Tachograph, issued by ERCA under
the production root `ERCA Gen2(1)` (CAR `FD45432001FFFF01`, the root in
`certs/`). They are public keys, published for download by the JRC Digital
Tachograph team on "Public Key Certificates for the Smart Tachograph issued by
ERCA" (https://dtc.jrc.ec.europa.eu/dtc_public_key_certificates_st.php.html),
file names `A_MSCA_Card(1-33)_Cert_000A.bin` and `CZ_MSCA_Card(1-3)_Cert_FFFF.bin`.

One is on brainpoolP256r1 and one on NIST P-256, the two curves the published
MSCA certificates use (190 and 53 of 243 when checked in November 2026; every one
of the 243 verified under the root in `certs/`). Saved as `.cvc` because `*.bin`
is git-ignored.
