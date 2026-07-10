"""Tests for Gen 2.2 (Smart Tachograph V2) support."""
import struct
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.engine import TachoParser
from core.parser.deterministic import DeterministicParser
from core.registry.registry import DecoderRegistry
from core.decoders import (
    parse_g22_gnss_accumulated_driving,
    parse_g22_load_unload_operations,
    parse_g22_trailer_registrations,
    parse_g22_gnss_enhanced_places,
    parse_g22_load_sensor_data,
    parse_g22_border_crossings,
    parse_g2_vu_record,
)
from core.parser.vu_dispatcher import (
    decode_detailed_speed,
    decode_sensor_gnss_coupled,
    decode_sensor_paired,
    decode_overspeeding_event,
    decode_overspeeding_control,
    decode_time_adj_gnss,
    decode_power_interruption,
    decode_sensor_fault,
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
        assert decode_detailed_speed(b'\x00' * 10) is None

    def test_short_overspeeding_event(self):
        assert decode_overspeeding_event(b'\x00' * 10) is None

    def test_short_overspeeding_control(self):
        assert decode_overspeeding_control(b'\x00' * 3) is None

    def test_short_time_adj_gnss(self):
        assert decode_time_adj_gnss(b'\x00' * 3) is None

    def test_short_power_interruption(self):
        assert decode_power_interruption(b'\x00' * 10) is None

    def test_short_sensor_fault(self):
        assert decode_sensor_fault(b'\x00' * 10) is None


class TestGen22Decoders:
    """Test actual decoding of Gen 2.2 fields."""

    @staticmethod
    def _coordinate(value):
        return value.to_bytes(3, "big", signed=True)

    def _gnss_place(self, timestamp=1700000000, latitude=45279, longitude=9114):
        return (
            struct.pack(">IB", timestamp, 5)
            + self._coordinate(latitude)
            + self._coordinate(longitude)
            + b"\x01"
        )

    def test_gnss_accumulated_driving_decode(self):
        """Decode the pointer-prefixed 19-byte G2.2 card record."""
        ts = 1700000000  # 2023-11-14
        record = struct.pack(">I", ts) + self._gnss_place(ts + 1) + (123456).to_bytes(3, "big")
        results = {}
        parse_g22_gnss_accumulated_driving(b"\x00\x00" + record, results)
        assert len(results["gnss_ad_records"]) == 1
        r = results["gnss_ad_records"][0]
        assert abs(r["latitude"] - 45.465) < 0.001
        assert abs(r["longitude"] - 9.19) < 0.001
        assert r["gnss_accuracy"] == 5
        assert r["vehicle_odometer_value"] == 123456

    def test_gnss_enhanced_places_decode(self):
        ts = 1700000000
        record = self._gnss_place(ts)
        results = {}

        parse_g22_gnss_enhanced_places(record, results)

        assert results["gnss_places"][0]["authenticated"] is True
        assert abs(results["gnss_places"][0]["latitude"] - 45.465) < 0.001

    def test_card_load_unload_full_record_decode(self):
        ts = 1700000000
        place = self._gnss_place(ts + 1)
        record = struct.pack(">IB", ts, 1) + place + (123456).to_bytes(3, "big")
        results = {}

        parse_g22_load_unload_operations(b"\x00\x00" + record, results)

        decoded = results["load_unload_records"][0]
        assert decoded["operation"] == "LOAD"
        assert decoded["vehicle_odometer_value"] == 123456
        assert decoded["gnss_authenticated"] is True

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
        """Decode the 17-byte CardBorderCrossingRecord layout."""
        ts = 1700000000
        place = self._gnss_place(ts)
        record = bytes([0x1A, 0x0D]) + place + (654321).to_bytes(3, "big")
        results = {}

        parse_g22_border_crossings(b"\x00\x00" + record, results)

        decoded = results["border_crossings"][0]
        assert decoded["nation_from"] == "I"
        assert decoded["nation_to"] == "D"
        assert decoded["vehicle_odometer_value"] == 654321
        assert decoded["authenticated"] is True

    def test_trailer_registrations_decode(self):
        """Decode the verified 0x24 VehicleRegistrationIdentification RecordArray."""
        nation = 0x1A  # Italy
        plate = b'\x01TEST000000001'  # InternationalString{13}
        record = bytes([nation]) + plate
        wrapped = b"\x24" + struct.pack(">HH", 15, 1) + record
        results = {}
        parse_g22_trailer_registrations(wrapped, results)
        assert len(results["trailer_registrations"]) == 1
        assert results["trailer_registrations"][0]["nation"] == "I"
        assert results["trailer_registrations"][0]["trailer_plate"] == "TEST000000001"

    def test_trailer_record_array_wrapper_dispatches_without_nested_tlv_parsing(self):
        record = bytes([0x1A]) + b"\x01TEST000000001"
        payload = b"\x24" + struct.pack(">HH", 15, 1) + record
        raw = struct.pack(">HBH", 0x0527, 0x02, len(payload)) + payload

        result = DeterministicParser().parse(raw, is_vu=False)

        assert DecoderRegistry.instance().is_container(0x0527, generation="G2.2", is_vu=False) is False
        assert result["metadata"].get("decoder_validation_warnings") is None
        assert len(result["trailer_registrations"]) == 1

    def test_card_payload_is_not_recursively_parsed_as_ber_container(self):
        payload = self._gnss_place()
        raw = struct.pack(">HBH", 0x0528, 0x02, len(payload)) + payload
        result = DeterministicParser().parse(raw, is_vu=False)

        assert DecoderRegistry.instance().is_container(0x0528, generation="G2.2", is_vu=False) is False
        assert len(result["gnss_places"]) == 1
        assert result["coverage"]["uncovered_ranges"] == []

    def test_wrong_gnss_accumulated_layout_produces_a_validation_warning(self):
        payload = b"\x00" * 38  # Two bare records are invalid: the EF requires a 2-byte pointer.
        raw = struct.pack(">HBH", 0x0525, 0x02, len(payload)) + payload
        result = DeterministicParser().parse(raw, is_vu=False)

        warnings = result["metadata"]["decoder_validation_warnings"]
        assert warnings[0]["tag_id"] == "0x0525"
        assert warnings[0]["code"] == "decoder_record_size_violation"

    @pytest.mark.parametrize(
        ("tag", "payload"),
        [
            (0x0526, lambda self: struct.pack(
                ">IB", 1700000000, 1
            ) + self._gnss_place(1700000001) + (123456).to_bytes(3, "big")),
            (0x052A, lambda self: bytes([0x1A, 0x0D]) + self._gnss_place(1700000000)
             + (654321).to_bytes(3, "big")),
        ],
    )
    def test_pointer_prefixed_card_payloads_do_not_lose_semantic_dispatch(self, tag, payload):
        record = payload(self)
        raw = struct.pack(">HBH", tag, 0x02, len(record) + 2) + b"\x00\x00" + record

        result = DeterministicParser().parse(raw, is_vu=False)

        assert result["metadata"].get("decoder_validation_warnings") is None
        key = "load_unload_records" if tag == 0x0526 else "border_crossings"
        assert len(result[key]) == 1

    def test_malformed_timestamp_and_coordinates_are_rejected(self):
        results = {}
        invalid_time = self._gnss_place(0)
        invalid_latitude = self._gnss_place(latitude=90600)
        invalid_longitude = self._gnss_place(longitude=180001)

        parse_g22_gnss_enhanced_places(invalid_time, results)
        parse_g22_gnss_enhanced_places(invalid_latitude, results)
        parse_g22_gnss_enhanced_places(invalid_longitude, results)

        assert results.get("gnss_places") is None

    @pytest.mark.parametrize("timestamp", [0, 0xFFFFFFFF, 946684799, 4102444801])
    def test_all_gnss_card_records_reject_invalid_timestamps(self, timestamp):
        place = self._gnss_place(timestamp)
        results = {}

        parse_g22_gnss_enhanced_places(place, results)
        parse_g22_gnss_accumulated_driving(
            b"\x00\x00" + struct.pack(">I", timestamp) + place + (1).to_bytes(3, "big"), results
        )
        parse_g22_load_unload_operations(
            b"\x00\x00" + struct.pack(">IB", timestamp, 1) + place + (1).to_bytes(3, "big"), results
        )
        parse_g22_border_crossings(b"\x00\x00" + bytes([0x1A, 0x0D]) + place + (1).to_bytes(3, "big"), results)

        assert results.get("gnss_places") is None
        assert results.get("gnss_ad_records") is None
        assert results.get("load_unload_records") is None
        assert results.get("border_crossings") is None

    def test_gnss_records_reject_coordinate_sentinels_and_out_of_range_values(self):
        results = {}
        invalid_latitude = self._gnss_place(latitude=0x7FFFFF)
        invalid_longitude = self._gnss_place(longitude=180600)

        parse_g22_gnss_enhanced_places(invalid_latitude, results)
        parse_g22_load_unload_operations(
            b"\x00\x00" + struct.pack(">IB", 1700000000, 1) + invalid_longitude
            + (1).to_bytes(3, "big"), results
        )

        assert results.get("gnss_places") is None
        assert results.get("load_unload_records") is None

    @pytest.mark.parametrize("timestamp", [0, 0xFFFFFFFF, 946684799, 4102444801])
    def test_load_sensor_rejects_out_of_range_timestamp(self, timestamp):
        results = {}
        parse_g22_load_sensor_data(struct.pack(">IHH", timestamp, 5000, 7000), results)
        assert results.get("load_sensor_data") is None

    def test_detailed_speed_decode(self):
        ts = 1700000000
        speed_samples = bytes(range(60))
        record = struct.pack(">I", ts) + speed_samples

        decoded = decode_detailed_speed(record)

        assert decoded["valid_speed_count"] == 60
        assert decoded["max_speed_kmh"] == 59
        assert decoded["avg_speed_kmh"] == 29.5

    def test_g22_sensor_gnss_decode_normative_record(self):
        """SensorExternalGNSSCoupledRecord (28B): serial(8) + approval(16 IA5) + date(4)."""
        ts = 1700000000
        record = struct.pack(">Q", 0x0102030405060708) + b'e1-0002         ' + struct.pack(">I", ts)

        decoded = decode_sensor_gnss_coupled(record)

        assert decoded["sensor_serial"] == "0102030405060708"
        assert decoded["sensor_approval"] == "e1-0002"
        assert decoded["coupling_date"] is not None

    def test_g22_sensor_paired_decode_normative_record(self):
        """SensorPairedRecord (28B): serial(8) + approval(16 IA5) + pairingDate(4)."""
        ts = 1700000000
        record = struct.pack(">Q", 0x0102030405060708) + b'e1-0002         ' + struct.pack(">I", ts)

        decoded = decode_sensor_paired(record)

        assert decoded["sensor_serial"] == "0102030405060708"
        assert decoded["sensor_approval"] == "e1-0002"
        assert decoded["pairing_date"] is not None

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
        record += struct.pack(">BB", 0x01, 0x1A)
        record += b'DRV12345CARD    '
        record += struct.pack(">B", 0x01)
        record += struct.pack(">B", 0x03)
        decoded = decode_overspeeding_event(record)
        assert decoded is not None
        assert decoded["event_type"] == 0x01
        assert decoded["record_purpose"] == 0x02
        assert decoded["max_speed_kmh"] == 120
        assert decoded["average_speed_kmh"] == 95
        assert decoded["similar_events"] == 0x03
        assert decoded["card_driver"]["nation"] == "I"
        assert decoded["card_driver"]["generation"] == 1
        assert decoded["begin"] != "N/A"
        assert decoded["end"] != "N/A"

    def test_overspeeding_control_decode(self):
        ts_last = 1700000000
        ts_first = 1699900000
        record = struct.pack(">IIB", ts_last, ts_first, 42)
        decoded = decode_overspeeding_control(record)
        assert decoded is not None
        assert decoded["number_of_overspeed"] == 42
        assert decoded["last_control_time"] != "N/A"
        assert decoded["first_overspeed_since"] != "N/A"

    def test_time_adj_gnss_decode(self):
        ts_old = 1700000000
        ts_new = 1700003600
        record = struct.pack(">II", ts_old, ts_new)
        decoded = decode_time_adj_gnss(record)
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
            record += struct.pack(">B", 0x01)
        record += b'\x00'
        decoded = decode_power_interruption(record)
        assert decoded is not None
        assert decoded["event_type"] == 0x01
        assert decoded["record_purpose"] == 0x02
        assert decoded["begin"] != "N/A"
        assert decoded["end"] != "N/A"
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
            record += struct.pack(">B", 0x01)
        record += b'\x00' * (90 - len(record))  # pad to 90 bytes
        decoded = decode_sensor_fault(record)
        assert decoded is not None
        assert decoded["event_type"] == 0x01
        assert decoded["event_purpose"] == 0x02
        assert decoded["begin_time"] != "N/A"
        assert decoded["end_time"] != "N/A"
        assert "payload_hex" in decoded

    def test_overspeeding_event_record_array_dispatch(self):
        ts_begin = 1700000000
        ts_end = 1700003600
        record = struct.pack(">BBIIBB", 0x01, 0x02, ts_begin, ts_end, 120, 95)
        record += struct.pack(">BB", 0x01, 0x1A)
        record += b'DRV12345CARD    '
        record += struct.pack(">B", 0x01)
        record += struct.pack(">B", 0x03)
        record_array = struct.pack(">BHH", 1, 32, 1) + record
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
            record += struct.pack(">B", 0x01)
        record += b'\x00'  # tail byte
        record_array = struct.pack(">BHH", 1, 87, 1) + record
        results = {}

        parse_g2_vu_record(record_array, results, 0x0530)

        assert len(results["power_interruptions"]) == 1
        assert results["power_interruptions"][0]["event_type"] == 0x01
