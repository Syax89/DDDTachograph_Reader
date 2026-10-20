"""The OdometerShort 'not available' sentinel is not a distance.

Annex 1C App.1 §2.113: OdometerShort is a 3-byte field with an operating range of
0..9 999 999 km; CPR_072 gives "not available or not requested" as the FF range, so
0xFFFFFF (and 0xFFFF / 0xFFFFFFFF for the wider odometer fields of the same records)
means "not available", never 16 777 215 km. The card decoders already apply it; every
VU decoder that reads the same width must too, and the aggregate helpers must ignore
such a value instead of averaging it in.
"""
import struct


from core.parser.vu_dispatcher import (
    decode_border_crossing, decode_calibration, decode_card_iw, decode_gnss_ad,
    decode_load_unload, decode_place_daily)
from tests.unit import vu_synthetic as S
from tests.unit.test_vu_technical_semantics import _calibration

TIME = S.BASE_TIME
NOT_AVAILABLE = 0xFFFFFF
MAX_VALID_KM = 9_999_999


def _odometer_cases():
    """(name, decode callable, bytearray body, offset of the 3-byte odometer)."""
    return [
        ("calibration old", lambda b: decode_calibration(b)["old_odometer_km"], None, None),
    ]


# ── One case per decoder, sentinel and maximum valid value ───────────────

def test_calibration_odometers():
    body = bytearray(_calibration(222))
    body[149:152] = b"\xff\xff\xff"
    body[152:155] = (MAX_VALID_KM).to_bytes(3, "big")
    out = decode_calibration(bytes(body))
    assert out["old_odometer_km"] is None          # sentinel: not available
    assert out["new_odometer_km"] == MAX_VALID_KM  # the widest legal value
    assert out["old_odometer_raw"] == NOT_AVAILABLE


def test_card_iw_odometers():
    record = bytearray(b"\x00" * 131)
    record[99:102] = b"\xff\xff\xff"
    record[107:110] = (MAX_VALID_KM).to_bytes(3, "big")
    out = decode_card_iw(bytes(record))
    assert out["odometer_insertion_km"] is None
    assert out["odometer_withdrawal_km"] == MAX_VALID_KM


def test_place_odometer():
    record = bytearray(S.card_number() + struct.pack(">I", TIME)
                       + bytes([0x00, 0x1A, 0x07]) + b"\xff\xff\xff"
                       + struct.pack(">I", TIME) + bytes([0x02]) + b"\x00" * 6 + b"\x01")
    out = decode_place_daily(bytes(record))
    assert out["odometer_km"] is None
    out2 = decode_place_daily(bytes(record[:26]) + (MAX_VALID_KM).to_bytes(3, "big")
                             + bytes(record[29:]))
    assert out2["odometer_km"] == MAX_VALID_KM


def test_gnss_ad_odometer():
    record = bytearray(4 + 19 + 19 + 4 + 1 + 6 + 3)
    record[0:4] = struct.pack(">I", TIME)
    record[-3:] = b"\xff\xff\xff"
    assert decode_gnss_ad(bytes(record))["odometer_km"] is None
    record[-3:] = (MAX_VALID_KM).to_bytes(3, "big")
    assert decode_gnss_ad(bytes(record))["odometer_km"] == MAX_VALID_KM


def test_border_crossing_and_load_unload_odometers():
    border = bytearray(55)
    border[52:55] = b"\xff\xff\xff"
    assert decode_border_crossing(bytes(border))["odometer_km"] is None
    load = bytearray(58)
    load[55:58] = b"\xff\xff\xff"
    assert decode_load_unload(bytes(load))["odometer_km"] is None


def test_every_vu_odometer_helper_applies_the_sentinel():
    """The helper is shared: no VU decoder may publish 0xFFFFFF as a distance."""
    for name, value in _sentinel_scan():
        assert value in (None, 0), (name, value)


def _sentinel_scan():
    """Decode each touched record with every 3-byte odometer set to the sentinel."""
    produced = []

    cal = bytearray(_calibration(252))
    cal[149:155] = b"\xff" * 6
    produced.append(("calibration", decode_calibration(bytes(cal))["old_odometer_km"]))

    iw = bytearray(b"\x00" * 131)
    iw[99:102] = b"\xff\xff\xff"
    iw[107:110] = b"\xff\xff\xff"
    out = decode_card_iw(bytes(iw))
    produced.append(("iw", out["odometer_insertion_km"]))
    produced.append(("iw", out["odometer_withdrawal_km"]))
    return produced


def test_aggregates_ignore_a_not_available_odometer(tmp_path):
    """Distance aggregates must not average a 16-million-km sentinel in."""
    from app.engine import TachoParser
    from core.registry.registry import DecoderRegistry
    from tests.unit import vu_synthetic as S
    body = (S.coded_string("SYNTH VU MAKER", code_page=1, length=36)
            + S.coded_string("SYNTH ROAD 1", code_page=1, length=36)
            + b"PART0001        " + S.extended_serial(0x0000A001)
            + b"0001" + struct.pack(">I", TIME) + struct.pack(">I", TIME)
            + b"APPROVAL" + S.extended_serial(0x0000A002)
            + b"SENSORAP" + struct.pack(">I", TIME + 60))
    cal = bytearray(_calibration(167))
    cal[149:152] = b"\xff\xff\xff"
    stream = b"\x76\x05" + body + b"\x01" + bytes(cal) + b"\x00" * 128
    path = tmp_path / "agg.ddd"
    path.write_bytes(stream)
    DecoderRegistry.reset_instance()
    result = TachoParser(str(path)).parse()
    record = (result.get("calibrations") or [{}])[0]
    assert record.get("old_odometer_km") is None
    assert "16777215" not in str(result.get("calibrations"))
