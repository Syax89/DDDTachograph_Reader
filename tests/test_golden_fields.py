"""Field-level golden assertions for all 19 real DDD files.

Every assertion documents a known decoded value — card number, driver name,
plate, VIN, activity count, event count, certificate count, signature
verification status — so a decoder regression that accidentally changes the
output of a real file is caught immediately.

Regenerate (update) this file when decoded output changes intentionally by
copying the assertions from a passing test run.
"""
import os
import pytest
from ddd_parser import TachoParser

DDD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "DDD")

# ── Helpers ────────────────────────────────────────────────────────────────

def _parse(name):
    path = os.path.join(DDD_DIR, name)
    assert os.path.isfile(path), f"File missing: {name}"
    return TachoParser(path).parse()

def _gen(r):
    return r["metadata"]["generation"]

def _is_vu(r):
    return r["metadata"].get("is_vu", False)

def _cov(r):
    return r["metadata"].get("coverage_pct", 0)

def _driver(r):
    return r.get("driver", {})

def _vehicle(r):
    return r.get("vehicle", {})

def _act_count(r):
    return len(r.get("activities", []))

def _evt_count(r):
    return len(r.get("events", []))

def _certs(r):
    return r.get("certificates", [])

def _cert_formats(r):
    return sorted(c.get("format", "?") for c in _certs(r) if c.get("format"))

def _sv(r):
    return r.get("signature_verification") or {}

def _efv(r):
    return r.get("ef_signature_verification") or {}

def _raw_tag_keys(r):
    return sorted(r.get("raw_tags", {}).keys())


# ── G1 Driver Card files (D6xxxxx) ─────────────────────────────────────────

class TestG1DriverCards:
    """D6xxx series — G1 digital tachograph driver card downloads."""

    def test_D600038072109061001(self):
        r = _parse("D600038072109061001.ddd")
        assert _gen(r) == "G1 (Digital)"
        assert not _is_vu(r)
        assert _cov(r) == 100.0
        d = _driver(r)
        assert d["card_number"] == "0000000000X1I003"
        assert d["surname"] == "Gaborean"
        assert d["firstname"] == "Ioan"
        assert _act_count(r) == 248
        assert _evt_count(r) == 14
        assert _cert_formats(r) == ["G1_RSA", "G1_RSA"]
        assert len(_certs(r)) == 2
        sv = _efv(r)
        assert "All 9 EF" in sv.get("summary", "")
        assert "verified" in sv.get("summary", "")

    def test_D600206451908241231I(self):
        r = _parse("D600206451908241231I-00000272884002.ddd")
        assert _gen(r) == "G1 (Digital)"
        d = _driver(r)
        assert d["card_number"] == "I00000272884002"
        assert d["surname"] == "ROSSINI"
        assert d["firstname"] == "SAVERIO"
        assert _act_count(r) == 152
        assert _evt_count(r) == 12
        assert _cert_formats(r) == ["G1_RSA", "G1_RSA"]

    def test_D600236742105210407(self):
        r = _parse("D600236742105210407I-00000028389002_vasile_apulia.ddd")
        assert _gen(r) == "G1 (Digital)"
        d = _driver(r)
        assert d["card_number"] == "I00000028389002"
        assert d["surname"] == "VASILE"
        assert d["firstname"] == "GAETANO"
        assert _act_count(r) == 159
        assert _evt_count(r) == 25
        assert _cert_formats(r) == ["G1_RSA", "G1_RSA"]
        sv = _efv(r)
        assert "All 12 EF" in sv.get("summary", "")

    def test_D600359121909021330(self):
        r = _parse("D600359121909021330 (5).ddd")
        assert _gen(r) == "G1 (Digital)"
        d = _driver(r)
        assert d["card_number"] == "I00000272884002"
        assert d["surname"] == "ROSSINI"
        assert _act_count(r) == 153
        assert _evt_count(r) == 12
        assert _cert_formats(r) == ["G1_RSA", "G1_RSA"]
        sv = _efv(r)
        assert "All 12 EF" in sv.get("summary", "")


# ── G1 VU TREP06 CardDownload files (D200xxx) ──────────────────────────────

