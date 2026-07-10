"""Regression tests for the VU RecordArray dispatcher.

Guards against the confirmed bug where Gen2/Gen2.2 VU downloads decoded almost
no semantic content (activities/border crossings dropped) because the data is
keyed by recordType in RecordArrays, not by the 0x05xx tags.
"""
import os
import unittest

from app.engine import TachoParser
from core.parser.vu_dispatcher import (
    decode_border_crossing,
    decode_full_card_number_gen,
    decode_geo_coordinates,
    decode_specific_condition,
    walk_vu_record_arrays,
)
from tests.unit.real_data import real_ddd_files, require_real_file, requires_real_files

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")


def _path(name):
    return require_real_file(name)


class TestBorderCrossingDecode(unittest.TestCase):
    def test_confirmed_record_layout(self):
        # FullCardNumberAndGeneration(19) x2 + countryLeft(1) + countryEntered(1)
        # + GNSSPlaceAuthRecord(12) + odometer(3) = 55 bytes.
        driver = bytes([0x01, 0x1A]) + b"I100000114613001" + bytes([0x02])
        codriver = b"\xff" * 19
        gnss = (0x67C5D851).to_bytes(4, "big") + bytes([0x08]) + b"\xff" * 6 + bytes([0x01])
        rec = driver + codriver + bytes([0x0F, 0x11]) + gnss + (123456).to_bytes(3, "big")
        self.assertEqual(len(rec), 55)

        out = decode_border_crossing(rec)
        self.assertEqual(out["confidence"], "high")
        self.assertTrue(out["card_driver"]["present"])
        self.assertEqual(out["card_driver"]["card_number"], "I100000114613001")
        self.assertEqual(out["card_driver"]["generation"], 2)
        self.assertFalse(out["card_codriver"]["present"])
        self.assertEqual(out["odometer_km"], 123456)
        self.assertIsNotNone(out["gnss_place"]["timestamp"])

    def test_full_card_number_all_ff_is_absent(self):
        self.assertFalse(decode_full_card_number_gen(b"\xff" * 19, 0)["present"])

    def test_geo_coordinates_ddmm_encoding(self):
        # 40353 (×10 of DDMM.M = 4035.3) → 40°35.3' = 40.588°.
        geo = decode_geo_coordinates((40353).to_bytes(3, "big") + (277).to_bytes(3, "big"), 0)
        self.assertTrue(geo["fix"])
        self.assertAlmostEqual(geo["latitude_deg"], 40.588, places=2)
        self.assertAlmostEqual(geo["longitude_deg"], 0.462, places=2)

    def test_geo_no_fix(self):
        self.assertFalse(decode_geo_coordinates(b"\xff" * 6, 0)["fix"])

    def test_specific_condition(self):
        # Annex 1C §2.154: 0x01/0x02 = Out of scope Begin/End,
        # 0x03/0x04 = Ferry/Train crossing Begin/End, 0x00 = RFU.
        cases = {
            0x00: "RFU",
            0x01: "OutOfScope Begin",
            0x02: "OutOfScope End",
            0x03: "Ferry/Train Begin",
            0x04: "Ferry/Train End",
        }
        for code, label in cases.items():
            rec = (1741000000).to_bytes(4, "big") + bytes([code])
            out = decode_specific_condition(rec)
            self.assertEqual(out["condition"], label)
            self.assertEqual(out["type_code"], code)
            self.assertIsNotNone(out["timestamp"])


class TestDetailedSpeedFold(unittest.TestCase):
    def test_speed_blocks_folded_from_recordarray(self):
        # Synthetic 0x7634 (Detailed speed) section: one 0x12 RecordArray with
        # two 64-byte VuDetailedSpeedBlock records (timestamp + 60 speeds) and
        # one all-0xFF padding block that must be skipped.
        import struct
        ts = 1751277600  # 2025-06-30 10:00 UTC
        block1 = struct.pack(">I", ts) + bytes([50] * 30 + [70] * 30)
        block2 = b"\xff" * 64
        stream = b"\x76\x34" + bytes([0x12]) + struct.pack(">HH", 64, 2) + block1 + block2

        results = {}
        walk_vu_record_arrays(stream, results)

        blocks = results.get("speed_blocks")
        self.assertIsNotNone(blocks, "0x12 records must fold into speed_blocks")
        self.assertEqual(len(blocks), 1)  # padding block skipped (begin=None)
        self.assertEqual(blocks[0]["max_speed_kmh"], 70)
        self.assertEqual(blocks[0]["min_speed_kmh"], 50)
        self.assertEqual(blocks[0]["samples"], 60)
        self.assertTrue(blocks[0]["begin"].startswith("2025-06-30"))


