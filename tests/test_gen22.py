"""Tests for Gen 2.2 (Smart Tachograph V2) support."""
import struct
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddd_parser import TachoParser
from core.decoders import (
    parse_g22_gnss_accumulated_driving,
    parse_g22_load_unload_operations,
    parse_g22_trailer_registrations,
    parse_g22_gnss_enhanced_places,
    parse_g22_load_sensor_data,
    parse_g22_border_crossings,
)


def _make_temp_file(data):
    """Write data to a temp file and return path."""
    f = tempfile.NamedTemporaryFile(suffix='.ddd', delete=False)
    f.write(data)
    f.close()
    return f.name


class TestGen22Detection:
    """Test Gen 2.2 header detection."""

    def test_detect_g22_header(self):
        """Files starting with 0x7631 should be detected as G2.2."""
        # Build minimal file: 0x7631 header + length + some padding
        header = b'\x76\x31'
        length = struct.pack(">H", 10)
        payload = b'\x00\x02' + b'\x00' * 8  # version + padding
        data = header + length + payload
        path = _make_temp_file(data)
        try:
            parser = TachoParser(path)
            result = parser.parse()
            assert result["metadata"]["generation"] == "G2.2 (Smart V2)"
        finally:
            os.unlink(path)

    def test_detect_g2_header_unchanged(self):
        """Files with 0x7621 still detected as G2."""
        header = b'\x76\x21'
        length = struct.pack(">H", 10)
        payload = b'\x00\x02' + b'\x00' * 8
        data = header + length + payload
        path = _make_temp_file(data)
        try:
            parser = TachoParser(path)
            result = parser.parse()
            assert result["metadata"]["generation"] == "G2 (Smart)"
        finally:
            os.unlink(path)

    def test_detect_g1_header_unchanged(self):
        """Files without 0x76xx header still detected as G1."""
        data = b'\x00\x05\x01\x00\x04' + b'\x00' * 20
        path = _make_temp_file(data)
        try:
            parser = TachoParser(path)
            result = parser.parse()
            assert result["metadata"]["generation"] == "G1 (Digital)"
        finally:
            os.unlink(path)


class TestGen22RealFiles:
    """Test with real DDD files if available."""

    @pytest.fixture
    def real_g22_path(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_gen22_1.ddd')
        if not os.path.exists(p):
            pytest.skip("Real Gen 2.2 test file not available")
        return p

    @pytest.fixture
    def real_g2_path(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_real_g2.ddd')
        if not os.path.exists(p):
            pytest.skip("Real G2 test file not available")
        return p

    @pytest.fixture
    def real_g1_path(self):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_real_g1.ddd')
        if not os.path.exists(p):
            pytest.skip("Real G1 test file not available")
        return p

    def test_real_g22_detection(self, real_g22_path):
        result = TachoParser(real_g22_path).parse()
        assert result["metadata"]["generation"] == "G2.2 (Smart V2)"

    def test_real_g2_still_works(self, real_g2_path):
        result = TachoParser(real_g2_path).parse()
        assert result["metadata"]["generation"] == "G2 (Smart)"

    def test_real_g1_still_works(self, real_g1_path):
        result = TachoParser(real_g1_path).parse()
        assert result["metadata"]["generation"] == "G1 (Digital)"

    def test_real_g22_no_crash_and_extracts_data(self, real_g22_path):
        result = TachoParser(real_g22_path).parse()
        assert result["metadata"]["coverage_pct"] > 0
        assert "Error" not in result["metadata"].get("integrity_check", "")


class TestGen22GracefulFallback:
    """Test that partial/missing Gen 2.2 data doesn't crash."""

    def test_empty_gnss_accumulated(self):
        """Empty data should not crash gnss decoder."""
        results = {"gnss_ad_records": []}
        parse_g22_gnss_accumulated_driving(b'', results)
        assert results["gnss_ad_records"] == []

    def test_short_load_unload(self):
        """Short data should not crash load/unload decoder."""
        results = {}
        parse_g22_load_unload_operations(b'\x00\x01\x02', results)
        assert results.get("load_unload_records") is None

    def test_short_trailer(self):
        """Short data should not crash trailer decoder."""
        results = {}
        parse_g22_trailer_registrations(b'\x00' * 5, results)
        assert results.get("trailer_registrations") is None

    def test_short_border_crossings(self):
        results = {}
        parse_g22_border_crossings(b'\x00' * 5, results)
        assert results.get("border_crossings") is None

    def test_short_load_sensor(self):
        results = {}
        parse_g22_load_sensor_data(b'\x00' * 3, results)
        assert results.get("load_sensor_data") is None


class TestGen22Decoders:
    """Test actual decoding of Gen 2.2 fields."""

    def test_gnss_accumulated_driving_decode(self):
        """Correctly decode a GNSS accumulated driving record."""
        ts = 1700000000  # 2023-11-14
        lat = int(45.4642 * 10_000_000)  # Milan
        lon = int(9.1900 * 10_000_000)
        speed = 85
        heading = 180
        record = struct.pack(">IiiHH", ts, lat, lon, speed, heading)
        results = {}
        parse_g22_gnss_accumulated_driving(record, results)
        assert len(results["gnss_ad_records"]) == 1
        r = results["gnss_ad_records"][0]
        assert abs(r["latitude"] - 45.4642) < 0.001
        assert abs(r["longitude"] - 9.19) < 0.001
        assert r["speed_kmh"] == 85
        assert r["heading"] == 180

    def test_load_sensor_data_decode(self):
        """Correctly decode load sensor data."""
        ts = 1700000000
        w1, w2, total = 5000, 7000, 12000
        record = struct.pack(">IHHH", ts, w1, w2, total)
        results = {}
        parse_g22_load_sensor_data(record, results)
        assert len(results["load_sensor_data"]) == 1
        assert results["load_sensor_data"][0]["weights_kg"] == [5000, 7000, 12000]

    def test_border_crossings_decode(self):
        """Correctly decode border crossing records."""
        ts = 1700000000
        nation_from = 0x1A  # Italy
        nation_to = 0x0D    # Germany
        lat = int(47.0 * 10_000_000)
        lon = int(11.0 * 10_000_000)
        record = struct.pack(">IBBii", ts, nation_from, nation_to, lat, lon)
        results = {}
        parse_g22_border_crossings(record, results)
        assert len(results["border_crossings"]) == 1
        r = results["border_crossings"][0]
        assert r["nation_from"] == "I"
        assert r["nation_to"] == "D"
        assert abs(r["latitude"] - 47.0) < 0.001

    def test_trailer_registrations_decode(self):
        """Correctly decode trailer registration."""
        ts = 1700000000
        nation = 0x1A  # Italy
        plate = b'AB12345CD     '  # 14 bytes
        coupling = 0  # coupled
        padding = b'\x00' * 5  # pad to 24 bytes
        record = struct.pack(">IB", ts, nation) + plate + bytes([coupling]) + padding
        results = {}
        parse_g22_trailer_registrations(record, results)
        assert len(results["trailer_registrations"]) == 1
        assert results["trailer_registrations"][0]["event"] == "COUPLED"
        assert "AB12345CD" in results["trailer_registrations"][0]["trailer_plate"]
