"""Regression tests for the VU RecordArray dispatcher.

Guards against the confirmed bug where Gen2/Gen2.2 VU downloads decoded almost
no semantic content (activities/border crossings dropped) because the data is
keyed by recordType in RecordArrays, not by the 0x05xx tags.
"""
import os
import unittest

from ddd_parser import TachoParser
from core.vu_record_dispatcher import (
    decode_border_crossing,
    decode_full_card_number_gen,
    decode_geo_coordinates,
    decode_specific_condition,
    walk_vu_record_arrays,
)
from tests.real_data import requires_real_files

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")


def _path(name):
    return os.path.join(DDD_DIR, name)


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


@requires_real_files
class TestRealFileRecovery(unittest.TestCase):
    """These G2.2 files contain data the legacy heuristic dropped."""

    def test_border_crossings_recovered(self):
        # 13 border crossings are present in this file (recordType 0x22, 55 bytes).
        r = TachoParser(_path("V600625842504021733_1740873600-1743465600.ddd")).parse()
        bc = r.get("border_crossings", [])
        self.assertGreaterEqual(len(bc), 13)
        # First crossing: Spain (E) -> France (F).
        self.assertEqual(bc[0]["country_left"], "E")
        self.assertEqual(bc[0]["country_entered"], "F")

    def test_g2_vu_files_recover_activities(self):
        for name in (
            "V600625842504021733_1740873600-1743465600.ddd",
            "V_20250710_1206_EUROCARGO_GB625AL.ddd",
        ):
            with self.subTest(file=name):
                r = TachoParser(_path(name)).parse()
                events = sum(len(a.get("changes", [])) for a in r.get("activities", []))
                self.assertGreater(events, 100, "VU activity changes should be recovered")

    def test_record_arrays_summary_present(self):
        r = TachoParser(_path("V_20250715_0614_GV692XZ_GV692XZ.ddd")).parse()
        self.assertTrue(r.get("vu_record_arrays"), "section summary should be populated")

    def test_places_and_gnss_recovered(self):
        # Places (0x1C) and GNSS accumulated driving (0x16) were dropped before.
        r = TachoParser(_path("V600625842504021733_1740873600-1743465600.ddd")).parse()
        self.assertGreater(len(r.get("places", [])), 0)
        gnss = r.get("gnss_ad_records", [])
        self.assertGreater(len(gnss), 0)
        # Coordinates must be geographically sane (truck in Spain → ~40-44°N, -2-4°E).
        geo = gnss[0]["gnss_place"]["geo"]
        self.assertTrue(geo["fix"])
        self.assertTrue(35 < geo["latitude_deg"] < 46)
        self.assertTrue(-5 < geo["longitude_deg"] < 6)


@requires_real_files
class TestFullDecodeCoverage(unittest.TestCase):
    """Every record in the real VU files must be field-decoded (no raw fallback)."""

    def test_no_raw_records_in_real_files(self):
        import struct
        from core.vu_record_dispatcher import _decode_record

        for name in os.listdir(DDD_DIR):
            if not name.lower().endswith(".ddd"):
                continue
            data = open(_path(name), "rb").read()
            if not data.startswith(b"\x76") or data[1] in (0x06, 0x26, 0x36):
                continue  # card file or TREP card download, not a VU RecordArray stream
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