class TestG1D200Trep06:
    """D200xxx — G1 VU TREP06 card download section, parsed as VU."""

    def test_D200_15502_120523(self):
        r = _parse("D200116311604120523I-00000155024001.ddd")
        assert _gen(r) == "G1 (Digital)"
        assert _is_vu(r)
        assert _cov(r) == 100.0
        # Card download entries from TREP06
        assert len(r.get("card_downloads", [])) > 0
        assert len(r.get("inserted_drivers", [])) > 0
        assert _certs(r) == []

    def test_D200_15502_270654(self):
        r = _parse("D200116311604270654I-00000155024001.ddd")
        assert _gen(r) == "G1 (Digital)"
        assert _is_vu(r)
        assert len(r.get("card_downloads", [])) > 0

    def test_D200_17471_180634(self):
        r = _parse("D200154311604180634I-00000174712001.ddd")
        assert _gen(r) == "G1 (Digital)"
        assert _is_vu(r)
        assert len(r.get("card_downloads", [])) > 0

    def test_D200_17471_270814(self):
        r = _parse("D200154311604270814I-00000174712001.ddd")
        assert _gen(r) == "G1 (Digital)"
        assert _is_vu(r)
        assert len(r.get("card_downloads", [])) > 0


# ── G2 Card file ────────────────────────────────────────────────────────────

class TestG2Card:
    """G2 smart tachograph driver card with G1+G2 appendix copies."""

    def test_D_20250715_Milan_Adalberto(self):
        r = _parse("D_20250715_1849_Milan_Adalberto_I100000168598002.ddd")
        assert _gen(r) == "G2 (Smart)"
        assert not _is_vu(r)
        d = _driver(r)
        assert d["card_number"] == "I100000168598002"
        assert d["surname"] == "MILAN"
        assert d["firstname"] == "ADALBERTO"
        assert _act_count(r) == 188
        assert _evt_count(r) == 44
        # G2 card carries both G1 RSA (appendix 1) and CVC (appendix 2) certs
        fmt = _cert_formats(r)
        assert "G1_RSA" in fmt
        assert "CVC" in fmt
        assert len(_certs(r)) == 4
        sv = _efv(r)
        assert "verified" in sv.get("summary", "")


# ── G2 / G2.2 VU downloads ─────────────────────────────────────────────────

class TestG2G22VU:
    """Gen2/Gen2.2 Vehicle Unit downloads with RecordArray ECDSA signatures."""

    def test_M_20200618_FW847FB(self):
        r = _parse("M_20200618_0720_FW847FB_XLRTEM4300G274169 (2).DDD")
        assert _gen(r) == "G2 (Smart)"
        assert _vehicle(r)["plate"] == "FW847FB"
        assert _vehicle(r)["vin"] == "XLRTEM4300G274169"
        assert _act_count(r) >= 300
        assert _evt_count(r) >= 30
        sig = _sv(r)
        assert sig.get("msca_to_vu") is True
        assert sig.get("all_treps_valid") is True

    def test_M_20250725_FY898NX(self):
        r = _parse("M_20250725_0959_FY898NX_YV2R0P0C8KA851055.DDD")
        assert _gen(r) == "G2 (Smart)"
        assert _vehicle(r)["plate"] == "FY898NX"
        assert _vehicle(r)["vin"] == "YV2R0P0C8KA851055"
        assert _act_count(r) >= 20
        sig = _sv(r)
        assert sig.get("msca_to_vu") is True
        assert sig.get("all_treps_valid") is True

    def test_V_20250710_EUROCARGO(self):
        r = _parse("V_20250710_1206_EUROCARGO_GB625AL.ddd")
        assert _gen(r) == "G2 (Smart)"
        assert _vehicle(r)["plate"] == "GB625AL"
        assert _act_count(r) == 31
        sig = _sv(r)
        assert sig.get("msca_to_vu") is True
        assert sig.get("all_treps_valid") is True

    def test_V60062584_G22(self):
        r = _parse("V600625842504021733_1740873600-1743465600.ddd")
        assert _gen(r) == "G2.2 (Smart V2)"
        assert _vehicle(r)["plate"] == "FP904WC"
        assert _vehicle(r)["vin"] == "YV2RTY0C8JB863180"
        assert _act_count(r) == 31
        sig = _sv(r)
        assert sig.get("msca_to_vu") is True
        assert sig.get("all_treps_valid") is True
        assert sig.get("root_anchored") is True

    def test_V60064236_G22(self):
        r = _parse("V600642362507021832_1748736000-1751328000.ddd")
        assert _gen(r) == "G2.2 (Smart V2)"
        assert _vehicle(r)["plate"] == "FG538JH"
        assert _vehicle(r)["vin"] == "YV2RTY0C9HB792078"
        assert _act_count(r) == 31
        sig = _sv(r)
        assert sig.get("msca_to_vu") is True
        assert sig.get("all_treps_valid") is True

    def test_V_20250715_GV692XZ(self):
        r = _parse("V_20250715_0614_GV692XZ_GV692XZ.ddd")
        assert _gen(r) == "G2.2 (Smart V2)"
        assert _vehicle(r)["plate"] == "GV692XZ"
        assert _vehicle(r)["vin"] == "WMA10KZZ8RM950889"
        assert _act_count(r) >= 5
        sig = _sv(r)
        assert sig.get("msca_to_vu") is True
        assert sig.get("all_treps_valid") is True


