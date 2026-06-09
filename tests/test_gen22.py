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
    parse_g22_load_sensor_data,
    parse_g22_border_crossings,
    parse_g2_vu_record,
)
from core.g2_decoders import (
    parse_g22_detailed_speed,
    parse_g2_sensor_gnss_coupled,
    parse_g2_sensor_paired,
    parse_g22_overspeeding_event,
    parse_g22_overspeeding_control,
    parse_g22_time_adj_gnss,
    parse_g22_power_interruption,
    parse_g22_sensor_fault,
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

    def test_short_detailed_speed(self):
        assert parse_g22_detailed_speed(b'\x00' * 10) is None

    def test_short_overspeeding_event(self):
        assert parse_g22_overspeeding_event(b'\x00' * 10) is None

    def test_short_overspeeding_control(self):
        assert parse_g22_overspeeding_control(b'\x00' * 3) is None

    def test_short_time_adj_gnss(self):
        assert parse_g22_time_adj_gnss(b'\x00' * 3) is None

    def test_short_power_interruption(self):
        assert parse_g22_power_interruption(b'\x00' * 10) is None

    def test_short_sensor_fault(self):
        assert parse_g22_sensor_fault(b'\x00' * 10) is None


class TestGen22Decoders:
    """Test actual decoding of Gen 2.2 fields."""

    def test_gnss_accumulated_driving_decode(self):
        """Correctly decode a GNSS accumulated driving record (Annex 1C §2.79: 11 bytes)."""
        ts = 1700000000  # 2023-11-14
        accuracy = 0x03  # 3 meters
        # Annex 1C §2.76: GeoCoordinates as signed int24 ±DDMM.M ×10
        lat_raw = 45279   # 45°27.852'N → 4527.85 × 10
        lon_raw = 9114    # 009°11.4'E → 911.4 × 10
        record = struct.pack(">IB", ts, accuracy) + lat_raw.to_bytes(3, 'big', signed=True) + lon_raw.to_bytes(3, 'big', signed=True)
        results = {}
        parse_g22_gnss_accumulated_driving(record, results)
        assert len(results["gnss_ad_records"]) == 1
        r = results["gnss_ad_records"][0]
        assert abs(r["latitude"] - 45.465) < 0.001
        assert abs(r["longitude"] - 9.19) < 0.001
        assert r["gnss_accuracy"] == 0x03

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
        """Correctly decode border crossing records (annex 1c §2.76: 12 bytes)."""
        ts = 1700000000
        nation_from = 0x1A  # Italy
        nation_to = 0x0D    # Germany
        lat_raw = 47000  # 47°00.0'N → 4700.0 × 10
        lon_raw = 11000  # 011°00.0'E → 1100.0 × 10
        record = struct.pack(">IBB", ts, nation_from, nation_to) + lat_raw.to_bytes(3, 'big', signed=True) + lon_raw.to_bytes(3, 'big', signed=True)
        results = {}
        parse_g22_border_crossings(record, results)
        assert len(results["border_crossings"]) == 1
        r = results["border_crossings"][0]
        assert r["nation_from"] == "I"
        assert r["nation_to"] == "D"
        assert abs(r["latitude"] - 47.0) < 0.001

    def test_trailer_registrations_decode(self):
        """Correctly decode trailer registration (ASN.1: 20 bytes)."""
        ts = 1700000000
        nation = 0x1A  # Italy
        plate = b'AB12345CD     '  # 14 bytes
        coupling = 0  # coupled
        record = struct.pack(">IB", ts, nation) + plate + bytes([coupling])
        results = {}
        parse_g22_trailer_registrations(record, results)
        assert len(results["trailer_registrations"]) == 1
        assert results["trailer_registrations"][0]["event"] == "COUPLED"
        assert "AB12345CD" in results["trailer_registrations"][0]["trailer_plate"]

    def test_detailed_speed_decode(self):
        ts = 1700000000
        speed_samples = bytes(range(60))
        record = struct.pack(">I", ts) + speed_samples

        decoded = parse_g22_detailed_speed(record)

        assert decoded["raw_timestamp"] == ts
        assert decoded["speeds_kmh"] == list(range(60))
        assert decoded["valid_speed_count"] == 60
        assert decoded["max_speed_kmh"] == 59
        assert decoded["avg_speed_kmh"] == 29.5

    def test_g22_sensor_gnss_decode_reuses_g2_structure(self):
        ts = 1700000000
        record = struct.pack(">QQI", 0x0102030405060708, 0x1112131415161718, ts)

        decoded = parse_g2_sensor_gnss_coupled(record)

        assert decoded["serial_number"] == "0x0102030405060708"
        assert decoded["approval_number"] == "0x1112131415161718"
        assert decoded["coupling_date"] != "N/A"

    def test_g22_sensor_paired_decode_reuses_g2_structure(self):
        first_ts = 1700000000
        current_ts = 1700003600
        record = struct.pack(">QQII", 0x0102030405060708, 0x1112131415161718, first_ts, current_ts)

        decoded = parse_g2_sensor_paired(record)

        assert decoded["serial_number"] == "0x0102030405060708"
        assert decoded["approval_number"] == "0x1112131415161718"
        assert decoded["pairing_first"] != "N/A"
        assert decoded["pairing_current"] != "N/A"

    def test_g22_record_array_dispatches_high_priority_records(self):
        ts = 1700000000
        record = struct.pack(">I", ts) + bytes(range(60))
        record_array = struct.pack(">BHH", 1, 64, 1) + record
        results = {}

        parse_g2_vu_record(record_array, results, 0x052C)

        assert len(results["detailed_speed"]) == 1
        assert results["detailed_speed"][0]["max_speed_kmh"] == 59

    def test_overspeeding_event_decode(self):
        ts_begin = 1700000000
        ts_end = 1700003600
        record = struct.pack(">BBIIBB", 0x01, 0x02, ts_begin, ts_end, 120, 95)
        record += struct.pack(">BB", 0x01, 0x1A)  # gen=1, nation=I
        record += b'DRV12345CARD    '  # 16-byte card number
        record += struct.pack(">BB", 0x01, 0x02)  # repl=1, renew=2
        record += struct.pack(">B", 0x03)  # similarEvents=3
        decoded = parse_g22_overspeeding_event(record)
        assert decoded is not None
        assert decoded["event_type"] == 0x01
        assert decoded["event_purpose"] == 0x02
        assert decoded["max_speed_kmh"] == 120
        assert decoded["average_speed_kmh"] == 95
        assert decoded["similar_events"] == 0x03
        assert decoded["card_begin"]["nation"] == "I"
        assert decoded["card_begin"]["generation"] == 1
        assert decoded["begin_time"] != "N/A"
        assert decoded["end_time"] != "N/A"

    def test_overspeeding_control_decode(self):
        ts_last = 1700000000
        ts_first = 1699900000
        record = struct.pack(">IIH", ts_last, ts_first, 42)
        decoded = parse_g22_overspeeding_control(record)
        assert decoded is not None
        assert decoded["number_of_overspeed"] == 42
        assert decoded["last_control_time"] != "N/A"
        assert decoded["first_overspeed_since"] != "N/A"

    def test_time_adj_gnss_decode(self):
        ts_old = 1700000000
        ts_new = 1700003600
        record = struct.pack(">II", ts_old, ts_new)
        decoded = parse_g22_time_adj_gnss(record)
        assert decoded is not None
        assert decoded["old_time"] != "N/A"
        assert decoded["new_time"] != "N/A"

    def test_power_interruption_decode(self):
        ts_begin = 1700000000
        ts_end = 1700003600
        record = struct.pack(">BBII", 0x01, 0x02, ts_begin, ts_end)
        for _ in range(4):
            record += struct.pack(">BB", 0x01, 0x1A)
            record += b'DRV12345CARD    '
            record += struct.pack(">BB", 0x01, 0x02)
        decoded = parse_g22_power_interruption(record)
        assert decoded is not None
        assert decoded["event_type"] == 0x01
        assert decoded["event_purpose"] == 0x02
        assert decoded["begin_time"] != "N/A"
        assert decoded["end_time"] != "N/A"
        assert decoded["card_driver_begin"]["nation"] == "I"
        assert decoded["card_driver_end"]["nation"] == "I"
        assert decoded["card_codriver_begin"]["nation"] == "I"
        assert decoded["card_codriver_end"]["nation"] == "I"

    def test_sensor_fault_decode(self):
        ts_begin = 1700000000
        ts_end = 1700003600
        record = struct.pack(">BBII", 0x01, 0x02, ts_begin, ts_end)
        for _ in range(4):
            record += struct.pack(">BB", 0x01, 0x1A)
            record += b'DRV12345CARD    '
            record += struct.pack(">BB", 0x01, 0x02)
        decoded = parse_g22_sensor_fault(record)
        assert decoded is not None
        assert decoded["event_type"] == 0x01
        assert decoded["event_purpose"] == 0x02
        assert decoded["begin_time"] != "N/A"
        assert decoded["end_time"] != "N/A"
        assert "raw_hex" in decoded

    def test_overspeeding_event_record_array_dispatch(self):
        ts_begin = 1700000000
        ts_end = 1700003600
        record = struct.pack(">BBIIBB", 0x01, 0x02, ts_begin, ts_end, 120, 95)
        record += struct.pack(">BB", 0x01, 0x1A)
        record += b'DRV12345CARD    '
        record += struct.pack(">BB", 0x01, 0x02)
        record += struct.pack(">B", 0x03)
        record_array = struct.pack(">BHH", 1, 33, 1) + record
        results = {}

        parse_g2_vu_record(record_array, results, 0x052D)

        assert len(results["overspeeding_events"]) == 1
        assert results["overspeeding_events"][0]["max_speed_kmh"] == 120

    def test_power_interruption_record_array_dispatch(self):
        ts_begin = 1700000000
        ts_end = 1700003600
        record = struct.pack(">BBII", 0x01, 0x02, ts_begin, ts_end)
        for _ in range(4):
            record += struct.pack(">BB", 0x01, 0x1A)
            record += b'DRV12345CARD    '
            record += struct.pack(">BB", 0x01, 0x02)
        record_array = struct.pack(">BHH", 1, 90, 1) + record
        results = {}

        parse_g2_vu_record(record_array, results, 0x0530)

        assert len(results["power_interruptions"]) == 1
        assert results["power_interruptions"][0]["event_type"] == 0x01
