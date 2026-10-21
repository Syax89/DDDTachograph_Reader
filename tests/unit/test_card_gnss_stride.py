"""EF GNSS_Places (0x0524) record-stride detection.

CARD-GNSS-STRIDE: the stride was chosen by ``len(data) % 18 == 0`` first, so a
G2.2 payload whose 19-byte records also happen to fill a whole number of
18-byte chunks (36 × 19 = 684 = 38 × 18) was decoded at the wrong stride. The
misaligned chunks mostly fail validation, so almost every position was lost and
the survivors carried fabricated values (wrong latitude, wrong odometer).
"""

import struct

from core.decoders.card_ef import parse_card_gnss_places


def _coord(raw):
    return int(raw).to_bytes(3, "big", signed=True)


def _rec18(ts, lat, lon, odo):
    """GNSSAccumulatedDrivingRecord: ts + GNSSPlaceRecord(ts, acc, coords) + odo."""
    return (struct.pack(">I", ts) + struct.pack(">I", ts) + bytes([5])
            + _coord(lat) + _coord(lon) + odo.to_bytes(3, "big"))


def _rec19(ts, lat, lon, auth, odo):
    """G2.2 variant: the GNSSPlaceRecord also carries authenticationStatus."""
    return (struct.pack(">I", ts) + struct.pack(">I", ts) + bytes([5])
            + _coord(lat) + _coord(lon) + bytes([auth]) + odo.to_bytes(3, "big"))


def test_g22_payload_that_also_fills_18_byte_chunks_keeps_every_record():
    n = 36
    data = b"".join(_rec19(1700000000 + 60 * i, 45312, 9125, 1, 100000 + i)
                    for i in range(n))
    assert len(data) % 18 == 0 and len(data) % 19 == 0   # the ambiguity
    results = {}
    parse_card_gnss_places(b"\x00\x00" + data, results)
    records = results["gnss_ad_records"]
    assert len(records) == n
    assert records[0]["latitude"] == 45.52
    assert records[0]["longitude"] == 9.2083333
    assert records[0]["odometer_km"] == 100000
    assert records[0]["gnss_authenticated"] is True
    assert records[-1]["odometer_km"] == 100000 + n - 1


def test_g2_payload_still_decoded_at_18_bytes():
    n = 10
    data = b"".join(_rec18(1700000000 + 60 * i, 45312, 9125, 200000 + i)
                    for i in range(n))
    results = {}
    parse_card_gnss_places(b"\x00\x00" + data, results)
    records = results["gnss_ad_records"]
    assert len(records) == n
    assert records[0]["odometer_km"] == 200000
    assert "gnss_authenticated" not in records[0]


def test_generation_metadata_breaks_a_genuine_tie():
    """An 18-record G2.2 payload is 342 bytes: valid at 19 *and* at 18."""
    n = 18
    data = b"".join(_rec19(1700000000 + 60 * i, 45312, 9125, 1, 300000 + i)
                    for i in range(n))
    assert len(data) == 342
    hinted = {"metadata": {"generation": "G2.2"}}
    parse_card_gnss_places(b"\x00\x00" + data, hinted)
    assert len(hinted["gnss_ad_records"]) == n
    assert hinted["gnss_ad_records"][-1]["odometer_km"] == 300000 + n - 1