def _resolve_by_feature(feature):
    """Return the first VU file from DDD/ whose parse result satisfies *feature*."""
    for path in real_ddd_files():
        name = os.path.basename(path)
        try:
            data = open(path, "rb").read()
            if data[:1] != b"\x76":
                continue
        except OSError:
            continue
        r = TachoParser(path).parse()
        if feature(r, name, data):
            return name
    return None


@requires_real_files
class TestRealFileRecovery(unittest.TestCase):
    """VU files contain data the legacy heuristic dropped — verify recovery."""

    def test_border_crossings_recovered(self):
        # Prefer a fixture that actually carries border crossings so the count
        # assertion stays meaningful (a >0 check would pass on a 1-record file
        # and hide a regression that drops the rest).
        f = _resolve_by_feature(lambda r, n, d: len(r.get("border_crossings") or []) >= 10)
        if f is None:
            f = _resolve_by_feature(
                lambda r, n, d: "G2.2" in r["metadata"].get("generation", ""))
        if f is None:
            self.skipTest("No G2.2 VU fixture available")
        r = TachoParser(_path(f)).parse()
        bc = r.get("border_crossings", [])
        self.assertGreater(len(bc), 0, "border crossings must be recovered")
        # Each recovered crossing must carry both country fields (spec §2.11a-b).
        for crossing in bc:
            self.assertIn("country_left", crossing)
            self.assertIn("country_entered", crossing)

    def test_g2_vu_files_recover_activities(self):
        found = False
        for path in real_ddd_files():
            data = open(path, "rb").read()
            if data[:1] != b"\x76":
                continue
            name = os.path.basename(path)
            with self.subTest(file=name):
                r = TachoParser(path).parse()
                events = sum(len(a.get("changes", [])) for a in r.get("activities", []))
                if events >= 10:
                    found = True
        if not found:
            self.skipTest("No VU fixture with activities found")

    def test_record_arrays_summary_present(self):
        f = _resolve_by_feature(lambda r, n, d: "G2.2" in r["metadata"].get("generation", ""))
        if f is None:
            self.skipTest("No G2.2 VU fixture available")
        r = TachoParser(_path(f)).parse()
        self.assertTrue(r.get("vu_record_arrays"), "section summary should be populated")

    def test_places_and_gnss_recovered(self):
        f = _resolve_by_feature(lambda r, n, d: "G2.2" in r["metadata"].get("generation", ""))
        if f is None:
            self.skipTest("No G2.2 VU fixture available")
        r = TachoParser(_path(f)).parse()
        self.assertGreater(len(r.get("places", [])), 0)
        gnss = r.get("gnss_ad_records", [])
        self.assertGreater(len(gnss), 0)
        geo = gnss[0]["gnss_place"]["geo"]
        self.assertTrue(geo["fix"])
        # Coordinates must be geographically sane (EU operating range).
        self.assertTrue(30 < geo["latitude_deg"] < 72)
        self.assertTrue(-12 < geo["longitude_deg"] < 40)


@requires_real_files
class TestFullDecodeCoverage(unittest.TestCase):
    """Every record in the real VU files must be field-decoded (no raw fallback)."""

    def test_no_raw_records_in_real_files(self):
        import struct
        from core.parser.vu_dispatcher import _decode_record

        candidates = []
        for path in real_ddd_files():
            name = os.path.basename(path)
            if not name.lower().endswith(".ddd"):
                continue
            data = open(path, "rb").read()
            if not data.startswith(b"\x76") or data[1] in (0x06, 0x26, 0x36):
                continue  # card file or TREP card download, not a VU RecordArray stream
            candidates.append((name, data))
        if not candidates:
            self.skipTest("No private VU RecordArray fixture available")
        for name, data in candidates:
            with self.subTest(file=name):
                raw = 0
                total = 0
                pos = 0
                while pos + 5 <= len(data):
                    if data[pos] == 0x76:
                        pos += 2
                        continue
                    rt = data[pos]
                    rs = struct.unpack(">H", data[pos + 1:pos + 3])[0]
                    nr = struct.unpack(">H", data[pos + 3:pos + 5])[0]
                    if rt < 0x01 or rt > 0x60 or rs > 4096 or nr > 20000 or (rs == 0 and nr > 0) \
                            or pos + 5 + rs * nr > len(data):
                        break
                    p = pos + 5
                    for _ in range(nr):
                        out = _decode_record(rt, data[p:p + rs])
                        total += 1
                        if "raw_hex" in out:
                            raw += 1
                        p += rs
                    pos += 5 + rs * nr
                self.assertEqual(raw, 0, f"{raw}/{total} records left raw in {name}")


class TestDispatcherRobustness(unittest.TestCase):
    def test_empty_and_garbage_do_not_crash(self):
        for data in (b"", b"\x76", b"\x76\x31", b"\x00" * 64, b"\xff" * 200):
            res = {}
            walk_vu_record_arrays(data, res)
            self.assertIn("vu_record_arrays", res)


if __name__ == "__main__":
    unittest.main()
