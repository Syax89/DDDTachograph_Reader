"""Regression tests for VU G1 decoder fixes.

M1: parse_vu_vehicle_identification field order was inverted vs the Annex 1B
    §2.15 spec (VIN(17) + nation(1) + plate(14)); the validation gate then
    silently failed on real data.
M4: the TREP 02 timestamp-scan heuristic matched the (0, 0) change-stream
    terminator as a valid pair, emitting a phantom REST change at 00:00.
"""

import struct

import pytest

from core.decoders.vu_g1 import (
    _parse_trep_02_activities,
    _parse_trep_02_g1_structured,
    parse_g1_vu_overview,
    parse_vu_vehicle_identification,
)


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


def _g1_trep02_body(odometer):
    """A valid Annex 1B §2.2.6.2 TREP 02 body with one IW record and one change."""
    out = bytearray()
    out += struct.pack(">I", 1600000000)          # dateOfDay
    out += odometer.to_bytes(3, "big")            # odometerValueMidnight
    out += struct.pack(">H", 1)                   # noOfIWRecords
    iw = bytearray(129)
    iw[0:6] = b"SMITH\x00"
    iw[36:41] = b"JOHN\x00"
    iw[72] = 0x01
    iw[73] = 0x1A
    iw[74:90] = b"I100000114613001"
    iw[90:94] = struct.pack(">I", 1600000000)
    iw[94:98] = struct.pack(">I", 1600000000)
    out += bytes(iw)
    out += struct.pack(">H", 1)                   # noOfActivityChanges
    out += struct.pack(">H", (5 << 2) | 3)
    out += bytes([0])                             # noOfPlaceRecords
    out += struct.pack(">H", 0)                   # noOfSpecificConditionRecords
    return bytes(out)


def test_trep02_odometer_0x7622_does_not_misroute_to_g2():
    """B-F2: an odometer of 30242 km (0x007622) puts the byte pair ``76 22``
    inside a valid G1 TREP 02 body. That must NOT make the body be handed to the
    G2 parser (which returns nothing) — the day + driver must survive."""
    body = _g1_trep02_body(30242)
    assert b"\x76\x22" in body[:500]              # the tell-tale odometer pair

    results = {}
    _parse_trep_02_activities(body, results)

    assert results.get("activities"), "G1 day silently dropped (misrouted to G2)"
    assert results.get("inserted_drivers"), "G1 driver silently dropped"


def test_trep02_plain_body_still_parses():
    """Negative sibling: a body without the 0x76 0x22 pair keeps parsing."""
    results = {}
    _parse_trep_02_activities(_g1_trep02_body(12345), results)
    assert results.get("activities")
    assert results.get("inserted_drivers")


def _g1_trep02_malformed_recovery_bodies():
    """Deterministic mutations of the valid TREP 02 body, each carrying the
    odometer byte pair ``76 22``/``76 32`` inside the first 500 bytes AND
    rejected by the structured G1 layout (Annex 1B §2.2.6.2), so the legacy
    fallback is the *only* path that recovers the driver.

    These are exactly the inputs on which the removed 0x7622/0x7632 content
    sniff is load-bearing: reinstating it (reviewer's M4) routes them to the G2
    parser, which recovers nothing, and the driver is silently lost. The
    well-formed case above cannot see that mutant (the structured parse
    short-circuits first), so the pin must use malformed bodies.
    """
    wrong_len = bytearray(_g1_trep02_body(30242))
    wrong_len[7:9] = b"\xff\xff"                 # noOfIWRecords -> 65535
    return {
        "truncated": _g1_trep02_body(30242)[:140],
        "wrong_length_card_record": bytes(wrong_len),
        "odometer_7632_truncated": _g1_trep02_body(30258)[:140],
    }


@pytest.mark.parametrize("name", sorted(_g1_trep02_malformed_recovery_bodies()))
def test_malformed_trep02_driver_survives_in_fallback(name):
    """The fallback must still recover the driver from a malformed G1 day whose
    bytes contain the 0x76 0x22 / 0x76 0x32 pair. Restoring the content sniff
    (M4) makes this lose the driver."""
    body = _g1_trep02_malformed_recovery_bodies()[name]
    assert b"\x76\x22" in body[:500] or b"\x76\x32" in body[:500]
    assert _parse_trep_02_g1_structured(body, {}) is False, (
        "structured layout must reject this body so the fallback runs")

    results = {}
    _parse_trep_02_activities(body, results)

    drivers = results.get("inserted_drivers") or []
    assert drivers, f"fallback recovered no driver for {name} (sniff stole the body)"
    assert drivers[0]["card_number"].startswith("I100000114613001")


def _g1_overview_body(first_byte):
    """A 433-byte-shaped Overview whose fields validate at offset 0 and whose
    shifted (val[2:]) view would also validate, so only the alignment rule
    decides which VIN is published."""
    val = bytearray(600)
    val[0] = first_byte
    val[388:405] = b"XXSHIFTEDVIN00000"           # alignment-0 VIN
    val[405] = ord("Z")                           # alignment-2 VIN byte 15
    val[406] = ord("9")                           # alignment-2 VIN byte 16
    val[422:426] = struct.pack(">I", 1700000000)  # alignment-2 TimeReal
    val[428:432] = struct.pack(">I", 1700000001)  # alignment-0 TimeReal
    return bytes(val)


def test_overview_vin_independent_of_certificate_first_byte():
    """B-F4: the first byte of the 194-byte MemberStateCertificate is an RSA
    signature byte; choosing the 2-byte shift on it moved VIN/plate/nation. The
    published VIN must be identical for byte 0x00 vs 0x01."""
    def vin(first_byte):
        results = {"vehicle": {"vin": "N/A", "plate": "N/A", "registration_nation": "N/A"},
                   "metadata": {}, "vu_overview": {}}
        parse_g1_vu_overview(_g1_overview_body(first_byte), results)
        return results["vehicle"]["vin"]

    assert vin(0x00) == vin(0x01) == "XXSHIFTEDVIN00000"