# ── G1 VU / Mass Memory ─────────────────────────────────────────────────────

class TestG1VUMassMemory:
    """G1 digital tachograph Vehicle Unit and Mass Memory downloads."""

    def test_V60064236_G1(self):
        r = _parse("V600642362501071440_1732579200-1736121600.ddd")
        assert _gen(r) == "G1 (Digital)"
        assert _vehicle(r)["plate"] == "FG538JH"
        assert _vehicle(r)["vin"] == "YV2RTY0C9HB792078"
        assert _evt_count(r) >= 30
        certs = _certs(r)
        assert len(certs) == 2
        assert certs[0]["format"] == "G1_RSA"

    def test_M_20230130_FP469VP(self):
        r = _parse("M_20230130_0734_FP_469_VP_VLUR8X20009117178.DDD")
        assert _gen(r) == "G1 (Digital)"
        assert _vehicle(r)["plate"] == "FP 469 VP"
        assert _vehicle(r)["vin"] == "VLUR8X20009117178"
        assert _act_count(r) >= 90
        certs = _certs(r)
        assert len(certs) == 2

    def test_M_20240522_FS137FR(self):
        r = _parse("M_20240522_1707_FS137FR      _XLRTEH4300G267680.DDD")
        assert _gen(r) == "G1 (Digital)"
        assert _vehicle(r)["plate"] == "FS137FR"
        assert _vehicle(r)["vin"] == "XLRTEH4300G267680"
        assert _act_count(r) >= 350
        certs = _certs(r)
        assert len(certs) == 2


# ── G1 Sensor file ──────────────────────────────────────────────────────────

class TestG1Sensor:
    """G1 digital tachograph sensor download (0x7611 opaque section)."""

    def test_S_20240522_FS137FR(self):
        r = _parse("S_20240522_1721_FS137FR      _XLRTEH4300G267680.DDD")
        assert _gen(r) == "G1 (Digital)"
        assert _vehicle(r)["plate"] == "FS137FR"
        assert _vehicle(r)["vin"] == "XLRTEH4300G267680"
        assert _act_count(r) == 0
        assert _evt_count(r) == 0
        certs = _certs(r)
        assert len(certs) == 2
        assert certs[0]["format"] == "G1_RSA"
        # Sensor file has 0x7611 sensor/special raw section
        assert _cov(r) == 100.0


# ── Cross-file invariants ───────────────────────────────────────────────────

class TestGlobalInvariants:
    """Properties that must hold for every real file in the dataset."""

    _ALL_FILES = sorted(
        [f for f in os.listdir(DDD_DIR) if f.endswith(('.ddd', '.DDD')) and f != '.DS_Store'])

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_decoded_without_errors(self, name):
        r = _parse(name)
        assert r["metadata"].get("integrity_check", "") != ""
        assert "Error" not in r["metadata"].get("integrity_check", "")

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_has_full_coverage(self, name):
        r = _parse(name)
        assert _cov(r) == 100.0, f"{name}: coverage {_cov(r)}%"

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_has_non_empty_raw_tags(self, name):
        r = _parse(name)
        tags = _raw_tag_keys(r)
        assert len(tags) > 0, f"{name}: raw_tags is empty"

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_has_generation(self, name):
        r = _parse(name)
        gen = _gen(r)
        assert gen in ("G1 (Digital)", "G2 (Smart)", "G2.2 (Smart V2)")
