"""Regression tests for VU G1 decoder fixes.

M1: parse_vu_vehicle_identification field order was inverted vs the Annex 1B
    §2.15 spec (VIN(17) + nation(1) + plate(14)); the validation gate then
    silently failed on real data.
M4: the TREP 02 timestamp-scan heuristic matched the (0, 0) change-stream
    terminator as a valid pair, emitting a phantom REST change at 00:00.
"""

import struct

from core.decoders.vu_g1 import _parse_trep_02_activities, parse_vu_vehicle_identification


def _results_with_vehicle():
    return {"vehicle": {"vin": "N/A", "plate": "N/A", "registration_nation": "N/A"}}


def test_vu_vehicle_identification_spec_field_order():
    """VIN(17) + nation(1) + plate(14) must decode in spec order."""
    payload = b"YV2RTY0C9HB792078" + b"\x1a" + b"FG538JH" + b" " * 7
    assert len(payload) == 32

    results = _results_with_vehicle()
    parse_vu_vehicle_identification(payload, results)

    assert results["vehicle"]["vin"] == "YV2RTY0C9HB792078"
    assert results["vehicle"]["plate"] == "FG538JH"
    assert results["vehicle"]["registration_nation"] == "I"


def test_vu_vehicle_identification_garbage_payload_leaves_defaults():
    """A payload that fails the validation gate must not overwrite defaults."""
    payload = b"ABC1234567890123!" + b"\x00" + b"1" * 14  # VIN contains '!' -> not alnum
    assert len(payload) == 32
    results = _results_with_vehicle()
    parse_vu_vehicle_identification(payload, results)

    assert results["vehicle"] == {"vin": "N/A", "plate": "N/A", "registration_nation": "N/A"}


def test_trep02_terminator_does_not_emit_midnight_rest():
    """A '00 00' change-stream terminator must stop the walk, not append a
    phantom REST change at 00:00."""
    header_ts = 1_700_000_000
    daily_ts = 1_700_000_001
    surname = b"SMITH".ljust(36, b" ")
    firstname = b"JOHN".ljust(36, b" ")
    payload = bytearray()
    payload += struct.pack(">I", header_ts)   # [0:4]   header timestamp
    payload += b"\x00\x00\x00"                # [4:7]   rest of binary header
    payload += b"\xff\xff"                    # [7:9]   n_iw -> structured parser bails
    payload += b"\x00"                        # [9:10]
    payload += surname                        # [10:46]
    payload += b"\x01"                        # [46]    codepage
    payload += firstname                      # [47:83]
    payload += b"\x01"                        # [83]    codepage
    payload += struct.pack(">I", daily_ts)    # [84:88] daily timestamp
    payload += b"\x00\x00\x01"                # [88:91] odometer
    payload += b"\x01"                        # [91]    card inserted
    payload += struct.pack(">H", 2)           # [92:94] no_changes
    payload += struct.pack(">HH", 60, 0)      # [94:98] valid pair: REST at 01:00
    payload += struct.pack(">HH", 0, 0)       # [98:102] terminator
    payload += b"\x00" * 8                    # [102:110] padding
    assert len(payload) == 110

    results = {}
    _parse_trep_02_activities(bytes(payload), results)

    records = results.get("activities", [])
    assert len(records) == 1
    times = [c["time"] for c in records[0]["changes"]]
    assert times == ["01:00"]
    assert not any(t == "00:00" for t in times)
