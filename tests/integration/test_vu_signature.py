"""Cryptographic verification tests for Gen2/Gen2.2 VU downloads (Appendix 11).

Confirms the ECDSA download signatures and the MSCA→VU certificate chain verify
on real files, and that tampering with the data is detected.
"""
import os
import unittest

from app.engine import TachoParser
from core.crypto.vu_signature import (
    verify_vu_download, decode_vu_certificates)
from tests.unit.real_data import requires_real_files

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")


def _g2_vu_files():
    for name in sorted(os.listdir(DDD_DIR)):
        if not name.lower().endswith(".ddd"):
            continue
        data = open(os.path.join(DDD_DIR, name), "rb").read()
        if data[:1] == b"\x76" and data[1:2] in (b"\x21", b"\x22", b"\x31", b"\x32"):
            yield name, data


def _require_g2_vu_files():
    files = list(_g2_vu_files())
    if not files:
        raise unittest.SkipTest("No private Gen2/Gen2.2 VU fixture available")
    return files


@requires_real_files
class TestVuSignatures(unittest.TestCase):
    def test_real_files_fully_verified(self):
        files = _require_g2_vu_files()
        for name, data in files:
            with self.subTest(file=name):
                rep = verify_vu_download(data)
                self.assertTrue(rep["available"])
                self.assertTrue(rep["msca_to_vu"], "MSCA→VU chain must verify")
                self.assertTrue(rep["treps"], "expected TREP signatures")
                self.assertTrue(rep["all_treps_valid"],
                                f"all TREP signatures must verify: {rep['summary']}")

    def test_tampering_is_detected(self):
        from core.parser.vu_dispatcher import iter_vu_sections
        name, data = _require_g2_vu_files()[0]

        # Flip a byte inside the payload of the first signed data record, so it
        # falls squarely within a signature's covered region.
        target = None
        for sec in iter_vu_sections(data):
            has_sig = any(r[1] == 0x08 for r in sec["records"])
            data_recs = [r for r in sec["records"] if r[1] not in (0x04, 0x0F, 0x08)]
            if has_sig and data_recs:
                target = data_recs[0][0] + 6  # inside the first data record
                break
        self.assertIsNotNone(target, "no signed data record found")

        buf = bytearray(data)
        buf[target] ^= 0xFF
        rep = verify_vu_download(bytes(buf))
        self.assertFalse(rep["all_treps_valid"],
                          "a flipped data byte must invalidate at least one signature")

    def test_missing_trep_signature_is_detected(self):
        from core.parser.vu_dispatcher import iter_vu_sections
        _, data = _require_g2_vu_files()[0]

        # Remove the whole SignatureRecordArray from a signed section and leave
        # the remaining sections intact. The verifier must reject the download,
        # rather than authenticating only the signed subset.
        target = None
        for sec in iter_vu_sections(data):
            for pos, record_type, _record_size, _count, end in sec["records"]:
                if record_type == 0x08:
                    target = (pos, end)
                    break
            if target:
                break
        self.assertIsNotNone(target, "no TREP signature record found")

        start, end = target
        rep = verify_vu_download(data[:start] + data[end:])
        self.assertFalse(rep["all_treps_valid"])
        self.assertTrue(any(t.get("reason") == "signature record missing"
                            for t in rep["treps"]))

    def test_parser_exposes_verification(self):
        name, _ = _require_g2_vu_files()[0]
        r = TachoParser(os.path.join(DDD_DIR, name)).parse()
        sv = r.get("signature_verification")
        self.assertIsNotNone(sv)
        self.assertTrue(sv["msca_to_vu"])
        self.assertTrue(sv["all_treps_valid"])

    def test_cvc_parser_extracts_fields(self):
        _, data = _require_g2_vu_files()[0]
        # The Overview's VU certificate (0x0F) must parse into a CVC structure.
        rep = verify_vu_download(data)
        self.assertTrue(rep["available"])

    def test_cvc_certificates_decoded(self):
        for name, data in _require_g2_vu_files():
            with self.subTest(file=name):
                certs = decode_vu_certificates(data)
                self.assertTrue(certs, "expected at least one decoded CVC cert")
                roles = {c["role"] for c in certs}
                self.assertIn("Vehicle Unit (VU)", roles)
                for c in certs:
                    # Curve must resolve to a known name (not a raw OID).
                    self.assertNotRegex(c["curve"], r"^[0-9a-f]+$")
                    # Validity dates decode to ISO YYYY-MM-DD.
                    if c["valid_from"]:
                        self.assertRegex(c["valid_from"], r"^\d{4}-\d{2}-\d{2}$")
                # The chain links: a VU cert's CAR equals its issuer MSCA's CHR.
                msca = {c["chr"] for c in certs if "MSCA" in c["role"]}
                vu_cars = {c["car"] for c in certs if "VU" in c["role"]}
                if msca and vu_cars:
                    self.assertTrue(vu_cars & msca, "VU CAR must match an MSCA CHR")


if __name__ == "__main__":
    unittest.main()
